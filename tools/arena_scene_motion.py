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


class GroundPatchMotion:
    """Research candidate: unique 2D texture matches inside neural ground.

    A weak platform proposal only selects pixels; it does not supply motion.
    Independent, spatially separated patches must agree on one translation.
    Grid sampling keeps bright foreground blades from taking every corner.
    """
    def __init__(self):
        self.previous=None
        self.x=np.arange(640)[None,:]
        self.y=np.arange(360)[:,None]

    def mask(self,segments,player):
        x,y=self.x,self.y
        mask=np.zeros((360,640),bool)
        for s in segments:
            if (s['kind']!='platform'or s['confidence']<.25
                    or s['b'][0]-s['a'][0]<96):continue
            a,b=s['a'],s['b']
            line=a[1]+(b[1]-a[1])*(x-a[0])/(b[0]-a[0])
            mask|=(x>a[0]+8)&(x<b[0]-8)&(y>=line+4)&(y<=line+32)
        mask&=(y>60)&(y<356)&~((y>270)&((x<140)|(x>510)))
        if player is not None:
            mask&=~((x>player.x-20)&(x<player.x+player.w+20)
                    &(y>player.y-20)&(y<player.y+player.h+20))
        return mask.astype(np.uint8)*255

    @staticmethod
    def peak_offset(a,b,c):
        denominator=float(a)-2*float(b)+float(c)
        return .5*(float(a)-float(c))/denominator if denominator<-.001 else 0.

    def observe(self,rgb,segments,stamp,player=None):
        if rgb.shape[:2]!=(360,640):
            self.previous=None
            return None
        gray=cv2.cvtColor(rgb[:,:,:3],cv2.COLOR_RGB2GRAY)
        mask=self.mask(segments,player)
        old=self.previous;self.previous=(gray,mask,stamp)
        if old is None:return None
        first,oldmask,oldstamp=old;dt=stamp-oldstamp
        if not .006<=dt<=.16 or not mask.any()or not oldmask.any():return None
        cells=[]
        # Crop empty rows, retaining the same per-cell feature population.
        rows=np.flatnonzero(oldmask.any(axis=1));top=max(0,int(rows[0])-3)
        bottom=min(360,int(rows[-1])+4)
        for left in range(0,640,64):
            cellmask=oldmask[top:bottom,left:left+64]
            if not cellmask.any():continue
            cell=cv2.goodFeaturesToTrack(first[top:bottom,left:left+64],maxCorners=4,
                qualityLevel=.02,minDistance=10,mask=cellmask,blockSize=5)
            if cell is not None:
                cell[:,:,0]+=left;cell[:,:,1]+=top;cells.append(cell)
        if not cells:return None
        matches=[]
        for x,y in np.concatenate(cells)[:,0].astype(int):
            half=7
            if min(x,y)<half or x+half>=640 or y+half>=360:continue
            template=first[y-half:y+half+1,x-half:x+half+1]
            if template.std()<3:continue
            left=max(half,x-110);right=min(639-half,x+1)
            top=max(half,y-35);bottom=min(359-half,y+35)
            if right<=left or bottom<=top:continue
            search=gray[top-half:bottom+half+1,left-half:right+half+1]
            scores=cv2.matchTemplate(search,template,cv2.TM_CCOEFF_NORMED)
            scores[mask[top:bottom+1,left:right+1]==0]=-1
            _,score,_,(px,py)=cv2.minMaxLoc(scores)
            if not np.isfinite(score)or score<.85:continue
            others=scores.copy()
            others[max(0,py-3):py+4,max(0,px-3):px+4]=-1
            if score-float(others.max())<.06:continue
            sx=self.peak_offset(scores[py,px-1],scores[py,px],scores[py,px+1])if 0<px<scores.shape[1]-1 else 0.
            sy=self.peak_offset(scores[py-1,px],scores[py,px],scores[py+1,px])if 0<py<scores.shape[0]-1 else 0.
            matches.append((x,left+px+sx-x,top+py+sy-y))
        if len(matches)<4:return None
        values=np.asarray(matches);delta=values[:,1:]
        median=np.median(delta,axis=0)
        inlier=np.linalg.norm(delta-median,axis=1)<1.5
        if inlier.sum()<4 or inlier.mean()<.7:return None
        span=float(np.ptp(values[inlier,0]))
        if span<96:return None
        dx,dy=map(float,np.median(delta[inlier],axis=0))
        return dict(dx=dx,dt=dt,vx=dx/dt,camera_dy=dy,response=float(inlier.mean()),
                    points=int(inlier.sum()),span=span,source='ground_unique_template')
