#!/usr/bin/env python3
"""Score pixel reticle clocks against saved native labels, after estimation.

No client connection or model training. Cached detector outputs and image times
are the estimator input; native IDs, states and colliders enter scoring only.
"""
import argparse
from collections import defaultdict
import json
from pathlib import Path
import numpy as np
from arena_bamboo_motion import BambooClocks
from arena_obb_detector import decode
from arena_oriented import bounds
from arena_support import VisualSupports
from arena_vision import Box
from arena_yolo_obb_data import collider_quad,visible_quad


def review(predictions_path,profile_path):
    profile=json.loads(profile_path.read_text());groups=defaultdict(list);result=[]
    for line in predictions_path.open():
        row=json.loads(line);groups[row['episode']].append(row)
    for episode,predictions in groups.items():
        labels={r['image']:r for r in map(json.loads,(Path(episode)/'labels.jsonl').open())}
        clocks=BambooClocks();supports=VisualSupports();seen=set();pred=[];truth=[];previous={};samples=[]
        for row in predictions:
            raw=labels[row['image']];stamp=raw['t'];objects=row['predictions']
            player,_,segments,_=decode([q for c,q,s in objects],[c for c,q,s in objects],
                                       [s for c,q,s in objects],profile)
            support=supports.observe(segments,player,stamp);camera_y=support['tracking_reference'][1]
            cues=[dict(box=Box(*bounds(q)),phase=profile['classes'][c]['phase'],confidence=s)
                  for c,q,s in objects if profile['classes'][c].get('motion_kind')=='bamboo'
                  and profile['classes'][c]['kind']=='cue']
            clocks.observe(cues,stamp,camera_y)
            forecasts=clocks.forecasts(stamp,support['scene_vx']if support['scene_motion_observed']else None,camera_y)
            for f in forecasts:
                if f.id not in seen:
                    pred.append(dict(id=f.id,lo=f.fire_earliest,hi=f.fire_latest,
                                     y=f.box.center[1]-camera_y,created=stamp));seen.add(f.id)
            # This is the first native-state access after estimator update.
            attacks=[]
            for obj in raw.get('objects',[]):
                if obj.get('type')!='EnemyFlyBamboo'or obj.get('dead'):continue
                state=obj['controller']['_enemyState'].split(':')[0];old=previous.get(obj['id'])
                collider=next((c for c in obj['colliders']if c['name']=='Attack'),None)
                if collider and state=='flyToNinja':
                    quad=collider_quad(collider);y=float(np.mean(quad,axis=0)[1])
                    if visible_quad(quad)is not None:attacks.append(Box(*bounds(quad)))
                    if old and old[1]=='readyAttack'and stamp-old[0]<.08 and 55<y<360:
                        truth.append(dict(id=obj['id'],lo=old[0],hi=stamp,y=y-camera_y))
                previous[obj['id']]=(stamp,state)
            samples.append(dict(t=stamp,camera_y=camera_y,forecasts=forecasts,attacks=attacks))
        candidates=[]
        for i,p in enumerate(pred):
            for j,g in enumerate(truth):
                dt=max(0,g['lo']-p['hi'],p['lo']-g['hi']);dy=abs(p['y']-g['y'])
                if dt<.2 and dy<12:candidates.append((dt+dy*.003,i,j))
        used_p=set();used_g=set();matches=[]
        for _,i,j in sorted(candidates):
            if i in used_p or j in used_g:continue
            used_p.add(i);used_g.add(j);p,g=pred[i],truth[j]
            matches.append(dict(pred=p,truth=g,mid_error_ms=((p['lo']+p['hi']-g['lo']-g['hi'])/2)*1000,
                interval_gap_ms=max(0,g['lo']-p['hi'],p['lo']-g['hi'])*1000,y_error=abs(p['y']-g['y'])))
        coverage={};missed_forecasts=[]
        for horizon in(.0,.2,.4):
            targets=covered=0
            for i,snapshot in enumerate(samples):
                future=min(samples[i:],key=lambda s:abs(s['t']-snapshot['t']-horizon))
                if abs(future['t']-snapshot['t']-horizon)>.018:continue
                boxes=[f.future(future['t']-snapshot['t'])for f in snapshot['forecasts']]
                for attack in future['attacks']:
                    targets+=1;y=attack.center[1]-future['camera_y']+snapshot['camera_y']
                    matched=any(b.x<=attack.x and b.x+b.w>=attack.x+attack.w and
                                abs(b.center[1]-y)<=8 for b in boxes)
                    covered+=matched
                    if not matched:
                        closest=sorted(boxes,key=lambda b:abs(b.center[1]-y))[:2]
                        missed_forecasts.append(dict(t=snapshot['t'],horizon=horizon,
                            attack=dict(x=attack.x,w=attack.w,y=y),
                            nearest=[dict(x=b.x,w=b.w,y=b.center[1])for b in closest]))
            coverage[str(horizon)]=dict(targets=targets,covered=covered,recall=covered/max(1,targets))
        result.append(dict(episode=episode,predictions=len(pred),native_in_view_launches=len(truth),
            matched=len(matches),known_onsets=sum(p['hi']-p['lo']<.2 for p in pred),
            unknown_onsets=sum(p['hi']-p['lo']>=.2 for p in pred),matches=matches,
            unmatched_predictions=[p for i,p in enumerate(pred)if i not in used_p],
            missed_native=[g for j,g in enumerate(truth)if j not in used_g],forecast_coverage=coverage,
            missed_forecasts=missed_forecasts))
    return dict(episodes=result,scope='Pixel clocks only; native data used after estimation. Coverage requires full X box and <=8px center-Y error; it is an uncertainty envelope, not exact trajectory accuracy or no-hit success.')


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    for name in('predictions','profile','output'):parser.add_argument('--'+name,type=Path,required=True)
    args=parser.parse_args();report=review(args.predictions,args.profile)
    with args.output.open('x')as stream:stream.write(json.dumps(report,indent=2)+'\n')
    for r in report['episodes']:
        print(json.dumps({k:v for k,v in r.items()if k not in('matches','unmatched_predictions','missed_native','missed_forecasts')}))
