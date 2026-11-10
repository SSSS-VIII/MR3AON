"""Static ground texture translation from pixels, without scene/game telemetry."""
import cv2
import numpy as np


class GroundTextureMotion:
    """Rectify a thin visible material strip below the detected platform top.

    Fixed screen X windows avoid turning a moving crop into camera movement.
    Foreground platforms, rope, sky/parallax and an inferred floor are excluded.
    A weak/ambiguous texture measurement is returned as unknown.
    """
    WIDTH=256
    DEPTH=24
    WINDOWS=(24,168,360)

    def __init__(self):
        self.previous=None
        self.window=cv2.createHanningWindow((self.WIDTH,self.DEPTH),cv2.CV_32F)
        self.xs=np.arange(self.WIDTH,dtype=np.float32)
        self.depths=np.arange(4,4+self.DEPTH,dtype=np.float32)[:,None]

    @staticmethod
    def line(segment,x):
        a,b=segment['a'],segment['b']
        return a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0])

    def strip(self,gray,segment,start):
        xs=self.xs+start
        ys=self.line(segment,xs)[None,:]+self.depths
        if ys.min()<60 or ys.max()>=gray.shape[0]-2:return None
        pixels=cv2.remap(gray,np.broadcast_to(xs,ys.shape),ys,cv2.INTER_LINEAR)
        pixels-=pixels.mean(axis=1,keepdims=True)
        if float(pixels.std())<1.5:return None
        return pixels

    def observe(self,rgb,segments,stamp,player=None):
        gray=cv2.cvtColor(rgb[:,:,:3],cv2.COLOR_RGB2GRAY).astype(np.float32)
        ground=[s for s in segments if s['kind']=='platform'and s['confidence']>=.7
                and s['b'][0]-s['a'][0]>=self.WIDTH+16]
        previous=self.previous;self.previous=(gray,ground,stamp,player)
        if previous is None:return None
        old_gray,old_segments,old_stamp,old_player=previous;dt=stamp-old_stamp
        if not .006<=dt<=.16:return None
        measurements=[]
        for current in ground:
            slope=(current['b'][1]-current['a'][1])/(current['b'][0]-current['a'][0])
            for old in old_segments:
                old_slope=(old['b'][1]-old['a'][1])/(old['b'][0]-old['a'][0])
                if abs(slope-old_slope)>.06:continue
                for start in self.WINDOWS:
                    end=start+self.WIDTH-1
                    if max(current['a'][0],old['a'][0])+8>start or min(current['b'][0],old['b'][0])-8<end:continue
                    if abs(self.line(current,(start+end)/2)-self.line(old,(start+end)/2))>35:continue
                    # The role's render/trail can overlap the ground material;
                    # choose another fixed window rather than mask stationary
                    # black edges into the Fourier correlation.
                    if any(p is not None and p.x-20<end and p.x+p.w+20>start for p in (player,old_player)):continue
                    first=self.strip(old_gray,old,start);second=self.strip(gray,current,start)
                    if first is None or second is None:continue
                    (dx,dy),response=cv2.phaseCorrelate(first.copy(),second.copy(),self.window)
                    # Forward Gale scrolls static ground to the left. Repeated
                    # tiles can alias a large inter-frame displacement to a
                    # positive Fourier peak; that contradicts this camera prior
                    # and is unknown, never a reverse world velocity.
                    if (not np.isfinite([dx,dy,response]).all()or response<.4 or dx>1.
                            or abs(dy)>3 or abs(dx)>.43*self.WIDTH):continue
                    measurements.append((dx,dy,response,start))
        # A window can appear in several geometrically similar support pairs.
        # It remains one observation, not independent corroboration.
        by_window={}
        for row in measurements:
            if row[3]not in by_window or row[2]>by_window[row[3]][2]:by_window[row[3]]=row
        rows=list(by_window.values())
        if not rows or len(rows)==1 and rows[0][2]<.5:return None
        dx=float(np.median([r[0]for r in rows]))
        if max(abs(r[0]-dx)for r in rows)>4:return None
        return dict(dx=dx,dt=dt,vx=dx/dt,response=float(np.median([r[2]for r in rows])),
                    windows=len(rows),source='ground_texture')
