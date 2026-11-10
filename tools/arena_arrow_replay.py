#!/usr/bin/env python3
"""Score cached pixel forecasts against native arrows only after estimation."""
from collections import Counter,defaultdict
from copy import deepcopy
from dataclasses import asdict
import argparse
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from arena_obb_detector import decode,ObbPerception
from arena_obb_replay import observe_own_input
from arena_vision import Box
from arena_oriented import bounds
from arena_yolo_obb_data import collider_quad,visible_quad
from arena_vision_dataset import continuous_identity


class CachedDetector:
    confidence=.25
    last_ms=0.
    def __init__(self,profile):self.profile=profile;self.reset_tracking();self.predictions=[]
    def reset_tracking(self):self.player_x=180.
    def detect(self,rgb):
        rows=self.predictions
        result=decode([q for c,q,s in rows],[c for c,q,s in rows],[s for c,q,s in rows],self.profile,self.player_x)
        if result[0]is not None:self.player_x=result[0].center[0]
        return result


def summary(rows):
    if not rows:return dict(samples=0)
    errors=[r['center_error_px']for r in rows]
    return dict(samples=len(rows),center_median_px=float(np.median(errors)),center_p95_px=float(np.percentile(errors,95)),
                center_covered=sum(r['center_covered']for r in rows),full_box_covered=sum(r['full_box_covered']for r in rows),
                area_ratio_median=float(np.median([r['area_ratio']for r in rows])),
                area_ratio_p95=float(np.percentile([r['area_ratio']for r in rows],95)))


def review(predictions_path,profile_path,output):
    if output.exists():raise FileExistsError(output)
    profile=json.loads(profile_path.read_text());groups=defaultdict(list);all_counts=Counter();scored=[]
    for line in predictions_path.open():
        row=json.loads(line);groups[row['episode']].append((row['image'],row['predictions']))
    for episode,predictions in groups.items():
        raw={r['image']:r for r in map(json.loads,(Path(episode)/'labels.jsonl').open())}
        detector=CachedDetector(profile);actor=ObbPerception(detector);previous=None;snapshots=[]
        for image,predicted in predictions:
            row=raw[image];detector.predictions=predicted
            pixels=cv2.cvtColor(cv2.imread(str(Path(episode)/image)),cv2.COLOR_BGR2RGB)
            # The estimator receives pixels, exposure time and its submitted
            # preceding key only. No truth from the prediction cache is read.
            obs=observe_own_input(actor,pixels,row['t'],previous,row.get('previous_action'));previous=row['t']
            snapshots.append(dict(t=row['t'],image=image,camera_y=obs['camera_reference_y'],phase=obs['phase'],
                                  terrain=obs['terrain']is not None,terrain_at_player=bool(obs['terrain']and obs['terrain']['at_player']),
                                  tracks=deepcopy(obs['tracks'])))
        # Native identities/states/geometry enter only the scoring pass.
        truth=[]
        for snapshot in snapshots:
            row=raw[snapshot['image']];objects={}
            if row['physics'].split(':')[0]in('runOnGround','slideOnGround'):
                all_counts['native_ground_frames']+=1
                all_counts['visible_terrain_in_native_ground']+=snapshot['terrain']
                all_counts['visible_underfoot_in_native_ground']+=snapshot['terrain_at_player']
            for obj in row.get('objects')or[]:
                if obj['type']!='EnemyArrow'or obj.get('dead')or not obj.get('renderers'):continue
                collider=next((c for c in obj.get('colliders')or[]if c['tag']=='Enemy'and c['type']=='BoxCollider'),None)
                if collider is None:continue
                quad=collider_quad(collider)
                if visible_quad(quad)is None:continue
                # Score a full body only when the whole physical rectangle is
                # visible. Crop growth is a separate detector/entry problem.
                if np.min(quad[:,0])<3 or np.max(quad[:,0])>637 or np.min(quad[:,1])<60 or np.max(quad[:,1])>355:continue
                objects[obj['id']]=(obj,Box(*bounds(quad)))
            truth.append((row,None,objects,None))
        times=np.array([r['t']for r in snapshots])
        for index,snapshot in enumerate(snapshots):
            objects=truth[index][2];tracks=[t for t in snapshot['tracks']if t.collider_shape=='BoxCollider'and t.confidence>=.25 and t.observations>=3]
            all_counts['native_visible_arrows']+=len(objects)
            candidates=[]
            for identity,(obj,box)in objects.items():
                for j,t in enumerate(tracks):
                    distance=float(np.linalg.norm(np.subtract(box.center,t.box.center)))
                    if distance<=24:candidates.append((distance,identity,j))
            used_t=set();used_g=set()
            for distance,identity,j in sorted(candidates):
                if identity in used_g or j in used_t:continue
                used_g.add(identity);used_t.add(j);all_counts['matched_confirmed_tracks']+=1
                obj,current_box=objects[identity];track=tracks[j]
                all_counts['matched_with_arrow_models']+=bool(getattr(track,'models',()))
                for horizon in(.1,.2):
                    end=int(np.argmin(abs(times-snapshot['t']-horizon)));dt=times[end]-snapshot['t']
                    if abs(dt-horizon)>.018 or not continuous_identity(truth,index,end,identity):continue
                    target_obj,target=truth[end][2][identity];prediction=track.future(float(dt))
                    target=Box(target.x,target.y-(snapshots[end]['camera_y']-snapshot['camera_y']),target.w,target.h)
                    cx,cy=target.center;pad=4.
                    scored.append(dict(episode=episode,image=snapshot['image'],horizon=horizon,dt=float(dt),
                        native_id=identity,track_id=track.id,track_kind=track.kind,
                        arrow_models=len(getattr(track,'models',())),has_floor=track.floor_segment is not None,
                        grounded_models=sum(m.grounded for m in getattr(track,'models',())),
                        model_velocity=[(m.vx,m.vy,m.ay)for m in getattr(track,'models',())],
                        scene_velocity_x=getattr(track,'scene_vx',None),
                        transition=obj['controller']['_enemyState'].split(':')[0]+'->'+target_obj['controller']['_enemyState'].split(':')[0],
                        center_error_px=float(np.linalg.norm(np.subtract(prediction.center,target.center))),
                        center_covered=prediction.x-pad<=cx<=prediction.x+prediction.w+pad and prediction.y-pad<=cy<=prediction.y+prediction.h+pad,
                        full_box_covered=prediction.x-pad<=target.x and prediction.x+prediction.w+pad>=target.x+target.w and
                                         prediction.y-pad<=target.y and prediction.y+prediction.h+pad>=target.y+target.h,
                        area_ratio=prediction.w*prediction.h/max(1.,target.w*target.h),
                        prediction=asdict(prediction),target=asdict(target)))
    grouped=defaultdict(list)
    for row in scored:grouped[str(row['horizon'])+'/'+row['transition']].append(row)
    report=dict(counts=dict(all_counts),by_transition={k:summary(v)for k,v in sorted(grouped.items())},
                by_horizon={str(t):summary([r for r in scored if r['horizon']==t])for t in(.1,.2)},
                source_sha256={str(p):hashlib.sha256(p.read_bytes()).hexdigest()for p in
                    (predictions_path,profile_path,Path(__file__),*[Path(__file__).with_name(n)for n in
                     ('arena_arrow_motion.py','arena_vision.py','arena_obb_detector.py','arena_obb_replay.py',
                      'arena_scene_motion.py','arena_object_support.py','arena_support.py','arena_oriented.py')])},
                scope='Cached pixels/own keys only estimator; native state/identity used after estimation. Full visible continuous arrow bodies; geometry recall and area inflation reported separately; not no-hit gameplay.')
    output.mkdir(parents=True)
    (output/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    (output/'forecasts.jsonl').write_text(''.join(json.dumps(r)+'\n'for r in scored))
    print(json.dumps(report),flush=True)
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    for name in('predictions','profile','output'):p.add_argument('--'+name,type=Path,required=True)
    args=p.parse_args();review(args.predictions,args.profile,args.output)
