"""Optional stock YOLO classifier to confirm solid walls from support pixels."""
from pathlib import Path
import hashlib
import time
import cv2
import numpy as np

KINDS=('floating_platform','platform','rope')
THRESHOLD=.995
CROP=128


def crop_center(segment):
    """Only the visible leading-end distribution validated for this model."""
    if segment.get('kind')not in('floating_platform','rope'):return None
    a,b=np.asarray(segment['a'],float),np.asarray(segment['b'],float)
    if a.shape!=(2,)or b.shape!=(2,)or not np.isfinite([a,b]).all():return None
    if not 16<a[0]<620 or not 48<a[1]<320 or b[0]-a[0]<16:return None
    return float(a[0]+48.),float(a[1]+32.)


class SupportTypeRefiner:
    """Confirm solid ground, preserving detected geometry/confidence.

    Default detector construction does not enable this candidate. Cropped-left
    lines remain unchanged. Unrestricted retyping lost correct short ground
    lines in old regression scenes, so existing solid ground is never removed.
    A float/rope/none vote abstains. No native state enters this model.
    """
    def __init__(self,weights):
        from arena_yolo import offline_sdk
        self.model=offline_sdk().YOLO(str(weights))
        self.names=tuple(self.model.names.values())
        if self.model.task!='classify'or self.names not in(KINDS,('floating_platform','none','platform','rope')):
            raise ValueError('Expected the reviewed stock support-type model')
        self.options=dict(device=0,imgsz=128,quantize=32,verbose=False)
        self.info=dict(model='stock YOLO26n-cls',weights=str(weights),
                       sha256=hashlib.sha256(Path(weights).read_bytes()).hexdigest(),
                       classes=list(self.names),crop_px=CROP,threshold=THRESHOLD,
                       transitions=['rope->platform','floating_platform->platform'],
                       eligibility='visible leading endpoint x16..620/y48..320; span>=16px')
        self.last_ms=0.;self.last_votes=[]
        blank=np.zeros((CROP,CROP,3),np.uint8)
        for n in range(1,9):self.model.predict([blank]*n,**self.options)

    def refine(self,bgr,segments):
        self.last_ms=0.;self.last_votes=[]
        eligible=[(i,center)for i,s in enumerate(segments)for center in[crop_center(s)]if center is not None]
        if not eligible:return segments
        start=time.perf_counter();patches=[cv2.getRectSubPix(bgr,(CROP,CROP),center)for _,center in eligible]
        results=[]
        for i in range(0,len(patches),8):results.extend(self.model.predict(patches[i:i+8],**self.options))
        if len(results)!=len(eligible):raise ValueError('Support classifier result count differs from proposals')
        output=list(segments)
        for (i,center),result in zip(eligible,results):
            probabilities=np.asarray(result.probs.data.cpu().numpy(),float)
            names=getattr(self,'names',KINDS)
            if (probabilities.shape!=(len(names),)or not np.isfinite(probabilities).all()
                    or np.any(probabilities<0)or np.any(probabilities>1)
                    or abs(probabilities.sum()-1)>1e-4):
                self.last_votes.append(dict(index=i,status='invalid_probabilities'));continue
            choice=int(np.argmax(probabilities));kind=names[choice];confidence=float(probabilities[choice])
            changed=kind=='platform'and confidence>=THRESHOLD
            self.last_votes.append(dict(index=i,kind=kind,confidence=confidence,changed=changed,center=center))
            if changed:
                output[i]=dict(segments[i],kind=kind,raw_kind=segments[i]['kind'],
                               support_type_confidence=confidence)
        self.last_ms=(time.perf_counter()-start)*1000
        return output
