#!/usr/bin/env python3
"""Preserve original Unity resources and dependencies for fidelity recovery.

Exports original decrypted serialized files, object payloads, animation/VFX/
shader data and a dependency audit. This is asset recovery, NOT a reconstructed
or validated simulator. No Android input or account files are accessed.
"""
from __future__ import annotations
import argparse
import collections
import hashlib
import json
from pathlib import Path
import re

from arena_client import ClientSource, safe_asset_path, text_asset_bytes, unwrap_bundle


def dependency_closure(manifest, roots):
    names = dict(manifest['AssetBundleNames'])
    ids = {name: key for key, name in names.items()}
    infos = dict(manifest['AssetBundleInfos'])
    seen, order = set(), []
    def visit(key):
        if key in seen:
            return
        if key not in names or key not in infos:
            raise ValueError(f'Missing dependency manifest entry: {key}')
        seen.add(key)
        for dep in infos[key].get('AssetBundleDependencies', []):
            visit(dep)
        order.append(names[key])
    for root in roots:
        if root not in ids:
            raise ValueError(f'Root bundle absent from current manifest: {root}')
        visit(ids[root])
    return order


def write_exact(path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(payload).hexdigest()
    if path.exists() and hashlib.sha256(path.read_bytes()).hexdigest() != digest:
        raise ValueError(f'Conflicting original resource at {path}')
    path.write_bytes(payload)
    return {'bytes': len(payload), 'sha256': digest}


def spine_header(data):
    # Header conventions differ across Spine versions. Report only a version
    # literally present in the original header; never infer from a filename.
    match = re.search(rb'(?<![0-9])([234]\.[0-9]{1,2}\.[0-9]{1,3})(?![0-9])', data[:256])
    return match.group(1).decode() if match else None


def audit_unity_export(project):
    """Detect known exporter substitutions; their absence is not fidelity proof."""
    assets = project / 'Assets'
    if not assets.is_dir():
        raise ValueError(f'Unity Assets directory missing: {assets}')
    shaders = list(assets.rglob('*.shader'))
    scripts = list(assets.rglob('*.cs'))
    placeholders = [str(p.relative_to(project)) for p in shaders
                    if 'DummyShaderTextExporter' in p.read_text(errors='replace')]
    dummy = [str(p.relative_to(project)) for p in scripts
             if 'Dummy class.' in p.read_text(errors='replace')]
    return {'shader_files': len(shaders), 'placeholder_shaders': len(placeholders),
            'script_files': len(scripts), 'dummy_scripts': len(dummy),
            'placeholder_shader_paths': placeholders, 'dummy_script_paths': dummy,
            'ready_for_visual_training': False,
            'reason': 'Export audit does not verify runtime behavior or rendered-frame equivalence'}


def export_recovery(source, manifest, roots, output):
    import UnityPy
    from UnityPy.files import SerializedFile
    order = dependency_closure(manifest, roots)
    env = UnityPy.Environment()
    report = {'schema': 1, 'status': 'asset_recovery_only_not_training_environment',
              'roots': roots, 'dependency_closure': order, 'load_order_note': 'References can be cyclic; load the complete closure before instantiating assets', 'bundles': [], 'errors': [],
              'type_counts': {}, 'spine_versions': [], 'script_classes': [], 'texture_preview_omissions': []}
    before = source.version()
    classes, versions, types = set(), set(), collections.Counter()
    output.mkdir(parents=True, exist_ok=True)
    object_log = (output/'objects.jsonl').open('w')
    try:
        for index, name in enumerate(order):
            data, origin = source.read_bundle(name)
            bundle = env.load_file(unwrap_bundle(data), name=name)
            row = {'name': name, 'source': origin, 'source_sha256': hashlib.sha256(data).hexdigest(),
                   'serialized_files': [], 'container': list(bundle.container)}
            for file_name, child in bundle.files.items():
                relative = safe_asset_path(file_name)
                reader = child.reader if isinstance(child, SerializedFile) else child
                original = bytes(reader.bytes)
                stats = write_exact(output/'serialized'/relative, original)
                row['serialized_files'].append({'name': file_name, **stats})
                if not isinstance(child, SerializedFile):
                    continue
                for obj in child.objects.values():
                    types[obj.type.name] += 1
                    raw = obj.get_raw_data()
                    raw_path = Path('object-payloads')/name/f'{obj.path_id}.{obj.type.name}.bin'
                    record = {'bundle': name, 'serialized_file': file_name, 'path_id': obj.path_id,
                              'type': obj.type.name, 'payload': str(raw_path), **write_exact(output/raw_path, raw)}
                    def binary_ref(value):
                        if not isinstance(value, bytes):
                            raise TypeError(type(value).__name__)
                        digest = hashlib.sha256(value).hexdigest()
                        path = Path('binary-fields')/(digest+'.bin')
                        return {'$binary': str(path), **write_exact(output/path, value)}
                    try:
                        tree = obj.read_typetree()
                        tree_path = Path('type-trees')/name/f'{obj.path_id}.{obj.type.name}.json'
                        target = output/tree_path
                        target.parent.mkdir(parents=True, exist_ok=True)
                        target.write_text(json.dumps(tree, ensure_ascii=True, default=binary_ref)+'\n')
                        record['type_tree'] = str(tree_path)
                        record['name'] = tree.get('m_Name') if isinstance(tree, dict) else None
                        if obj.type.name == 'MonoScript':
                            classes.add(tree.get('m_Namespace','')+'.'+tree.get('m_ClassName',''))
                        if obj.type.name == 'TextAsset':
                            payload = text_asset_bytes(obj)
                            text_path = Path('text-assets')/name/(str(obj.path_id)+'.bytes')
                            write_exact(output/text_path, payload)
                            record['text_asset'] = str(text_path)
                            if '.skel' in (record['name'] or ''):
                                version = spine_header(payload)
                                record['spine_header_version'] = version
                                if version: versions.add(version)
                    except Exception as exc:
                        error = {'bundle': name, 'path_id': obj.path_id, 'type': obj.type.name,
                                 'operation': 'type_tree', 'error': str(exc)}
                        report['errors'].append(error)
                    object_log.write(json.dumps(record, ensure_ascii=False)+'\n')
            report['bundles'].append(row)
            object_log.flush()
            print(f'{index+1}/{len(order)} preserved {name}', flush=True)
        # Decode original texture pixels as inspection files; raw compressed
        # resources and shaders above remain the authoritative recovery input.
        for obj in env.objects:
            if obj.type.name != 'Texture2D':
                continue
            try:
                texture = obj.read()
                if texture.m_Width == 0 and texture.m_Height == 0 and texture.m_CompleteImageSize == 0:
                    report['texture_preview_omissions'].append({'path_id': obj.path_id, 'name': texture.m_Name,
                        'reason': 'Zero-sized serialized texture; runtime pixel generation not restored'})
                    continue
                target = output/'texture-previews'/f"{obj.path_id}-{re.sub(r'[^a-zA-Z0-9_.-]+', '_', texture.m_Name)}.png"
                target.parent.mkdir(parents=True, exist_ok=True)
                texture.image.save(target)
            except Exception as exc:
                report['errors'].append({'path_id': obj.path_id, 'type': 'Texture2D',
                                         'operation': 'texture_preview', 'error': str(exc)})
        if before != source.version():
            raise RuntimeError('Patch version changed during recovery')
        report['type_counts'] = dict(types)
        report['spine_versions'] = sorted(versions)
        report['script_classes'] = sorted(classes)
        report['patch_version_bytes_hex'] = before
        report['limitations'] = ['No game behavior recovered from IL2CPP or encrypted Lua',
                                 'No rendered-frame or collider equivalence verified',
                                 'Bundle dependencies do not include arbitrary runtime string-based loads']
        (output/'recovery.json').write_text(json.dumps(report, ensure_ascii=False, indent=2)+'\n')
        return report
    finally:
        object_log.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--apk', type=Path, required=True)
    parser.add_argument('--dynamic', type=Path, required=True)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--key-file', type=Path)
    parser.add_argument('--root', action='append', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    import UnityPy
    source = ClientSource(args.apk, args.dynamic)
    try:
        key = args.key_file.read_bytes() if args.key_file else source.key()
        UnityPy.set_assetbundle_decrypt_key(key)
        report = export_recovery(source, json.loads(args.manifest.read_text()), args.root, args.output)
        print(json.dumps({'bundles': len(report['bundles']), 'types': report['type_counts'],
                          'spine_versions': report['spine_versions'], 'errors': len(report['errors'])}))
        if report['errors']:
            raise SystemExit(1)
    finally:
        source.close()


if __name__ == '__main__':
    main()
