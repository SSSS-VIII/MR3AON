"""Replay paired native labels for metrics/training; no privileged actor input."""
from collections import Counter, defaultdict
import copy
import json
from pathlib import Path
import cv2
import numpy as np
from arena_vision import Box, Perception
from arena_native_json import normalize_arrays


def native_box(row):
    boxes=[c['box'] for c in row['colliders']]
    if not boxes:
        return None
    # Union is an annotation envelope. Collider purpose/activation needs separate
    # verification; neither damage geometry nor a solid box is implied.
    a=np.asarray(boxes)
    x,y=a[:,:2].min(0);right,bottom=a[:,2:].max(0)
    return Box(float(x),float(y),float(right-x),float(bottom-y))


def objects(row, visible=False):
    row=normalize_arrays(row)
    out={}
    for obj in row.get('objects',[]) or []:
        box=native_box(obj)
        if box and (not visible or 85<box.center[0]<615 and 65<box.center[1]<330):
            out[obj['id']]=(obj,box)
    return out


def in_roi(box):
    return 85<box.center[0]<615 and 65<box.center[1]<330


def match(tracks, truth):
    pairs=[]
    for i,t in enumerate(tracks):
        if t.confidence<.7:
            continue
        for identity,(obj,box) in truth.items():
            distance=np.linalg.norm(np.asarray(t.box.center)-box.center)
            if distance<max(28,min(55,box.w*.6)):
                pairs.append((distance,i,identity))
    used=set();assigned={}
    for distance,i,identity in sorted(pairs):
        if i not in used and identity not in assigned:
            used.add(i);assigned[identity]=(tracks[i],distance)
    return assigned


def replay(folder,perception=None):
    folder=Path(folder)
    labels=[json.loads(line) for line in (folder/'labels.jsonl').read_text().splitlines()]
    perception=perception or Perception()
    for row in labels:
        image=cv2.cvtColor(cv2.imread(str(folder/row['image'])),cv2.COLOR_BGR2RGB)
        # Tracker objects mutate on subsequent observations. Freeze each replay
        # sample before retaining it for future-label alignment.
        obs=copy.deepcopy(perception.observe(image,row['t']))
        yield row,obs,objects(row),match([t for t in obs['tracks']if in_roi(t.box)],objects(row,True))


def continuous_identity(rows,start,end,identity):
    """Reject absent/recycled native pool IDs before scoring a future target.

    InstanceID identifies the pooled component, not one spawn. An absence,
    resource change or teleport must not be scored as a movement prediction.
    """
    previous=None
    for row,_,truth,_ in rows[start:end+1]:
        if identity not in truth:
            return False
        obj,box=truth[identity]
        if previous:
            before,old,stamp=previous
            if (obj.get('name')!=before.get('name') or obj['type']!=before['type']
                    or np.linalg.norm(np.subtract(box.center,old.center))>
                       max(96,2500*(row['t']-stamp))):
                return False
        previous=obj,box,row['t']
    return True


def audit(folder,forecaster=None,perception=None):
    counts=Counter();errors=defaultdict(list);forecast=defaultdict(list)
    rows=list(replay(folder,perception));times=np.asarray([r[0]['t'] for r in rows])
    for index,(row,obs,truth,assigned) in enumerate(rows):
        visible=objects(row,True)
        counts['visible']+=len(visible)
        counts['proposals']+=sum(bool(t.confidence>=.7 and in_roi(t.box)) for t in obs['tracks'])
        counts['matched']+=len(assigned)
        for identity,(track,distance) in assigned.items():
            obj,box=truth[identity]
            errors[obj['type']].append(distance)
            for horizon in (.2,.4,.6):
                j=int(np.argmin(abs(times-row['t']-horizon)))
                actual=times[j]-row['t']
                if abs(actual-horizon)>.045 or identity not in rows[j][2] or track.observations<4:
                    continue
                if not continuous_identity(rows,index,j,identity):
                    counts['skipped_pool_reuse']+=1
                    continue
                future=rows[j][2][identity][1]
                predicted=forecaster.predict(track,actual) if forecaster else track.future(actual)
                error=float(np.linalg.norm(np.asarray(predicted.center)-future.center))
                forecast[f'{obj["type"]}@{horizon}'].append(error)
    def stats(values):
        return dict(n=len(values),median=float(np.median(values)),p90=float(np.percentile(values,90)),
                    mean=float(np.mean(values)))
    return dict(folder=str(folder),counts=dict(counts),recall=counts['matched']/max(1,counts['visible']),
        precision=counts['matched']/max(1,counts['proposals']),centers={k:stats(v)for k,v in errors.items()},
        prediction={k:stats(v)for k,v in forecast.items()})


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('folders',type=Path,nargs='+')
    args=parser.parse_args()
    cv2.setNumThreads(1)
    for folder in args.folders:
        print(json.dumps(audit(folder)),flush=True)
