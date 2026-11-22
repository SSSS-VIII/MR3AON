"""Check duplicate candidates within each independent Maa route list.

maa-checker 1.2.7 merges next and on_error before checking duplicates. Maa
executes these lists separately, so sharing a fallback between them is valid.
"""
import argparse
import json
from pathlib import Path
import re


def route_key(route):
    if isinstance(route, str):
        attrs = re.findall(r'^((?:\[[^\]]+\])+)', route)
        prefix = attrs[0] if attrs else ''
        return route[len(prefix):], '[Anchor]' in prefix
    return route['name'], route.get('anchor', False)


def duplicate_routes(value, location='$'):
    if isinstance(value, dict):
        for field, routes in value.items():
            path = f'{location}.{field}'
            if field in ('next', 'on_error') and isinstance(routes, list):
                seen = set()
                for index, route in enumerate(routes):
                    key = route_key(route)
                    if key in seen:
                        yield f'{path}[{index}]: duplicate route {key[0]}'
                    seen.add(key)
            yield from duplicate_routes(routes, path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from duplicate_routes(child, f'{location}[{index}]')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('paths', type=Path, nargs='+')
    args = parser.parse_args()
    files = set()
    for path in args.paths:
        if not path.exists():
            parser.error(f'path does not exist: {path}')
        files.update(path.rglob('*.json') if path.is_dir() else [path])
    failed = False
    for path in sorted(files):
        for error in duplicate_routes(json.loads(path.read_text(encoding='utf-8'))):
            print(f'{path}: {error}')
            failed = True
    print(f'Checked route lists in {len(files)} files.')
    return int(failed)


if __name__ == '__main__':
    raise SystemExit(main())
