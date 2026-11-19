"""Native rollout rankings must guide choices without certifying heuristic safety."""
from copy import deepcopy
from pathlib import Path
import random
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/arena_checkpoint_lab'))
import native_planner as planner
from prefix_cache import PrefixCache


class Oracle:
    def __init__(self,impossible=False):
        self.data=dict(frame=0,health=5000,mode='ground',early=False,secret=17)
        self.points={};self.serial=0;self.impossible=impossible;self.update()
    def state(self):
        d=self.data
        return dict(episodeFrame=d['frame'],health=d['health'],speed=18.5,
                    physics={'ground':'runOnGround: 5','air':'jump: 14','slide':'slideOnGround: 6'}[d['mode']],
                    position=dict(x=d['frame']*.37,y=2.8 if d['mode']=='air'else .75,z=0))
    def update(self):self.view=dict(state=self.state())
    def observation(self):
        s=self.state()
        return dict(state=s,role=[dict(center=s['position'],extents=dict(x=.18,y=.468))],
            jumps_used=int(self.data['mode']=='air'),
            support=dict(start=dict(x=-10,y=0),finish=dict(x=100,y=0),continues=True,is_ground=True),
            hazards=[dict(id=1,center=dict(x=4.,y=.75),extents=dict(x=.3,y=.8),enabled=True)])
    def snapshot(self):
        self.serial+=1;self.points[self.serial]=deepcopy(self.data)
        return dict(result=dict(id=self.serial))
    def restore(self,p):self.data=deepcopy(self.points[p]);self.update();return dict(ms=1)
    def drop(self,p):del self.points[p]
    def call(self,op,**kwargs):
        if op=='state':return self.state()
        return dict(map=42,stage_index=int(self.data['frame']>=20),mounted=False)
    def step(self,ticks,action):
        before=self.state();d=self.data
        if action=='jump':
            d['early']=d['early']or d['frame']<=2;d['mode']='air'
        elif action=='down':d['mode']='slide'
        d['frame']+=ticks;d['secret']+=ticks*7
        if self.impossible or d['frame']>=10 and not d['early']:d['health']=4750
        self.update()
        return dict(before=before,after=self.state(),done=True)


@pytest.fixture(autouse=True)
def original_observation(monkeypatch):
    monkeypatch.setattr(planner,'read',lambda gate:gate.observation())


def start(g):return dict(health=5000,board=dict(map=42,stage_index=0))


def test_ranked_native_rollouts_override_a_wrong_rule_and_commit_an_early_safe_choice(monkeypatch):
    # All first 50ms actions survive. A purely reactive rule keeps waiting;
    # only the original oracle says whether that early choice is recoverable.
    monkeypatch.setattr(planner,'decision',lambda obs:dict(order=['none','down','jump'],
                        reason='anticipate_ground_obstacle',nearest=[dict(ttc=.2)]))
    g=Oracle();result=planner.search_window(g,start=start(g),offset=0,horizon=8,commit=2,max_trials=160)
    assert result['found']and result['crossed']and g.data['health']==5000
    first=next(r for r in result['path']if r['action']!='none')
    assert first['action']=='jump'and first['job']['before']['episodeFrame']<=2
    assert result['stats']['planner']=='native_trajectory_beam'
    assert any(t['alternatives']>1 for t in result['stats']['beam_trace'])
    assert result['stats']['selected_trajectory']['risk']>=0


def test_budget_exhaustion_restores_hidden_original_state_and_releases_unowned_nodes():
    g=Oracle();before=deepcopy(g.data)
    result=planner.search_window(g,start=start(g),offset=0,horizon=8,commit=2,max_trials=2)
    assert not result['found']and 'budget'in result['reason']
    assert g.data==before and set(g.points)=={result['root']}


def test_real_damage_rejects_every_action_even_if_heuristics_look_safe():
    g=Oracle(impossible=True);before=deepcopy(g.data)
    result=planner.search_window(g,start=start(g),offset=0,horizon=8,commit=2)
    assert not result['found']and result['stats']['rejected_damage']>0
    assert g.data==before


def test_rejected_operation_prefix_is_not_returned_as_a_native_exit():
    g=Oracle();entry=start(g);root=g.snapshot()['result']['id'];cache=PrefixCache()
    args=dict(start=entry,offset=0,horizon=8,commit=2,root_point=root,tree_cache=cache)
    first=planner.search_window(g,**args)
    blocked=tuple(r['action']for r in first['path'])
    second=planner.search_window(g,forbidden_prefixes=[blocked],**args)
    assert second['found']and tuple(r['action']for r in second['path'])!=blocked
    assert second['stats']['prefix_cache_hits']>0 and second['stats']['decision_cache_hits']>0
    keep={r['point']for r in second['forecast_path']};cache.close(g,keep)
    assert set(g.points)=={root,*keep}


def test_published_forecast_has_every_committed_vm_point_and_no_speculative_damage():
    g=Oracle();result=planner.search_window(g,start=start(g),offset=0,horizon=6,commit=2)
    assert result['found']and not result['crossed']and len(result['path'])==2
    assert len(result['forecast_path'])==6
    assert all(r['point']in g.points and r['job']['after']['health']==5000 for r in result['forecast_path'])
    assert g.state()==result['path'][-1]['job']['after']


def test_slope_and_hazard_velocity_use_successive_states_of_the_same_native_branch():
    g=Oracle();a=g.observation();a['state']['episodeFrame']=0
    a['role'][0]['extents']['y']=a['hazards'][0]['extents']['y']=.1
    b=deepcopy(a);b['state']['episodeFrame']=5
    b['role'][0]['center']=dict(x=1.85,y=1.75,z=0)
    b['hazards'][0]['center']['y']=1.75
    moving=planner.quality(b,a)
    static=deepcopy(a);static['hazards'][0]['center']['y']=1.75
    untracked=planner.quality(b,static)
    assert moving['risk']>untracked['risk']  # Threat follows the slope upward with the role.


def test_heuristic_prefers_regained_ground_jump_budget_to_a_spent_air_state():
    g=Oracle();ground=g.observation();air=deepcopy(ground)
    air['state']['physics']='fall2: 17';air['jumps_used']=2
    air['hazards']=ground['hazards']=[]
    assert planner.quality(ground)['mobility']<planner.quality(air)['mobility']


def test_observation_cannot_silently_advance_a_completed_physics_boundary(monkeypatch):
    g=Oracle();before=deepcopy(g.data)
    def read(gate):
        obs=gate.observation()
        if gate.data['frame']:obs['state']['episodeFrame']+=1
        return obs
    monkeypatch.setattr(planner,'read',read)
    with pytest.raises(RuntimeError,match='exact step boundary'):
        planner.search_window(g,start=start(g),offset=0,horizon=6,commit=2)
    assert g.data==before


def test_empty_hazard_list_cannot_prune_an_airborne_rescue_jump():
    class AirRescue(Oracle):
        def observation(self):
            obs=super().observation();obs['hazards']=[]
            return obs
    g=AirRescue();g.data['mode']='air';g.update()
    result=planner.search_window(g,start=start(g),offset=0,horizon=8,commit=2)
    assert result['found']and g.data['early']and g.data['health']==5000
    assert any(r['action']=='jump'for r in result['path'])


def test_cached_transition_must_match_its_actual_saved_native_observation():
    g=Oracle();entry=start(g);root=g.snapshot()['result']['id'];cache=PrefixCache()
    kwargs=dict(start=entry,offset=0,horizon=8,commit=2,root_point=root,tree_cache=cache)
    result=planner.search_window(g,**kwargs)
    child=result['forecast_path'][0]['point']
    cache.observations[child]['state']['episodeFrame']+=1
    with pytest.raises(RuntimeError,match='Cached native trajectory'):
        planner.search_window(g,**kwargs)
    assert g.data==g.points[root]
    cache.close(g)


@pytest.mark.parametrize('width',[1,2,3])
def test_streamed_diverse_beam_selection_matches_ranking_every_candidate_together(width):
    rng=random.Random(12)
    for _ in range(80):
        pool=[];candidates=[]
        for i in range(20):
            node=dict(integral=rng.random(),peak=0,inputs=0,progress=0,
                quality=dict(risk=0,mobility=0,drop=0,phase=rng.choice(['runonground','fall']),jumps_used=rng.randrange(3)),
                path=[dict(action=rng.choice(['none','jump','down']))])
            candidates.append(node);pool=planner.select(pool+[node],width)
            assert list(map(id,pool))==list(map(id,planner.select(candidates,width)))


def test_noncompetitive_native_rollouts_do_not_write_unneeded_vm_snapshots():
    g=Oracle();result=planner.search_window(g,start=start(g),offset=0,horizon=8,commit=2)
    assert result['found']and g.data['health']==5000
    assert result['stats']['snapshots_avoided']>0
    assert g.serial==result['stats']['snapshots_created']+1
    assert all(r['point']in g.points for r in result['forecast_path'])


def test_endpoint_feedback_ranks_other_timings_without_banning_a_native_trajectory():
    def path(tick,previous=4):
        return[dict(action=a,job=dict(before=dict(episodeFrame=t)))for t,a in((previous,'jump'),(tick,'down'))]
    feedback=[dict(before=((4,'jump'),),frame=20,action='down',shift=2)]
    assert planner.timing_cost(path(18),feedback)<planner.timing_cost(path(20),feedback)<planner.timing_cost(path(22),feedback)
    assert planner.timing_cost(path(20,previous=6),feedback)==0
    feedback[0]['shift']=-2
    assert planner.timing_cost(path(22),feedback)<planner.timing_cost(path(20),feedback)<planner.timing_cost(path(18),feedback)
