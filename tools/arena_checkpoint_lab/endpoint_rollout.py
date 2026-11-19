"""Finite native endpoint scenarios, preserving each executed physical prefix.

Each key is timed relative to that prefix's own unperturbed world-X crossing.
The counterfactual crossing is measured using Unity.Time.time, then a real VM
point is restored for the chosen endpoint. No previous timing offset is added.
Different physical prefixes are never merged by a reduced state signature.
"""
from collections import OrderedDict,deque
from math import isfinite

from arena_action_contract import prerequisite,effect_matches,meaningful
from arena_fixed_goal import exit_kind

RADIUS=.04
QUANTUM=1/60
EPS=.00002


def scenarios(indices,*,pairs=True):
    indices=tuple(indices);zero=(0,)*len(indices)
    plans=[('nominal',zero)]
    for i in range(len(indices)):
        for sign in (-40,40):
            shifts=list(zero);shifts[i]=sign
            plans.append(('single',tuple(shifts)))
    for shifts in ((-40,)*len(indices),(40,)*len(indices),
                   tuple(-40 if i%2==0 else 40 for i in range(len(indices))),
                   tuple(40 if i%2==0 else -40 for i in range(len(indices)))):
        plans.append(('continuous',shifts))
    if pairs:
        for i in range(len(indices)-1):
            for sign in (-40,40):
                shifts=list(zero);shifts[i]=sign;shifts[i+1]=-sign
                plans.append(('adjacent',tuple(shifts)))
    seen=set();result=[]
    for kind,shifts in plans:
        if shifts in seen:continue
        seen.add(shifts)
        result.append(dict(kind=kind,offsets=dict(zip(indices,shifts)),schedule=list(shifts)))
    return result


class Rejected(Exception):
    def __init__(self,reason,**evidence):self.evidence=dict(reason=reason,**evidence)


class Rollouts:
    def __init__(self,gate,keys,*,point,state,start,board_code,end_state,whole_board,cache_limit=96):
        self.gate=gate;self.keys=keys;self.point=point;self.state=state
        self.start=start;self.board_code=board_code;self.end=end_state;self.whole=whole_board
        self.cache=OrderedDict();self.limit=cache_limit;self.owned=set();self.steps=0
        self.board=start['board'];self.furthest=state['position']['x']
        self.deadline=state['time']+max(3.,(end_state['time']-state['time'])*2+2)

    def snapshot(self):
        point=self.gate.snapshot()['result']['id'];self.owned.add(point);return point

    def drop(self,point):
        if point in self.owned:self.gate.drop(point);self.owned.remove(point)

    def close(self):
        for point in list(self.owned):self.drop(point)

    def step(self,state,frames=1,action='none'):
        if state['time']>=self.deadline:raise Rejected('native_progress_timeout',actual=state)
        job=self.gate.render_step(frames,action);self.steps+=1
        after=job['after']
        self.furthest=max(self.furthest,after['position']['x'],
                          *(s['position']['x']for s in job.get('samples',[])))
        if (job.get('terminated')or any(s['health']!=self.start['health']
                for s in [after,*job.get('samples',[])])):
            raise Rejected('native_damage',before=state,actual=after,max_world_x=self.furthest)
        if not isfinite(after['time'])or after['time']<=state['time']:
            raise Rejected('invalid_engine_clock',actual=after)
        self.board=job.get('board')or self.gate.call('exec',code=self.board_code)
        return after,job

    def locate(self,current,key,shift):
        """Measure this reachable prefix's no-input crossing, with a short VM ring."""
        ring=deque();chosen=None
        origin=current
        try:
            while current['position']['x']<key['x']-1e-5:
                gap=key['x']-current['position']['x']
                speed=max(40.,abs(current.get('speed',18.5))*1.5)
                frames=max(1,min(12,int(gap/speed/QUANTUM)-5))
                if frames==1:
                    ring.append((current,self.snapshot()))
                    while len(ring)>7:self.drop(ring.popleft()[1])
                current,_=self.step(current,frames)
                if exit_kind(self.start['board'],self.board):
                    raise Rejected('board_exit_before_operation',event=key['index'],actual=current)
            if current['position']['x']-key['x']>max(.8,abs(current.get('speed',18.5))*QUANTUM*2):
                raise Rejected('missed_nominal_crossing',event=key['index'],actual=current)
            baseline=current['time']
            if shift<0:
                candidates=[entry for entry in ring if entry[0]['time']<=baseline-RADIUS+EPS]
                if not candidates:
                    raise Rejected('earlier_side_precedes_reachable_prefix',event=key['index'],
                                   actual=current,prefix=origin)
                current,chosen=max(candidates,key=lambda entry:entry[0]['time'])
                self.gate.restore(chosen)
            elif shift>0:
                while current['time']<baseline+RADIUS-EPS:current,_=self.step(current)
            actual_ms=(current['time']-baseline)*1000
            if shift and not RADIUS*1000-.03<=abs(actual_ms)<=(RADIUS+QUANTUM)*1000+.03:
                raise Rejected('endpoint_clock_not_covered',event=key['index'],actual_shift_ms=actual_ms)
            return current,dict(nominal_crossing_time=baseline,input_time=current['time'],
                                requested_shift_ms=shift,actual_shift_ms=actual_ms)
        finally:
            for _,point in ring:self.drop(point)

    def remember(self,prefix,node):
        self.cache[prefix]=node
        while len(self.cache)>self.limit:
            _,old=self.cache.popitem(last=False);self.drop(old['point'])

    def run(self,plan):
        current=self.state;actions=[];prefix=();before_steps=self.steps
        self.board=self.start['board'];self.furthest=current['position']['x']
        self.gate.restore(self.point)
        if self.gate.call('state')!=current:raise RuntimeError('Reachable-prefix root did not restore exactly')
        key=None;shift=0
        try:
            for key in self.keys:
                shift=plan['offsets'].get(key['index'],0);prefix+=((key['index'],shift),)
                node=self.cache.get(prefix)
                if node is not None:
                    self.cache.move_to_end(prefix);self.gate.restore(node['point'])
                    current=node['state'];self.board=node['board'];actions=list(node['actions'])
                    if self.gate.call('state')!=current:raise RuntimeError('Cached physical prefix did not restore exactly')
                    continue
                current,clock=self.locate(current,key,shift)
                if not meaningful(key['contract']):
                    raise Rejected('nominal_operation_has_no_effect',event=key['index'],actual=current)
                if not prerequisite(key['contract'],current['physics']):
                    raise Rejected('operation_prerequisite_mismatch',event=key['index'],actual=current,
                                   expected=key['contract'],clock=clock)
                before=current
                current,job=self.step(current,1,key['action'])
                record=dict(index=key['index'],action=key['action'],x=before['position']['x'],
                    frame=before['episodeFrame'],before_physics=before['physics'],
                    after_physics=current['physics'],before_y=before['position']['y'],
                    after_y=current['position']['y'],**clock)
                actions.append(record)
                if not effect_matches(key['contract'],current['physics']):
                    raise Rejected('operation_effect_mismatch',event=key['index'],actual=current,
                                   expected=key['contract'],clock=clock)
                self.remember(prefix,dict(point=self.snapshot(),state=current,board=self.board,actions=list(actions)))
            while not exit_kind(self.start['board'],self.board):
                if not self.whole and current['position']['x']>=self.end['position']['x']-1e-5:break
                current,_=self.step(current,12 if self.whole else min(6,max(1,int(
                    (self.end['position']['x']-current['position']['x'])/40/QUANTUM))))
            return dict(passed=True,actions=actions,steps=self.steps-before_steps,actual=current,
                        reason='native_exit'if self.whole else'forecast_end',max_world_x=self.furthest)
        except Rejected as error:
            return dict(passed=False,actions=actions,steps=self.steps-before_steps,
                        shift_ms=shift,event=key,**{k:v for k,v in error.evidence.items()if k!='event'},
                        failed_event=error.evidence.get('event',key['index']if key else None))
