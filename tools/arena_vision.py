"""Pixels-only baseline: foreground proposals, short tracks and reactive avoidance.

Coordinates are 640x360 screen pixels, velocities pixels/second. This first
detector deliberately has no map IDs, game-object queries or board clock input.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
import math
import cv2
import numpy as np
from arena_terrain import GroundEdges,arrow_score
import arena_motion as motion


@dataclass
class Box:
    x: float
    y: float
    w: float
    h: float

    @property
    def center(self):
        return self.x + self.w / 2, self.y + self.h / 2

    def overlaps(self, other, margin=0):
        return (self.x < other.x + other.w + margin and self.x + self.w + margin > other.x
                and self.y < other.y + other.h + margin and self.y + self.h + margin > other.y)


@dataclass
class Detection:
    box: Box
    kind: str
    confidence: float
    active: bool = False
    arming: bool = False
    attack_phase: str | None = None


@dataclass
class Track:
    id: int
    box: Box
    kind: str
    confidence: float
    seen: float
    history: deque = field(default_factory=lambda: deque(maxlen=32))
    vx: float = 0
    vy: float = 0
    ax: float = 0
    ay: float = 0
    residual: float = 0
    observations: int = 0
    active: bool = False
    arming: bool = False
    reference: tuple = (0.,0.)
    curve_count: int = 0
    sine_frequency: float = 0
    sine_a: float = 0
    sine_b: float = 0
    sine_count: int = 0
    adaptive_velocity: bool = False
    ballistic: bool = False
    gravity_up: float = 0
    gravity_down: float = 0
    floor_y: float = 0
    rebound_speed: float = 0
    attack_phase: str | None = None
    ready_started: float | None = None
    ready_remaining: float = 0
    rush_scale_remaining: float = 0
    rush_target_w: float = 0
    rush_target_h: float = 0
    horizontal_stopped: bool = False

    def update(self, detection, stamp, player):
        self.box, self.kind, self.confidence, self.seen = (
            detection.box, detection.kind, detection.confidence, stamp)
        self.active = detection.active
        self.arming = detection.arming
        self.reference = player
        x, y = self.box.center
        self.history.append((stamp, x - player[0], y - player[1]))
        self.observations += 1
        if detection.attack_phase is not None or self.attack_phase is not None:
            from arena_object_motion import configure_crow
            configure_crow(self,detection,stamp)
        all_samples=np.asarray(self.history)
        samples=all_samples[-10:]
        if len(samples) < 3 or samples[-1, 0] - samples[0, 0] < .035:
            return
        t = samples[:, 0] - stamp
        # A short regression suppresses single-frame wing/animation jitter.
        design = np.column_stack((np.ones(len(t)), t))
        weights = np.exp(t / (.18 if self.adaptive_velocity else .09))[:, None]
        fit, _, _, _ = np.linalg.lstsq(design * weights, samples[:, 1:] * weights, rcond=None)
        self.vx, self.vy = map(float, fit[1])
        if self.adaptive_velocity:
            residual_y=samples[:,2]-(design@fit)[:,1]
            centered=t-np.average(t,weights=weights[:,0]**2)
            denominator=float(np.sum((centered*weights[:,0])**2))
            sigma=float(np.sqrt(np.mean(residual_y**2)/max(denominator,1e-6)))
            if abs(self.vy)<max(10,2*sigma):self.vy=0.
        elif np.ptp(samples[:, 2]) < 12:
            self.vy = 0.
        self.residual = float(np.sqrt(np.mean((design @ fit - samples[:, 1:]) ** 2)))
        old_a=(self.ax,self.ay)
        self.ax = self.ay = 0
        stable=False
        if len(samples) >= 7 and t[0] < -.16:
            quadratic = np.column_stack((np.ones(len(t)), t, t * t / 2))
            curved, _, _, _ = np.linalg.lstsq(quadratic, samples[:, 1:], rcond=None)
            error = np.sqrt(np.mean((quadratic @ curved - samples[:, 1:]) ** 2))
            # Curvature is diagnostic until sufficiently stable; extrapolating noisy
            # acceleration would turn sprite animation into fictitious hazards.
            if error < self.residual * .6:
                self.ax, self.ay = map(float, curved[2])
                magnitude=math.hypot(self.ax,self.ay)
                previous=math.hypot(*old_a)
                stable=(30<magnitude<6000 and previous>0 and
                        (old_a[0]*self.ax+old_a[1]*self.ay)/(magnitude*previous)>.8)
                if stable and self.curve_count>=2:
                    self.vx,self.vy=map(float,curved[1])
        self.curve_count=self.curve_count+1 if stable else 0
        sine=None
        if (self.confidence>=.7 and self.kind!='pinball' and len(all_samples)>=11 and all_samples[-1,0]-all_samples[0,0]>=.25
                and np.ptp(all_samples[:,2])>8 and not self.arming and not self.active):
            times=all_samples[:,0]-stamp;ys=all_samples[:,2]
            centered=times-times.mean()
            slope=float((centered*(ys-ys.mean())).sum()/(centered*centered).sum())
            linear_error=float(np.sqrt(np.mean((ys.mean()+slope*centered-ys)**2)))
            quadratic=np.column_stack((np.ones(len(times)),times,times*times))
            qfit,_,_,_=np.linalg.lstsq(quadratic,ys,rcond=None)
            quadratic_error=float(np.sqrt(np.mean((quadratic@qfit-ys)**2)))
            preferred=1 if self.kind=='red_enemy' else 3
            for frequency in (1.,2.,3.,4.,5.,6.):
                design=np.column_stack((np.ones(len(times)),np.sin(frequency*times),np.cos(frequency*times)))
                fit,_,_,_=np.linalg.lstsq(design,ys,rcond=None)
                error=float(np.sqrt(np.mean((design@fit-ys)**2)))
                amplitude=math.hypot(fit[1],fit[2])
                if quadratic_error<.1 and error>quadratic_error+.02:
                    continue
                if 8<amplitude<200 and error<1.6 and error<linear_error*.8:
                    score=error+.2*abs(frequency-preferred)
                    if sine is None or score<sine[0]:
                        sine=(score,frequency,float(fit[1]),float(fit[2]))
        if sine:
            _,self.sine_frequency,self.sine_a,self.sine_b=sine
            self.sine_count+=1
            if self.sine_count>=2:
                self.vy=self.sine_a*self.sine_frequency
                self.ay=-self.sine_b*self.sine_frequency**2
        else:
            self.sine_count=0
        if self.attack_phase=='normal'and len(all_samples)>=3:
            recent=all_samples[-3:]
            stationary=recent[-1,0]-recent[0,0]>.025 and np.ptp(recent[:,1])<4
            self.horizontal_stopped=bool(stationary and
                                         (self.horizontal_stopped or np.ptp(all_samples[-10:,1])>20))
            if self.horizontal_stopped:
                self.vx=self.ax=0.
        else:
            self.horizontal_stopped=False
        if self.adaptive_velocity and self.kind=='pinball':
            from arena_object_motion import fit_ballistic
            from arena_projection import SCALE
            self.ballistic=False
            fit_ballistic(self,SCALE)

    def future(self, seconds):
        if self.attack_phase in ('ready','rush'):
            from arena_object_motion import crow_geometry
            from arena_projection import SCALE
            return crow_geometry(self,seconds,SCALE)
        horizon=min(seconds,.25)
        ax,ay=(self.ax,self.ay) if self.curve_count>=3 else (0,0)
        dy=self.vy*seconds+.5*ay*horizon*horizon
        if self.sine_count>=2:
            angle=self.sine_frequency*seconds
            dy=self.sine_a*math.sin(angle)+self.sine_b*(math.cos(angle)-1)
        if self.ballistic:
            from arena_object_motion import bounce_y
            dy=bounce_y(self.box.center[1],self.vy,seconds,floor=self.floor_y,
                        gravity_up=self.gravity_up,gravity_down=self.gravity_down,
                        rebound=self.rebound_speed)-self.box.center[1]
        return Box(self.box.x + self.vx * seconds+.5*ax*horizon*horizon,
                   self.box.y+dy,
                   self.box.w, self.box.h)

    def at(self,seconds):
        result=replace(self,box=self.future(seconds))
        if self.attack_phase in ('ready','rush'):
            moving=max(0,seconds-self.ready_remaining)
            result.ready_remaining=max(0,self.ready_remaining-seconds)
            result.rush_scale_remaining=max(0,self.rush_scale_remaining-moving)
            if result.ready_remaining<=0:
                result.attack_phase='rush';result.active=True;result.arming=False
            return result
        if self.ballistic:
            from arena_object_motion import bounce_state
            _,result.vy=bounce_state(self.box.center[1],self.vy,seconds,floor=self.floor_y,
                gravity_up=self.gravity_up,gravity_down=self.gravity_down,rebound=self.rebound_speed)
        elif self.sine_count>=2:
            angle=self.sine_frequency*seconds
            result.sine_a=self.sine_a*math.cos(angle)-self.sine_b*math.sin(angle)
            result.sine_b=self.sine_a*math.sin(angle)+self.sine_b*math.cos(angle)
            result.vy=result.sine_a*self.sine_frequency
            result.ay=-result.sine_b*self.sine_frequency**2
        elif self.curve_count>=3:
            result.vx+=self.ax*min(seconds,.25)
            result.vy+=self.ay*min(seconds,.25)
        return result


class Tracker:
    def __init__(self,adaptive=False):
        self.adaptive=adaptive
        self.tracks = []
        self.next_id = 1

    def update(self, detections, stamp, player):
        available = {t.id: t for t in self.tracks if stamp - t.seen < .22}
        predicted={identity:t.future(stamp-t.seen).center for identity,t in available.items()}
        pairs = []
        for i, d in enumerate(detections):
            for t in available.values():
                elapsed=stamp-t.seen
                tx, ty = predicted[t.id]
                x, y = d.box.center
                ox,oy=player[0]-t.reference[0],player[1]-t.reference[1]
                distance = math.hypot(x-(tx+ox),y-(ty+oy))
                compatible=(d.kind==t.kind or {d.kind,t.kind}<={'eye_enemy','spider'})
                if (compatible and distance < max(35, min(180, 1600 * elapsed + 12))
                        and abs(y-(ty+oy)) < max(19,abs(t.vy)*elapsed+12)):
                    pairs.append((distance, i, t.id))
        used, matched = set(), set()
        for _, i, identity in sorted(pairs):
            if i not in used and identity not in matched:
                available[identity].update(detections[i], stamp, player)
                used.add(i); matched.add(identity)
        for i, d in enumerate(detections):
            if i not in used:
                t = Track(self.next_id, d.box, d.kind, d.confidence, stamp)
                if self.adaptive:
                    t.adaptive_velocity=True;t.history=deque(maxlen=64)
                self.next_id += 1
                t.update(d, stamp, player)
                available[t.id] = t
        self.tracks = list(available.values())
        output=[]
        for t in self.tracks:
            age=stamp-t.seen
            if age:
                prediction=t.at(age)
                b=prediction.box
                dx,dy=player[0]-t.reference[0],player[1]-t.reference[1]
                b=Box(b.x+dx,b.y+dy,b.w,b.h)
                output.append(replace(prediction,box=b,confidence=t.confidence-age*.6,
                                      reference=player,floor_y=prediction.floor_y+dy))
            else:
                output.append(t)
        return output


class Perception:
    def __init__(self):
        self.tracker = Tracker()
        self.visual_role = False
        self.previous_player = None
        self.last = None
        self.jump_count = 0
        self.last_action = -10
        self.last_flip = -10
        self.rope = None
        self.player_velocity = 0
        self.body_height = 53.
        yy,xx=np.mgrid[-15:16,-15:16]
        rr=xx*xx+yy*yy
        inner=(rr<=7*7).astype(np.float32)
        ring=((rr>=12*12)&(rr<=15*15)).astype(np.float32)
        self.head_kernel=ring/ring.sum()-inner/inner.sum()
        self.red_near_kernel=cv2.getStructuringElement(cv2.MORPH_ELLIPSE,(31,31))
        self.head = None
        self.head_stamp = None
        self.head_vy = 0.
        self.previous_vertical = None
        self.ground=GroundEdges()
        self.sliding_until=-10
        self.support_mode=None
        self.last_rope_hint=-10
        self.last_observation=None
        self.active_motion=None
        self.motion_origin=None

    def action(self, action, stamp, observation=None):
        self.last_action = stamp
        current=observation or self.last_observation
        phase=current['phase'] if current else 'unknown'
        name=None
        if action == 'jump':
            if phase=='rope_below':
                name='rope_up';self.jump_count=0
            else:
                # The supplied observation is projected to input receipt. It
                # may already have landed while the last captured frame was
                # still airborne; commit the same state the planner used.
                jumps=current.get('jumps',self.jump_count)if current else self.jump_count
                if phase in ('rope_above','ground'):
                    jumps=0
                name='jump1' if not jumps else 'jump2'
                self.jump_count=min(2,jumps+1)
        elif action == 'down':
            self.last_flip = stamp
            if phase=='rope_above':
                name='rope_down';self.jump_count=0
            elif current and can_air_down(current):
                name='air_down';self.jump_count=0
        elif action=='slide':
            self.sliding_until=stamp+.55
        if name and current and current['player']:
            self.active_motion=create_motion(current,name,stamp)
            ox,oy=current_offsets(current)
            p=current['player'];scale=current.get('scale_px',41.)
            support=current.get('rope')
            if current.get('terrain')and current['terrain']['y']is not None:
                support=current['terrain']['y']+7
            self.motion_origin=dict(x=p.center[0]-ox*scale,
                y=p.center[1]+oy*scale-(support or 0),scale=scale,
                stand_w=current.get('stand_w',self.body_height*.36),
                stand_h=current.get('stand_h',self.body_height*.73))

    def observe(self, rgba, stamp):
        rgb = rgba[:, :, :3]
        if rgb.shape[:2] != (360, 640):
            raise ValueError('Baseline expects 640x360 RGBA/RGB pixels')
        dark = ((rgb[:, :, 0] < 95) & (rgb[:, :, 1] < 130) & (rgb[:, :, 2] < 200)
                & (rgb[:, :, 2].astype(np.int16)-rgb[:, :, 0] < 98)).astype(np.uint8)
        dark[:55] = 0
        dark[275:, :135] = 0
        dark[275:, 515:] = 0
        gray = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.int16)
        contrast = np.zeros(gray.shape, np.uint8)
        contrast[7:-7] = ((np.minimum(gray[:-14], gray[14:]) - gray[7:-7]) > 18).astype(np.uint8)
        horizontal = cv2.morphologyEx(contrast, cv2.MORPH_OPEN, np.ones((1, 70), np.uint8))
        counts = horizontal.sum(axis=1)
        peaks = np.flatnonzero((counts > 250) & (np.arange(360) > 80) & (np.arange(360) < 310))
        ropes = []
        for group in np.split(peaks, np.flatnonzero(np.diff(peaks) > 1) + 1):
            if len(group) and len(group) <= 10:
                ropes.append(float(np.average(group, weights=counts[group])))
        self.rope = min(ropes, key=lambda y: abs(y - (self.rope or 260))) if ropes else None
        dark[horizontal > 0] = 0
        if self.rope is not None:
            dark[max(0,int(self.rope)-5):int(self.rope)+6] = 0
        red = ((rgb[:, :, 0] > 80) & (rgb[:, :, 0] > rgb[:, :, 1].astype(float) * 1.4)
               & (rgb[:, :, 0] > rgb[:, :, 2].astype(float) * 1.15))
        # Attacking crows flash red before accelerating. Preserve their geometry
        # through this original colour-state change instead of dropping the track.
        gold_mask = ((rgb[:, :, 0] > 130) & (rgb[:, :, 1] > 65)
                     & (rgb[:, :, 1] < 210) & (rgb[:, :, 2] < 150)
                     & (rgb[:, :, 0] > rgb[:, :, 1].astype(float)*1.08)
                     & (rgb[:, :, 1] > rgb[:, :, 2].astype(float)*1.12))
        gold_mask=cv2.morphologyEx(gold_mask.astype(np.uint8),cv2.MORPH_CLOSE,
                                  np.ones((3,5),np.uint8)).astype(bool)
        nr, lr, sr, _ = cv2.connectedComponentsWithStats(red.astype(np.uint8))
        for i in range(1, nr):
            x, y, w, h, area = sr[i]
            if 12 < w < 100 and 10 < h < 80 and area > 60 and y > 60:
                if gold_mask[y:y+h, x:x+w].sum() > 18:
                    region=dark[y:y+h,x:x+w]
                    region[lr[y:y+h,x:x+w]==i]=1
        scarf = np.zeros(red.shape, np.uint8)
        touches_edge=any(s[0] <= 2 and s[2]>70 and s[1]>60 for s in sr[1:])
        for i in range(1, nr):
            x, y, w, h, area = sr[i]
            if (x <= (2 if touches_edge else 130) and 60 < x+w < 270
                    and w > 50 and area > 40 and y+h > 65):
                scarf[lr == i] = 1
        scarf[:60] = 0; scarf[:, 270:] = 0; scarf[:, :40] = 0
        ys, xs = np.where(scarf)
        anchor = None
        if len(xs) > 15:
            tip = xs.max()
            anchor = (float(tip), float(np.median(ys[xs > tip - 4])))
        n, labels, stats, centroids = cv2.connectedComponentsWithStats(dark)
        body = None
        best = 1e9
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if not (100 < area < 4500 and 12 < w < 125 and 18 < h < 110 and 65 < x < 310):
                continue
            if anchor:
                # Scarf ends at the neck, inside or immediately beside the body.
                distance = math.hypot(max(x - anchor[0], 0, anchor[0] - x - w),
                                      max(y - anchor[1], 0, anchor[1] - y - h))
                if distance < 12 and distance < best:
                    best = distance
                    body = (i, Box(float(x), float(y), float(w), float(h)))
        player = None
        if anchor or self.head is not None:
            # Calibrated 640px Xiaohei camera scale. Running dust and scarf can
            # join the silhouette, so its changing height is not a scale sensor.
            h = self.body_height
            tracking = self.head is not None and stamp-self.head_stamp < .15
            if tracking:
                dt = stamp-self.head_stamp
                ax,ay=int(self.head[0]),int(np.clip(self.head[1]+self.head_vy*dt,35,325))
                lo,hi=-28,29
                left,right=-18,19
            else:
                ax,ay=map(int,anchor or self.head)
                below = self.rope is not None and ay > self.rope + 10
                lo,hi=(-2,19) if below else (-18,-1)
                left,right=-5,28
            x0,y0=max(0,ax-40),max(0,ay-50)
            cut=gray[y0:min(360,ay+51),x0:min(640,ax+51)].astype(np.float32)
            response=cv2.filter2D(cut,-1,self.head_kernel)
            window=np.zeros(response.shape,np.uint8)
            window[max(0,ay-y0+lo):ay-y0+hi,max(0,ax-x0+left):ax-x0+right]=1
            yy,xx=np.indices(response.shape)
            # The native runner camera keeps Xiaohei in this foreground lane.
            # HUD circles and a severed scarf tail must never capture the tracker.
            min_x,max_x=(175,215) if self.support_mode=='rope' else (140,300)
            window[(xx+x0<min_x)|(xx+x0>max_x)|(yy+y0<60)|(yy+y0>320)]=0
            near_red=cv2.dilate(red[y0:y0+window.shape[0],x0:x0+window.shape[1]].astype(np.uint8),
                               self.red_near_kernel)
            window &= near_red
            if tracking:
                response -= np.sqrt((xx+x0-ax)**2+(yy+y0-ay)**2).astype(np.float32)*.25
            _,score,_,local_head=cv2.minMaxLoc(response,mask=window)
            head=(local_head[0]+x0,local_head[1]+y0)
            below = self.rope is not None and head[1] > self.rope+10
            px, py = head[0] - h * .28, head[1] + h * (-.28 if below else .28)
            # Calibration of rendered silhouette against the original Role capsule;
            # item pickup bounds and scarf are intentionally excluded.
            if score > 12:
                player = Box(px - h * .18, py - h * .365, h * .36, h * .73)
                if tracking and dt>.005:
                    self.head_vy=.5*self.head_vy+.5*(head[1]-self.head[1])/dt
                else:
                    self.head_vy=0.
                self.head,self.head_stamp=head,stamp
        detections = []
        ng, lg, sg, cg = cv2.connectedComponentsWithStats(gold_mask.astype(np.uint8))
        for i in range(1, ng):
            x,y,w,h,area = sg[i]
            if not (65 < y < 335 and 60 < x < 625 and 25 < area < 1600
                    and 4 <= w <= 150 and 2 <= h <= 25):
                continue
            streak=w/max(1,h)>3 and w>20
            spider_eye=not streak and w/max(1,h)>1.7
            scale=(max(.65,h/6)if streak else
                   max(w/13,h/7,w/9*.85)if spider_eye else max(w/9,h/9))
            padx,pady=int(10*scale),int(9*scale)
            x1,y1,x2,y2=max(0,x-padx),max(0,y-pady),min(640,x+w+padx),min(360,y+h+pady)
            foreground = dark[y1:y2,x1:x2] | red[y1:y2,x1:x2]
            if foreground.mean() < .22:
                continue
            tone=gray[y1:y2,x1:x2]
            border=np.concatenate((tone[0],tone[-1],tone[:,0],tone[:,-1]))
            background=float(np.percentile(border,75))
            dark_eye=background<55 and h<=11 and area/(w*h)>.45
            if (tone<background-22).mean()<.18 and not dark_eye:
                continue
            cx,cy = cg[i]
            if streak:
                cx = x + 6*scale
            if not streak and not spider_eye and not dark_eye:
                gx,gy=int(cx),int(cy)
                inner,outer,half=max(8,w+1),max(17,int(w*2.15)),max(4,h//2)
                side=np.concatenate((gray[max(0,gy-half):gy+half+1,max(0,gx-outer):gx-inner].ravel(),
                                     gray[max(0,gy-half):gy+half+1,gx+inner:min(640,gx+outer)].ravel()))
                if len(side)==0 or (side<np.percentile(border,75)-22).mean()<.15:
                    continue
            height=(28 if spider_eye else 24)*scale
            b = Box(float(cx-15*scale),float(cy+3*scale-height/2),30.*scale,height)
            if player and b.overlaps(player, 3):
                continue
            patch=rgb[y1:y2,x1:x2].astype(np.float32)
            red_body=((patch[:,:,0]>80)&(patch[:,:,0]>patch[:,:,1]*1.7)
                      &(patch[:,:,0]>patch[:,:,2]*1.2)&(patch[:,:,1]<115))
            red_body &= scarf[y1:y2,x1:x2]==0
            detections.append(Detection(b,'spider' if spider_eye else 'eye_enemy',.93,
                                        bool(streak),bool(red_body.mean()>.1)))
        # Bee and spider eyes are red, including during their native attack pose.
        eye_red=((rgb[:,:,0]>170)&(rgb[:,:,1]<80)&(rgb[:,:,2]<90)).astype(np.uint8)
        ne,le,se,ce=cv2.connectedComponentsWithStats(eye_red)
        red_candidates=[]
        for i in range(1,ne):
            x,y,w,h,area=se[i]
            if not (4<area<145 and 2<=w<=18 and 2<=h<=12 and 65<y<335 and 70<x<625):
                continue
            if player and x<player.center[0]+55:
                continue
            if scarf[y:y+h,x:x+w].sum()>area*.4:
                continue
            x1,x2=max(0,x-20),min(640,x+w+21);y1,y2=max(0,y-18),min(360,y+h+19)
            tone=gray[y1:y2,x1:x2]
            border=np.concatenate((tone[0],tone[-1],tone[:,0],tone[:,-1]))
            if (tone<np.percentile(border,75)-22).mean()<.18:
                continue
            # A white sclera around the pupil distinguishes the larger bouncing
            # pinball from a bee's red face. Its native collider covers the spikes.
            ax,ay,bx,by=max(0,x-35),max(0,y-35),min(640,x+w+36),min(360,y+h+36)
            patch=rgb[ay:by,ax:bx]
            white=((patch.min(2)>180)&((patch.max(2).astype(np.int16)-patch.min(2))<65)).astype(np.uint8)
            nw,lw,sw,cw=cv2.connectedComponentsWithStats(white)
            ball=None
            for j in range(1,nw):
                wx,wy,ww,wh,wa=sw[j]
                if (80<wa<2200 and 10<ww<52 and 10<wh<52 and .65<ww/wh<1.5
                        and wx+ax-3<x+w/2<wx+ax+ww+3 and wy+ay-3<y+h/2<wy+ay+wh+3):
                    radius=max(ww,wh)*.95
                    ball=Box(float(wx+ax+ww/2-radius),float(wy+ay+wh/2-radius),radius*2,radius*2)
                    break
            if ball:
                if not any(d.kind=='pinball'and d.box.overlaps(ball) for d in detections):
                    detections.append(Detection(ball,'pinball',.95))
                continue
            red_candidates.append(Box(float(x),float(y),float(w),float(h)))
        groups=[]
        for b in red_candidates:
            group=next((g for g in groups if any(abs(b.center[0]-v.center[0])<52
                                                  and abs(b.center[1]-v.center[1])<28 for v in g)),None)
            if group is None:
                groups.append([b])
            else:
                group.append(b)
        for group in groups:
            x1=min(b.x for b in group);x2=max(b.x+b.w for b in group)
            y1=min(b.y for b in group);y2=max(b.y+b.h for b in group)
            cx,cy=(x1+x2)/2,(y1+y2)/2
            b=Box(cx-24,cy-15,48.,30.)
            if not any(b.overlaps(d.box) for d in detections):
                detections.append(Detection(b,'red_enemy',.88,bool(x2-x1>30 and y2-y1<16)))
        for i in range(1, n):
            x, y, w, h, area = stats[i]
            if body and i == body[0]:
                continue
            if (x < 80 or y < 65 or x + w > 639 or y + h > 350
                    or not (70 < area < 4500 and 12 <= w < 105 and 10 <= h < 105)):
                continue
            if player and x + w < player.x - 35:
                continue
            kind = 'dark_object'
            confidence = .45
            if any(Box(float(x),float(y),float(w),float(h)).overlaps(d.box) for d in detections):
                continue
            # Thin rope fragments, tiny floor dust and decorative background chips
            # are excluded. Unknown compact foreground remains explicitly uncertain.
            if w / h > 4 or (self.rope and abs(y + h - self.rope) < 9 and h < 18):
                continue
            if player and Box(float(x),float(y),float(w),float(h)).overlaps(player, 3):
                continue
            detections.append(Detection(Box(float(x), float(y), float(w), float(h)), kind, confidence))
        return self._finish(rgb,stamp,player,detections,body)

    def _finish(self,rgb,stamp,player,detections,body=None):
        phase = 'unknown'
        tracks = []
        support=None
        rope_hint=arrow_score(rgb,95)>.5
        if rope_hint:
            self.support_mode='rope';self.last_rope_hint=stamp
        on_rope=self.support_mode=='rope'
        terrain=None
        if not on_rope:
            terrain=self.ground.observe(rgb,player,stamp)
        elif (stamp-self.last_rope_hint>1.5 and not self.jump_count and stamp-self.last_action>1.):
            candidate=self.ground.observe(rgb,player,stamp)
            if (candidate and candidate['at_player'] and player
                    and 15<candidate['y']+7-player.center[1]<43):
                terrain=candidate;on_rope=False;self.support_mode='ground'
        if player:
            px, py = player.center
            support=self.rope if on_rope else (terrain['y']+7 if terrain and terrain['y']is not None else None)
            if self.active_motion and not self.visual_role:
                name=self.active_motion['name'];elapsed=max(0,stamp-self.active_motion['started'])
                offset_x,root_y,offset_y,width,height=motion.point(name,elapsed,self.active_motion)
                origin=self.motion_origin;scale=origin['scale']
                cx=origin['x']+offset_x*scale
                cy=(support or 0)+origin['y']-(root_y+offset_y)*scale
                w=origin['stand_w']*width/motion.DATA['stand_width']
                h=origin['stand_h']*height/motion.DATA['stand_height']
                player=Box(cx-w/2,cy-h/2,w,h)
                px,py=player.center
            vertical = py-(support or 0)
            if self.previous_player and self.last is not None:
                dt = stamp - self.last
                if dt > .005:
                    self.player_velocity = .6 * self.player_velocity + .4 * (
                        vertical - self.previous_vertical) / dt
            if (support is not None and 16 < abs(py-support) < 43
                    and stamp-self.last_action > .25):
                phase = ('rope_above' if py < support else 'rope_below') if on_rope else 'ground'
                if stamp - self.last_action > .22 and not self.active_motion:
                    self.jump_count = 0
            else:
                phase = ('jump2' if self.jump_count >= 2 else 'jump1' if self.jump_count else 'air')
                phase += '_rising' if self.player_velocity < -30 else '_falling'
            if terrain and terrain['y']is not None and stamp<self.sliding_until:
                if py>terrain['y']-25:
                    player=Box(player.x,terrain['y']-8,player.w,10.)
                    phase='slide'
            if self.active_motion:
                name=self.active_motion['name'];elapsed=max(0,stamp-self.active_motion['started'])
                phase=motion.phase(name,elapsed,self.active_motion)
                if motion.is_rope_transition(name)and elapsed>=motion.duration(name,self.active_motion):
                    self.active_motion=None;self.jump_count=0
                elif name.startswith('jump')and 'falling' in phase and support is not None:
                    available=on_rope or bool(terrain and terrain['at_player'])
                    landing=support-.75*self.motion_origin['scale']
                    if available and py>=landing-(3 if self.visual_role else 0) and (not self.visual_role or abs(py-landing)<15):
                        if not self.visual_role:
                            player=Box(player.x,landing-self.motion_origin['stand_h']/2,
                                       self.motion_origin['stand_w'],self.motion_origin['stand_h'])
                        phase='rope_above'if on_rope else 'ground'
                        self.active_motion=None;self.jump_count=0
            if not self.visual_role and not self.active_motion and phase in ('rope_above','rope_below')and support is not None:
                center=support+30 if phase=='rope_below'else support-29
                player=Box(player.x,center-player.h/2,player.w,player.h)
            # Use the visible rope as vertical camera reference. A player's flip
            # must not become a fictitious upward velocity of every crow.
            tracks = self.tracker.update(detections, stamp, (px,support if support is not None else py))
            self.previous_player, self.last = player, stamp
            self.previous_vertical = vertical
        elif on_rope and self.rope is not None and self.previous_player is not None:
            # A high jump can leave the image while enemies remain visible.
            # Keep their state history using the visible camera reference;
            # missing role pixels still prohibit choosing an input.
            tracks=self.tracker.update(detections,stamp,(self.previous_player.center[0],self.rope))
        result=dict(time=stamp, player=player, silhouette=body[1] if body else None,
                    rope=self.rope, phase=phase, vy=self.player_velocity, jumps=self.jump_count,
                    tracks=tracks, detections=detections,terrain=terrain,
                    motion_reference='support' if support is not None else 'player',
                    scale_px=self.body_height*.73/.936,stand_w=self.body_height*.36,
                    stand_h=self.body_height*.73,motion=self.active_motion)
        self.last_observation=result
        return result


def current_offsets(observation):
    active=observation.get('motion')
    if active:
        p=motion.point(active['name'],max(0,observation['time']-active['started']),active)
        return p[0],p[2]
    return motion.DATA['stand_offset_x'],0.


def can_air_down(observation):
    return (observation.get('player')is not None and observation.get('rope')is not None
            and observation['phase'].startswith('jump')
            and observation['player'].center[1]<observation['rope']+.75*observation.get('scale_px',41.))


def create_motion(observation,name,stamp=None):
    active=dict(name=name,started=observation['time']if stamp is None else stamp)
    if name=='air_down':
        scale=observation.get('scale_px',41.);p=observation['player'];ox,oy=current_offsets(observation)
        delay=motion.DATA['air_down']['input_delay'];previous=observation.get('motion')
        if previous and previous['name'].startswith('jump'):
            elapsed=max(0,observation['time']-previous['started'])
            lead=motion.point(previous['name'],elapsed+delay)[1]-motion.point(previous['name'],elapsed)[1]
        else:
            lead=-observation.get('vy',0.)*delay/scale
        active.update(height=max(0,(observation['rope']-p.center[1])/scale+.75-oy),lead=lead,
                      offset_x=ox,offset_y=oy,width=p.w/scale,height_box=p.h/scale)
    return active


def native_motion_box(observation,name,seconds):
    p=observation['player'];scale=observation.get('scale_px',41.)
    ox,oy=current_offsets(observation)
    parameters=create_motion(observation,name)if name=='air_down'else None
    x,y,offset_y,w,h=motion.point(name,seconds,parameters)
    cx=p.center[0]+(x-ox)*scale
    cy=p.center[1]-(y+offset_y-oy)*scale
    w=observation.get('stand_w',p.w)*w/motion.DATA['stand_width']
    h=observation.get('stand_h',p.h)*h/motion.DATA['stand_height']
    result=Box(cx-w/2,cy-h/2,w,h)
    if name.startswith('jump'):
        result=cap_landing(observation,result,seconds,name)
    return result


def cap_landing(observation,box,seconds,name):
    if seconds<motion.DATA['profiles'][name]['apex']:
        return box
    support=None
    terrain=observation.get('terrain')
    if terrain and terrain['y']is not None:
        x=observation['player'].center[0]+(terrain['speed']or 14*observation.get('scale_px',41.))*seconds
        samples=terrain['samples']
        sample=min(samples,key=lambda s:abs(s[0]-x))if samples else None
        if sample and sample[2]and abs(sample[0]-x)<12:
            support=sample[1]+7
    elif observation.get('rope')is not None:
        support=observation['rope']
    if support is not None:
        cy=support-.75*observation.get('scale_px',41.)
        if box.center[1]>=cy:
            h=observation.get('stand_h',box.h);w=observation.get('stand_w',box.w)
            return Box(box.center[0]-w/2,cy-h/2,w,h)
    return box


def player_future(observation,seconds):
    """Short native-parameter prior, corrected each frame by measured motion."""
    p=observation['player']
    active=observation.get('motion')
    if active:
        elapsed=max(0,observation['time']-active['started'])
        a=motion.point(active['name'],elapsed,active);b=motion.point(active['name'],elapsed+seconds,active)
        scale=observation.get('scale_px',41.)
        cx=p.center[0]+(b[0]-a[0])*scale
        cy=p.center[1]-((b[1]+b[2])-(a[1]+a[2]))*scale
        w=observation.get('stand_w',p.w)*b[3]/motion.DATA['stand_width']
        h=observation.get('stand_h',p.h)*b[4]/motion.DATA['stand_height']
        result=Box(cx-w/2,cy-h/2,w,h)
        if active['name'].startswith('jump'):
            result=cap_landing(observation,result,elapsed+seconds,active['name'])
        return result
    phase=observation['phase']
    if phase in ('ground','slide','rope_above','rope_below','unknown'):
        return p
    scale=observation.get('scale_px',41.)
    vy=observation.get('vy',0.)
    second=observation['jumps']>=2
    up=(9.8 if second else 25.)*3.5*scale
    down=(9.8 if second else 9.)*3.5*scale
    if not observation['jumps']:
        down=19.8*3.5*scale
    if vy<0:
        apex=-vy/up
        rise=min(seconds,apex)
        dy=vy*rise+.5*up*rise*rise+.5*down*max(0,seconds-apex)**2
    else:
        dy=vy*seconds+.5*down*seconds*seconds
    terrain=observation.get('terrain')
    landing=None
    if terrain and terrain['y']is not None:
        x=p.center[0]+(terrain['speed']or 550)*seconds
        samples=terrain['samples']
        sample=min(samples,key=lambda s:abs(s[0]-x)) if samples else None
        if sample and sample[2] and abs(sample[0]-x)<10:
            landing=sample[1]-25
    elif observation.get('rope') is not None:
        landing=observation['rope']-30
    if landing is not None and dy>0:
        dy=min(dy,max(0,landing-p.center[1]))
    return Box(p.x,p.y+dy,p.w,p.h)


def advance_player(observation,seconds):
    """Advance geometry and action state together, including landing/flip end."""
    current=dict(observation,time=observation['time']+seconds)
    if observation['player']is None:
        return current
    current['player']=player_future(observation,seconds)
    active=observation.get('motion')
    if active:
        elapsed=current['time']-active['started'];name=active['name']
        current['phase']=motion.phase(name,elapsed,active)
        if motion.is_rope_transition(name)and elapsed>=motion.duration(name,active):
            current.update(motion=None,jumps=0)
        elif name.startswith('jump')and 'falling'in current['phase']:
            support=observation.get('rope');terrain=observation.get('terrain')
            if terrain and terrain['y']is not None:support=terrain['y']+7
            if support is not None:
                landing=support-.75*observation.get('scale_px',41.)
                if abs(current['player'].center[1]-landing)<.15:
                    current.update(motion=None,jumps=0,phase='ground'if terrain else'rope_above')
    return current


def extrapolate(observation,stamp):
    age=max(0,stamp-observation['time'])
    current=advance_player(observation,age)
    current['observation_age_ms']=age*1000
    current['tracks']=[t.at(age) for t in observation['tracks']]
    return current


def serializable(observation):
    def pack(v):
        if isinstance(v, deque):
            return list(v)
        if hasattr(v, '__dataclass_fields__'):
            return {k: pack(x) for k, x in vars(v).items()}
        if isinstance(v, list):
            return [pack(x) for x in v]
        return v
    return {k: pack(v) for k, v in observation.items()}


def overlay(rgb, observation, action=None, reason=''):
    image = cv2.cvtColor(rgb[:, :, :3], cv2.COLOR_RGB2BGR)
    def rect(b, color):
        cv2.rectangle(image, (int(b.x), int(b.y)), (int(b.x+b.w), int(b.y+b.h)), color, 1)
    if observation['rope'] is not None:
        y = int(observation['rope']); cv2.line(image, (0, y), (639, y), (255, 255, 0), 1)
    if observation['player']:
        rect(observation['player'], (0, 255, 0))
    terrain=observation.get('terrain')
    if terrain:
        for x,y,solid in terrain['samples']:
            if solid:
                cv2.circle(image,(x,y),1,(0,255,255),-1)
        if terrain['edge']is not None:
            x=int(terrain['edge']);cv2.line(image,(x,180),(x,310),(255,0,255),2)
    for t in observation['tracks']:
        color = (0, 0, 255) if t.confidence >= .7 else (140, 140, 140)
        rect(t.box, color)
        x, y = t.box.center
        cv2.arrowedLine(image, (int(x), int(y)), (int(x+t.vx*.2), int(y+t.vy*.2)), color, 1)
        path=np.array([[int(t.future(dt).center[0]),int(t.future(dt).center[1])]
                       for dt in np.arange(0,.51,.05)],np.int32)
        cv2.polylines(image,[path],False,color,1)
        cv2.putText(image, f'{t.id}:{t.vx:.0f},{t.vy:.0f}', (int(t.box.x), int(t.box.y-3)), 0, .3, color, 1)
    cv2.putText(image, f"{observation['phase']} {action or '-'} {reason}", (100, 25), 0, .45, (0, 255, 0), 1)
    return image
