#!/usr/bin/env python3
"""Build the Gale-only route → level → map → board-slot catalog from recovered data."""
from __future__ import annotations
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def is_scroll_entry(stage):
    """Recognize the native portal cutscene by actual items/actions, not its ID."""
    blocks = [b for group in stage['_levelBlockInfos'] for b in group]
    if any(b.get('enemyInfos') for b in blocks):
        return False
    items = [i for b in blocks for i in b.get('itemInfos', [])]
    actions = [a for i in items for a in i.get('_itemInfoCustom', {}).get('_levelActionDataList', [])]
    return (all(i.get('_itemType') in (81, 100) for i in items)
            and any(i.get('_itemType') == 81 for i in items)
            and any(a.get('_actionType') == 15 and any(
                p.get('_effectName') == 'Portal' for p in a.get('_finalParamList', [])) for a in actions)
            and any(a.get('_actionType') == 5 and any(
                p.get('_changeType') == 14 for p in a.get('_finalParamList', [])) for a in actions))


# These describe the route's initial scene/line context, before its portal.
# They stay intact in the original map; only menu identity excludes them.
ENTRY_CONTEXT = {'_levelID', '_stageRandomGroup', '_themeCtrlGround', '_groundType',
                 '_ninjaBornPos', '_lineSuffix', '_lineIsScaleMode',
                 'addAirGroundAvoidFall', 'addEnemyGround'}


def map_covers(left, right):
    """Same ordered gameplay, allowing an entry route to have fewer candidates."""
    if left['settings'] != right['settings'] or len(left['groups']) != len(right['groups']):
        return False
    for a, b in zip(left['groups'], right['groups']):
        if {k: v for k, v in a.items() if k != '_stageRandomList'} != {
                k: v for k, v in b.items() if k != '_stageRandomList'}:
            return False
        if not all(v in a['_stageRandomList'] for v in b['_stageRandomList']):
            return False
    return True


def unique_maps(pool, maps, content):
    # Prefer an original map containing every candidate, then the shortest entry.
    # Never synthesize a union of pools or alter the client's source groups.
    ordered = sorted(pool.values(), key=lambda v: (
        -sum(len(g['_stageRandomList']) for g in content[v['id']]['groups']),
        content[v['id']]['offset'], v['id']))
    representatives = []
    for entry in ordered:
        identity = entry['id']
        representative = next((v for v in representatives
                               if map_covers(content[v['id']], content[identity])
                               and (content[v['id']]['offset'] != content[identity]['offset']
                                    or (content[v['id']]['groups'] == content[identity]['groups']
                                        and content[v['id']]['context'] == content[identity]['context']))), None)
        if representative is None:
            representatives.append(entry)
        else:
            maps[str(identity)]['menuMap'] = representative['id']
            maps[str(identity)]['menuBoardOffset'] = (
                content[identity]['offset'] - content[representative['id']]['offset'])
    return sorted(representatives, key=lambda v: v['id'])


def has_game_start(stage):
    for group in stage['_levelBlockInfos']:
        for block in group:
            for item in block.get('itemInfos', []):
                if item.get('_itemType') == 3:
                    return True
                if item.get('_itemType') == 100 and any(
                        action.get('_actionType') == 23
                        for action in item.get('_itemInfoCustom', {}).get('_levelActionDataList', [])):
                    return True
    return False


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
    maps, content = {}, {}
    for identity in sorted(map_ids):
        source = json.loads((dataset / f'level_endless_gale_{identity}.bytes.json').read_text())[0]
        if source['_levelDataType']['value__'] != 6:
            raise ValueError('A non-Gale map cannot enter this catalog')
        slots, opening, gameplay = [], [], []
        entry_offset = 0
        in_entry = True
        for group_index, group in enumerate(source['_stageRandomGroup'], 1):
            pool = []
            scroll_pool = True
            for candidate in group['_stageRandomList']:
                stage_id = candidate['_stageID']
                path = dataset / f'stage_endless_gale_{stage_id}.json'
                if not path.exists():
                    raise ValueError(f'Missing Gale board {stage_id}')
                stage = json.loads(path.read_text())
                scroll_pool = scroll_pool and is_scroll_entry(stage)
                if stage.get('_levelDataType', 0) != 6:
                    raise ValueError(f'Non-Gale board {stage_id}')
                blocks = [block for group_ in stage['_levelBlockInfos'] for block in group_]
                pool.append(dict(id=stage_id, weight=candidate['_weight'],
                                 blocks=len(blocks), startsGame=has_game_start(stage), classification=classify_board(stage), entry=entry_info(blocks), opening=stage.get('_stageUseFor') == 1))
            if pool and all(candidate['opening'] for candidate in pool):
                opening.append(dict(group=group_index, pool=pool))
            else:
                slots.append(dict(position=len(slots) + 1, group=group_index, pool=pool))
                if in_entry and pool and scroll_pool:
                    entry_offset += 1
                else:
                    in_entry = False
                    gameplay.append(group)
        loop = []
        for candidate in source.get('_loopRandomStage', {}).get('_stageRandomList', []):
            stage_id = candidate['_stageID']
            stage = json.loads((dataset / f'stage_endless_gale_{stage_id}.json').read_text())
            if stage.get('_levelDataType', 0) != 6:
                raise ValueError(f'Non-Gale loop board {stage_id}')
            blocks = [block for group_ in stage['_levelBlockInfos'] for block in group_]
            loop.append(dict(id=stage_id, weight=candidate['_weight'], blocks=len(blocks), startsGame=has_game_start(stage),
                             classification=classify_board(stage), entry=entry_info(blocks), opening=False))
        maps[str(identity)] = dict(id=identity, ground=source['_groundType']['value__'],
                                   difficulty=source['_difficultyLevel'], opening=opening, slots=slots, loop=loop)
        content[identity] = dict(groups=gameplay, offset=entry_offset,
                                context={k: v for k, v in source.items() if k in ENTRY_CONTEXT
                                         and k not in ('_levelID', '_stageRandomGroup')},
                                settings={k: v for k, v in source.items() if k not in ENTRY_CONTEXT
                                          and not (k == 'changeToStageList' and not v)})
    # The original scroll routes 3..6 begin at absolute levels 3..6.
    # Keep raw route indices for the client; present absolute levels to humans.
    absolute = {}
    for route in sorted(routes, key=lambda v: v['id']):
        offset = route['id'] - 1 if route['id'] >= 3 else 0
        for level in route['levels']:
            ordinal = level['id'] + offset
            target = absolute.setdefault(ordinal, {})
            for identity in level['maps']:
                target.setdefault(identity, dict(id=identity, chapter=route['id'], level=level['id']))
                old = maps[str(identity)].setdefault('absoluteLevel', ordinal)
                if old != ordinal:
                    raise ValueError(f'Conflicting absolute level for map {identity}')
    levels = [dict(id=k, maps=unique_maps(pool, maps, content)) for k, pool in sorted(absolute.items())]
    return dict(version=1, mode=6, routes=sorted(routes, key=lambda v: v['id']), maps=maps, levels=levels)


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
    visible = sum(len(level['maps']) for level in catalog['levels'])
    print(f"Gale catalog: {len(catalog['routes'])} routes, {len(catalog['maps'])} source maps, {visible} menu maps → {a.output}")


if __name__ == '__main__':
    main()
