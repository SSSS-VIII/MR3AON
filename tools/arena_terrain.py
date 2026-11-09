"""Local foreground support edges; screen coordinates only."""
from collections import deque
import cv2
import numpy as np


def arrow_score(rgb,cx):
    values=rgb[290:339,cx-22:cx+23,:3].min(axis=2)
    scores=[]
    # The native UI dims unavailable buttons during a jump. Shape remains useful
    # after their white pixels fall far below a fixed bright threshold.
    for threshold in (205,160,120,90):
        white=values>threshold
        if 80<white.sum()<600:
            scores.append(float((white&white[:,::-1]).sum()/max(1,(white|white[:,::-1]).sum())))
    return max(scores,default=0.)


class GroundEdges:
    def __init__(self):
        self.y=None
        self.color=None
        self.history=deque(maxlen=8)

    def observe(self,rgb,player,stamp):
        if player is None:
            return None
        px,py=player.center
        if self.y is not None and self.y<py+12:
            self.y=self.color=None
        gray=cv2.cvtColor(rgb[:,:,:3],cv2.COLOR_RGB2GRAY)
        smooth=cv2.blur(gray,(7,1))
        gradient=-cv2.Sobel(smooth,cv2.CV_32F,0,1,ksize=3)
        colors=cv2.blur(rgb[:,:,:3],(5,5)).astype(np.float32)
        if self.y is None and py<180:
            return None
        expected=self.y if self.y is not None else py+30
        lo,hi=max(15,int(expected)-38),min(340,int(expected)+39)
        if self.y is None:
            lo,hi=max(15,int(py)+20),min(340,int(py)+39)
        if lo>=hi:
            return None
        column=int(np.clip(px+(40 if self.y is None else 0),10,629))
        initial=gradient[lo:hi,max(0,column-12):min(640,column+13)].mean(axis=1)-np.abs(np.arange(lo,hi)-expected)*1.1
        row=lo+int(initial.argmax())
        if self.color is None and initial.max()>45:
            candidate=colors[min(350,row+8),column].copy()
            if candidate.max()>18:
                self.color=candidate
                self.y=float(row)
        if self.color is None:
            return None
        xs=np.arange(max(10,int(px)-80),min(630,int(px)+430),4)
        samples=[]
        for x in xs:
            yy=np.arange(lo,hi)
            distance=np.maximum(np.abs(colors[np.minimum(yy+6,359),x]-self.color).sum(axis=1),
                                np.abs(colors[np.minimum(yy+14,359),x]-self.color).sum(axis=1))
            values=gradient[lo:hi,x]-np.abs(yy-expected)*1.1
            values[distance>100]=-1000
            index=int(values.argmax())
            samples.append((int(lo+index),bool(values[index]>40)))
        valid=np.asarray([s[1]for s in samples],np.uint8)[None,:]
        valid=cv2.morphologyEx(valid,cv2.MORPH_CLOSE,np.ones((1,9),np.uint8))
        valid=cv2.morphologyEx(valid,cv2.MORPH_OPEN,np.ones((1,5),np.uint8))[0].astype(bool)
        nearest=int(np.argmin(abs(xs-px)))
        local=[samples[i][0] for i in range(max(0,nearest-3),min(len(xs),nearest+4))if valid[i]]
        if local:
            current=float(np.median(local))
            self.y=current if self.y is None else .7*self.y+.3*current
            # Slowly adapt to lighting; do not sample a hole or a midair character.
            if 15<self.y+7-py<45:
                self.color=.95*self.color+.05*colors[min(350,int(self.y)+6),column]
        edge=landing=None
        for i in range(1,len(xs)-12):
            if valid[i-1] and not valid[i] and not valid[i:i+12].any():
                edge=float(xs[i])
                starts=np.flatnonzero(valid[i+6:])
                if len(starts):
                    landing=float(xs[i+6+starts[0]])
                break
        speed=None
        if edge is not None:
            if self.history and (stamp-self.history[-1][0]>.2 or abs(edge-self.history[-1][1])>90):
                self.history.clear()
            self.history.append((stamp,edge))
            if len(self.history)>=3:
                t=np.array([v[0]-stamp for v in self.history]);x=np.array([v[1]for v in self.history])
                denominator=float(((t-t.mean())**2).sum())
                if denominator>1e-6:
                    speed=-float(((t-t.mean())*(x-x.mean())).sum()/denominator)
                    speed=float(np.clip(speed,0,1000))
        else:
            self.history.clear()
        return dict(y=self.y,edge=edge,landing=landing,speed=speed,
                    at_player=bool(valid[nearest]),
                    samples=[(int(x),int(y),bool(v))for x,(y,_),v in zip(xs,samples,valid)])
