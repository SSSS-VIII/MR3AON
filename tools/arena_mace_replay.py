#!/usr/bin/env python3
"""Pixel-only Mace forecasts, with native geometry scored after estimation."""
from collections import Counter,defaultdict
from copy import deepcopy
from pathlib import Path
import argparse,hashlib,json
import cv2,numpy as np
from arena_arrow_replay import CachedDetector,summary
from arena_obb_detector import ObbPerception
from arena_obb_replay import observe_own_input
from arena_oriented import bounds
from arena_vision import Box
from arena_vision_dataset import continuous_identity
from arena_yolo_obb_data import collider_quad


def review(predictions_path,profile_path,output):
    if output.exists():raise FileExistsError(output)
    cv2.setNumThreads(1);profile=json.loads(profile_path.read_text())
    groups=defaultdict(list)
    for line in predictions_path.open():
        row=json.loads(line);groups[row['episode']].append(row)
    counts=Counter();results=[]
    for episode,predictions in groups.items():
        raw={r['image']:r for r in map(json.loads,(Path(episode)/'labels.jsonl').open())}
        detector=CachedDetector(profile);actor=ObbPerception(detector);previous=None;snapshots=[]
        for row in predictions:
            source=raw[row['image']];rgb=cv2.cvtColor(cv2.imread(str(Path(episode)/row['image'])),cv2.COLOR_BGR2RGB)
            detector.predictions=row['predictions']
            # Native object/state/geometry are not estimator inputs.
            obs=observe_own_input(actor,rgb,source['t'],previous,source.get('previous_action'));previous=source['t']
            snapshots.append(dict(t=source['t'],image=row['image'],camera=obs['camera_reference_y'],tracks=deepcopy(obs['tracks'])))
        # Only now read native identities and full collider targets for scoring.
        truth=[];quads=[]
        for snap in snapshots:
            source=raw[snap['image']];objects={};bodies={}
            for obj in source.get('objects')or[]:
                if obj['type']!='EnemyMace'or obj.get('dead')or not obj.get('renderers'):continue
                for collider in obj.get('colliders')or[]:
                    if collider['type']!='BoxCollider'or collider['tag']!='Enemy':continue
                    q=collider_quad(collider)
                    if q[:,0].min()<3 or q[:,0].max()>637 or q[:,1].min()<60 or q[:,1].max()>355:continue
                    identity=(obj['id'],collider['id']);objects[identity]=(obj,Box(*bounds(q)));bodies[identity]=q
            truth.append((source,None,objects,None));quads.append(bodies)
        times=np.array([s['t']for s in snapshots])
        for i,snap in enumerate(snapshots):
            objects=truth[i][2];counts['visible_native_maces']+=len(objects)
            tracks=[t for t in snap['tracks']if t.collider_shape=='BoxCollider'and t.observations>=3 and t.confidence>=.25]
            pairs=[]
            for identity,(obj,box)in objects.items():
                for j,track in enumerate(tracks):
                    error=float(np.linalg.norm(np.subtract(box.center,track.box.center)))
                    if error<=24:pairs.append((error,identity,j))
            used=set();ids=set()
            for _,identity,j in sorted(pairs):
                if identity in ids or j in used:continue
                ids.add(identity);used.add(j);counts['matched_confirmed_tracks']+=1;track=tracks[j]
                counts['with_mace_models']+=track.kind=='mace'and bool(getattr(track,'models',()))
                for horizon in(.1,.2,.4):
                    end=int(np.argmin(abs(times-snap['t']-horizon)));dt=float(times[end]-snap['t'])
                    if abs(dt-horizon)>.02 or not continuous_identity(truth,i,end,identity):continue
                    obj,_=truth[end][2][identity];q=quads[end][identity].copy();q[:,1]-=snapshots[end]['camera']-snap['camera']
                    target=Box(*bounds(q));forecast=track.future(dt);cx,cy=target.center;pad=4.
                    results.append(dict(episode=episode,image=snap['image'],resource=obj['name'].split('(')[0],horizon=horizon,
                        track_kind=track.kind,models=len(getattr(track,'models',())),
                        center_error_px=float(np.linalg.norm(np.subtract(forecast.center,target.center))),
                        center_covered=forecast.x-pad<=cx<=forecast.x+forecast.w+pad and forecast.y-pad<=cy<=forecast.y+forecast.h+pad,
                        full_box_covered=forecast.x-pad<=target.x and forecast.x+forecast.w+pad>=target.x+target.w and forecast.y-pad<=target.y and forecast.y+forecast.h+pad>=target.y+target.h,
                        area_ratio=forecast.w*forecast.h/max(1.,target.w*target.h)))
    grouped=defaultdict(list)
    for row in results:grouped[f"{row['resource']}/{row['horizon']}"].append(row)
    sources=[predictions_path,profile_path,Path(__file__),*[Path(__file__).with_name(n)for n in
        ('arena_mace_motion.py','arena_vision.py','arena_obb_detector.py','arena_oriented.py',
         'arena_support.py','arena_scene_motion.py','arena_obb_replay.py','arena_arrow_replay.py')]]
    report=dict(counts=dict(counts),by_resource={k:summary(v)for k,v in sorted(grouped.items())},
        by_horizon={str(h):summary([r for r in results if r['horizon']==h])for h in(.1,.2,.4)},
        source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in sources},
        scope='Pixels/time/own keys only, then native full Mace bodies matched and scored. Coverage/area and unmatched targets separate; not native no-hit acceptance.')
    output.mkdir(parents=True)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'forecasts.jsonl').write_text(''.join(json.dumps(r)+'\n'for r in results))
    print(json.dumps(report),flush=True);return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in('predictions','profile','output'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();review(args.predictions,args.profile,args.output)
