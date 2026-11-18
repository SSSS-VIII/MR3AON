from copy import deepcopy
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/arena_checkpoint_lab'))
from timing_margin import verify


class Oracle:
    def __init__(self,fragile=False):
        self.data=dict(frame=0,x=0.,hp=5000,first=None,second=None,boost=0)
        self.points={};self.sequence=0;self.fragile=fragile;self.restored=[]
    def state(self):
        d=self.data
        return dict(episodeFrame=d['frame'],health=d['hp'],position=dict(x=d['x'],y=.75),speed=50)
    def call(self,op,**_):
        if op=='state':return self.state()
        return dict(map=42,stage_index=int(self.data['x']>=20))
    def snapshot(self):
        self.sequence+=1;self.points[self.sequence]=deepcopy(self.data)
        return dict(result=dict(id=self.sequence))
    def restore(self,p):
        self.data=deepcopy(self.points[p]);self.restored.append(deepcopy(self.data));return dict(ms=1)
    def drop(self,p):del self.points[p]
    def step(self,ticks,action):
        before=self.state();d=self.data
        if action=='jump':d['first']=d['frame'];d['boost']=2
        if action=='down':d['second']=d['frame']
        for _ in range(ticks):
            d['frame']+=1;d['x']+=1.5 if d['boost']else 1
            d['boost']=max(0,d['boost']-1)
            if self.fragile and d['x']>=10 and d['first']!=6:d['hp']=4750
        return dict(before=before,after=self.state(),done=True)


def baseline(oracle):
    initial=oracle.snapshot()['result']['id'];state=oracle.state();rows=[]
    for tick in range(0,20,2):
        action='jump'if tick==6 else'down'if tick==14 else'none'
        job=oracle.step(2,action);point=oracle.snapshot()['result']['id']
        rows.append(dict(job=job,action=action,ticks=2,point=point))
    return initial,state,rows


def test_total_eighty_ms_and_each_key_variant_restores_its_own_nominal_snapshot():
    oracle=Oracle();initial,state,rows=baseline(oracle);end=deepcopy(oracle.data)
    result=verify(oracle,rows,initial_point=initial,initial_state=state,
                  start=dict(health=5000,board=dict(map=42,stage_index=0)),board_code='board',whole_board=True)
    assert result['passed']and result['window_ms']==80 and len(result['checks'])==10
    assert result['offsets_ms']==[-40,-20,0,20,40]
    first=[r for r in result['checks']if r['event']==0]
    assert len({r['anchor_frame']for r in first})==1
    assert [r['actions'][0]['frame']for r in first]==[6,4,8,5,7]
    # Later inputs use their original world X, not original tick + the tested
    # offset. The physical state may differ; its input clock is not accumulated.
    assert all(abs(r['actions'][1]['x']-rows[7]['job']['before']['position']['x'])<=.5 for r in first)
    for r in result['checks'][5:]:
        assert r['actions'][0]['index']==1  # First key already in original snapshot.
    assert oracle.data==end
    assert all('before_physics'in a and 'after_physics'in a
               for check in result['checks']for a in check['actions'])


def test_a_nominally_safe_last_moment_input_is_rejected_and_cannot_pollute_the_next_test():
    oracle=Oracle(fragile=True);initial,state,rows=baseline(oracle);end=deepcopy(oracle.data)
    result=verify(oracle,rows,initial_point=initial,initial_state=state,
                  start=dict(health=5000,board=dict(map=42,stage_index=0)),board_code='board',whole_board=True)
    assert not result['passed']and result['checks'][0]['passed']
    assert result['failure']['shift_ticks']==-2 and result['failure']['reason']=='native_damage'
    assert result['failure']['max_world_x']>=result['failure']['actual']['position']['x']
    assert oracle.data==end and oracle.data['hp']==5000


def test_first_key_cannot_claim_early_tolerance_before_the_retained_entry():
    oracle=Oracle();initial,state,rows=baseline(oracle)
    rows[0]['action']='jump'
    result=verify(oracle,rows,initial_point=initial,initial_state=state,
                  start=dict(health=5000,board=dict(map=42,stage_index=0)),board_code='board')
    assert not result['passed']and result['failure']['reason']=='earlier_side_precedes_retained_entry'


def test_damage_witness_keeps_the_furthest_native_sample_when_a_hit_moves_the_role_back():
    class Knockback(Oracle):
        knockback=False
        def step(self,ticks,action):
            job=super().step(ticks,action)
            if self.knockback:
                forward=self.data['x']+4
                self.data['x']-=10;self.data['hp']=4750
                job.update(after=self.state(),samples=[dict(position=dict(x=forward))])
            return job
    oracle=Knockback();initial,state,rows=baseline(oracle)
    oracle.knockback=True
    result=verify(oracle,rows,initial_point=initial,initial_state=state,
                  start=dict(health=5000,board=dict(map=42,stage_index=0)),board_code='board')
    failure=result['failure']
    assert not result['passed']and failure['reason']=='native_damage'
    assert failure['max_world_x']==10 and failure['actual']['position']['x']==-4
