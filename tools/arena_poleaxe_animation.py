"""Static original Spine weapon geometry; no client access or scene state."""
from pathlib import Path
import json
import math
import numpy as np

PROFILE=Path(__file__).resolve().parents[1]/'arena/vision-poleaxe-animation.json'


class PoleaxeAnimation:
    def __init__(self,path=PROFILE):
        self.path=Path(path);self.data=json.loads(self.path.read_text())
        if self.data.get('schema')!=1:raise ValueError('Unsupported original animation schema')
        if self.data.get('columns')!=['time','x','y','a','b','c','d']:
            raise ValueError('Unexpected original bone coordinates')
        self.clips={}
        for name,clip in self.data['clips'].items():
            rows=np.asarray(clip['samples'],float)
            if (not math.isfinite(clip['duration'])or clip['duration']<=0
                    or rows.ndim!=2 or rows.shape[1]!=7 or len(rows)<2
                    or not np.isfinite(rows).all()or rows[0,0]!=0
                    or np.any(np.diff(rows[:,0])<=0)
                    or abs(rows[-1,0]-clip['duration'])>1e-6):
                raise ValueError('Invalid original animation samples: '+name)
            self.clips[name]=(clip,rows)
        c=self.data['collider'];sx,sy=c['size']['x']/2,c['size']['y']/2
        cx,cy=c['center']['x'],c['center']['y']
        self.local_corners=np.array([[cx-sx,cy-sy],[cx+sx,cy-sy],
                                     [cx+sx,cy+sy],[cx-sx,cy+sy]])
        self.render_scale=np.array([self.data['render_scale'][k]for k in ('x','y')])
        if (not np.isfinite(self.local_corners).all()or sx<=0 or sy<=0
                or not np.isfinite(self.render_scale).all()or np.any(self.render_scale<=0)):
            raise ValueError('Invalid original collider geometry')

    def pose(self,name,phase):
        """Return [x,y,a,b,c,d] in the original skeleton's local coordinates."""
        phase=float(phase)
        if not math.isfinite(phase):raise ValueError('Animation phase must be finite')
        clip,rows=self.clips[name]
        phase=max(0.,phase)
        phase=(phase%clip['duration']if clip['loop']else min(phase,clip['duration']))
        return np.array([np.interp(phase,rows[:,0],rows[:,j])for j in range(1,7)])

    def quad(self,name,phase,*,origin=(0.,0.),pixels_per_world=1.,screen=False):
        """Evaluate the original collider; only the caller supplies its origin.

        Ready curves describe setup skeletons. Live pooled enemies can retain
        bone scale, so matching a ready pose requires instance uncertainty.
        """
        return self.quads(name,[phase],origins=origin,pixels_per_world=pixels_per_world,screen=screen)[0]

    def quads(self,name,phases,*,origins=(0.,0.),pixels_per_world=1.,screen=False):
        """Evaluate a batch of original poses without repeated Python calls."""
        phases=np.asarray(phases,float);origins=np.asarray(origins,float);scale=float(pixels_per_world)
        if phases.ndim!=1 or not np.isfinite(phases).all():
            raise ValueError('Animation phases must be a finite vector')
        if (not math.isfinite(scale)or scale<=0 or origins.shape not in ((2,),(len(phases),2))
                or not np.isfinite(origins).all()):
            raise ValueError('Expected finite origins and a positive projection scale')
        clip,rows=self.clips[name];phases=np.maximum(0,phases)
        phases=phases%clip['duration']if clip['loop']else np.minimum(phases,clip['duration'])
        x,y,a,b,c,d=[np.interp(phases,rows[:,0],rows[:,j])for j in range(1,7)]
        local=self.local_corners
        world=np.stack([a[:,None]*local[None,:,0]+b[:,None]*local[None,:,1]+x[:,None],
                        c[:,None]*local[None,:,0]+d[:,None]*local[None,:,1]+y[:,None]],axis=2)
        world*=self.render_scale
        world*=scale
        if screen:world[:,:,1]*=-1
        return world+(origins if origins.shape==(2,)else origins[:,None,:])
