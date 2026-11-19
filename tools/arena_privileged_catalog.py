"""Mechanism dependencies for every canonical Gale fixed-board context.

Static prefab bindings only scope work. They never prove that a reducer covers
every phase, generated child, item effect, or entry state of a board.
"""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path

from arena_fixed_catalog import load_inventory, ROOT
from arena_privileged_families import FAMILIES

CATALOG = ROOT/'debug/arena-client/yolo/entity-catalog-final'


def dependencies(inventory, entities, prefabs):
    entity_index = {(r['kind'],r['type_id']):r for r in entities}
    families, cases, enemy_ids, item_ids = {}, {}, set(), set()
    for case in inventory['contexts']:
        stage = inventory['stages'][str(case['stage'])]
        mechanisms = stage['mechanism']
        required = []
        unresolved = []
        for identity in map(int,mechanisms['enemy_type_counts']):
            enemy_ids.add(identity)
            entity = entity_index.get(('enemies',identity),{})
            classes = {s['class_name'] for key in entity.get('prefabs',[])
                       for s in prefabs.get(key,{}).get('scripts',[])
                       if s['path'].count('/')==1 and s['class_name'].startswith('Enemy')
                       and s['class_name']!='EnemyBaseCollider'}
            # Three legacy ids have no Cfg/prefab binding. Keep them unresolved
            # until a native instance identifies their concrete implementation.
            if not classes:
                unresolved.append(identity)
            for name in sorted(classes):
                required.append(name)
                family = families.setdefault(name,dict(native_class=name,enemy_ids=set(),
                    contexts=set(),stages=set(),reducer=FAMILIES.get(name),
                    acceptance='pending_native_phase_and_variant_validation'))
                family['enemy_ids'].add(identity);family['contexts'].add(case['key'])
                family['stages'].add(case['stage'])
        items = sorted(map(int,mechanisms['item_type_counts']))
        item_ids.update(items)
        cases[case['key']] = dict(case,enemy_classes=sorted(set(required)),
            unbound_enemy_ids=unresolved,item_type_ids=items,
            unimplemented_enemy_classes=sorted(set(required)-FAMILIES.keys()),
            status='pending',native_no_damage=False,timing_robust=False,
            model_coverage_is_acceptance=False)
    for family in families.values():
        for key in ('enemy_ids','contexts','stages'):
            family[key]=sorted(family[key])
    return dict(schema=1,mode=6,counts=dict(inventory['counts'],
        enemy_type_ids=len(enemy_ids),item_type_ids=len(item_ids),
        enemy_classes=len(families),registered_classes=sum(bool(v['reducer']) for v in families.values()),
        kinds=dict(Counter(c['kind'] for c in cases.values()))),
        scope='All canonical fixed layouts, including motion-random, boss, reward and task contexts; no pass inferred from registration.',
        families=families,cases=cases,item_type_ids=sorted(item_ids),
        additional_work=['generated_child_closure','terrain_and_speed_transitions',
                         'item_effects_and_moving_platforms','boss_and_task_completion'])


def build():
    inventory = load_inventory()
    paths = [CATALOG/'entities.json',CATALOG/'prefabs.json']
    result = dependencies(inventory,*(json.loads(p.read_text()) for p in paths))
    result['sources'] = {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths}
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output',type=Path,required=True)
    args=parser.parse_args()
    report=build();args.output.parent.mkdir(parents=True,exist_ok=True)
    args.output.write_text(json.dumps(report,ensure_ascii=False,indent=2)+'\n')
    print(json.dumps(report['counts'],ensure_ascii=False))


if __name__=='__main__':
    main()
