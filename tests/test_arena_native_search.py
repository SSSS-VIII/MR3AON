"""Search must undo whole oracle state and retain honest finite-window bounds."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest
from arena_checkpoint_errors import NativeIntervalError

SOURCE = Path(__file__).resolve().parents[1] / 'tools/arena_checkpoint_lab/search.py'
spec = importlib.util.spec_from_file_location('arena_native_search', SOURCE)
search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search)


class Oracle:
    def __init__(self, *, impossible=False):
        self.native = dict(frame=0, hp=5000, lifted=False)
        self.points = {}
        self.sequence = 0
        self.impossible = impossible
        self.update()

    def update(self):
        n = self.native
        self.view = dict(state=dict(episodeFrame=n['frame'], health=n['hp'], physics='air' if n['lifted'] else 'rope'))

    def snapshot(self):
        self.sequence += 1
        self.points[self.sequence] = deepcopy(self.native)
        return dict(result=dict(id=self.sequence))

    def restore(self, point):
        self.native = deepcopy(self.points[point])
        self.update()
        return dict(ms=1)

    def drop(self, point):
        del self.points[point]

    def call(self, op, **args):
        if op == 'state':
            return deepcopy(self.view['state'])
        assert op == 'exec' and args['code'] == search.BOARD
        return dict(map=42, stage_index=int(self.native['frame'] >= 10), mounted=False)

    def step(self, ticks, action):
        before = deepcopy(self.view['state'])
        if action == 'jump' and self.native['frame'] < 3:
            self.native['lifted'] = True
        self.native['frame'] += ticks
        if self.impossible or (self.native['frame'] >= 7 and not self.native['lifted']):
            self.native['hp'] -= 250
        self.update()
        return dict(done=True, before=before, after=deepcopy(self.view['state']))


def start(oracle):
    return dict(health=5000, board=oracle.call('exec', code=search.BOARD))


def test_search_backtracks_before_an_unavoidable_late_collision():
    oracle = Oracle()
    result = search.search_window(oracle, start=start(oracle), offset=0, horizon=4, commit=2)
    assert result['found'] and result['crossed']
    assert [row['action'] for row in result['path']] == ['none', 'jump', 'none', 'none']
    assert result['stats']['rejected_damage'] > 0
    assert oracle.native == dict(frame=10, hp=5000, lifted=True)
    assert all(row['job']['after']['health'] == 5000 for row in result['path'])


def test_privileged_policy_replaces_the_minimum_input_order_and_acts_before_the_hurt_boundary(monkeypatch):
    monkeypatch.syspath_prepend(str(SOURCE.parent))
    import native_policy
    oracle=Oracle()
    def read(gate):
        x=gate.native['frame']*.37;y=3 if gate.native['lifted']else .75
        return dict(state=dict(physics='jump: 14'if gate.native['lifted']else'runOnGround: 0',
            speed=18.5,position=dict(x=x,y=y)),
            role=[dict(center=dict(x=x,y=y),extents=dict(x=.18,y=.468))],
            support=dict(start=dict(x=-10,y=0),finish=dict(x=100,y=0),continues=True,is_ground=True),
            jumps_used=int(gate.native['lifted']),hazards=[dict(id=1,center=dict(x=5,y=.75),
                extents=dict(x=.2,y=.8),enabled=True)])
    monkeypatch.setattr(native_policy,'read',read)
    result=search.search_window(oracle,start=start(oracle),offset=0,horizon=4,commit=2,guided=True)
    assert result['found']and result['path'][0]['action']=='jump'
    assert result['stats']['action_limits_tried']==[4]
    assert result['stats']['native_decisions'][0]['reason']=='anticipate_ground_obstacle'


def test_budget_exhaustion_restores_the_real_root_without_a_partial_success():
    oracle = Oracle()
    result = search.search_window(oracle, start=start(oracle), offset=0, horizon=4, commit=2, max_trials=2)
    assert not result['found']
    assert 'budget' in result['reason']
    assert oracle.native == dict(frame=0, hp=5000, lifted=False)
    assert result['root'] in oracle.points


def test_all_damaged_actions_leave_the_window_root_intact():
    oracle = Oracle(impossible=True)
    result = search.search_window(oracle, start=start(oracle), offset=0, horizon=2, commit=1)
    assert not result['found']
    assert result['stats']['rejected_damage'] == 3
    assert oracle.native == dict(frame=0, hp=5000, lifted=False)


@pytest.mark.parametrize('reject_jump,budget,expected_jump,late_required,phase,ignore_jump',[
    (False,100,True,False,'fallFromRun: 13',False),(True,100,False,False,'fallFromRun: 13',False),
    (False,4,False,False,'fallFromRun: 13',False),(False,100,True,True,'fallFromRun: 13',False),
    (False,100,True,False,'fall: 15',False),(False,100,False,False,'fall: 15',True)])
def test_original_early_jump_rollout_is_preferred_before_a_deep_walkoff(reject_jump,budget,expected_jump,late_required,phase,ignore_jump):
    class Cliff(Oracle):
        def update(self):
            super().update()
            n=self.native
            self.view['state'].update(position=dict(x=n['frame']*.37,
                y=n.get('jump_y',4)+(n['frame']-n.get('jump_at',10))*.2 if n['lifted']else 3-(n['frame']-10)),
                physics='jump: 14'if n['lifted']else phase,
                colliders=[dict(name='Role',enabled=True,extents=dict(y=.5))])
        def call(self,op,**args):
            if op=='state':return deepcopy(self.view['state'])
            return dict(map=42,stage_index=int(self.native['frame']>=30),mounted=False)
        def step(self,ticks,action):
            before=deepcopy(self.view['state'])
            if action=='jump'and not ignore_jump:
                self.native.update(lifted=True,jump_at=self.native['frame'],jump_y=before['position']['y'])
            if action=='jump'and reject_jump:self.native['hp']-=250
            self.native['frame']+=ticks
            if self.native['frame']>=(19 if late_required else 25)and not self.native['lifted']:self.native['hp']-=250
            self.update()
            return dict(done=True,before=before,after=deepcopy(self.view['state']))
    oracle=Cliff();oracle.native['frame']=10;oracle.update()
    result=search.search_window(oracle,start=start(oracle),offset=2,horizon=4,commit=2,early_jump=True,max_trials=budget)
    assert result['found']and result['stats']['early_jump_hint']
    assert result['path'][0]['action']==('jump'if expected_jump else'none')
    assert oracle.native['hp']==5000
    if expected_jump:assert oracle.view['state']['position']['y']>3


def test_blocked_under_rope_tries_original_up_then_jump_before_late_input_combinations():
    class Wall(Oracle):
        def update(self):
            super().update();j=self.native.get('jumps',0)
            self.view['state'].update(physics='runOnLineDown: 2'if not j else'rollToLineOn: 4',
                position=dict(x=self.native['frame']*.1 if j else 0,y=-.75),
                colliders=[dict(name='Role',enabled=True,extents=dict(x=.2,y=.5))])
        def call(self,op,**args):
            if op=='state':return deepcopy(self.view['state'])
            return dict(map=42,stage_index=int(self.native['frame']>=20),mounted=False)
        def step(self,ticks,action):
            before=deepcopy(self.view['state'])
            if action=='jump':self.native['jumps']=self.native.get('jumps',0)+1
            self.native['frame']+=ticks
            if self.native['frame']>=13 and self.native.get('jumps',0)<2:self.native['hp']-=250
            self.update()
            return dict(done=True,before=before,after=deepcopy(self.view['state']))
    oracle=Wall()
    result=search.search_window(oracle,start=start(oracle),offset=0,horizon=8,commit=4,max_trials=40,early_jump=True)
    assert result['found']and result['crossed']and result['stats']['blocked_rope_hint']
    assert [r['action']for r in result['path']].count('jump')==2
    assert result['path'][0]['action']=='jump'and oracle.native['hp']==5000


def test_tick_overshoot_is_restored_and_excluded_even_when_health_is_unchanged():
    class Overshoot(Oracle):
        def step(self,ticks,action):
            result=super().step(ticks,action)
            if self.native['frame']==2 and action=='none':
                self.native['frame']+=1;self.update()
                result['after']=deepcopy(self.view['state'])
                raise NativeIntervalError('requested 2, advanced 3',result)
            return result
    oracle=Overshoot()
    result=search.search_window(oracle,start=start(oracle),offset=0,horizon=4,commit=2)
    assert result['found']and result['crossed']
    assert result['stats']['rejected_invalid_interval']>0
    assert any(row.get('interval_error')and not row['safe']for row in result['trials'])
    assert result['path'][0]['action']=='jump'
    assert all(row['job']['after']['episodeFrame']-row['job']['before']['episodeFrame']==row['ticks']
               for row in result['path'])


def test_real_gate_keeps_the_complete_job_when_rejecting_a_tick_boundary(monkeypatch):
    from types import SimpleNamespace
    from arena_checkpoint_lab.gate import GameGate
    vm=SimpleNamespace(session=SimpleNamespace(spec=SimpleNamespace(name='arena-search')))
    gate=GameGate(vm)
    job=dict(done=True,before=dict(episodeFrame=0,health=5000),after=dict(episodeFrame=4,health=5000))
    gate.view=dict(state=job['after'])
    monkeypatch.setattr(gate,'call',lambda *_args,**_kwargs:job)
    with pytest.raises(NativeIntervalError,match='requested 3, advanced 4')as caught:
        gate.step(3,'none')
    assert caught.value.job==job


@pytest.mark.parametrize('file_ram,timeout',[(False,20),(True,180)])
def test_restore_keeps_one_transport_request_for_the_selected_backing(file_ram,timeout):
    from types import SimpleNamespace
    from arena_checkpoint_lab.gate import GameGate
    calls=[]
    def request(op,**args):calls.append((op,args));return dict(ms=1,result=dict(id=7))
    vm=SimpleNamespace(session=SimpleNamespace(spec=SimpleNamespace(name='arena-search')),
                       capabilities=dict(file_ram=file_ram),request=request)
    gate=GameGate(vm);gate.points[7]=dict(state=dict(health=5000));gate.waiting=True
    gate.restore(7)
    assert calls==[('restore',dict(id=7,timeout=timeout))]
    assert gate.view==gate.points[7]and not gate.waiting


def test_fifty_ms_parity_continues_after_a_committed_window():
    oracle = Oracle()
    result = search.search_window(oracle, start=start(oracle), offset=1, horizon=1, commit=1)
    assert result['path'][0]['ticks'] == 3
    assert oracle.native['frame'] == 3


def test_single_early_jump_is_found_before_late_action_combinations_exhaust_budget():
    class EarlyJump(Oracle):
        def call(self, op, **args):
            value = super().call(op, **args)
            if op == 'exec':
                value['stage_index'] = int(self.native['frame'] >= 20)
            return value

        def step(self, ticks, action):
            before = deepcopy(self.view['state'])
            if action == 'jump' and self.native['frame'] == 0:
                self.native['lifted'] = True
            self.native['frame'] += ticks
            if self.native['frame'] >= 12 and not self.native['lifted']:
                self.native['hp'] -= 250
            self.update()
            return dict(done=True, before=before, after=deepcopy(self.view['state']))

    oracle = EarlyJump()
    result = search.search_window(oracle, start=start(oracle), offset=0,
                                  horizon=8, commit=4, max_trials=100)
    assert result['found'] and result['crossed']
    assert result['path'][0]['action'] == 'jump'
    assert sum(row['action'] != 'none' for row in result['path']) == 1
    assert oracle.native['hp'] == 5000
    assert result['stats']['action_limits_tried'] == [0, 1]


@pytest.mark.parametrize('error', [RuntimeError('native transport failed'), KeyboardInterrupt()])
def test_native_failure_is_not_turned_into_a_bad_route(monkeypatch, error):
    oracle = Oracle()
    def fail(*_):
        oracle.native['hp'] = 0
        raise error
    monkeypatch.setattr(oracle, 'step', fail)
    with pytest.raises(type(error)):
        search.search_window(oracle, start=start(oracle), offset=0)
    assert oracle.native == dict(frame=0, hp=5000, lifted=False)


def test_bounded_prefix_cache_restores_exact_nodes_without_executing_them_again():
    plain,cached=Oracle(),Oracle()
    a=search.search_window(plain,start=start(plain),offset=0,horizon=4,commit=2,cache_prefix=0)
    b=search.search_window(cached,start=start(cached),offset=0,horizon=4,commit=2,cache_prefix=4)
    assert b['found']and b['crossed']
    assert [r['job']for r in a['path']]==[r['job']for r in b['path']]
    assert plain.native==cached.native
    assert b['stats']['prefix_cache_hits']>0
    assert b['stats']['trials']<a['stats']['trials']


@pytest.mark.parametrize('quality',[False,True])
def test_cross_window_dead_end_restores_an_earlier_real_root_and_changes_its_input(tmp_path,monkeypatch,quality):
    import sys
    from types import SimpleNamespace
    monkeypatch.syspath_prepend(str(SOURCE.parent))
    checks=[]
    if quality:
        import guided_search,timing_margin
        def proposed(gate,*,searcher,history,initial_point,initial_state,board_code,**kwargs):
            return searcher(gate,**kwargs)
        def verify(gate,rows,**kwargs):
            checks.append(len(rows))
            if len(checks)==1:
                bad=next(i for i,row in enumerate(rows)if row['action']=='jump')
                return dict(passed=False,failure=dict(event=dict(row_index=bad)))
            return dict(passed=True)
        monkeypatch.setattr(guided_search,'window',proposed)
        monkeypatch.setattr(timing_margin,'verify',verify)
    renderer=dict(width=320,height=180,interval=1)
    monkeypatch.setitem(sys.modules,'render',SimpleNamespace(
        prepare=lambda _:dict(requested=renderer),INFO='renderer'))
    class HistoryOracle(Oracle):
        def __init__(self):
            super().__init__()
            self.vm=SimpleNamespace(request=lambda *_,**__:dict(result=dict(file_ram=True)))
            self.rebases=0
        def rebase(self):
            self.rebases+=1
            self.points.clear()
            result=self.snapshot();result['result']['file_backed']=True
            return result
        def update(self):
            super().update()
            self.view['state'].update(fixedDeltaTime=.02,content='Running: 1',
                position=dict(x=self.native['frame']*.37,y=.75),
                physics='runOnLine: 1'if self.native['frame']<3 else'jump: 14')
        def call(self,op,**args):
            if op=='state':return deepcopy(self.view['state'])
            if args['code']=='renderer':return renderer
            return dict(map=42,stage_index=int(self.native['frame']>=20),mounted=False)
        def step(self,ticks,action):
            before=deepcopy(self.view['state'])
            if action=='jump'and self.native['frame']<3:self.native['lifted']=True
            self.native['frame']+=ticks
            if self.native['frame']>=18 and not self.native['lifted']:self.native['hp']-=250
            self.update()
            return dict(done=True,before=before,after=deepcopy(self.view['state']))
    oracle=HistoryOracle()
    class Collector:
        def __init__(self):self.rows=[];self.rejected=[]
        def begin(self,*_):self.rows.append(0)
        def window(self,gate,path,index):self.rows.extend(row['job']['after']['episodeFrame']for row in path)
        def rewind(self,count):self.rejected.extend(self.rows[count:]);del self.rows[count:]
        def status(self):return dict(count=len(self.rows))
    collector=Collector()
    result=search.run(oracle,tmp_path/'history',horizon=4,commit=2,max_trials=100,max_windows=30,
                      retain_history=True,collector=collector,native_decision=quality)
    assert result['complete']and result['no_health_loss']
    assert result['backtracks']and oracle.rebases==1
    assert any(len(backtrack['skipped_attempts'])>1 for backtrack in result['backtracks'])
    assert any(window['horizon']>result['horizon']for window in result['windows'])
    assert any(row['action']=='jump'for row in result['route'])
    assert result['route'][0]['job']['before']['episodeFrame']==0
    assert all(row['job']['after']['health']==5000 for row in result['route'])
    assert collector.rejected
    assert collector.rows==[0]+[row['job']['after']['episodeFrame']for row in result['route']]
    if quality:
        assert len(checks)>=2 and result['timing_validation']['passed']
        assert any(b['reason']=='independent_operation_margin_failed'for b in result['backtracks'])
    retained={result['initial_ram_root']['result']['id']}
    for window in result['windows']:
        if window.get('found')and not window.get('backtracked'):
            retained.update([window['root'],*(r['point']for r in window['path'])])
    assert set(oracle.points)<=retained
