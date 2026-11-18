"""Publish static native-proven programs; runtime still requires visual locks."""
import argparse
import hashlib
import json
from pathlib import Path
from arena_fixed_policy import compile_program


def publish(coverage, inventory, destination):
    cases = {c['key']: c for c in inventory['contexts']}
    programs = {}
    for key, evidence in coverage['cases'].items():
        if not evidence.get('native_passed') or not evidence.get('route'):
            continue
        source = Path(evidence['route'])
        route = json.loads(source.read_text())
        case = cases[key]
        observed = route['start']['board']
        if (observed['map'], observed['stage_index']+1, observed['stage_id']) != (
                case['map'], case['slot'], case['stage']):
            raise ValueError('A program source belongs to another board context')
        program = compile_program(route, key)
        program.update(source=str(source), source_sha256=hashlib.sha256(source.read_bytes()).hexdigest(),
                       classification=inventory['stages'][str(case['stage'])]['classification'])
        programs[key] = program
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = dict(schema=1, mode=6, programs=programs, visual_execution_verified=False)
    temporary = destination.with_suffix('.tmp')
    temporary.write_text(json.dumps(result, ensure_ascii=False, indent=2))
    temporary.replace(destination)
    return result


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--queue', type=Path, required=True)
    p.add_argument('--output', type=Path, required=True)
    a = p.parse_args()
    r = publish(json.loads((a.queue/'coverage.json').read_text()), json.loads((a.queue/'inventory.json').read_text()), a.output)
    print('原生已通过程序数:', len(r['programs']))
