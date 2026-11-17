"""Batch preparation must preserve the caller's hazard geometry semantics."""
import numpy as np
from arena_vision import Track,Box
from arena_mpc import forecast_geometry


class PreparedTrack(Track):
    def prepare_forecast(self,times):
        self.prepare_calls=getattr(self,'prepare_calls',0)+1
        self.prepared={float(t):super(PreparedTrack,self).future(t)for t in times}
    def future(self,t):
        return self.prepared[float(t)]


def test_preparation_keeps_custom_predict_and_oriented_geometry():
    times=np.linspace(0,.96,25)
    args=dict(id=1,box=Box(280,100,30,60),kind='trap',confidence=.9,seen=1.,vx=-620.,vy=40.,
              collider_shape='BoxCollider',quad=((280.,100.),(310.,100.),(310.,160.),(280.,160.)),angular_velocity=2.)
    normal=Track(**args);prepared=PreparedTrack(**args);calls=[]
    def predict(track,t):
        calls.append((track.id,float(t)))
        b=track.future(t)
        # Policy-specific corrections must still run for every query.
        return Box(b.x+3,b.y-7,b.w+2,b.h+4)
    expected=forecast_geometry([normal],times,predict,.04);actual=forecast_geometry([prepared],times,predict,.04)
    assert prepared.prepare_calls==1
    assert len(calls)==2*len(times)
    for left,right in zip(expected,actual):np.testing.assert_array_equal(left,right)


def test_preparation_runs_at_each_projected_query_time():
    track=PreparedTrack(2,Box(100,120,10,20),'trap',.9,1.,vx=-100.)
    first=forecast_geometry([track],[0.,.1],lambda t,s:t.future(s),.1)[0]
    second=forecast_geometry([track],[.2,.3],lambda t,s:t.future(s),.1)[0]
    assert track.prepare_calls==2
    np.testing.assert_allclose(second[:,:,0],first[:,:,0]-20)
