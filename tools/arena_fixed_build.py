"""Compile labelled local captures into a visual board/progress atlas.

Native metadata labels stored images offline. The deployed matcher receives
neither this loader nor a live client connection. No model weights are trained.
"""
import argparse
import hashlib
import json
import os
import inspect
from functools import cache
from pathlib import Path
import time
import cv2
import numpy as np

from arena_fixed_catalog import CATALOG, DATASET, ROOT
from arena_fixed_match import features, register
from arena_native_json import normalize_arrays
from arena_fixed_static import enemy_categories,resolved_anchors,support_anchors,expand


@cache
def anchor_types():
    rows=json.loads((ROOT/'debug/arena-client/nconfig-all/CfgGameEnemyInfo.json').read_text())
    return enemy_categories(rows)


def layout_anchors(layout):
    return resolved_anchors(normalize_arrays(layout),anchor_types())


def declared_contexts(catalog):
    result=[]
    for level in catalog['levels']:
        for world in level['maps']:
            raw=catalog['maps'][str(world['id'])]
            pools=[s['pool']for s in raw['slots']]+([raw['loop']]if raw['loop']else[])
            for slot,pool in enumerate(pools,1):
                for variant in pool:
                    if variant['classification']['layout']!='fixed':continue
                    path=DATASET/f"stage_endless_gale_{variant['id']}.json"
                    source=path.read_bytes();layout=expand(json.loads(source))
                    anchors=layout_anchors(layout)
                    supports=support_anchors(layout)
                    if not layout['finite']or len(anchors)+len(supports)<3:continue
                    meta=context(catalog,world['id'],slot,variant['id'])
                    result.append(dict(meta,length=layout['length'],blocks=[
                        {k:b[k]for k in ('index','start_x','finish_x')}for b in layout['blocks']],
                        anchors=anchors,support_anchors=supports,layout_origin='source_declaration',
                        anchor_source=dict(path=str(path),sha256=hashlib.sha256(source).hexdigest())))
    return result


def context(catalog, map_id, slot, stage):
    raw = catalog['maps'].get(str(map_id))
    if raw is None:
        return None
    actual = raw.get('menuMap', map_id)
    slot -= raw.get('menuBoardOffset', 0)
    world = catalog['maps'][str(actual)]
    pools = [s['pool'] for s in world['slots']] + ([world['loop']] if world['loop'] else [])
    if not 1 <= slot <= len(pools):
        return None
    variant = next((v for v in pools[slot-1] if v['id'] == stage), None)
    if variant is None:
        return None
    level = world['absoluteLevel']
    return dict(key=f'L{level}-M{actual}-S{slot}-B{stage}', level=level, map=actual,
                slot=slot, stage=stage, loop=slot>len(world['slots']), fixed=variant['classification']['layout'] == 'fixed',
                classification=variant['classification'])


def root_x(row):
    camera = row.get('camera')
    point = row['role'].get('point')
    if camera and point:
        matrix = np.array(camera['world_to_camera'], float).reshape(4, 4)
        projection = camera['projection']
        depth = point['z']
        local = np.array([(point['x']/row['width']*2-1)*depth/projection[0],
                          (1-point['y']/row['height']*2)*depth/projection[5], -depth, 1.])
        return float((np.linalg.inv(matrix) @ local)[0])
    for collider in row['role']['colliders']:
        if 'local_to_world' in collider:
            return float(collider['local_to_world'][3])
    return None


def legacy_samples(folder, catalog, step=5.):
    folder = Path(folder)
    try:
        setup = json.loads((folder/'setup.json').read_text())
        layout = normalize_arrays(json.loads((folder/'layout.json').read_text()))
    except (OSError, ValueError):
        return
    map_id = setup.get('map', setup.get('initial', {}).get('map'))
    seen = set()
    with (folder/'labels.jsonl').open() as stream:
        for line in stream:
            row = normalize_arrays(json.loads(line))
            if row.get('stage_id') != layout.get('stage_id') or 'stage_index' not in row:
                continue
            meta = context(catalog, map_id, row['stage_index']+1, row['stage_id'])
            if meta is None:
                continue
            x = root_x(row)
            if x is None:
                continue
            local = x-layout['stage_start']
            length = max(b['finish_x'] for b in layout['blocks'])-layout['stage_start']
            if not 0 <= local <= length:
                continue
            cell = int(local/step)
            if cell in seen:
                continue
            image = folder / row.get('image', f"{row['index']:06d}.png")
            if not image.is_file():
                continue
            seen.add(cell)
            yield dict(meta, image=str(image), local_x=local, length=length,
                anchors=layout_anchors(layout),
                episode=str(folder), blocks=[dict(index=b['index'], start_x=b['start_x']-layout['stage_start'],
                    finish_x=b['finish_x']-layout['stage_start']) for b in layout['blocks']],
                native_tick=row.get('tick'), native_phase=row.get('physics'),
                root_screen_x=row['role'].get('point', {}).get('x'))


def search_samples(path, catalog):
    path = Path(path)
    for row in json.loads(path.read_text()):
        board = row['board']
        meta = context(catalog, board['map'], board['stage_index']+1, board['stage_id'])
        if meta is None:
            continue
        layout = row['layout']
        yield dict(meta, image=str(path.parent/row['image']), local_x=row['local_x'],
            anchors=layout_anchors(layout),
            length=max(b['finish_x'] for b in layout['blocks'])-layout['stage_start'],
            episode=str(path.parent), native_tick=row.get('tick'), native_phase=row['state']['physics'],
            blocks=[dict(index=b['index'], start_x=b['start_x']-layout['stage_start'],
                         finish_x=b['finish_x']-layout['stage_start']) for b in layout['blocks']])


def build(samples, output, detector, *, per_case=96, detector_sha256=None, cache=None, declarations=()):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    rows, values, contexts = [], [], {c['key']:c for c in declarations}
    grouped={}
    for sample in samples:
        grouped.setdefault(sample['key'],[]).append(sample)
    selected=[]
    for group in grouped.values():
        # Keep the exit of long/repeated boards too, rather than truncating
        # the first 96 pictures and leaving the rest of the board unlocatable.
        selected.extend(group[i]for i in np.linspace(0,len(group)-1,min(per_case,len(group)),dtype=int))
    cache=Path(cache)if cache else None
    if cache is not None:cache.mkdir(parents=True,exist_ok=True)
    feature_code=inspect.getsource(features)+inspect.getsource(__import__('arena_fixed_match').semantic)
    feature_sha=hashlib.sha256(feature_code.encode()).hexdigest()
    detector_sources={str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in [*sorted((ROOT/'tools').glob('arena_*.py')),
                     *sorted((ROOT/'arena').glob('vision-*.json'))]}
    detector_signature=hashlib.sha256(json.dumps([detector_sources,getattr(detector,'options',{})],
        sort_keys=True,default=str).encode()).hexdigest()
    for sample in selected:
        key = sample['key']
        raw=Path(sample['image']).read_bytes()
        image_sha=hashlib.sha256(raw).hexdigest()
        fingerprint=hashlib.sha256(json.dumps([image_sha,detector_sha256,feature_sha,detector_signature,
            sample.get('root_screen_x')],sort_keys=True).encode()).hexdigest()
        cached=cache/(fingerprint+'.npz')if cache else None
        image = cv2.imread(sample['image'])
        if image is None:
            continue
        rgb = cv2.cvtColor(cv2.resize(image, (640, 360)), cv2.COLOR_BGR2RGB)
        if float(((rgb[:, :, 0] > 180) & (rgb[:, :, 1] < 90) & (rgb[:, :, 2] > 180)).mean()) > .01:
            continue
        if cached is not None and cached.is_file():
            with np.load(cached,allow_pickle=False)as archive:
                value={k:archive[k]for k in archive.files}
        else:
            found = detector.detect(rgb)
            observation = dict(player=found[0], detections=found[1],
                               visible_supports=found[2] if len(found)>2 else [],
                               root_screen_x=sample.get('root_screen_x'))
            value = features(rgb, observation)
            if cached is not None:np.savez_compressed(cached,**value)
        if value['count'] < 8:
            continue
        row = {k: v for k, v in sample.items() if k not in ('blocks', 'length','anchors')}
        row['image_sha256'] = image_sha
        rows.append(row)
        values.append(value)
        contexts.setdefault(key, {k: sample[k] for k in ('key','level','map','slot','stage','loop','fixed','classification','length','blocks')})
        if contexts[key].get('layout_origin')=='source_declaration':
            contexts[key].update(length=sample['length'],blocks=sample['blocks'],layout_origin='native_reference')
        if sample.get('anchors')and sample['fixed']:
            contexts[key].setdefault('anchors',sample['anchors'])
        if len(rows) % 100 == 0:
            print(f'视觉参考编译 {len(rows)}帧 / {len(contexts)}场景', flush=True)
    # Calibrate the actual parallax layer from labelled movement in the same
    # capture, never by assuming that background pixels use the player scale.
    for key, meta in contexts.items():
        scales = []
        by_episode = {}
        for i, row in enumerate(rows):
            if row['key'] == key:
                by_episode.setdefault(row['episode'], []).append(i)
        for indices in by_episode.values():
            indices.sort(key=lambda i: rows[i]['local_x'])
            for a, b in zip(indices, indices[1:]):
                delta = rows[b]['local_x']-rows[a]['local_x']
                if not .5 < delta < 18:
                    continue
                aligned = register(values[a], values[b])
                if aligned:
                    scale = -aligned['dx']/delta
                    if .5 < scale < 26:
                        scales.append(scale)
        if len(scales) >= 2:
            median = float(np.median(scales))
            mad = float(np.median(np.abs(np.asarray(scales)-median)))
            if mad < .25*median:
                meta.update(background_scale=median, background_scale_mad=mad, calibration_pairs=len(scales))
    np.savez_compressed(output/'features.npz', **{k: np.asarray([v[k] for v in values])
                                                 for k in ('coarse','points','descriptors','count','semantic','landmarks','landmark_count')})
    result = dict(schema=1, mode=6, detector_sha256=detector_sha256,feature_sha256=feature_sha,
                  detector_sources=detector_sources,detector_signature=detector_signature,references=rows,
                  contexts=list(contexts.values()), native_metadata_used='Offline image annotation only',
                  source='Same standard YOLO detector as the runtime, plus original labelled captures')
    (output/'index.json').write_text(json.dumps(result, ensure_ascii=False, indent=2))
    return result


def main():
    from arena_yolo_detector import make_perception, DEFAULT_WEIGHTS
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--legacy-root', type=Path, action='append', default=[])
    p.add_argument('--references', type=Path, action='append', default=[])
    p.add_argument('--queue',type=Path)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--weights', type=Path, default=DEFAULT_WEIGHTS)
    p.add_argument('--per-case', type=int, default=96)
    args = p.parse_args()
    catalog = json.loads(CATALOG.read_text())
    coverage=json.loads((args.queue/'coverage.json').read_text())if args.queue else None
    def samples():
        for path in args.references:
            yield from search_samples(path, catalog)
        if coverage:
            for item in coverage['cases'].values():
                if item['native_passed']and item.get('references'):
                    yield from search_samples(item['references'],catalog)
        for root in args.legacy_root:
            for layout in root.rglob('layout.json'):
                if layout.with_name('labels.jsonl').is_file():
                    yield from legacy_samples(layout.parent, catalog)
    detector = make_perception(args.weights).detector
    result = build(samples(), args.output, detector, per_case=args.per_case,
                   detector_sha256=hashlib.sha256(args.weights.read_bytes()).hexdigest(),
                   cache=args.output.parent/'feature-cache',declarations=declared_contexts(catalog))
    print(json.dumps(dict(references=len(result['references']), contexts=len(result['contexts']))), flush=True)


if __name__ == '__main__':
    for key in ('OMP_NUM_THREADS','OPENBLAS_NUM_THREADS','MKL_NUM_THREADS'):
        os.environ[key] = '1'
    cv2.setNumThreads(1)
    main()
