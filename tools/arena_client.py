#!/usr/bin/env python3
"""Export local Unity client resources. Does not connect to or control Android.

Use a separately created venv with tools/arena-requirements.txt. Proprietary
resources and recovered resource keys belong in an ignored local directory.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import re
import struct
import zipfile

from arena_nrbf import NrbfReader


def unwrap_bundle(data):
    # Current client prepends 78 bytes, including a duplicate UnityFS header.
    if data[:8] == b'UnityFS\0' and data[78:86] == b'UnityFS\0':
        inner = data[78:]
        pos = 12
        for _ in range(2):
            pos = inner.index(b'\0', pos) + 1
        declared = struct.unpack_from('>Q', inner, pos)[0]
        if declared != len(inner):
            raise ValueError('Wrapped bundle length does not match its header')
        return inner
    return data


def find_bundle_key(bundle, metadata):
    from Crypto.Cipher import AES
    data = unwrap_bundle(bundle)
    if data[:8] != b'UnityFS\0':
        raise ValueError('Not a UnityFS bundle')
    pos = 12
    for _ in range(2):
        pos = data.index(b'\0', pos) + 1
    flags = struct.unpack_from('>I', data, pos + 16)[0]
    if not flags & 0x1000:
        raise ValueError('Reference bundle does not use the expected encryption format')
    pos += 20 + 4  # Bundle header, then encryption version.
    data_sig = data[pos + 33:pos + 49]
    key_sig = data[pos + 49:pos + 65]
    for source in (metadata, bytes(x ^ 0x66 for x in metadata)):
        seen = set()
        for match in re.finditer(rb'(?=([A-Za-z0-9_]{16}))', source):
            key = match.group(1)
            if key in seen:
                continue
            seen.add(key)
            cipher = AES.new(key, AES.MODE_ECB).encrypt(key_sig)
            if bytes(x ^ y for x, y in zip(cipher, data_sig)) == b'#$unity3dchina!@':
                return key
    raise ValueError('No matching resource key found in this client metadata')


def text_asset_bytes(obj):
    """Keep binary TextAssets exact, without decoding their payload as text."""
    raw = obj.get_raw_data()
    name_len = struct.unpack_from('<I', raw)[0]
    pos = (4 + name_len + 3) & ~3
    size = struct.unpack_from('<I', raw, pos)[0]
    payload = raw[pos + 4:pos + 4 + size]
    if len(payload) != size:
        raise ValueError('Truncated TextAsset')
    return payload


def safe_asset_path(asset):
    path = PurePosixPath(asset)
    if path.is_absolute() or not path.parts or any(p in ('..', '') for p in path.parts) or '\\' in asset:
        raise ValueError('Unsafe asset path')
    return Path(*path.parts)


def summarize_stage(stage):
    blocks = [block for group in stage.get('_levelBlockInfos', []) for block in group]
    return {
        'level_data_type': stage.get('_levelDataType'), 'stage_id': stage.get('_stageID'),
        'blocks': len(blocks),
        'raw_ninja_speeds': sorted({b['_ninjaSpeed'] for b in blocks if '_ninjaSpeed' in b}),
        'enemies': sum(len(b.get('enemyInfos', [])) for b in blocks),
        'items': sum(len(b.get('itemInfos', [])) for b in blocks),
        'speed_units': 'client world units; runtime override and seconds conversion not verified',
    }


class ClientSource:
    def __init__(self, apk, dynamic):
        self.apk = Path(apk)
        self.dynamic = Path(dynamic) if dynamic else None
        if self.dynamic is not None:
            # is_file()/exists() can hide EACCES as False and quietly select the
            # old APK instead. An explicit dynamic source must be readable.
            self.dynamic.stat()
            next((self.dynamic / 'AssetBundles').iterdir(),None)
        self.zip = zipfile.ZipFile(apk)

    def bundles(self):
        names = {PurePosixPath(n).name for n in self.zip.namelist()
                 if n.startswith('assets/AssetBundles/') and n.endswith('.ab')}
        if self.dynamic:
            names.update(p.name for p in (self.dynamic / 'AssetBundles').glob('*.ab'))
        return sorted(names)

    def read_bundle(self, name):
        if PurePosixPath(name).name != name:
            raise ValueError('Bundle name must not contain a directory')
        path = self.dynamic / 'AssetBundles' / name if self.dynamic else None
        try:
            before=path.stat() if path else None
        except FileNotFoundError:
            before=None
        if before is not None:
            blob = path.read_bytes()
            after = path.stat()
            if (before.st_ino, before.st_size, before.st_mtime_ns) != (after.st_ino, after.st_size, after.st_mtime_ns):
                raise RuntimeError('Resource changed during extraction; retry after the client patch finishes')
            return blob, 'dynamic'
        return self.zip.read('assets/AssetBundles/' + name), 'apk'

    def key(self):
        path = self.dynamic / 'AssetBundles/AssetBundles' if self.dynamic else None
        if not path or not path.exists():
            raise ValueError('Provide the current DynamicContent directory to discover its resource key')
        metadata = self.zip.read('assets/bin/Data/Managed/Metadata/global-metadata.dat')
        return find_bundle_key(path.read_bytes(), metadata)

    def version(self):
        path = self.dynamic / 'PatchVersion' if self.dynamic else None
        if path is None:
            return None
        try:
            return path.read_bytes().hex()
        except FileNotFoundError:
            return None

    def close(self):
        self.zip.close()


def export_bundle(source, name, output, asset_pattern):
    import UnityPy
    blob, origin = source.read_bundle(name)
    env = UnityPy.load(unwrap_bundle(blob))
    info = {'bundle': name, 'source': origin, 'sha256': hashlib.sha256(blob).hexdigest(),
            'size': len(blob), 'container': list(env.container), 'exports': []}
    for asset, obj in env.container.items():
        if not asset_pattern.search(asset):
            continue
        obj = obj.deref()
        target = output / 'assets' / safe_asset_path(asset)
        target.parent.mkdir(parents=True, exist_ok=True)
        entry = {'asset': asset, 'type': obj.type.name, 'path_id': obj.path_id}
        if obj.type.name == 'TextAsset':
            payload = text_asset_bytes(obj)
            target.write_bytes(payload)
            entry.update(bytes=len(payload), sha256=hashlib.sha256(payload).hexdigest())
            if payload.startswith(b'\0\1\0\0\0'):
                parsed = NrbfReader(payload).parse().expanded()
                target.with_suffix(target.suffix + '.json').write_text(json.dumps(parsed, ensure_ascii=False, indent=2) + '\n')
                entry['decoded_format'] = 'NRBF structural graph'
            elif asset.endswith('.json'):
                parsed = json.loads(payload)
                if isinstance(parsed, dict) and '_levelBlockInfos' in parsed:
                    entry['stage'] = summarize_stage(parsed)
        else:
            parsed = obj.read_typetree()
            target.with_suffix(target.suffix + '.json').write_text(
                json.dumps(parsed, ensure_ascii=False, indent=2,
                           default=lambda x: {'$bytes_hex': x.hex()} if isinstance(x, bytes) else str(x)) + '\n')
        info['exports'].append(entry)
    if any(e['type'] != 'TextAsset' for e in info['exports']):
        structural = []
        for obj in env.objects:
            if obj.type.name in ('MonoBehaviour', 'MonoScript', 'GameObject', 'Transform', 'BoxCollider2D', 'CircleCollider2D', 'CapsuleCollider2D', 'PolygonCollider2D', 'EdgeCollider2D', 'Rigidbody2D', 'CapsuleCollider', 'SphereCollider', 'BoxCollider', 'MeshCollider', 'Rigidbody'):
                structural.append({'path_id': obj.path_id, 'type': obj.type.name, 'data': obj.read_typetree()})
        info['ninja_parameters'] = ninja_parameters(structural)
        target = output / 'objects' / (name + '.json')
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(json.dumps(structural, ensure_ascii=False, indent=2, default=lambda x: {'$bytes_hex': x.hex()} if isinstance(x, bytes) else str(x)) + '\n')
    return info


def ninja_parameters(objects):
    """Select actual Ninja components; keep NinjaCopy and enemies out."""
    scripts = {x['path_id']: x['data'].get('m_ClassName')
               for x in objects if x['type'] == 'MonoScript'}
    game_objects = {x['path_id']: x['data'] for x in objects if x['type'] == 'GameObject'}
    result = []
    for obj in objects:
        if obj['type'] != 'MonoBehaviour':
            continue
        data = obj['data']
        script = data.get('m_Script', {})
        if script.get('m_FileID') != 0:
            continue
        name = scripts.get(script.get('m_PathID'))
        go_id = data.get('m_GameObject', {}).get('m_PathID')
        go = game_objects.get(go_id, {})
        context = {'component_path_id': obj['path_id'], 'script': name,
                   'game_object_path_id': go_id, 'game_object_name': go.get('m_Name'),
                   'game_object_active': go.get('m_IsActive')}
        if name == 'Ninja' and '_ninjaData' in data:
            result.append({**context, 'ninja_data': data['_ninjaData'],
                           'main_collider_component_path_id': data.get('_ninjiaCollider', {}).get('m_PathID')})
        elif name == 'NinjaCollider':
            result.append({**context, 'collider_data': {k: v for k, v in data.items()
                                             if 'Collider' in k or 'collider' in k}})
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', required=True, type=Path)
    parser.add_argument('--dynamic', type=Path, help='Current client DynamicContent directory')
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--bundle', action='append', default=[], help='Explicit bundle name; repeated')
    parser.add_argument('--assets', default=r'/binarydatas/leveldata/(?:endless|endless_gale)/', help='Asset path regex to export')
    parser.add_argument('--key-file', type=Path, help='Optional local resource key; never printed')
    parser.add_argument('--index-only', action='store_true')
    args = parser.parse_args()
    import UnityPy
    source = ClientSource(args.apk, args.dynamic)
    try:
        key = args.key_file.read_bytes() if args.key_file else source.key()
        UnityPy.set_assetbundle_decrypt_key(key)
        args.output.mkdir(parents=True, exist_ok=True)
        version_before = source.version()
        pattern = re.compile(args.assets, re.I)
        names = args.bundle or source.bundles()
        report = args.output / 'resources.jsonl'
        with report.open('w') as stream:
            for index, name in enumerate(names, 1):
                if args.index_only:
                    blob, origin = source.read_bundle(name)
                    env = UnityPy.load(unwrap_bundle(blob))
                    info = {'bundle': name, 'source': origin, 'size': len(blob), 'sha256': hashlib.sha256(blob).hexdigest(), 'container': list(env.container)}
                else:
                    info = export_bundle(source, name, args.output, pattern)
                stream.write(json.dumps(info, ensure_ascii=False) + '\n')
                stream.flush()
                if index % 100 == 0 or len(names) < 100:
                    print(f'{index}/{len(names)} {name}', flush=True)
        if source.version() != version_before:
            raise RuntimeError('Client patch version changed; the export must be repeated')
        metadata = source.zip.read('assets/bin/Data/Managed/Metadata/global-metadata.dat')
        client = {'apk': str(source.apk.resolve()), 'apk_size': source.apk.stat().st_size,
                  'metadata_sha256': hashlib.sha256(metadata).hexdigest(),
                  'dynamic': str(source.dynamic) if source.dynamic else None,
                  'patch_version_bytes_hex': version_before, 'bundles_processed': len(names),
                  'asset_filter': args.assets, 'index_only': args.index_only,
                  'scope': 'local static resources; runtime selection, overrides and physics require separate verification'}
        (args.output / 'client.json').write_text(json.dumps(client, ensure_ascii=False, indent=2) + '\n')
    finally:
        source.close()


if __name__ == '__main__':
    main()
