"""Offline fixed-layout geometry; no client connection or inferred enemy IDs."""
from arena_gale_catalog import classify_board


def enemy_categories(rows):
    categories={}
    for row in rows:
        for value in row['values']:
            name=value.get('resourceName','').lower()
            script=value.get('editInfoScriptName')
            if script=='EnemyInfoSpider'and 'spider'in name:
                categories[value['ID']]=1
            elif script=='EnemyInfoHideBlade':
                categories[value['ID']]=2
    return categories


def resolved_anchors(layout,categories):
    anchors=[]
    for block in layout['blocks']:
        for enemy in block.get('enemies',[]):
            kind=categories.get(enemy['source_type_id'])
            if kind is not None:
                anchors.append([kind,round(block['start_x']-layout['stage_start']+enemy['position'].get('x',0),3)])
    return anchors


def support_anchors(layout):
    points=set()
    for block in layout['blocks']:
        ground=block.get('ground_type')
        if ground==0 or str(ground).startswith('line:'):
            for side in ('start_x','finish_x'):
                points.add((4,round(block[side]-layout['stage_start'],3)))
    return [list(point)for point in sorted(points)]


def expand(stage):
    """Unroll deterministic repeats while preserving original gaps/overlaps.

    Infinite native groups have no static exit length. Their finite declaration
    is exported for inspection but must not become an entire progress model.
    """
    if stage.get('_levelDataType')!=6 or classify_board(stage)['layout']!='fixed':
        raise ValueError('Static expansion requires a fixed Gale layout')
    groups=stage['_levelBlockInfos']
    origin=groups[0][0].get('_pointStart',{}).get('x',0)
    extra=0.
    blocks=[]
    finite=True
    for group_index,group in enumerate(groups):
        block=group[0]
        start=block.get('_pointStart',{}).get('x',0)
        finish=block.get('_pointEnd',{}).get('x',0)
        repeat=block.get('_repeatTimesMin',1)
        if type(repeat)is not int or not 1<=repeat<=1000:
            raise ValueError('Unsupported original repeat count')
        if block.get('_infiniteLoop'):
            finite=False
        for iteration in range(repeat):
            offset=extra+iteration*(finish-start)-origin
            blocks.append(dict(index=len(blocks),source_group=group_index,repeat=iteration,
                ground_type=block.get('_groundType',0),
                start_x=start+offset,finish_x=finish+offset,
                enemies=[dict(source_type_id=e['_enemyType'],position=e.get('_localPosition',{}))
                         for e in block.get('enemyInfos',[])]))
        extra+=(repeat-1)*(finish-start)
    return dict(stage_id=stage['_stageID'],stage_start=0.,blocks=blocks,finite=finite,
                length=max(b['finish_x']for b in blocks)if finite else None)
