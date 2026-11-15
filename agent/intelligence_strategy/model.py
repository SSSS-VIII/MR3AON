"""Catalog, bounded-subset counting/sampling and the offline native benchmark driver."""
from __future__ import annotations

from collections import Counter
from functools import lru_cache
import hashlib
import json
import math
import os
from pathlib import Path
import random
import shutil
import subprocess
import tempfile
import time

HERE = Path(__file__).resolve().parent
CATALOG = json.loads((HERE / 'cards.json').read_text())
CARDS = CATALOG['cards']
BY_NAME = {card['name']: card for card in CARDS}
ASSUMPTIONS = [
    '固定当前购买组合和位置，不假定以后再买牌、刷新或调整旧卡位置。',
    '累计当前回合至第5回合理论伤害；不推演对手、生命耗尽或提前结束。',
    '直接胜利另报，不换算为伤害分数。',
    '四向相邻；入场伤害只在放置当回合，且按最终棋盘计算。',
    '2回合增益默认包含放置当回合；先计算加法/光环，再乘法，最后计算额外伤害。',
    '默认每上场计数包含自身/同回合牌，只计来源牌入场当回合及以后的牌；可切换board_count对比。',
    '旧卡可填intrinsic_bonus锚定未建模的历史永久加成；未填则按声明的简化历史模型。',
    '属性种数不计无属性；金币含期末收入及后续每回合3金币、少买奖励。',
    '空购买组合作为不买基线，纳入统计；统计的是合法组合分布，不是商店抽牌概率。',
]


def _integer(value, label, low, high):
    if isinstance(value, bool) or not isinstance(value, int) or not low <= value <= high:
        raise ValueError(f'{label} 必须是 {low}..{high} 的整数')
    return value


def prepare_state(raw):
    turn = _integer(raw.get('round', 1), 'round', 1, 5)
    gold = _integer(raw.get('gold', 5), 'gold', 0, 100)
    slots = raw.get('board', [None] * 9)
    if not isinstance(slots, list) or len(slots) != 9:
        raise ValueError('board 必须是9格数组')
    board = []
    removed = Counter()
    for item in slots:
        if item is None:
            board.append((-1, 1, 0))
            continue
        if isinstance(item, str):
            item = {'name': item, 'entered_round': 1}
        if not isinstance(item, dict) or item.get('name') not in BY_NAME:
            raise ValueError(f'未知场上卡牌: {item}')
        card = BY_NAME[item['name']]
        entered = _integer(item.get('entered_round', 1), 'entered_round', 1, turn)
        bonus = _integer(item.get('intrinsic_bonus', 0), 'intrinsic_bonus', -10000, 10000)
        board.append((card['id'], entered, bonus))
        removed[card['name']] += 1
    extra = raw.get('known_unavailable', {})
    if not isinstance(extra, dict) or extra.keys() - BY_NAME.keys():
        raise ValueError('known_unavailable 只能包含已知牌名')
    for name, count in extra.items():
        removed[name] += _integer(count, name, 0, BY_NAME[name]['copies'])
    pool = []
    for card in CARDS:
        left = card['copies'] - removed[card['name']]
        if left < 0:
            raise ValueError(f"{card['name']} 的已知占用超过牌库张数")
        pool.append(left)
    if 'pool_override' in raw:
        override = raw['pool_override']
        if not isinstance(override, dict) or override.keys() - BY_NAME.keys():
            raise ValueError('pool_override 只能包含已知牌名')
        pool = [_integer(override.get(c['name'], 0), c['name'], 0, pool[c['id']]) for c in CARDS]
    return {'name': raw.get('name', 'custom'), 'round': turn, 'gold': gold,
            'board': board, 'pool': pool, 'empty': sum(c[0] < 0 for c in board)}


def count_space(state, max_purchases=None):
    """Exact DP counts without visiting placements; identical copies are not permuted."""
    gold, empty = state['gold'], state['empty']
    limit = empty if max_purchases is None else min(empty, max_purchases)
    dp = {(0, 0): (1, 1, 1)}
    for card, remaining in zip(CARDS, state['pool']):
        nxt = {}
        for (spent, used), (unique, physical, layouts) in dp.items():
            for k in range(min(remaining, (gold-spent)//card['cost'], limit-used)+1):
                key = spent+k*card['cost'], used+k
                a, b, c = nxt.get(key, (0, 0, 0))
                nxt[key] = (a+unique, b+physical*math.comb(remaining, k),
                            c+layouts*math.comb(empty-used, k))
        dp = nxt
    return {'combinations': sum(v[0] for v in dp.values()),
            'physical_subsets': sum(v[1] for v in dp.values()),
            'layouts': sum(v[2] for v in dp.values()), 'includes_pass': True}


def sample_combinations(state, count, seed, physical=False, max_purchases=None):
    """Draw uniformly from all affordable unique/physical subsets, not random shops."""
    pool = state['pool']
    @lru_cache(None)
    def ways(i, gold, slots):
        if i == len(CARDS):
            return 1
        card = CARDS[i]
        return sum((math.comb(pool[i], k) if physical else 1) *
                   ways(i+1, gold-k*card['cost'], slots-k)
                   for k in range(min(pool[i], gold//card['cost'], slots)+1))
    rng = random.Random(seed)
    result = []
    for _ in range(count):
        gold, slots = state['gold'], state['empty'] if max_purchases is None else min(state['empty'],max_purchases)
        combo = []
        for i, card in enumerate(CARDS):
            choice = rng.randrange(ways(i, gold, slots))
            for k in range(min(pool[i], gold//card['cost'], slots)+1):
                weight = (math.comb(pool[i], k) if physical else 1) * ways(i+1, gold-k*card['cost'], slots-k)
                if choice < weight:
                    combo.extend([i]*k)
                    gold -= k*card['cost']; slots -= k
                    break
                choice -= weight
        result.append(combo)
    return result


@lru_cache(maxsize=None)
def _compiler_version(compiler):
    return subprocess.check_output([compiler, '--version'], text=True).splitlines()[0]


def build_engine():
    compiler = shutil.which('g++') or shutil.which('clang++')
    if not compiler:
        raise RuntimeError('离线性能核需要g++或clang++（不安装或下载依赖）')
    expected = 'enum Effect { '+', '.join(name.upper() for name in CATALOG['effect_codes'])+' };'
    if expected not in (HERE/'effects.hpp').read_text():
        raise ValueError('cards.json与effects.hpp效果编号不一致')
    version = _compiler_version(compiler)
    digest = hashlib.sha256((HERE/'engine.cpp').read_bytes() + (HERE/'effects.hpp').read_bytes() + (HERE/'synergy.hpp').read_bytes()
                            + (compiler+version).encode()).hexdigest()[:16]
    cache = Path(tempfile.gettempdir()) / f'mr3a-intelligence-sim-{os.getuid()}'
    cache.mkdir(mode=0o700, exist_ok=True)
    binary = cache / digest
    started = time.perf_counter()
    if not binary.exists():
        temporary = cache / f'{digest}.{os.getpid()}.tmp'
        try:
            subprocess.run([compiler, '-std=c++17', '-O3', '-DNDEBUG', str(HERE/'engine.cpp'),
                            '-o', str(temporary)], check=True, capture_output=True, text=True, timeout=60)
            temporary.replace(binary)
        finally:
            temporary.unlink(missing_ok=True)
    return binary, version, time.perf_counter()-started


def histogram_summary(histogram, index):
    pairs = sorted((row[0], row[index]) for row in histogram if row[index])
    total = sum(n for _, n in pairs)
    if not total:
        return None
    def order(rank):
        cumulative = 0
        for value, n in pairs:
            cumulative += n
            if cumulative >= rank:
                return value
        raise AssertionError(rank)
    mean = sum(value*n for value, n in pairs)/total
    variance = sum((value-mean)**2*n for value, n in pairs)/total
    return {'count': total, 'mean': mean,
            'median': (order((total+1)//2)+order((total+2)//2))/2,
            'p10': order(max(1, math.ceil(total*.1))), 'p90': order(max(1, math.ceil(total*.9))),
            'min': pairs[0][0], 'max': pairs[-1][0], 'stddev': math.sqrt(variance)}


def simulate(raw, *, seconds=2.0, max_layouts=0, samples=0, seed=1,
             physical_sampling=False, growth_mode='since_entry', profile='full',
             max_purchases=None, trace_choices=False, position_tiebreak=False, future_pool=None, heuristics=None, position_candidates=1):
    if not math.isfinite(seconds) or seconds < 0:
        raise ValueError('seconds必须是有限非负数，0表示不限时')
    _integer(samples, 'samples', 0, 1000000)
    _integer(max_layouts, 'max_layouts', 0, 10**18)
    if growth_mode not in {'since_entry', 'board_count'}:
        raise ValueError('未知growth_mode')
    if profile not in {'full','refresh_v1','synergy_v2'}:
        raise ValueError('未知profile')
    if max_purchases is not None:
        _integer(max_purchases,'max_purchases',0,9)
    heuristics = dict(heuristics or {})
    defaults = dict(passive_weight=1, aura_weight=0, vacancy_weight=0, cumulative_damage=0, finish_priority=0, role_position_bias=0)
    if set(heuristics)-defaults.keys():
        raise ValueError('未知heuristics参数')
    defaults.update(heuristics); heuristics=defaults
    if any(not math.isfinite(v) or v<0 for v in heuristics.values()):
        raise ValueError('heuristics必须是有限非负值')
    _integer(position_candidates,'position_candidates',1,8)
    started = time.perf_counter()
    state = prepare_state(raw)
    space = count_space(state,max_purchases)
    combinations = sample_combinations(state, samples, seed, physical_sampling,max_purchases) if samples else []
    preparation_s = time.perf_counter()-started
    binary, compiler, build_s = build_engine()
    codes = CATALOG['effect_codes']
    lines = [f"{len(CARDS)} {state['round']} {state['gold']} {seconds} {max_layouts} {int(bool(samples))} {samples} {int(growth_mode=='since_entry')} {dict(full=0,refresh_v1=1,synergy_v2=2)[profile]} {int(position_tiebreak)} {9 if max_purchases is None else max_purchases} {int(trace_choices)}"]
    lines[0]+=' '+' '.join(map(str,heuristics.values()))+f' {position_candidates}'
    lines.extend(' '.join(str(c[k]) for k in ('attack','cost','element','category','copies'))+
                 f" {codes.index(c['effect'])} {c['param']}" for c in CARDS)
    lines.append(' '.join(map(str, state['pool'])))
    future_pool = state['pool'] if future_pool is None else future_pool
    bound_raw = dict(raw); bound_raw.pop('pool_override', None)
    bounds = prepare_state(bound_raw)['pool']
    if len(future_pool) != len(CARDS):
        raise ValueError('future_pool长度错误')
    for i, count in enumerate(future_pool):
        _integer(count, 'future_pool', state['pool'][i], bounds[i])
    lines.append(' '.join(map(str, future_pool)))
    lines.extend(' '.join(map(str, cell)) for cell in state['board'])
    lines.extend(' '.join(map(str, [len(combo), *combo])) for combo in combinations)
    started = time.perf_counter()
    process = subprocess.run([str(binary)], input='\n'.join(lines)+'\n', text=True,
                             capture_output=True, check=True, timeout=seconds+10 if seconds else None)
    wall_s = time.perf_counter()-started
    result = json.loads(process.stdout)
    if result['complete'] and not samples:
        assert result['combinations']==space['combinations']
        assert result['physical_subsets']==space['physical_subsets']
        assert result['layouts']==space['layouts']
    histogram = result.pop('histogram')
    result.update(name=state['name'], round=state['round'], gold=state['gold'], empty=state['empty'],
                  remaining_cards=sum(state['pool']), space=space,
                  mode='sample' if samples else 'exact', sampling='physical_subsets' if physical_sampling else 'unique_combinations',
                  samples_requested=samples, seed=seed, growth_mode=growth_mode, profile=profile,
                  max_purchases=max_purchases, position_tiebreak=position_tiebreak,
                  compiler=compiler, build_s=build_s, preparation_s=preparation_s, wall_s=wall_s,
                  assumptions=ASSUMPTIONS+(['refresh_v1: 老板娘、紫原、轮回戒指及鬼斩铠甲按白板；不加空格潜力或未触发羁绊估值。'] if profile=='refresh_v1' else []))
    result['heuristics']=heuristics
    result['placement_objective'] = 'strategic_damage' if profile=='synergy_v2' else 'damage'
    if profile=='synergy_v2':
        result['assumptions'].append('synergy_v2: 复杂牌沿用refresh_v1白板；未触发被动按场面、回合、余池和空位估值；潜力不属于真实伤害。')
    key = 'statistics' if result['complete'] and not samples else 'sample_estimate' if result['complete'] else 'partial_prefix_statistics_not_pool_estimate'
    def summarize(index):
        gain = histogram_summary(histogram, index)
        shifted = [[row[0]+result['baseline_damage'], row[1], row[2]] for row in histogram]
        return {'damage_gain': gain, 'total_damage': histogram_summary(shifted, index)}
    result[key] = {'sampled_distribution' if samples else 'unique_combinations': summarize(1)}
    if not samples:
        result[key]['physical_subsets'] = summarize(2)
    if samples and result['complete']:
        for metric in result[key]['sampled_distribution'].values():
            metric['mean_standard_error'] = metric['stddev']/math.sqrt(metric['count']) if metric['count'] else None
        result[key]['distribution'] = result['sampling']
    for choice in result['choices']+result['position_choices']:
        choice['cards']=[CARDS[i]['name'] for i in choice['cards']]
        choice['board']=[CARDS[i]['name'] if i>=0 else None for i in choice['board']]
        choice['potential_gain']=choice['synergy_potential']-result['baseline_potential']
        choice['adjusted_damage']=choice['strategic_damage']
        for detail in choice['synergy_details']:
            detail['card']=choice['board'][detail['cell']]
            detail['reason']=['active','row_blocked','insufficient_slots','insufficient_pool','past_round5','estimated','empty_slot_forecast'][detail['reason']]
            if detail['reason']=='empty_slot_forecast':
                detail['confidence']=detail['activation_round']=None
        choice['damage_gain']=choice['damage']-result['baseline_damage']
        choice['existing_card_damage_gain']=sum(value-result['baseline_cell_damage'][i] for i,value in enumerate(choice['cell_damage']) if state['board'][i][0]>=0)
        choice['new_card_damage']=sum(value for i,value in enumerate(choice['cell_damage']) if state['board'][i][0]<0)
        assert choice['existing_card_damage_gain']+choice['new_card_damage']==choice['damage_gain']
    for name in ('best_combo', 'best_board'):
        result[name] = [CARDS[i]['name'] if i>=0 else None for i in result[name]]
    result['histogram'] = histogram
    result['all_combinations_evaluated'] = result['complete'] and not samples
    if samples:
        result['sample_request_completion'] = result['combinations']/samples
        result['observed_unique_combinations'] = len({tuple(c) for c in combinations[:result['combinations']]})
        result['coverage'] = result['observed_unique_combinations']/space['combinations']
    else:
        result['coverage'] = result['combinations']/space['combinations']
    if result['layouts']:
        result['linear_full_runtime_estimate_s'] = result['elapsed_s']*space['layouts']/result['layouts']
    return result
