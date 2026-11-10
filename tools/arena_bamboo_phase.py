"""Stock YOLO classification of pixel crops proposed by the arena OBB model.

The fixed-size crop preserves the lock animation's ring contraction. Neither
native state nor a board timer supplies a phase label to the running actor.
"""
import hashlib
import json
from pathlib import Path
import time
import cv2
import numpy as np
from arena_yolo import offline_sdk


def reticle_crop(bgr,box,size=64):
    return cv2.getRectSubPix(bgr,(size,size),tuple(map(float,box.center)))


def refine_cues(cues,probabilities,threshold=.8):
    """Keep ambiguous exposures visible without treating them as fresh aiming."""
    output=[];index=0
    for cue in cues:
        if cue.get('motion_kind')!='bamboo':
            output.append(cue);continue
        scores=probabilities[index];index+=1
        best=max(scores,key=scores.get)
        # The native CrossFade initially still resembles the outgoing aim.
        # Two disagreeing visual heads do not prove either side of that onset;
        # in particular they must not assert a new aim after locking started.
        phase=(best if scores[best]>=threshold and(best=='none'or best==cue['phase'])
               else 'uncertain')
        output.append(dict(cue,obb_phase=cue['phase'],phase=phase,
                           phase_scores=scores,phase_confidence=scores[best]))
    if index!=len(probabilities):raise ValueError('Reticle crops and classifications differ')
    return output


class BambooPhaseRefiner:
    def __init__(self,weights,threshold=.8):
        weights=Path(weights)
        profile_path=weights.parent.parent/'profile.json'
        self.profile=json.loads(profile_path.read_text());self.threshold=threshold
        if (self.profile.get('task')!='classify'or self.profile.get('crop_px')!=64
                or self.profile.get('classes')!=['aim','locked','none']):
            raise ValueError('Expected a reviewed 64px bamboo phase classification profile')
        import torch
        torch.set_num_threads(2)
        self.model=offline_sdk().YOLO(str(weights))
        if self.model.task!='classify'or list(self.model.names.values())!=self.profile['classes']:
            raise ValueError('Bamboo phase checkpoint and classes differ')
        self.options=dict(device=0,imgsz=64,verbose=False,quantize=16)
        # Warm the actual batch shapes before live capture. A new reticle count
        # must not cause the first GPU shape setup in the action deadline.
        dummy=np.zeros((64,64,3),np.uint8)
        for size in(1,2,4,8,16,32,64,128,256):self.model.predict([dummy]*size,**self.options)
        self.info=dict(weights=str(weights),sha256=hashlib.sha256(weights.read_bytes()).hexdigest(),
                       profile_sha256=hashlib.sha256(profile_path.read_bytes()).hexdigest(),threshold=threshold,
                       batch_padding='power_of_two',phase_policy='agreement')
        self.last_ms=0.

    def refine(self,bgr,cues):
        self.last_ms=0.
        selected=[c for c in cues if c.get('motion_kind')=='bamboo']
        if not selected:return cues
        begin=time.perf_counter()
        crops=[reticle_crop(bgr,c['box'])for c in selected]
        size=1<<(len(crops)-1).bit_length()
        results=self.model.predict(crops+[crops[-1]]*(size-len(crops)),**self.options)[:len(crops)]
        probabilities=[dict(zip(self.profile['classes'],map(float,r.probs.data.cpu().numpy())))for r in results]
        output=refine_cues(cues,probabilities,self.threshold)
        self.last_ms=(time.perf_counter()-begin)*1000
        return output
