"""Source-bound eccentric Mace motion estimated from visible OBBs only."""
from collections import deque
from dataclasses import dataclass,field,replace
import math
import numpy as np
from arena_vision import Track,Box
from arena_oriented import rectangle,bounds


@dataclass(frozen=True)
class MaceState:
    x:float
    y:float
    vx:float
    rx:float
    ry:float
    angle:float
    omega:float
    omega_error:float=0.
    vx_error:float=0.
    age:float=0.


def advance(state,seconds):
    a=state.omega*seconds;c,s=math.cos(a),math.sin(a)
    rx=c*state.rx-s*state.ry;ry=s*state.rx+c*state.ry
    return replace(state,x=state.x+state.vx*seconds+rx-state.rx,y=state.y+ry-state.ry,
                   rx=rx,ry=ry,angle=state.angle+a,age=state.age+seconds)


@dataclass
class MaceTrack(Track):
    poses:deque=field(default_factory=lambda:deque(maxlen=8))
    models:tuple=()
    body_length:float=0.
    body_width:float=0.
    pivot_fit_error:float|None=None
    _forecast_cache:dict=field(default_factory=dict,repr=False,compare=False)

    def update(self,detection,stamp,player,support_y=None):
        super().update(detection,stamp,player,support_y)
        self.models=();self._forecast_cache={};self.pivot_fit_error=None
        ratio=detection.pivot_offset_ratio
        if detection.quad is None or ratio is None:return
        q=np.asarray(detection.quad)
        _,length,width,_=rectangle(q)
        # Cropped length is not the original collider's length/offset. Wait for
        # real full geometry; never infer a source pivot from a growing crop.
        if (width<1 or not self.angular_history or q[:,0].min()<=2 or q[:,0].max()>=638
                or q[:,1].min()<=56 or q[:,1].max()>=358 or length/max(width,1e-6)<1.8):
            self.poses.clear();self.angular_history.clear();return
        angle=self.angular_history[-1][1]
        cx,cy=self.box.center
        self.poses.append((stamp,cx-player[0],cy-player[1],angle,length))
        rows=np.asarray(self.poses,float)
        if len(rows)<4 or rows[-1,0]-rows[0,0]<.06:return
        t=rows[:,0]-stamp;weights=np.exp(t/.12);design=np.column_stack((np.ones(len(t)),t))
        angular,_,_,_=np.linalg.lstsq(design*weights[:,None],rows[:,3]*weights,rcond=None)
        residual=rows[:,3]-design@angular
        error=float(np.sqrt(np.mean(residual**2)))
        if error>.08:return
        omega=float(angular[1])
        centered=t-np.average(t,weights=weights**2)
        omega_error=float(np.sqrt(np.mean(residual**2)/max(1e-9,np.sum((centered*weights)**2))))
        measured_length=float(np.median(rows[:,4]));self.body_length=max(length,measured_length);self.body_width=width
        radius=ratio*measured_length
        units=np.column_stack((np.cos(rows[:,3]),np.sin(rows[:,3])))
        choices=[]
        for sign in(-1,1):
            roots=rows[:,1:3]-sign*radius*units
            fit,_,_,_=np.linalg.lstsq(design*weights[:,None],roots[:,0]*weights,rcond=None)
            root_y=float(np.average(roots[:,1],weights=weights**2))
            error=float(np.sqrt(np.mean((design@fit-roots[:,0])**2+(root_y-roots[:,1])**2)))
            vx=float(fit[1])
            vx_error=float(np.sqrt(np.mean((design@fit-roots[:,0])**2)/max(1e-9,np.sum((centered*weights)**2))))
            if vx>50 or vx< -2000:continue
            choices.append((error,sign,vx,vx_error))
        if not choices:return
        best=min(c[0]for c in choices);self.pivot_fit_error=best
        if best>4:return
        self.models=tuple(MaceState(cx-player[0],cy-player[1],vx,
            sign*radius*math.cos(angle),sign*radius*math.sin(angle),angle,omega,omega_error,vx_error)
            for error,sign,vx,vx_error in choices if error<=best+.75)
        self.sine_count=self.curve_count=0;self.ax=self.ay=0.
        self.vx=float(np.mean([s.vx-s.omega*s.ry for s in self.models]))
        self.vy=float(np.mean([s.omega*s.rx for s in self.models]))
        # Several possible pivots cannot be encoded as one rotating quad. The
        # existing planners consume their conservative camera-plane envelope.
        self.quad=None

    def forecast(self,seconds):
        if seconds in self._forecast_cache:return self._forecast_cache[seconds]
        states=tuple(advance(state,seconds)for state in self.models)
        lo_x=lo_y=math.inf;hi_x=hi_y=-math.inf
        for state in states:
            c,s=abs(math.cos(state.angle)),abs(math.sin(state.angle))
            hw=(c*self.body_length+s*self.body_width)/2;hh=(s*self.body_length+c*self.body_width)/2
            # Parameter uncertainty is separate from original collider size.
            # Bound radial movement from a two-standard-error angle interval.
            radius=math.hypot(state.rx,state.ry)
            pad=2*radius*math.sin(min(math.pi,2*state.omega_error*state.age)/2)
            pad_x=pad+2*state.vx_error*state.age
            lo_x=min(lo_x,state.x-hw-pad_x);hi_x=max(hi_x,state.x+hw+pad_x)
            lo_y=min(lo_y,state.y-hh-pad);hi_y=max(hi_y,state.y+hh+pad)
        result=Box(lo_x+self.reference[0],lo_y+self.reference[1],hi_x-lo_x,hi_y-lo_y),states
        self._forecast_cache[seconds]=result;return result

    def future(self,seconds):
        return self.forecast(seconds)[0]if self.models else super().future(seconds)

    def at(self,seconds):
        if not self.models:return super().at(seconds)
        box,states=self.forecast(seconds)
        return replace(self,box=box,models=states,quad=None,_forecast_cache={},
            vx=float(np.mean([s.vx-s.omega*s.ry for s in states])),
            vy=float(np.mean([s.omega*s.rx for s in states])))

    def sweep_margin(self,seconds):
        """Bound each collider point's arc/chord deviation for an MPC interval."""
        return max(((math.hypot(s.rx,s.ry)+math.hypot(self.body_length,self.body_width)/2)*
                    (1-math.cos(min(2*math.pi,(abs(s.omega)+2*s.omega_error)*seconds)/2))for s in self.models),default=0.)
