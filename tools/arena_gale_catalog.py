#!/usr/bin/env python3
"""Build the Gale-only route → level → map → board-slot catalog from recovered data."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def classify_board(stage):
    """Classify placement randomness separately from native action randomness.

    Fixed means the recovered layout has no configured placement variation;
    it is not a claim that every enemy's internal AI is deterministic.
    """
    placement, motion = [], []
    for gi, group in enumerate(stage['_levelBlockInfos']):
        if len(group) > 1:
            placement.append(f'block_group[{gi}].alternatives')
        for bi, block in enumerate(group):
            if block.get('_repeatTimesMin', 1) != block.get('_repeatTimesMax', 1):
                placement.append(f'block_group[{gi}][{bi}].repeat_range')
            for ei, enemy in enumerate(block.get('enemyInfos', [])):
                data = enemy.get('_enemyInfoCustom', {})
                for key in ('_randomRangeY', '_rangeRandomY'):
                    if data.get(key, 0) != 0:
                        placement.append(f'{enemy.get("_enemyType")}.{key}')
                for key in ('_randomRotateDir', '_randomSpeedRotate'):
                    if data.get(key, 0):
                        motion.append(f'{enemy.get("_enemyType")}.{key}')
    placement, motion = sorted(set(placement)), sorted(set(motion))
    return dict(layout='random' if placement else 'fixed',
                label='随机分布' if placement else '固定布置',
                motion='random' if motion else 'unspecified',
                layout_evidence=placement, motion_evidence=motion)


def entry_info(blocks):
    """Describe geometry risk; this is not a proof of collision-free spawning."""
    if not blocks:
        return {'risk': True, 'reason': '入口数据缺失'}
    origin_y = blocks[0].get('_pointStart', {}).get('y', 0)
    for block in blocks:
        a, b = block.get('_pointStart', {}), block.get('_pointEnd', {})
        length = abs(b.get('x', 0) - a.get('x', 0))
        if block.get('_groundType', 0) != 3 and length > .5:
            offset = a.get('y', 0) - origin_y
            reasons = []
            if length < 8:
                reasons.append('短平台入口')
            if abs(offset) > 4:
                reasons.append('入口有较大落差')
            return dict(length=length, heightOffset=offset, risk=bool(reasons), reason='、'.join(reasons))
    return {'risk': True, 'reason': '入口缺少常规地面'}


def build_catalog(config: Path, dataset: Path):
    routes = []
    map_ids = set()
    for row in json.loads(config.read_text()):
        chapter = row['key_path'][0]
        levels = []
        for value in row['values'][0]:
            ids = list(value['levelDataList'])
            map_ids.update(ids)
            levels.append(dict(id=value['levelID'], next=value['nextLevelID'], maps=ids))
        routes.append(dict(id=chapter, levels=sorted(levels, key=lambda v: v['id']),
                           label=f'路线 {chapter}' + ('（完整）' if chapter <= 2 else '（跳关）')))
    maps = {}
    for identity in sorted(map_ids):
        source = json.loads((dataset / f'level_endless_gale_{identity}.bytes.json').read_text())[0]
        if source['_levelDataType']['value__'] != 6:
            raise ValueError('A non-Gale map cannot enter this catalog')
        slots, opening = [], []
        for group_index, group in enumerate(source['_stageRandomGroup'], 1):
            pool = []
            for candidate in group['_stageRandomList']:
                stage_id = candidate['_stageID']
                path = dataset / f'stage_endless_gale_{stage_id}.json'
                if not path.exists():
                    raise ValueError(f'Missing Gale board {stage_id}')
                stage = json.loads(path.read_text())
                if stage.get('_levelDataType', 0) != 6:
                    raise ValueError(f'Non-Gale board {stage_id}')
                blocks = [block for group_ in stage['_levelBlockInfos'] for block in group_]
                pool.append(dict(id=stage_id, weight=candidate['_weight'],
                                 blocks=len(blocks), classification=classify_board(stage), entry=entry_info(blocks), opening=stage.get('_stageUseFor') == 1))
            if pool and all(candidate['opening'] for candidate in pool):
                opening.append(dict(group=group_index, pool=pool))
            else:
                slots.append(dict(position=len(slots) + 1, group=group_index, pool=pool))
        maps[str(identity)] = dict(id=identity, ground=source['_groundType']['value__'],
                                   difficulty=source['_difficultyLevel'], opening=opening, slots=slots)
    return dict(version=1, mode=6, routes=sorted(routes, key=lambda v: v['id']), maps=maps)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    base = ROOT / 'debug/arena-client'
    p.add_argument('--config', type=Path, default=base / 'nconfig-all/CfgEndlessGaleData.json')
    p.add_argument('--dataset', type=Path, default=base / 'dataset/assets/assets/gameresources/binarydatas/leveldata/endless_gale')
    p.add_argument('--output', type=Path, default=base / 'gameonly/gale-catalog-native.json')
    a = p.parse_args()
    catalog = build_catalog(a.config, a.dataset)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_text(json.dumps(catalog, ensure_ascii=False, separators=(',', ':')))
    print(f"Gale catalog: {len(catalog['routes'])} routes, {len(catalog['maps'])} maps → {a.output}")


if __name__ == '__main__':
    main()
