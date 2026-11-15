#!/usr/bin/env python3
"""Audit original Gale board pools and saved actor evidence, without a client/GPU."""
from __future__ import annotations

import argparse
import ast
from collections import Counter, defaultdict
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from arena_gale_catalog import classify_board

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / 'debug/arena-client'


def read(path):
    return json.loads(path.read_text())


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_name(path, root=ROOT):
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def mechanism(stage):
    """Classify explicit original mechanisms, not apparent visual difficulty."""
    blocks = [b for group in stage['_levelBlockInfos'] for b in group]
    enemies = Counter(e['_enemyType'] for b in blocks for e in b.get('enemyInfos', []))
    items = [item for b in blocks for item in b.get('itemInfos', [])]
    item_types = Counter(i['_itemType'] for i in items)
    bosses = [i.get('_itemInfoCustom', {}).get('_controllerDataID') for i in items if i['_itemType'] == 32]
    tasks = [i.get('_itemInfoCustom', {}).get('_speicalTaskGroupID') for i in items if i['_itemType'] == 43]
    kind = ('boss' if bosses else 'special_task' if tasks else
            'reward_coin_layout' if not enemies and item_types[2] and item_types[101] else 'ordinary')
    slopes = []
    for gi, group in enumerate(stage['_levelBlockInfos']):
        for bi, block in enumerate(group):
            a, b = block.get('_pointStart', {}), block.get('_pointEnd', {})
            dx, dy = b.get('x', 0)-a.get('x', 0), b.get('y', 0)-a.get('y', 0)
            if abs(dx) > .5 and abs(dy) > .2 and block.get('_groundType', 0) != 3:
                slopes.append(dict(group=gi, variant=bi, slope=dy/dx))
    return dict(kind=kind, boss_controller_ids=bosses, special_task_group_ids=tasks,
                native_loop_groups=[i for i, group in enumerate(stage['_levelBlockInfos'])
                                    if any(b.get('_infiniteLoop') for b in group)],
                enemy_type_counts=dict(enemies), item_type_counts=dict(item_types), slopes=slopes,
                coin_pile_mechanism=bool(item_types[2] or item_types[101]),
                speed_values=sorted({b['_ninjaSpeed'] for b in blocks if '_ninjaSpeed' in b}))


def actor_source_names(path):
    """Read the runner's literal manifest without importing its GPU/runtime."""
    tree=ast.parse(path.read_text())
    run=next(node for node in tree.body if isinstance(node,ast.FunctionDef)and node.name=='run')
    for node in ast.walk(run):
        if isinstance(node,ast.Assign)and any(isinstance(t,ast.Name)and t.id=='sources'for t in node.targets):
            names=ast.literal_eval(node.value)
            if names and isinstance(names,(tuple,list))and all(isinstance(n,str)for n in names):
                return set(names)
    raise ValueError('Actor source manifest is missing or not a literal list')


def actor_evidence(setup, report, catalog, *, current_hashes=None, required_sources=None):
    """Return genuine saved actor evidence; never turn entry/collection into a pass.

    Legacy reports lack a requested goal. Only a later observed stage proves
    their board completion, even when the entire report says ``passed``.
    Damage remains an episode total; it is not divided among its boards.
    """
    if not isinstance(setup, dict) or not isinstance(report, dict):
        return None, 'not_actor_report'
    required = {'status', 'final', 'actions', 'board_entries'}
    if not required <= report.keys() or 'initial' not in setup:
        return None, 'not_actor_report'
    if setup.get('observe'):
        return None, 'observe_only'
    if not isinstance(report['final'], dict) or not isinstance(setup['initial'], dict):
        return None, 'invalid_native_evidence'
    raw_map = catalog['maps'].get(str(setup.get('map')))
    if raw_map is None:
        return None, 'unknown_map'
    level = raw_map['absoluteLevel']
    map_id = raw_map.get('menuMap', raw_map['id'])
    offset = raw_map.get('menuBoardOffset', 0)
    start = setup.get('start', 1)
    if not isinstance(start, int) or isinstance(start, bool) or start < 1:
        return None, 'invalid_start'
    goal = setup.get('goal_stage_index')
    if goal is None and report.get('boards_requested') is not None:
        goal = start-1+report['boards_requested']
    if goal is not None and (not isinstance(goal, int) or goal < start):
        return None, 'invalid_goal'
    final, initial = report['final'], setup['initial']
    passed = report['status'] in ('passed', 'passed_with_damage')
    # Same semantics as the original evaluator: the last board can enter a
    # native boss map, whose stage index starts again. This only completes the
    # preceding requested ordinary board, never the new boss encounter.
    map_changed = (final.get('map') is not None and initial.get('map') is not None
                   and final['map'] != initial['map'])
    goal_reached = bool(goal is not None and (
        not map_changed and final.get('stageIndex', -1) >= goal or
        map_changed and initial.get('stageCount') is not None and goal <= initial['stageCount']))
    no_hit = (passed and final.get('damage') == 0 and not report.get('had_damage', False)
              and initial.get('god') is False and final.get('god') is False
              and not report.get('evaluation_error'))
    entries = report['board_entries']
    if not isinstance(entries, list):
        return None, 'invalid_board_entries'
    observed = []
    slots = catalog['maps'][str(map_id)]['slots']
    for i, entry in enumerate(entries):
        index, board = entry.get('stageIndex'), entry.get('stageID')
        if not isinstance(index, int) or index < start-1 or goal is not None and index >= goal:
            continue
        position = index+1-offset
        if not 1 <= position <= len(slots) or board not in [v['id'] for v in slots[position-1]['pool']]:
            continue
        crossed = any(v.get('stageIndex', -1) > index for v in entries[i+1:])
        completed = crossed or (passed and goal_reached)
        observed.append(dict(stage=board, map=map_id, slot=position, completed=completed,
                             whole_episode_no_hit=bool(completed and no_hit),
                             at_entry_damage=entry.get('damage')))
    if not observed:
        return None, 'no_valid_observed_board'
    sources = setup.get('sources', {})
    current_hashes = current_hashes or {}
    mismatches = sorted(name for name, sha in sources.items() if current_hashes.get(name) != sha)
    missing=sorted(set(required_sources or())-set(sources))
    recorded_match=bool(sources)and not mismatches
    return dict(level=level, raw_map=raw_map['id'], map=map_id, raw_start=start, start=start-offset,
        seed=setup.get('seed'), status=report['status'], boards_requested=report.get('boards_requested'),
        goal_stage_index=goal, goal_reached=goal_reached,
        whole_episode_damage=final.get('damage'), whole_episode_no_hit=no_hit,
        observed_boards=observed, detector=setup.get('detector'), source_hashes=sources,
        source_match_current=recorded_match and required_sources is not None and not missing,
        recorded_sources_match_current=recorded_match, source_manifest_missing=missing,
        source_mismatches_current=mismatches), None


def scan_actor_reports(roots, catalog, *, source_root=ROOT, required_sources=None):
    if required_sources is None:
        required_sources=actor_source_names(source_root/'tools/arena_visual_runner.py')
    records, excluded, errors, hashes, seen = [], Counter(), [], {}, set()
    for folder in roots:
        if not folder.exists():
            continue
        for path in sorted(folder.rglob('report.json')):
            path = path.resolve()
            if path in seen:
                continue
            seen.add(path)
            setup_path = path.with_name('setup.json')
            if not setup_path.exists():
                excluded['missing_setup'] += 1
                continue
            try:
                setup, report = read(setup_path), read(path)
                sources = setup.get('sources', {}) if isinstance(setup, dict) else {}
                for name in sources:
                    if name not in hashes:
                        local = source_root/name
                        hashes[name] = digest(local) if local.is_file() else None
                evidence, reason = actor_evidence(setup, report, catalog, current_hashes=hashes, required_sources=required_sources)
                if evidence is None:
                    excluded[reason] += 1
                    continue
            except (OSError, ValueError, KeyError, TypeError) as error:
                errors.append(dict(path=source_name(path), error=str(error)))
                continue
            records.append(dict(evidence, id=len(records), report=source_name(path),
                setup=source_name(setup_path), report_sha256=digest(path), setup_sha256=digest(setup_path),
                modified_ns=path.stat().st_mtime_ns))
    return dict(records=records, excluded=dict(excluded), read_errors=errors,
                roots=[source_name(p) for p in roots], current_source_hashes=hashes,
                required_actor_sources=sorted(required_sources))


def ordinary_batches(maps, boards, level_order):
    """Cover unique original variants, preserving finite original slot contexts."""
    seen, batches = set(), []
    for level in level_order:
        for world in sorted((m for m in maps.values() if m['level'] == level), key=lambda m: m['map']):
            segments, segment = [], []
            for slot in world['slots']:
                pool = [v['stage'] for v in slot['variants'] if boards[str(v['stage'])]['mechanism']['kind'] == 'ordinary']
                if pool:
                    segment.append((slot['position'], pool))
                elif segment:
                    segments.append(segment); segment = []
            if segment:
                segments.append(segment)
            for segment in segments:
                for i in range(max(len(pool) for _, pool in segment)):
                    pins = {str(position): pool[i % len(pool)] for position, pool in segment}
                    new = sorted(set(pins.values())-seen)
                    if not new:
                        continue
                    repeats = sorted(set(pins.values()) & seen)
                    seen.update(new)
                    start, end = segment[0][0], segment[-1][0]
                    native = dict(world['route'], map=world['map'], start=start, pins=pins)
                    batches.append(dict(batch=len(batches)+1, level=level, map=world['map'], start=start,
                        boards=end-start+1, pins=pins, unique_new_stages=new,
                        bridge_or_padding_repeats=repeats, native_select=native,
                        runner_arguments=['--level', str(level), '--map', str(world['map']), '--start', str(start),
                            '--boards', str(end-start+1), '--seconds', '180']+
                            [arg for position, stage in pins.items() for arg in ['--pin', f'{position}:{stage}']]))
    return batches


def build_audit(catalog, dataset, *, evidence=None, levels=(1, 2, 3, 4, 5, 6), boss_configs=None):
    if catalog.get('mode') != 6:
        raise ValueError('Only original Gale mode6 is supported')
    levels = sorted(set(levels))
    if not levels or any(level not in range(1, 7) for level in levels):
        raise ValueError('This audit is limited to Gale levels1–6')
    boss_configs = boss_configs or {}
    evidence = evidence or dict(records=[], excluded={}, read_errors=[], roots=[])
    records = [r for r in evidence['records'] if r['level'] in levels]
    index = defaultdict(list)
    for record in records:
        for board in record['observed_boards']:
            index[(record['level'], board['map'], board['slot'], board['stage'])].append((record, board))
    maps, boards, aliases = {}, {}, []
    for entry in catalog['levels']:
        level = entry['id']
        if level not in levels:
            continue
        for ref in entry['maps']:
            identity = ref['id']
            world = catalog['maps'][str(identity)]
            if world.get('menuMap'):
                raise ValueError('Catalog levels must already contain canonical menu maps')
            if world.get('loop'):
                raise ValueError('Level1–6 loop pools require explicit scheduling')
            raw_path = dataset/f'level_endless_gale_{identity}.bytes.json'
            raw = read(raw_path)[0]
            if raw['_levelDataType']['value__'] != 6:
                raise ValueError('Non-Gale source map')
            route = dict(chapter=ref['chapter'], level=ref['level'])
            slots = []
            for slot in world['slots']:
                group = raw['_stageRandomGroup'][slot['group']-1]
                variants = []
                for variant in slot['pool']:
                    stage, position = variant['id'], slot['position']
                    if stage not in [v['_stageID'] for v in group['_stageRandomList']]:
                        raise ValueError('Catalog variant is absent from its original map group')
                    stage_path = dataset/f'stage_endless_gale_{stage}.json'
                    source = read(stage_path)
                    if source.get('_levelDataType') != 6 or source.get('_stageID') != stage:
                        raise ValueError('Non-Gale source board')
                    key = (level, identity, position, stage)
                    historic = index[key]
                    current = [(r, b) for r, b in historic if r['source_match_current']]
                    native = dict(route, map=identity, start=position, pins={str(position): stage})
                    direct = [r['id'] for r, _ in historic if r['start'] == position
                              and r['observed_boards'][0]['stage'] == stage]
                    context = dict(level=level, map=identity, slot=position, raw_group=slot['group'],
                        difficulty=world['difficulty'], native_select=native, static_pool_valid=True,
                        entry_safety='historical_actor_started' if direct else 'not_proven',
                        direct_start_record_ids=direct, historical_record_ids=[r['id'] for r, _ in historic],
                        historical_completed=any(b['completed'] for _, b in historic),
                        historical_whole_episode_no_hit=any(b['whole_episode_no_hit'] for _, b in historic),
                        current_source_record_ids=[r['id'] for r, _ in current],
                        current_source_completed=any(b['completed'] for _, b in current),
                        current_source_whole_episode_no_hit=any(b['whole_episode_no_hit'] for _, b in current))
                    if str(stage) not in boards:
                        body = {k: v for k, v in source.items() if k != '_stageID'}
                        boards[str(stage)] = dict(stage=stage, source=source_name(stage_path),
                            source_sha256=digest(stage_path),
                            content_sha256_excluding_stage_id=hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest(),
                            classification=classify_board(source), entry=variant.get('entry'),
                            starts_game=variant.get('startsGame'), mechanism=mechanism(source), contexts=[])
                    special = boards[str(stage)]['mechanism']
                    if special['boss_controller_ids']:
                        context['original_boss_config'] = {str(i): boss_configs.get(identity, {}).get(i)
                                                          for i in special['boss_controller_ids']}
                    boards[str(stage)]['contexts'].append(context)
                    variants.append(dict(stage=stage, weight=variant['weight'], native_select=native))
                slots.append(dict(position=slot['position'], raw_group=slot['group'], variants=variants,
                                  settings={k: v for k, v in group.items() if k != '_stageRandomList'}))
            maps[str(identity)] = dict(level=level, map=identity, route=route, difficulty=world['difficulty'],
                ground=world['ground'], opening=world['opening'], slots=slots,
                source=source_name(raw_path), source_sha256=digest(raw_path))
    for world in catalog['maps'].values():
        if world.get('menuMap') and world['absoluteLevel'] in levels:
            aliases.append(dict(raw_map=world['id'], representative=world['menuMap'],
                                board_offset=world['menuBoardOffset'], level=world['absoluteLevel']))
    summaries, equal = [], defaultdict(list)
    for board in boards.values():
        board['recommended_native_select'] = board['contexts'][0]['native_select']
        equal[board['content_sha256_excluding_stage_id']].append(board['stage'])
        for prefix in ('historical', 'current_source'):
            for metric in ('completed', 'whole_episode_no_hit'):
                board[prefix+'_'+metric] = any(c[prefix+'_'+metric] for c in board['contexts'])
        if board['mechanism']['kind'] != 'ordinary':
            board['automatic_mechanism_acceptance'] = 'not_established_by_this_audit'
    for level in levels:
        members = [b for b in boards.values() if any(c['level'] == level for c in b['contexts'])]
        ordinary = [b for b in members if b['mechanism']['kind'] == 'ordinary']
        summaries.append(dict(level=level, maps=[m['map'] for m in maps.values() if m['level'] == level],
            unique_stages=len(members), kinds=dict(Counter(b['mechanism']['kind'] for b in members)),
            ordinary_layout=dict(Counter(b['classification']['layout'] for b in ordinary)),
            historical_completed=sum(b['historical_completed'] for b in ordinary),
            historical_whole_episode_no_hit=sum(b['historical_whole_episode_no_hit'] for b in ordinary),
            current_source_completed=sum(b['current_source_completed'] for b in ordinary)))
    batches = ordinary_batches(maps, boards, [i for i in (5, 6, 1, 2, 3, 4) if i in levels])
    expected = {b['stage'] for b in boards.values() if b['mechanism']['kind'] == 'ordinary'}
    if expected != {stage for batch in batches for stage in batch['unique_new_stages']}:
        raise ValueError('Batch enumeration lost an ordinary variant')
    return dict(schema=1, mode=6, created_utc=datetime.now(timezone.utc).isoformat(),
        scope='Read-only source catalog and saved actor reports; no new live tests.',
        rules=[
            'Canonical menu maps reuse native catalog entry aliases; one first-pass board is one original StageID, with every legal context retained.',
            'Static legal native_select and historical preparation do not prove safe arrival for every random seed.',
            'Fixed layout means no configured placement variation, not deterministic enemy AI.',
            'No-hit requires completed whole actor episode with damage0, had_damage false and original god false. Damage remains an episode total.',
            'Materials, observe-only, native action probes and offline scores are excluded. Legacy final entry alone is not completion.',
            'Current source evidence requires every source declared by the current runner and equal recorded hashes. It does not assert equal weights, configuration outside the manifest, or complete gameplay acceptance.',
            'Boss, coin-reward and special-task mechanisms need separate acceptance; entering a boss map only completes its preceding board.',
            'One seed is first-pass coverage, not acceptance of all random layouts. Interrupted/unreached batch slots remain pending.'],
        counts=dict(canonical_maps=len(maps), removed_entry_aliases=len(aliases),
            slots=sum(len(m['slots']) for m in maps.values()),
            candidate_occurrences=sum(len(s['variants']) for m in maps.values() for s in m['slots']),
            unique_stages=len(boards), kinds=dict(Counter(b['mechanism']['kind'] for b in boards.values())),
            actor_reports=len(records), current_source_actor_reports=sum(r['source_match_current'] for r in records)),
        levels=summaries, aliases=aliases, maps=maps, boards=boards,
        exact_content_duplicate_ids=[v for v in equal.values() if len(v) > 1],
        historical_actor_records=records, current_source_actor_record_ids=[r['id'] for r in records if r['source_match_current']],
        evidence_scan={k: v for k, v in evidence.items() if k != 'records'},
        ordinary_first_pass_batches=batches,
        special_mechanisms=dict(
            boss='ItemBossController32/controllerDataID/native loop: local native_boss.lua sets original max/current/phase HP1; completion still needs original boss death/exit.',
            reward='No configured enemies plus ItemCoinPileStart2/End101. Coin collection, springs/magnets and terrain remain unverified.',
            special_task='ItemSpecialTaskStart43 original task group; task goals are not ordinary trap avoidance.'))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--catalog', type=Path, default=BASE/'gameonly/gale-catalog-native.json')
    parser.add_argument('--dataset', type=Path, default=BASE/'dataset/assets/assets/gameresources/binarydatas/leveldata/endless_gale')
    parser.add_argument('--boss-config', type=Path, default=BASE/'nconfig-all/CfgEndlessGaleBossInfo.json')
    parser.add_argument('--reports-root', type=Path, action='append')
    parser.add_argument('--levels', type=int, nargs='+', default=[1, 2, 3, 4, 5, 6])
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    catalog = read(args.catalog)
    evidence = scan_actor_reports(args.reports_root or [BASE/'yolo', BASE/'visual-runs'], catalog)
    boss_configs = {r['key_path'][0]: dict(r['values'][0]['$lua_pairs']) for r in read(args.boss_config)}
    result = build_audit(catalog, args.dataset, evidence=evidence, levels=args.levels, boss_configs=boss_configs)
    result['input_hashes'] = {source_name(p): digest(p) for p in (args.catalog, args.boss_config, Path(__file__))}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2)+'\n')
    print(json.dumps(dict(result['counts'], batches=len(result['ordinary_first_pass_batches']),
                          output=str(args.output)), ensure_ascii=False))


if __name__ == '__main__':
    main()
