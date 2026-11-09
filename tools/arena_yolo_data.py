#!/usr/bin/env python3
"""Build standard YOLO detection data from native colliders and original sprites.

Targets are visible enemy collider envelopes and the player's Role capsule.
Native items are negative distractors. Whole episodes are kept in one split.
"""
from __future__ import annotations
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import cv2
import numpy as np
from arena_native_json import normalize_arrays

NAMES=['player','spider','flying','pinball','trap','projectile']
STATE_NAMES=NAMES+['flying_ready','flying_rush']


class MissingControllerState(ValueError):
    pass


def category(resource):
    name=resource.lower()
    if 'spider'in name and 'web'not in name:
        return 1
    if 'pinball'in name:
        return 3
    if any(x in name for x in ('bat','crow','bee','smurf','firefairy','ghostfire')):
        return 2
    if any(x in name for x in ('dart','arrow','smallsword')):
        return 5
    return 4


def envelope(boxes):
    if not boxes:
        return None
    a=np.asarray(boxes,float)
    return np.r_[a[:,:2].min(0),a[:,2:].max(0)]


def clipped(box):
    x1,y1,x2,y2=np.clip(box,[0,0,0,0],[640,360,640,360])
    if x2-x1<2 or y2-y1<2:
        return None
    return [float(x1),float(y1),float(x2),float(y2)]


def annotations(row,states=False):
    row=normalize_arrays(row)
    result=[]
    role=envelope([c['box']for c in row['role']['colliders']])
    if role is not None:
        box=clipped(role)
        if box:result.append((0,box))
    for obj in row.get('objects',[])or[]:
        if obj.get('dead'):
            continue
        # New captures distinguish hidden state from an active EnemyBase. Legacy
        # captures are accepted only for always-rendered basic enemy families.
        resource=obj['name'].split('(Clone)',1)[0]
        if 'renderers'in obj and not obj['renderers']:
            continue
        if 'renderers'not in obj and resource not in ('EnemySpider','EnemyCurveCrow','EnemyStraightCrow','EnemyPinball'):
            continue
        box=envelope([c['box']for c in obj['colliders']])
        if box is None:
            continue
        cx,cy=(box[:2]+box[2:])/2
        if cy<55 or (cy>275 and (cx<135 or cx>515)):
            continue
        box=clipped(box)
        if box:
            cls=category(resource)
            if states and obj['type']=='EnemyStraightBat':
                state=obj.get('controller',{}).get('_currState')
                if state is None:
                    raise MissingControllerState('Visible straight crow lacks native controller state')
                state=state.split(':')[0]
                cls={'ready':6,'rushToNinja':7}.get(state,2)
            result.append((cls,box))
    return result


def label_text(labels):
    lines=[]
    for cls,(x1,y1,x2,y2)in labels:
        lines.append(f'{cls} {(x1+x2)/1280:.7f} {(y1+y2)/720:.7f} {(x2-x1)/640:.7f} {(y2-y1)/360:.7f}\n')
    return ''.join(lines)


def sprite_bank(references):
    bank=[]
    for row in json.loads((references/'references.json').read_text()):
        if row.get('error')or not row.get('image'):
            continue
        image=cv2.imread(str(references/row['image']));box=row.get('appearance_box',row['visual_box'])
        x1,y1,x2,y2=np.clip(np.asarray(box,int),0,256)
        patch=image[y1:y2,x1:x2].astype(np.float32)
        if not patch.size:
            continue
        background=np.median(np.r_[image[:5,:5].reshape(-1,3),image[-5:,-5:].reshape(-1,3)],axis=0)
        alpha=np.clip(np.max(abs(patch-background),axis=2)/14,0,1)
        pixels=np.clip((patch-(1-alpha[:,:,None])*background)/np.maximum(alpha[:,:,None],.02),0,255)
        colliders=[c['box']for c in row.get('colliders',[])if c['configured_enabled']
                   and c['box'][2]-c['box'][0]>1 and c['box'][3]-c['box'][1]>1]
        target=envelope(colliders)
        if row['kind']=='enemies' and target is None:
            continue
        if target is not None:
            target=(target-np.array([x1,y1,x1,y1]))/np.array([x2-x1,y2-y1,x2-x1,y2-y1])
            if np.max(abs(target))>4:
                continue
        bank.append(dict(resource=row['resource'],kind=row['kind'],cls=category(row['resource']),
            pixels=pixels.astype(np.uint8),alpha=alpha,relative_box=target,
            world_h=row['bounds']['height'],world_w=row['bounds']['width']))
    return bank


def synthesize(background,base_labels,bank,rng):
    image=background.copy();labels=list(base_labels);resources=[]
    count=int(rng.integers(3,10))
    for _ in range(count):
        obj=bank[int(rng.integers(len(bank)))];h0,w0=obj['pixels'].shape[:2]
        # Original world bounds anchor the scale; randomized native placement
        # scales cover small targets without resizing every enemy to one size.
        h=int(np.clip(obj['world_h']*41*rng.uniform(.6,1.5),10,180))
        w=int(np.clip(h*w0/h0,3,230))
        if obj['kind']!='enemies':
            h=int(rng.integers(12,35));w=max(4,int(h*w0/h0))
        x=int(rng.integers(65,640-w));y=int(rng.integers(65,max(66,280-h)))
        pixels=cv2.resize(obj['pixels'],(w,h),interpolation=cv2.INTER_LINEAR)
        alpha=cv2.resize(obj['alpha'],(w,h),interpolation=cv2.INTER_LINEAR)[:,:,None]
        image[y:y+h,x:x+w]=(pixels*alpha+image[y:y+h,x:x+w]*(1-alpha)).astype(np.uint8)
        if obj['kind']=='enemies':
            box=obj['relative_box']*np.array([w,h,w,h])+np.array([x,y,x,y])
            box=clipped(box)
            if box:labels.append((obj['cls'],box))
        resources.append(obj['resource'])
    return image,labels,resources


def build(output,train,validation,references,synthetic=1600,states=False):
    overlap={p.resolve()for p in train}&{p.resolve()for p in validation}
    if overlap:
        raise ValueError('Episodes must be disjoint across splits')
    output.mkdir(parents=True,exist_ok=False);cv2.setNumThreads(1)
    records=[];backgrounds=[];counts=Counter()
    for split,folders in [('train',train),('val',validation)]:
        for part in ('images','labels'):
            (output/part/split).mkdir(parents=True)
        for folder in folders:
            for line in(folder/'labels.jsonl').open():
                row=json.loads(line)
                try:labels=annotations(row,states)
                except MissingControllerState:
                    counts[split+'_skipped_missing_state']+=1
                    continue
                name=folder.name+'-'+row['image']
                dest=output/'images'/split/name;dest.symlink_to((folder/row['image']).resolve())
                (output/'labels'/split/Path(name).with_suffix('.txt')).write_text(label_text(labels))
                records.append(dict(split=split,origin='native',episode=str(folder),image=name,labels=len(labels)))
                counts[split+'_native']+=1
                if split=='train'and row['physics']!='runOnLine: 1':
                    # Balance real upside-down/airborne poses without leaking
                    # adjacent frames into validation. These are repeats, not
                    # additional independent observations.
                    for repeat in range(2):
                        duplicate=f'pose{repeat}-'+name
                        (output/'images'/split/duplicate).symlink_to((folder/row['image']).resolve())
                        (output/'labels'/split/Path(duplicate).with_suffix('.txt')).write_text(label_text(labels))
                        records.append(dict(split=split,origin='native_pose_repeat',episode=str(folder),
                                            image=duplicate,labels=len(labels)))
                        counts[split+'_pose_repeat']+=1
                if split=='train'and row['t']<3 and not row.get('objects'):
                    backgrounds.append((folder/row['image'],labels))
    if not backgrounds:
        raise ValueError('Need enemy-free training backgrounds')
    bank=sprite_bank(references)
    if states:
        bank=[r for r in bank if r['resource']!='EnemyStraightCrow']
    for split,n,seed in [('train',synthetic,17),('val',0 if states else max(100,synthetic//6),119)]:
        rng=np.random.default_rng(seed)
        for i in range(n):
            file,base=backgrounds[int(rng.integers(len(backgrounds)))];image=cv2.imread(str(file))
            image,labels,resources=synthesize(image,base,bank,rng)
            name=f'synthetic-{i:06d}.jpg';cv2.imwrite(str(output/'images'/split/name),image,[cv2.IMWRITE_JPEG_QUALITY,94])
            (output/'labels'/split/Path(name).with_suffix('.txt')).write_text(label_text(labels))
            records.append(dict(split=split,origin='composite',image=name,resources=resources,labels=len(labels)))
            counts[split+'_synthetic']+=1
    names=STATE_NAMES if states else NAMES
    config=dict(path=str(output.resolve()),train='images/train',val='images/val',names=names)
    (output/'data.yaml').write_text(json.dumps(config,indent=2)+'\n')
    (output/'manifest.json').write_text(json.dumps(dict(counts=counts,train=[str(p)for p in train],
        validation=[str(p)for p in validation],target='native collider envelope; items negative',
        source_hashes={str(p):hashlib.sha256((p/'labels.jsonl').read_bytes()).hexdigest()for p in train+validation},
        references=str(references),classes=names),indent=2)+'\n')
    (output/'samples.jsonl').write_text(''.join(json.dumps(r)+'\n'for r in records))
    print(json.dumps(dict(counts=counts,templates=len(bank))),flush=True)


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--train',type=Path,nargs='+',required=True);p.add_argument('--validation',type=Path,nargs='+',required=True)
    p.add_argument('--references',type=Path,required=True);p.add_argument('--synthetic',type=int,default=1600)
    p.add_argument('--states',action='store_true',help='Native-labelled straight-crow ready/rush classes')
    a=p.parse_args();build(a.output,a.train,a.validation,a.references,a.synthetic,a.states)
