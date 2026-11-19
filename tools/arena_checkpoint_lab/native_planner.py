"""Rank a bounded beam of actual native trajectories, never simulated physics."""
from math import exp, hypot
import time

from arena_checkpoint_errors import NativeIntervalError
from arena_fixed_goal import exit_kind
from native_policy import REST, decision, read, support_y
from search import BOARD


def quality(observation,previous=None):
    """A ranking heuristic, not a collision oracle or proof of future safety."""
    state=observation['state'];body=observation['role'][0]
    p,r=body['center'],body['extents'];phase=state['physics'].split(':')[0].lower()
    dt=(state['episodeFrame']-previous['state']['episodeFrame'])*.02 if previous else 0
    old={h['id']:h for h in previous.get('hazards',[])}if previous else{}
    velocity=(0.,0.)
    if dt>0:
        a=previous['role'][0]['center'];velocity=((p['x']-a['x'])/dt,(p['y']-a['y'])/dt)
    else:velocity=(state.get('speed',18.5),0.)
    risk=0.;clearance=32.
    for h in observation.get('hazards',[]):
        q,e=h['center'],h['extents']
        if q['x']+e['x']<p['x']-r['x']-.4:continue
        vx=vy=0.
        if dt>0 and h['id']in old:
            a=old[h['id']]['center'];vx=(q['x']-a['x'])/dt;vy=(q['y']-a['y'])/dt
        gapx=max(0.,abs(q['x']-p['x'])-e['x']-r['x'])
        gapy=max(0.,abs(q['y']-p['y'])-e['y']-r['y'])
        clearance=min(clearance,hypot(gapx,gapy))
        closing=velocity[0]-vx
        if closing<=.1:continue
        t=max(0.,(q['x']-e['x']-p['x']-r['x'])/closing)
        if t>.65:continue
        # Finite differences come from two successive native observations of
        # this exact branch, including slope Y and moving hazard Y. These
        # local extrapolations rank candidates; native damage is authoritative.
        lead=min(t,.25)
        vertical=max(0.,abs(q['y']+vy*lead-p['y']-velocity[1]*lead)-e['y']-r['y'])
        risk+=(1-t/.65)*exp(-vertical/.55)*(1. if h['enabled']else .3)
    used=observation.get('jumps_used')
    if phase in REST:used=0
    elif phase in ('jump2','fall2')or 'jump2'in str(observation.get('last_physics','')).lower():used=2
    elif used is None:used=1
    air=phase not in REST
    mobility=(.12+.12*used)if air else 0.
    line=support_y(observation,p['x']);drop=0.
    if air and line is not None:drop=max(0.,line-p['y']-1.5)*.12
    return dict(risk=min(8.,risk),clearance=clearance,mobility=mobility,
                drop=min(3.,drop),phase=phase,jumps_used=used)


def rank(node):
    q=node['quality']
    return (node['integral']+node['peak']*.4+q['risk']*.35+q['mobility']+q['drop']
            +node['inputs']*.06-node['progress']*.015)


def select(nodes,width):
    ordered=sorted(nodes,key=rank);chosen=[];seen=set()
    for node in ordered:
        keys=tuple(r['action']for r in node['path']if r['action']!='none')[-2:]
        signature=(keys,node['quality']['phase']in REST,node['quality']['jumps_used'])
        if signature in seen:continue
        chosen.append(node);seen.add(signature)
        if len(chosen)==width:return chosen
    return chosen+[n for n in ordered if all(n is not c for c in chosen)][:width-len(chosen)]


def search_window(gate,*,start,offset,horizon=24,commit=6,max_trials=1200,on_trial=None,
                  root_point=None,forbidden_prefixes=(),tree_cache=None,last_input_frame=None,
                  warm_start=(),beam_width=3,retain_forecast=True,**unused):
    if not 1<=commit<=horizon<=24 or max_trials<1 or offset<0 or not 1<=beam_width<=4:
        raise ValueError('Invalid native trajectory beam bounds')
    root=gate.snapshot()['result']['id']if root_point is None else root_point
    if tree_cache is not None:tree_cache.bind(root,start,offset,horizon,last_input_frame)
    owned=set();started=time.monotonic();trials=[]
    stats=dict(trials=0,seconds=0,restores_ms=[],rejected_damage=0,rejected_invalid_interval=0,
               prefix_cache_hits=0,decision_cache_hits=0,timing_spacing_pruned=0,
               native_decisions=[],beam_trace=[],planner='native_trajectory_beam',beam_width=beam_width)
    observations=tree_cache.observations if tree_cache is not None else{}
    proposals=tree_cache.decisions if tree_cache is not None else{}
    unsafe=tree_cache.unsafe if tree_cache is not None else set()
    forbidden=tuple(tuple(p)for p in forbidden_prefixes)
    def excluded(actions):return any(actions[:len(p)]==p for p in forbidden if len(p)<=len(actions))
    def restore(point):stats['restores_ms'].append(gate.restore(point)['ms'])
    def observe(point):
        if point not in observations:
            observations[point]=read(gate)
            if not observations[point].get('role'):raise ValueError('Native trajectory needs the original hurt collider')
        return observations[point]
    def proposal(point):
        if point not in proposals:
            proposals[point]=decision(observations[point])
            stats['native_decisions'].append(dict(point=point,**proposals[point]))
        else:stats['decision_cache_hits']+=1
        return proposals[point]
    def release(keep):
        cached=tree_cache.points if tree_cache is not None else set()
        for p in list(owned-keep-cached):gate.drop(p);owned.remove(p)
    def failure(reason):
        restore(root);release(set())
        return dict(found=False,reason=reason,root=root,path=[],trials=trials,stats=stats)
    try:
        restore(root);initial=observe(root);x0=initial['state']['position']['x']
        q=quality(initial)
        frontier=[dict(point=root,path=[],quality=q,integral=0.,peak=0.,inputs=0,progress=0.)]
        exits=[]
        for depth in range(horizon):
            children=[];ticks=2 if(offset+depth)%2==0 else 3
            for node in frontier:
                point=node['point'];obs=observations[point];p=proposal(point)
                order=tuple(p['order'])
                previous=next((r['job']['before']['episodeFrame']for r in reversed(node['path'])if r['action']!='none'),last_input_frame)
                if previous is not None and obs['state']['episodeFrame']-previous<=2:
                    stats['timing_spacing_pruned']+=2;order=('none',)
                elif p['reason']=='clear_native_corridor'and not p['nearest']:
                    order=('none',)
                elif depth%2 and all(h['ttc']>.18 for h in p['nearest']):
                    order=tuple(dict.fromkeys((order[0],'none')))
                # The warm continuation is only a tie ordering. It cannot
                # replace native trajectory scores or force a policy action.
                actions=tuple(r['action']for r in node['path'])
                if depth<len(warm_start)and actions==tuple(warm_start[:depth])and warm_start[depth]in order:
                    preferred=warm_start[depth];order=(preferred,*(a for a in order if a!=preferred))
                for action in order:
                    if excluded(actions+(action,))or(point,action)in unsafe:continue
                    row=tree_cache.transitions.get((point,action))if tree_cache is not None else None
                    if row is not None:
                        stats['prefix_cache_hits']+=1;child=row['point']
                        if child not in observations:restore(child);observe(child)
                    else:
                        if stats['trials']>=max_trials:return failure('Native trajectory beam trial budget exhausted')
                        restore(point);error=None
                        try:job=gate.step(ticks,action)
                        except NativeIntervalError as e:job=e.job;error=str(e);stats['rejected_invalid_interval']+=1
                        stats['trials']+=1
                        safe=error is None and not job.get('terminated')and job['after']['health']==start['health']
                        trial=dict(depth=depth,action=action,ticks=ticks,safe=safe,job=job)
                        if error:trial['interval_error']=error
                        trials.append(trial)
                        if on_trial:on_trial(trial)
                        if not safe:
                            stats['rejected_damage']+=int(bool(job.get('terminated')or job['after']['health']!=start['health']))
                            unsafe.add((point,action));continue
                        board=gate.call('exec',code=BOARD);crossed=exit_kind(start['board'],board)is not None
                        if board['mounted']or(board['map']!=start['board']['map']and not crossed):continue
                        future=read(gate)
                        if future['state']!=job['after']:
                            raise RuntimeError('Native trajectory observation changed the exact step boundary')
                        child=gate.snapshot()['result']['id'];owned.add(child);observations[child]=future
                        row=dict(action=action,ticks=ticks,job=job,board=board,point=child)
                        if tree_cache is not None:tree_cache.remember(point,action,row)
                    future=observations[child];q=quality(future,obs)
                    item=dict(point=child,path=node['path']+[row],quality=q,
                              integral=node['integral']+q['risk']*ticks*.02,
                              peak=max(node['peak'],q['risk']),inputs=node['inputs']+int(action!='none'),
                              progress=future['state']['position']['x']-x0)
                    if exit_kind(start['board'],row['board'])is not None:exits.append(item)
                    else:children.append(item)
            frontier=select(children,beam_width)
            stats['beam_trace'].append(dict(depth=depth,alternatives=len(children),
                retained=[dict(point=n['point'],score=rank(n),**n['quality'])for n in frontier]))
            keep={r['point']for n in frontier+exits for r in n['path']}
            release(keep)
            if not frontier:
                if exits:break
                return failure('Bounded native trajectory beam has no surviving continuation')
        candidates=exits or frontier
        if not candidates:return failure('No original trajectory reached the finite horizon')
        best=min(candidates,key=rank);path=best['path'];crossed=bool(exits)
        count=len(path)if crossed else commit
        restore(path[count-1]['point'])
        if gate.call('state')!=path[count-1]['job']['after']:
            raise RuntimeError('Chosen trajectory VM point differs from its original native state')
        release({r['point']for r in path})
        stats['selected_trajectory']=dict(score=rank(best),inputs=best['inputs'],**best['quality'])
        parent=root;guidance=[]
        for row in path:
            proposal=proposals.get(parent,{})
            guidance.append(dict(action=row['action'],frame=row['job']['before']['episodeFrame'],
                                 rule=proposal.get('order',[None])[0],reason=proposal.get('reason')))
            parent=row['point']
        stats['selected_guidance']=guidance
        result=dict(found=True,crossed=crossed,root=root,path=path[:count],trials=trials,stats=stats)
        if retain_forecast:result['forecast_path']=path
        else:release({r['point']for r in path[:count]})
        return result
    except BaseException:
        restore(root);release(set());raise
    finally:stats['seconds']=time.monotonic()-started
