"""Pixels-only baseline: foreground proposals, short tracks and reactive avoidance.

Coordinates are 640x360 screen pixels, velocities pixels/second. This first
detector deliberately has no map IDs, game-object queries or board clock input.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field, replace
import math
from statistics import median
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
    resource: str | None = None
    collider_shape: str | None = None
    quad: tuple | None = None
    velocity_prior: tuple | None = None
    scene_velocity_x: float | None = None
    geometry_restored: bool = False
    pivot_offset_ratio: float | None = None


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
    floor_y: float | None = 0
    floor_vy: float = 0.
    floor_segment: dict | None = None
    rebound_speed: float = 0
    attack_phase: str | None = None
    ready_started: float | None = None
    ready_remaining: float = 0
    rush_scale_remaining: float = 0
    rush_target_w: float = 0
    rush_target_h: float = 0
    horizontal_stopped: bool = False
    resource: str | None = None
    collider_shape: str | None = None
    quad: tuple | None = None
    angular_velocity: float = 0.
    angular_history: deque = field(default_factory=lambda: deque(maxlen=10))
    adaptive_rush_speed: bool = False
    rush_history: deque = field(default_factory=lambda: deque(maxlen=6))
    rush_fit_velocity: float | None = None
    rush_velocity: float | None = None
    confidence_history: deque = field(default_factory=lambda:deque(maxlen=8))
    source_pinball_prior: bool = False

    def update(self, detection, stamp, player, support_y=None):
        if self.quad is not None or detection.quad is not None:
            from arena_oriented import update_rotation
            update_rotation(self,detection,stamp)
        self.resource=detection.resource;self.collider_shape=detection.collider_shape
        self.box, self.kind, self.confidence, self.seen = (
            detection.box, detection.kind, detection.confidence, stamp)
        self.active = detection.active
        self.arming = detection.arming
        self.reference = player
        self.confidence_history.append(detection.confidence)
        if callable(support_y):
            floor=support_y(detection)
            self.floor_y=floor['y']-self.box.h/2 if floor is not None else None
            self.floor_segment=floor['segment']if floor is not None else None
        else:
            self.floor_y=(player[1]if support_y is None else support_y)-self.box.h/2
            self.floor_segment=None
        x, y = self.box.center
        self.history.append((stamp, x - player[0], y - player[1]))
        self.observations += 1
        if detection.velocity_prior is not None and self.observations<3:
            self.vx,self.vy=detection.velocity_prior
        if detection.kind=='bamboo':
            self.attack_phase='bamboo_attack'
        elif detection.attack_phase is not None or self.attack_phase is not None:
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
        if self.kind=='bamboo':
            # Original flyToNinja is a straight horizontal translation. Keep
            # measured horizontal speed; silhouette jitter is not acceleration,
            # oscillation or a rotation of this native attack.
            self.vy=0.;self.ax=self.ay=0.;self.curve_count=self.sine_count=0
            self.angular_velocity=0.
            return
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
            from arena_object_motion import pinball_state
            dy=pinball_state(self,seconds)[0]-self.box.center[1]
        forecast=Box(self.box.x + self.vx * seconds+.5*ax*horizon*horizon,
                   self.box.y+dy,
                   self.box.w, self.box.h)
        if self.quad is not None and self.collider_shape=='BoxCollider':
            from arena_oriented import bounds,transform
            return Box(*bounds(transform(self.quad,self.angular_velocity*seconds,forecast.center)))
        return forecast

    def future_quad(self,seconds):
        if self.quad is None:return None
        from arena_oriented import transform
        return transform(self.quad,self.angular_velocity*seconds,self.future(seconds).center)

    def at(self,seconds):
        result=replace(self,box=self.future(seconds))
        if self.quad is not None:result.quad=self.future_quad(seconds)
        if self.attack_phase in ('ready','rush'):
            moving=max(0,seconds-self.ready_remaining)
            result.ready_remaining=max(0,self.ready_remaining-seconds)
            result.rush_scale_remaining=max(0,self.rush_scale_remaining-moving)
            if result.ready_remaining<=0:
                result.attack_phase='rush';result.active=True;result.arming=False
            return result
        if self.ballistic:
            from arena_object_motion import pinball_state,floor_horizon
            _,result.vy=pinball_state(self,seconds)
            result.floor_y=(self.floor_y+self.floor_vy*seconds
                            if self.floor_y is not None and seconds<=floor_horizon(self)else None)
            if self.floor_segment:
                result.floor_segment=dict(self.floor_segment)
                for key in ('a','b'):
                    x,y=self.floor_segment[key]
                    result.floor_segment[key]=(x+self.floor_segment['vx']*seconds,y+self.floor_segment['vy']*seconds)
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


def track_confidence(track,stamp):
    """A brief weak/occluded frame cannot erase a repeatedly confirmed hazard."""
    if not track.confidence_history:return track.confidence
    confirmed=median(track.confidence_history)-.6*max(0,stamp-track.seen)
    return max(track.confidence,confirmed)


class Tracker:
    def __init__(self,adaptive=False,adaptive_rush_speed=False):
        self.adaptive=adaptive;self.adaptive_rush_speed=adaptive_rush_speed
        self.source_pinball_prior=False
        self.tracks = []
        self.next_id = 1

    def update(self, detections, stamp, player, support_y=None):
        available = {t.id: t for t in self.tracks if stamp - t.seen < .22}
        predicted={identity:t.future(stamp-t.seen).center for identity,t in available.items()}
        pairs = []
        for i, d in enumerate(detections):
            for t in available.values():
                elapsed=stamp-t.seen
                tx, ty = predicted[t.id]
                # A new repeated trap has no fitted motion yet. Match it after
                # the measured scene translation, rather than to its neighbour
                # at the old screen position. Mature tracks keep their own fit.
                if (t.kind=='trap'and t.observations<3 and d.scene_velocity_x is not None
                        and math.isfinite(d.scene_velocity_x)):
                    tx=t.box.center[0]+d.scene_velocity_x*elapsed
                x, y = d.box.center
                ox,oy=player[0]-t.reference[0],player[1]-t.reference[1]
                distance = math.hypot(x-(tx+ox),y-(ty+oy))
                compatible=(d.kind==t.kind or {d.kind,t.kind}<={'eye_enemy','spider'})
                if d.collider_shape and t.collider_shape and ((d.collider_shape=='BoxCollider')!=(t.collider_shape=='BoxCollider')):
                    compatible=False
                if (compatible and distance < max(35, min(180, 1600 * elapsed + 12))
                        and abs(y-(ty+oy)) < max(19,abs(t.vy)*elapsed+12)):
                    pairs.append((distance, i, t.id))
        used, matched = set(), set()
        for _, i, identity in sorted(pairs):
            if i not in used and identity not in matched:
                available[identity].update(detections[i], stamp, player,support_y)
                used.add(i); matched.add(identity)
        for i, d in enumerate(detections):
            if i not in used:
                track_type=Track
                if d.kind=='arrow':
                    from arena_arrow_motion import ArrowTrack
                    track_type=ArrowTrack
                elif d.kind=='mace':
                    from arena_mace_motion import MaceTrack
                    track_type=MaceTrack
                t = track_type(self.next_id, d.box, d.kind, d.confidence, stamp)
                t.source_pinball_prior=self.source_pinball_prior and d.kind=='pinball'
                t.adaptive_rush_speed=self.adaptive_rush_speed
                if self.adaptive:
                    t.adaptive_velocity=True;t.history=deque(maxlen=64)
                self.next_id += 1
                t.update(d, stamp, player,support_y)
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
                floor_segment=prediction.floor_segment
                if floor_segment:
                    floor_segment=dict(floor_segment)
                    for key in ('a','b'):floor_segment[key]=(floor_segment[key][0]+dx,floor_segment[key][1]+dy)
                output.append(replace(prediction,box=b,confidence=t.confidence-age*.6,
                                      reference=player,floor_y=prediction.floor_y+dy if prediction.floor_y is not None else None,
                                      floor_segment=floor_segment,
                                      quad=tuple((x+dx,y+dy)for x,y in prediction.quad)if prediction.quad else None))
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
        self.support_mode=None
        self.last_rope_hint=-10
        self.last_observation=None
        self.active_motion=None
        self.motion_origin=None
        self.horizontal_history=deque(maxlen=6)
        self.player_horizontal_velocity=0.
        self.pending_rope_clamp=False

    def action(self, action, stamp, observation=None,*,primitive=None,source_observation=None):
        self.last_action = stamp
        current=observation or self.last_observation
        phase=current['phase'] if current else 'unknown'
        name=None
        support_unconfirmed=False
        if action == 'jump':
            if current and can_air_up(current):
                name='air_up';self.jump_count=current.get('jumps',self.jump_count)
            elif primitive=='air_up'and current and source_observation and can_air_up(source_observation):
                # The key has already been sent. Losing the visible rope before
                # ACK cannot turn that recovery command into a claimed jump2.
                # Retain only our last pixel target as an uncertain short-term
                # trajectory; a fresh actual support/body contact must end it.
                surface=rope_reference_height(source_observation,stamp,current['player'].center[0])
                current=dict(current,phase='flip_down',rope=surface,rope_segment=None,rope_segments=[],
                             terrain=None,motion=source_observation['motion'])
                name='air_up';support_unconfirmed=True
                self.jump_count=source_observation.get('jumps',self.jump_count)
            elif phase=='rope_below':
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
                name='air_down';self.jump_count=current.get('jumps',self.jump_count)
            elif (primitive=='air_down'and current and source_observation
                    and can_reverse_rope_up(source_observation)):
                # A submitted left during original state4 remains a down
                # reversal even if its finite pixel rope ends before ACK.
                surface=rope_reference_height(source_observation,stamp,current['player'].center[0])
                current=dict(current,phase='flip_up',rope=surface,rope_segment=None,rope_segments=[],
                             terrain=None,motion=source_observation['motion'])
                name='air_down';support_unconfirmed=True
                self.jump_count=source_observation.get('jumps',self.jump_count)
        elif action=='slide':
            name='slide'
        if name and current and current['player']:
            self.active_motion=create_motion(current,name,stamp)
            if name in ('air_down','air_up')and self.visual_role:
                self.active_motion['requires_contact']=True
            if support_unconfirmed:
                self.active_motion.update(requires_contact=True,support_unconfirmed=True)
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

    def _finish(self,rgb,stamp,player,detections,body=None,support_observation=None,player_observed=True):
        down_action_end_observed=False
        if self.active_motion and (player is None or not player_observed):
            self.active_motion=dict(self.active_motion)
            self.active_motion.pop('pose_restore_since',None)
        phase = 'unknown'
        tracks = []
        support=None
        floor_query=None
        if support_observation and support_observation.get('tracking_reference')is not None:
            from arena_object_support import object_support
            floor_query=lambda d:object_support(support_observation['segments'],d)
        rope_hint=support_observation is None and arrow_score(rgb,95)>.5
        if rope_hint:
            self.support_mode='rope';self.last_rope_hint=stamp
        on_rope=self.support_mode=='rope'
        terrain=None
        if support_observation is not None:
            self.support_mode=support_observation['mode']
            on_rope=self.support_mode=='rope'
            self.rope=support_observation['rope']
            terrain=support_observation['terrain']
        elif not on_rope:
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
            if support_observation and support_observation.get('tracking_reference')is not None:
                vertical=py-support_observation['tracking_reference'][1]
                active=self.active_motion
                offset=motion.point(active['name'],max(0,stamp-active['started']),active)[0]if active else motion.DATA['stand_offset_x']
                from arena_projection import SCALE
                self.horizontal_history.append((stamp,px-offset*SCALE))
                if len(self.horizontal_history)>=3:
                    samples=np.asarray(self.horizontal_history);times=samples[:,0]-stamp
                    if times[0]<-.035:
                        design=np.column_stack((np.ones(len(times)),times))
                        fit,_,_,_=np.linalg.lstsq(design,samples[:,1],rcond=None)
                        self.player_horizontal_velocity=float(fit[1])
            if self.previous_player and self.last is not None:
                dt = stamp - self.last
                if dt > .005:
                    self.player_velocity = .6 * self.player_velocity + .4 * (
                        vertical - self.previous_vertical) / dt
            support_available=(support_observation is None or on_rope or bool(terrain and terrain['at_player']))
            if (self.visual_role and support_observation is not None and self.active_motion
                    and motion.is_rope_transition(self.active_motion['name'])
                    and self.active_motion.get('destination','rope')=='rope'and not on_rope):
                self.active_motion=dict(self.active_motion,requires_contact=True,support_unconfirmed=True)
            if (support_available and support is not None and 16 < abs(py-support) < 43
                    and stamp-self.last_action > .25):
                phase = ('rope_above' if py < support else 'rope_below') if on_rope else 'ground'
                if stamp - self.last_action > .22 and not self.active_motion and(not self.visual_role or player_observed):
                    self.jump_count = 0
            else:
                phase = ('jump2' if self.jump_count >= 2 else 'jump1' if self.jump_count else 'air')
                phase += '_rising' if self.player_velocity < -30 else '_falling'
            if self.active_motion:
                name=self.active_motion['name'];elapsed=max(0,stamp-self.active_motion['started'])
                phase=motion.phase(name,elapsed,self.active_motion)
                if motion.is_ground_transition(name):
                    if elapsed>=motion.duration(name,self.active_motion)and abs(motion.point(name,elapsed,self.active_motion)[0]-motion.DATA['stand_offset_x'])<.005:
                        self.active_motion=None
                elif motion.is_rope_transition(name)and (elapsed>=motion.duration(name,self.active_motion)
                        or (name=='air_up'or self.active_motion.get('support_unconfirmed'))
                        and elapsed>=motion.DATA['air_up']['input_delay']and player_observed
                        and down_contact(dict(player=player,rope=self.rope,
                            rope_segment=(support_observation or{}).get('rope_segment'),
                            rope_segments=(support_observation or{}).get('rope_segments',[]),terrain=terrain,
                            scale_px=self.motion_origin['scale'],stand_h=self.motion_origin['stand_h']),self.active_motion)):
                    requires=self.active_motion.get('requires_contact',False)
                    arrived=not requires or player_observed and down_contact(dict(
                        player=player,rope=self.rope,rope_segment=(support_observation or{}).get('rope_segment'),
                        rope_segments=(support_observation or{}).get('rope_segments',[]),terrain=terrain,
                        scale_px=self.motion_origin['scale'],vx=self.player_horizontal_velocity,
                        stand_h=self.motion_origin['stand_h']),self.active_motion)
                    recovered=False
                    if (not arrived and requires and self.active_motion.get('destination')=='ground'
                            and player_observed and player.h>=.85*self.motion_origin['stand_h']
                            and player.w>=.8*self.motion_origin['stand_w']):
                        since=self.active_motion.get('pose_restore_since',stamp)
                        self.active_motion=dict(self.active_motion,pose_restore_since=since)
                        recovered=stamp-since>=.035
                    elif self.active_motion.get('pose_restore_since')is not None:
                        self.active_motion=dict(self.active_motion)
                        self.active_motion.pop('pose_restore_since',None)
                    if recovered:
                        # Original rollToGround can land briefly and leave a
                        # narrow platform between images (fallFromRun). Normal
                        # body restoration ends its compact input lock; absent
                        # visible support still means airborne, not grounded.
                        self.active_motion=None;self.jump_count=0;phase='air_falling'
                        down_action_end_observed=True
                    elif arrived:
                        if requires:
                            phase=('ground'if not on_rope and terrain and terrain.get('at_player')
                                   else transition_landing_phase(self.active_motion))
                        self.active_motion=None;self.jump_count=0
                    else:
                        self.active_motion=dict(self.active_motion,contact_pending=True)
                        phase='flip_up'if name in ('air_up','rope_up')else'flip_down'
                elif name.startswith('jump')and 'falling' in phase and support is not None:
                    available=on_rope or bool(terrain and terrain['at_player'])
                    landing=support-.75*self.motion_origin['scale']
                    if (available and (not self.visual_role or player_observed)
                            and py>=landing-(3 if self.visual_role else 0)and(not self.visual_role or abs(py-landing)<15)):
                        if not self.visual_role:
                            player=Box(player.x,landing-self.motion_origin['stand_h']/2,
                                       self.motion_origin['stand_w'],self.motion_origin['stand_h'])
                        phase='rope_above'if on_rope else 'ground'
                        self.active_motion=landing_recovery(self.active_motion,stamp)if not on_rope else None;self.jump_count=0
            if not self.visual_role and not self.active_motion and phase in ('rope_above','rope_below')and support is not None:
                center=support+30 if phase=='rope_below'else support-29
                player=Box(player.x,center-player.h/2,player.w,player.h)
            # Use the visible rope as vertical camera reference. A player's flip
            # must not become a fictitious upward velocity of every crow.
            reference=(support_observation.get('tracking_reference')if support_observation else None)
            tracks = self.tracker.update(detections, stamp, reference or (px,support if support is not None else py),floor_query or support)
            self.previous_player, self.last = player, stamp
            self.previous_vertical = vertical
        elif on_rope and self.rope is not None and self.previous_player is not None:
            # A high jump can leave the image while enemies remain visible.
            # Keep their state history using the visible camera reference;
            # missing role pixels still prohibit choosing an input.
            reference=(support_observation.get('tracking_reference')if support_observation else None)
            tracks=self.tracker.update(detections,stamp,reference or (self.previous_player.center[0],self.rope),floor_query or self.rope)
        result=dict(time=stamp, player=player, silhouette=body[1] if body else None,
                    rope=self.rope, phase=phase, vy=self.player_velocity, jumps=self.jump_count,
                    tracks=tracks, detections=detections,terrain=terrain,
                    motion_reference='support' if support is not None else 'player',
                    pending_rope_clamp=self.pending_rope_clamp,
                    scale_px=self.body_height*.73/.936,stand_w=self.body_height*.36,
                    stand_h=self.body_height*.73,motion=self.active_motion,vx=self.player_horizontal_velocity)
        result['ground_contact_observed']=bool(self.visual_role and player_observed and player
            and phase=='ground'and (not self.active_motion or motion.is_ground_transition(self.active_motion['name']))and support_available
            and player.h>=.65*(self.motion_origin['stand_h']if self.motion_origin else self.body_height*.73))
        result['down_action_end_observed']=down_action_end_observed
        result['rope_contact_observed']=bool(self.visual_role and player_observed and player
            and phase in ('rope_above','rope_below')and not self.active_motion and on_rope
            and player.h>=.65*(self.motion_origin['stand_h']if self.motion_origin else self.body_height*.73))
        self.last_observation=result
        if support_observation is not None:
            result['rope_segment']=support_observation.get('rope_segment')
            result['rope_segments']=support_observation.get('rope_segments',[])
        return result


def current_offsets(observation):
    active=observation.get('motion')
    if active:
        p=motion.point(active['name'],max(0,observation['time']-active['started']),active)
        return p[0],p[2]
    return motion.DATA['stand_offset_x'],0.


def root_foot_box(observation):
    """Original movement blocker probes the root/foot, not the hurt capsule."""
    p=observation['player'];ox,oy=current_offsets(observation);scale=observation.get('scale_px',41.)
    return Box(p.center[0]-ox*scale,p.center[1]+(oy+motion.DATA['blocking']['foot_point'])*scale,0.,0.)


def constrain_ground_motion(before,after):
    """Original forward movement stops at next ground X minus climbDistance."""
    from arena_support import leading_ground_faces,height,advance_terrain
    faces=before.get('blocking_faces')
    if faces is None:
        faces=[dict(f,stamp=before['time'])for f in leading_ground_faces(before.get('visible_supports',[]),before['time'])]
    if not faces or before['player']is None or after['player']is None:return after
    first=root_foot_box(before);last=root_foot_box(after);scale=before.get('scale_px',41.)
    clearance=motion.DATA['blocking']['climb_distance']*scale
    limit=None
    for face in faces:
        dt0=before['time']-face['stamp'];dt1=after['time']-face['stamp']
        x0=face['x']+face['vx']*dt0;x1=face['x']+face['vx']*dt1
        ground=face['y']-6+face['vy']*dt1
        if first.center[0]>x0+3 or last.center[1]<=ground:continue
        allowed=x1-clearance
        if last.center[0]>allowed:limit=allowed if limit is None else min(limit,allowed)
    if limit is None:return after
    after=dict(after);p=after['player'];ox,_=current_offsets(after)
    after['player']=Box(limit+ox*scale-p.w/2,p.y,p.w,p.h)
    after['predicted_blocked']=True
    terrain=before.get('terrain');seconds=after['time']-before['time']
    if before.get('motion')is None and before['phase']in ('ground','slide')and terrain and terrain.get('source')=='neural_segments':
        selected=next(s for s in terrain['segments']if s['id']==terrain['selected_id'])
        y0=height(selected,before['player'].center[0]);y1=height(selected,after['player'].center[0],seconds)
        if y0 is not None and y1 is not None:
            p=after['player'];after['player']=Box(p.x,before['player'].y+y1-y0,p.w,p.h)
            after.update(phase=before['phase'],motion=None,jumps=0,vy=0.)
        after['terrain']=advance_terrain(terrain,seconds,after['player'].center[0])
    if before.get('motion')is None and before['phase']in ('rope_above','rope_below')and before.get('rope_segment'):
        y0=rope_height(before);y1=rope_height(after)
        if y0 is not None and y1 is not None:
            p=after['player'];after['player']=Box(p.x,before['player'].y+y1-y0,p.w,p.h)
            after.update(rope=y1,phase=before['phase'],motion=None,jumps=0,vy=0.)
    return after


def can_air_down(observation):
    if can_reverse_rope_up(observation):return True
    if (observation.get('player')is not None and observation.get('rope')is None
            and(observation.get('terrain')or{}).get('source')=='neural_segments'):
        return (observation['phase'].startswith(('jump','air_'))
                and ground_down_target(observation)is not None)
    surface,destination=down_surface(observation)
    allowed=(observation.get('player')is not None and surface is not None
            and observation['phase'].startswith(('jump','air_'))
            and observation['player'].center[1]<surface+(.75 if destination=='rope'else -.75)*observation.get('scale_px',41.))
    if allowed and destination=='ground':
        active=create_motion(observation,'air_down')
        future,_=down_surface(observation,motion.duration('air_down',active))
        return future is not None
    return allowed


def can_reverse_rope_up(observation):
    """Restrict the newly calibrated state4 reversal to confirmed flat rope."""
    active=observation.get('motion')
    # Native IsInAir uses GroundCollider.PointStart.y, which a cropped slope
    # cannot supply. Check all visible pieces as well as the selected segment:
    # a flat local piece must not hide a slope in the same rope observation.
    # One pixel / 1% only tolerates endpoint measurement noise, not game slope.
    segments=list(observation.get('rope_segments')or[])
    if observation.get('rope_segment')is not None:segments.append(observation['rope_segment'])
    flat=all(s['b'][0]-s['a'][0]>=4 and abs(s['b'][1]-s['a'][1])<=1.
             and abs(s['b'][1]-s['a'][1])<=.01*(s['b'][0]-s['a'][0])for s in segments)
    return bool(observation.get('player')is not None and observation.get('rope')is not None
                and observation.get('terrain')is None and observation.get('phase')=='flip_up'
                and active and active['name']in ('air_up','rope_up')
                and active.get('destination','rope')=='rope'and flat and rope_height(observation)is not None)


def can_air_up(observation):
    """Original right input can redirect a rope down transfer before contact."""
    active=observation.get('motion')
    return bool(observation.get('player')is not None and observation.get('rope')is not None
                and observation.get('phase')=='flip_down'and active
                and active['name']in ('air_down','rope_down')
                and active.get('destination','rope')=='rope'
                and rope_height(observation)is not None)


def transition_landing_phase(active):
    if active.get('destination')=='ground':return 'ground'
    return 'rope_above'if active['name']in ('rope_up','air_up')else'rope_below'


def transition_surface_offset(active,destination):
    return .75 if destination=='rope'and transition_landing_phase(active)=='rope_below'else -.75


def transition_speed(active):
    if active['name']=='air_up':return active['speed']
    if active['name']=='rope_up':return -motion.DATA['air_up']['up_speed']
    if active['name']=='rope_down':return motion.DATA['air_up']['up_speed']
    return active.get('speed',motion.DATA['air_down']['speed'])


def rope_reference_height(observation,stamp,x):
    """Extrapolate a last pixel line as a reference, not as verified support."""
    segment=observation.get('rope_segment')
    if segment is None:return observation['rope']
    a,b=segment['a'],segment['b'];dt=stamp-observation['time']
    slope=(b[1]-a[1])/max(1e-6,b[0]-a[0])
    return a[1]+segment.get('vy',0.)*dt+slope*(x-a[0]-segment.get('vx',0.)*dt)


def down_surface(observation,seconds=0):
    if observation.get('rope')is not None:return rope_height(observation,seconds),'rope'
    terrain=observation.get('terrain')
    if terrain and terrain.get('source')=='neural_segments'and observation.get('player'):
        from arena_support import landing_height
        return landing_height(terrain,observation['player'].center[0]+observation.get('vx',0.)*seconds,seconds,observation['player'].center[1]),'ground'
    if terrain and terrain.get('at_player')and terrain.get('y')is not None:return terrain['y']+7,'ground'
    return None,None


def down_contact(observation,active):
    """A restored collider at the visible surface acknowledges native landing."""
    surface,destination=down_surface(observation)
    if surface is None:return False
    expected=active.get('destination','rope')
    if destination!=expected and not(active.get('support_unconfirmed')and destination=='ground'):
        return False
    p=observation['player'];scale=observation.get('scale_px',41.)
    target=surface+transition_surface_offset(active,destination)*scale
    offset=p.center[1]-target
    tolerance=8.
    if destination=='rope'and active['name']=='air_up'and offset*active['speed']<=0:
        tolerance+=abs(active['speed'])*motion.DATA['air_up']['collider_restore_lead']*scale
    return p.h>=.85*observation.get('stand_h',motion.DATA['stand_height']*scale)and abs(offset)<=tolerance


def air_down_lead(observation,delay=None):
    delay=motion.DATA['air_down']['input_delay']if delay is None else delay
    previous=observation.get('motion')
    if previous and (previous['name'].startswith('jump')or motion.is_rope_transition(previous['name'])):
        elapsed=max(0,observation['time']-previous['started'])
        if previous.get('contact_pending'):
            return -transition_speed(previous)*delay
        return motion.point(previous['name'],elapsed+delay,previous)[1]-motion.point(previous['name'],elapsed,previous)[1]
    return -observation.get('vy',0.)*delay/observation.get('scale_px',41.)


def ground_down_target(observation):
    """Intersect native downward motion with each actually visible moving top.

    The role need not already be horizontally above its eventual landing. Solve
    contact time first, then require the original finite segment at that time;
    never fabricate a floor across the gap between two platforms.
    """
    from arena_support import height
    p=observation['player'];scale=observation.get('scale_px',41.);ox,oy=current_offsets(observation)
    x=p.center[0]-ox*scale;vx=observation.get('vx',0.)
    lead=air_down_lead(observation);prior=motion.DATA['air_down'];choices=[]
    for s in observation['terrain']['segments']:
        if s['kind']=='rope'or s.get('confidence',1.)<.25:continue
        a,b=s['a'],s['b']
        if b[0]-a[0]<4:continue
        slope=(b[1]-a[1])/(b[0]-a[0])
        surface=a[1]+slope*(x-a[0])
        target=(surface-p.center[1])/scale-.75-oy
        velocity=(s.get('vy',0.)+slope*(vx-s.get('vx',0.)))/scale
        relative=prior['speed']-velocity
        if target<=0 or relative<=0:continue
        contact=(target+lead+prior['speed']*prior['input_delay'])/relative
        if not prior['input_delay']<=contact<=1.:continue
        settled=contact+prior['settle_seconds']
        if height(s,x+vx*contact,contact)is None or height(s,x+vx*settled,settled)is None:continue
        choices.append(dict(height=target,lead=lead,destination='ground',surface_velocity=velocity,
                            contact_seconds=contact,surface_id=s['id']))
    return min(choices,key=lambda c:c['contact_seconds'])if choices else None


def create_motion(observation,name,stamp=None):
    active=dict(name=name,started=observation['time']if stamp is None else stamp)
    previous=observation.get('motion')
    if (name=='jump2'and observation.get('incoming_jump2')and previous
            and previous['name']=='jump1'):
        scale=observation.get('scale_px',41.);p=observation['player'];ox,oy=current_offsets(observation)
        active['jump_entry']=dict(parent=dict(previous),age=max(0.,observation['time']-previous['started']),
            initial_point=[ox,0.,oy,p.w/scale,p.h/scale])
    if previous and (motion.is_ground_transition(previous['name'])or previous.get('offset_carry_x')):
        elapsed=max(0,observation['time']-previous['started'])
        if previous['name']=='slide'and motion.phase('slide',elapsed)=='slide':
            # Two original fixed updates can finish before EnterJump switches
            # physics; the parent then freezes throughout the airborne phase.
            ox=motion.point('slide',elapsed,previous)[0]-.026
            prior=motion.DATA['profiles']['slide'];target=prior['offset_target_x']
            carry=target-(target-ox)*prior['slide_multiplier']**2 if name.startswith('jump')else ox
        else:
            carry=motion.point(previous['name'],elapsed,previous)[0]-motion.DATA['stand_offset_x']
        active['offset_carry_x']=carry
    if name=='slide':
        scale=observation.get('scale_px',41.)
        active['base_speed']=(max(0,(observation.get('vx',0.)-observation['scene_velocity_x'])/scale)
                              if observation.get('scene_motion_observed')else motion.DATA['profiles']['slide']['reference_speed'])
    if name=='air_up':
        if not can_air_up(observation):raise ValueError('Upper rope recovery requires an active rope down transfer')
        scale=observation.get('scale_px',41.);p=observation['player'];ox,oy=current_offsets(observation)
        surface=rope_height(observation);future=rope_height(observation,.04)
        height=(surface-p.center[1])/scale-.75-oy
        elapsed=max(0,observation['time']-previous['started']);delay=motion.DATA['air_up']['input_delay']
        lead=motion.point(previous['name'],elapsed+delay,previous)[1]-motion.point(previous['name'],elapsed,previous)[1]
        prior=motion.DATA['air_up']
        active.update(height=height,lead=lead,speed=prior['down_speed']if height+lead>0 else -prior['up_speed'],destination='rope',
                      surface_velocity=(future-surface)/(.04*scale)if future is not None else 0.,
                      offset_x=ox,offset_y=oy,width=p.w/scale,height_box=p.h/scale)
    if name=='air_down':
        scale=observation.get('scale_px',41.);p=observation['player'];ox,oy=current_offsets(observation)
        if observation.get('ground_down_collider_restore'):
            active['collider_restore_lead']=motion.DATA['air_down']['ground_collider_restore_lead']
        if (observation.get('rope')is None and(observation.get('terrain')or{}).get('source')=='neural_segments'):
            target=ground_down_target(observation)
            if target is None:raise ValueError('No visible ground intersects the native down trajectory')
            return dict(active,**target,offset_x=ox,offset_y=oy,width=p.w/scale,height_box=p.h/scale)
        surface,destination=down_surface(observation);future,_=down_surface(observation,.04)
        reversing=can_reverse_rope_up(observation)
        delay=motion.DATA['air_down'].get('reverse_input_delay',motion.DATA['air_down']['input_delay'])if reversing else motion.DATA['air_down']['input_delay']
        lead=air_down_lead(observation,delay)
        if reversing:
            # IsInAirWhenEnterRollToLineDown compares original root height to
            # rope+foot+InAirOffsetWhenEnterRollToLineDown at action entry.
            # The offset is supplied by the original static-field probe.
            root_height=(surface-p.center[1])/scale-oy+lead
            prior=motion.DATA['air_down']
            active.update(speed=prior['speed']if root_height>.75+prior['reverse_air_offset']
                          else motion.DATA['air_up']['up_speed'],input_delay=delay,redirected_from=previous['name'])
        active.update(height=max(0,(surface-p.center[1])/scale+(.75 if destination=='rope'else -.75)-oy),lead=lead,
                      destination=destination,surface_velocity=(future-surface)/(.04*scale)if future is not None else 0.,
                      offset_x=ox,offset_y=oy,width=p.w/scale,height_box=p.h/scale)
    return active


def landing_recovery(active,stamp):
    carry=active.get('offset_carry_x',0.)
    return dict(name='ground_recovery',started=stamp,offset_carry_x=carry)if abs(carry)>.005 else None


def native_motion_box(observation,name,seconds):
    p=observation['player'];scale=observation.get('scale_px',41.)
    ox,oy=current_offsets(observation)
    parameters=create_motion(observation,name)
    if name=='slide':
        return ground_primitive_future(dict(observation,motion=parameters),seconds)
    x,y,offset_y,w,h=motion.point(name,seconds,parameters)
    cx=p.center[0]+(x-ox)*scale+observation.get('vx',0.)*seconds
    cy=p.center[1]-(y+offset_y-oy)*scale
    w=observation.get('stand_w',p.w)*w/motion.DATA['stand_width']
    h=observation.get('stand_h',p.h)*h/motion.DATA['stand_height']
    result=Box(cx-w/2,cy-h/2,w,h)
    if name.startswith('jump'):
        result=cap_landing(observation,result,seconds,name,parameters=parameters)
    return result


def ground_primitive_future(observation,seconds):
    """Original slide/recovery shape; follow terrain at root X, not body X."""
    from arena_support import height,connected_height
    active=observation['motion'];name=active['name'];elapsed=max(0,observation['time']-active['started'])
    a=motion.point(name,elapsed,active);b=motion.point(name,elapsed+seconds,active)
    scale=observation.get('scale_px',41.);p=observation['player']
    base_vx=observation.get('vx',0.)-motion.root_extra_velocity(name,elapsed,active)*scale
    def root_dx(t):
        return base_vx*t+(motion.root_extra(name,elapsed+t,active)-motion.root_extra(name,elapsed,active))*scale
    root_x=p.center[0]-a[0]*scale;dx=root_dx(seconds)
    cy=p.center[1]-((b[1]+b[2])-(a[1]+a[2]))*scale
    w=observation.get('stand_w',p.w)*b[3]/motion.DATA['stand_width']
    h=observation.get('stand_h',p.h)*b[4]/motion.DATA['stand_height']
    terrain=observation.get('terrain')
    if terrain and terrain.get('source')=='neural_segments'and terrain['at_player']:
        segments=terrain['segments'];selected=next(s for s in segments if s['id']==terrain['selected_id'])
        y0=height(selected,root_x)
        y1=connected_height(segments,selected['id'],root_x+dx,seconds)
        if y0 is not None and y1 is not None:cy+=y1-y0
        elif y0 is not None:
            # Find the visible end in time. Do not extend the slide along an
            # infinite slope or keep the small body after stepping into air.
            lo,hi=0.,seconds
            for _ in range(12):
                mid=(lo+hi)/2
                if connected_height(segments,selected['id'],root_x+root_dx(mid),mid)is None:hi=mid
                else:lo=mid
            end=connected_height(segments,selected['id'],root_x+root_dx(lo),lo)
            cy+=(end-y0 if end is not None else 0)+.5*motion.DATA['fall_from_run']['gravity']*scale*(seconds-lo)**2
            h=max(h,observation.get('stand_h',p.h))
    cx=p.center[0]+dx+(b[0]-a[0])*scale
    return Box(cx-w/2,cy-h/2,w,h)


def cap_landing(observation,box,seconds,name,forecast_seconds=None,parameters=None):
    if seconds<motion.apex(name,parameters):
        return box
    support=None
    terrain=observation.get('terrain')
    if terrain and terrain.get('source')=='neural_segments':
        from arena_support import landing_height
        support=landing_height(terrain,box.center[0],seconds if forecast_seconds is None else forecast_seconds,
                               observation['player'].center[1])
    elif terrain and terrain['y']is not None:
        x=observation['player'].center[0]+(terrain['speed']or 14*observation.get('scale_px',41.))*seconds
        samples=terrain['samples']
        sample=min(samples,key=lambda s:abs(s[0]-x))if samples else None
        if sample and sample[2]and abs(sample[0]-x)<12:
            support=sample[1]+7
    elif observation.get('rope')is not None:
        support=rope_height(observation,seconds if forecast_seconds is None else forecast_seconds)
    if support is not None:
        cy=support-.75*observation.get('scale_px',41.)
        if box.center[1]>=cy:
            h=observation.get('stand_h',box.h);w=observation.get('stand_w',box.w)
            return Box(box.center[0]-w/2,cy-h/2,w,h)
    return box


def rope_height(observation,seconds=0):
    segment=observation.get('rope_segment')
    if segment:
        from arena_support import connected_height
        return connected_height(observation.get('rope_segments')or[segment],segment['id'],
                                observation['player'].center[0]+observation.get('vx',0.)*seconds,seconds)
    return observation.get('rope')


def supported_future(observation,seconds):
    """Follow the visible slope in the fixed current camera plane, then fall."""
    from arena_support import height,connected_height
    p=observation['player'];terrain=observation.get('terrain');selected=None;segments=[]
    if observation['phase'].startswith('rope_')and observation.get('rope_segment'):
        selected=observation['rope_segment'];segments=observation.get('rope_segments')or[selected]
    elif terrain and terrain.get('source')=='neural_segments'and terrain['at_player']:
        segments=terrain['segments'];selected=next(s for s in segments if s['id']==terrain['selected_id'])
    if selected is None:return p
    dx=observation.get('vx',0.)*seconds
    y=height(selected,p.center[0]);future=connected_height(segments,selected['id'],p.center[0]+dx,seconds)
    if y is None:return p
    if future is not None:return Box(p.x+dx,p.y+future-y,p.w,p.h)
    # Walking off the visible end cannot leave a stationary capsule over air.
    vx=selected.get('vx',0)-observation.get('vx',0.)
    edge=max(0,(selected['b'][0]-p.center[0])/-vx)if vx<0 else seconds
    until=min(seconds,edge)
    end_y=height(selected,p.center[0]+observation.get('vx',0.)*until,until)
    dy=(end_y-y if end_y is not None else 0)+.5*motion.DATA['fall_from_run']['gravity']*observation.get('scale_px',41.)*max(0,seconds-edge)**2
    return Box(p.x+dx,p.y+dy,p.w,p.h)


def player_future(observation,seconds):
    """Short native-parameter prior, corrected each frame by measured motion."""
    p=observation['player']
    active=observation.get('motion')
    if active:
        if motion.is_ground_transition(active['name']):return ground_primitive_future(observation,seconds)
        if active.get('contact_pending'):
            scale=observation.get('scale_px',41.)
            cx=p.center[0]+observation.get('vx',0.)*seconds
            speed=transition_speed(active)
            cy=p.center[1]+speed*scale*seconds
            surface,destination=down_surface(observation,seconds)
            w,h=p.w,p.h
            if surface is not None:
                target=surface+transition_surface_offset(active,destination)*scale
                crosses=min(p.center[1],cy)<=target<=max(p.center[1],cy)
                # Original rope transfers clamp at their selected side. A
                # slightly overshot compact pixel body must not make waiting
                # for contact extrapolate through the rope indefinitely.
                # Keep the phase/jump ledger pending until observed contact.
                past_rope=(observation.get('pending_rope_clamp',False)and destination=='rope'
                           and active.get('destination','rope')=='rope'
                           and not active.get('support_unconfirmed')and (cy-target)*speed>=0)
                if crosses or past_rope:
                    cy=target;w=observation.get('stand_w',w);h=observation.get('stand_h',h)
            return Box(cx-w/2,cy-h/2,w,h)
        elapsed=max(0,observation['time']-active['started'])
        a=motion.point(active['name'],elapsed,active);b=motion.point(active['name'],elapsed+seconds,active)
        scale=observation.get('scale_px',41.)
        cx=p.center[0]+(b[0]-a[0])*scale+observation.get('vx',0.)*seconds
        cy=p.center[1]-((b[1]+b[2])-(a[1]+a[2]))*scale
        w=observation.get('stand_w',p.w)*b[3]/motion.DATA['stand_width']
        h=observation.get('stand_h',p.h)*b[4]/motion.DATA['stand_height']
        result=Box(cx-w/2,cy-h/2,w,h)
        if active['name'].startswith('jump'):
            result=cap_landing(observation,result,elapsed+seconds,active['name'],forecast_seconds=seconds,parameters=active)
        return result
    phase=observation['phase']
    if phase in ('ground','slide','rope_above','rope_below','unknown'):
        return supported_future(observation,seconds)
    scale=observation.get('scale_px',41.)
    vy=observation.get('vy',0.)
    up,down=(value*scale for value in motion.air_accelerations(observation['jumps']))
    if vy<0:
        apex=-vy/up
        rise=min(seconds,apex)
        dy=vy*rise+.5*up*rise*rise+.5*down*max(0,seconds-apex)**2
    else:
        dy=vy*seconds+.5*down*seconds*seconds
    terrain=observation.get('terrain')
    landing=None
    if terrain and terrain.get('source')=='neural_segments':
        from arena_support import landing_height
        surface=landing_height(terrain,p.center[0]+observation.get('vx',0.)*seconds,seconds,p.center[1])
        if surface is not None:landing=surface-.75*scale
    elif terrain and terrain['y']is not None:
        x=p.center[0]+(terrain['speed']or 550)*seconds
        samples=terrain['samples']
        sample=min(samples,key=lambda s:abs(s[0]-x)) if samples else None
        if sample and sample[2] and abs(sample[0]-x)<10:
            landing=sample[1]-25
    elif observation.get('rope') is not None:
        surface=rope_height(observation,seconds)
        if surface is not None:landing=surface-30
    if landing is not None and dy>0:
        dy=min(dy,max(0,landing-p.center[1]))
    return Box(p.x+observation.get('vx',0.)*seconds,p.y+dy,p.w,p.h)


def advance_player(observation,seconds,*,predict_contact=False):
    """Advance geometry and action state together, including landing/flip end."""
    current=dict(observation,time=observation['time']+seconds)
    # Forecast geometry can be used in a planning branch, never as a new
    # observation proving the original action has finished or jumps refreshed.
    if predict_contact:
        current['ground_contact_observed']=False
        current['rope_contact_observed']=False
    if observation['player']is None:
        return current
    current['player']=player_future(observation,seconds)
    if observation.get('rope_segment'):
        segments=[]
        for segment in observation.get('rope_segments')or[observation['rope_segment']]:
            moving=dict(segment)
            for key in('a','b'):
                moving[key]=(segment[key][0]+segment['vx']*seconds,segment[key][1]+segment['vy']*seconds)
            segments.append(moving)
        current['rope_segments']=segments
        current['rope_segment']=next(s for s in segments if s['id']==observation['rope_segment']['id'])
        current['rope']=rope_height(current)
        if current['rope']is not None:
            from arena_support import height
            current['rope_segment']=min((s for s in segments if height(s,current['player'].center[0])is not None),
                key=lambda s:abs(height(s,current['player'].center[0])-current['rope']))
    terrain=current.get('terrain')
    if terrain and terrain.get('source')=='neural_segments':
        from arena_support import advance_terrain
        current['terrain']=advance_terrain(terrain,seconds,root_foot_box(current).center[0])
    active=observation.get('motion')
    if not active:
        phase=observation['phase'];scale=observation.get('scale_px',41.)
        if phase.startswith('air_')or phase.startswith('jump'):
            vy=observation.get('vy',0.)
            up,down=(value*scale for value in motion.air_accelerations(observation['jumps']))
            apex=max(0,-vy/up)
            current['vy']=vy+up*min(seconds,apex)+down*max(0,seconds-apex)
            current['phase']=phase.rsplit('_',1)[0]+('_rising'if current['vy']<0 else'_falling')
        elif phase in('ground','rope_above','rope_below'):
            lost=(current.get('rope_segment')is not None and current['rope']is None)if phase.startswith('rope')else bool(current.get('terrain')and not current['terrain']['at_player'])
            if lost:
                selected=observation.get('rope_segment')
                if selected is None and terrain:
                    selected=next(s for s in terrain['segments']if s['id']==terrain['selected_id'])
                vx=selected.get('vx',0)-observation.get('vx',0.)if selected else 0
                edge=max(0,(selected['b'][0]-observation['player'].center[0])/-vx)if vx<0 else seconds
                current.update(phase='air_falling',jumps=0,vy=motion.DATA['fall_from_run']['gravity']*scale*max(0,seconds-edge))
    if active:
        elapsed=current['time']-active['started'];name=active['name']
        current['phase']=motion.phase(name,elapsed,active)
        if motion.is_ground_transition(name):
            previous_elapsed=max(0,observation['time']-active['started']);scale=observation.get('scale_px',41.)
            current['vx']=observation.get('vx',0.)+scale*(motion.root_extra_velocity(name,elapsed,active)-motion.root_extra_velocity(name,previous_elapsed,active))
            if current.get('terrain')and not current['terrain']['at_player']:
                current.update(motion=None,phase='air_falling',jumps=0)
        elif motion.is_rope_transition(name)and elapsed>=motion.duration(name,active):
            contact=down_contact(current,active)
            confirmed_target=contact and not active.get('support_unconfirmed')
            if confirmed_target and (not active.get('requires_contact')or predict_contact):
                current.update(motion=None,jumps=0,phase=transition_landing_phase(active),landing_predicted=True)
            else:
                uncertain=bool(active.get('support_unconfirmed')or
                               active.get('destination','rope')=='rope'and current.get('rope')is None)
                current.update(motion=dict(active,contact_pending=True,support_unconfirmed=uncertain),
                               phase='flip_up'if name in ('air_up','rope_up')else'flip_down')
        elif name.startswith('jump')and 'falling'in current['phase']:
            support=current.get('rope');terrain=current.get('terrain')
            if terrain and terrain.get('source')=='neural_segments':
                from arena_support import landing_height
                support=landing_height(terrain,current['player'].center[0],0,current['player'].center[1])
            elif terrain and terrain['y']is not None:support=terrain['y']+7
            if support is not None:
                landing=support-.75*observation.get('scale_px',41.)
                if abs(current['player'].center[1]-landing)<.15:
                    current.update(motion=landing_recovery(active,current['time'])if terrain else None,jumps=0,phase='ground'if terrain else'rope_above')
    return constrain_ground_motion(observation,current)


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
            return {k: pack(x) for k, x in vars(v).items()if k!='_forecast_cache'}
        if isinstance(v, dict):
            return {k: pack(x) for k,x in v.items()}
        if isinstance(v, (list,tuple)):
            return [pack(x) for x in v]
        return v
    return {k: pack(v) for k, v in observation.items()}


def overlay(rgb, observation, action=None, reason=''):
    image = cv2.cvtColor(rgb[:, :, :3], cv2.COLOR_RGB2BGR)
    def rect(b, color):
        cv2.rectangle(image, (int(b.x), int(b.y)), (int(b.x+b.w), int(b.y+b.h)), color, 1)
    if observation['rope'] is not None:
        segment=observation.get('rope_segment')
        if segment:
            cv2.line(image,tuple(int(v)for v in segment['a']),tuple(int(v)for v in segment['b']),(255,255,0),1)
        else:
            y = int(observation['rope']); cv2.line(image, (0, y), (639, y), (255, 255, 0), 1)
    if observation['player']:
        rect(observation['player'], (0, 255, 0))
        path=np.array([advance_player(observation,float(t))['player'].center for t in np.arange(0,.81,.04)],np.int32)
        cv2.polylines(image,[path],False,(255,255,255),1)
    terrain=observation.get('terrain')
    if terrain:
        if terrain.get('source')=='neural_segments':
            for segment in terrain['segments']:
                cv2.line(image,tuple(int(v)for v in segment['a']),tuple(int(v)for v in segment['b']),(0,255,255),1)
        for x,y,solid in terrain['samples']:
            if solid:
                cv2.circle(image,(int(round(x)),int(round(y))),1,(0,255,255),-1)
        if terrain['edge']is not None:
            x=int(terrain['edge']);cv2.line(image,(x,180),(x,310),(255,0,255),2)
    if observation.get('visible_supports')and observation.get('player'):
        from arena_support import leading_ground_faces
        for face in leading_ground_faces(observation['visible_supports'],observation['time']):
            if face['x']<observation['player'].x-100:continue
            x,y=int(round(face['x'])),int(round(face['y']))
            cv2.line(image,(x,y),(x,359),(0,165,255),1)
    for t in observation['tracks']:
        color = (0, 0, 255) if track_confidence(t,observation['time']) >= observation.get('hazard_confidence',.7) else (140, 140, 140)
        if t.kind=='slice_target':color=(255,180,0)
        if getattr(t,'quad',None)is not None:cv2.polylines(image,[np.asarray(t.quad,np.int32)],True,color,1)
        else:rect(t.box, color)
        x, y = t.box.center
        cv2.arrowedLine(image, (int(x), int(y)), (int(x+t.vx*.2), int(y+t.vy*.2)), color, 1)
        path=np.array([[int(t.future(dt).center[0]),int(t.future(dt).center[1])]
                       for dt in np.arange(0,.51,.05)],np.int32)
        cv2.polylines(image,[path],False,color,1)
        label=('target 'if t.kind=='slice_target'else'')+f'{t.id}:{t.vx:.0f},{t.vy:.0f}'
        cv2.putText(image, label, (int(t.box.x), int(t.box.y-3)), 0, .3, color, 1)
    cv2.putText(image, f"{observation['phase']} {action or '-'} {reason}", (100, 25), 0, .45, (0, 255, 0), 1)
    return image
