"""Canonical Gale fixed-board contexts and explicit coverage denominators."""
import hashlib
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CATALOG = ROOT / 'debug/arena-client/gameonly/gale-catalog-native.json'
DATASET = ROOT / 'debug/arena-client/dataset/assets/assets/gameresources/binarydatas/leveldata/endless_gale'


def inventory(catalog, dataset):
    from arena_board_audit import mechanism
    if catalog.get('mode') != 6:
        raise ValueError('Only the original Gale catalog is supported')
    contexts, stages = [], {}
    for level in catalog['levels']:
        for ref in level['maps']:
            world = catalog['maps'][str(ref['id'])]
            if world.get('menuMap'):
                raise ValueError('Enumerate canonical maps, not their portal aliases')
            slots = list(world['slots'])
            if world.get('loop'):
                slots.append(dict(position=len(slots) + 1, pool=world['loop'], loop=True))
            for slot in slots:
                for variant in slot['pool']:
                    if variant['classification']['layout'] != 'fixed':
                        continue
                    identity = variant['id']
                    if identity not in stages:
                        source = Path(dataset) / f'stage_endless_gale_{identity}.json'
                        raw = source.read_bytes()
                        body = json.loads(raw)
                        if body.get('_levelDataType') != 6 or body['_stageID'] != identity:
                            raise ValueError('Fixed-board source does not belong to Gale')
                        stages[identity] = dict(stage=identity, classification=variant['classification'],
                            source=str(source), sha256=hashlib.sha256(raw).hexdigest(),
                            mechanism=mechanism(body), groups=[dict(index=i, alternatives=len(group),
                              repeats=[dict(min=b.get('_repeatTimesMin', 1), max=b.get('_repeatTimesMax', 1),
                                            infinite=bool(b.get('_infiniteLoop'))) for b in group])
                              for i, group in enumerate(body['_levelBlockInfos'])])
                    key = f"L{level['id']}-M{ref['id']}-S{slot['position']}-B{identity}"
                    contexts.append(dict(key=key, level=level['id'], map=ref['id'], slot=slot['position'],
                        stage=identity, loop=bool(slot.get('loop')), kind=stages[identity]['mechanism']['kind'],
                        motion_random=variant['classification']['motion'] == 'random',
                        selection=dict(chapter=ref['chapter'], level=ref['level'], map=ref['id'],
                                       start=slot['position'], pins={str(slot['position']): identity})))
    return dict(schema=1, mode=6, counts=dict(unique_fixed=len(stages), contexts=len(contexts)),
                stages={str(k): v for k, v in stages.items()}, contexts=contexts)


def load_inventory():
    return inventory(json.loads(CATALOG.read_text()), DATASET)
