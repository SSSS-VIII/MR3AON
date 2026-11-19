"""Rank a bounded beam of actual native trajectories, never simulated physics."""
from math import exp, hypot
import time

from arena_checkpoint_errors import NativeIntervalError
from arena_fixed_goal import exit_kind
from arena_action_contract import contract, meaningful, native_pose
from native_policy import REST, decision, read, support_y
from search import BOARD
from arena_input_transport import transport_action, key as transport_key, minimum_gap


def contact_time(dx,half_width,relative_vx):
    if abs(dx)<=half_width:return 0.
    if dx>half_width and relative_vx<-.1:return(dx-half_width)/-relative_vx
    if dx<-half_width and relative_vx>.1:return(-dx-half_width)/relative_vx
    return None


def quality(observation,previous=None,previous_quality=None,*,jitter_seconds=.04):
    """A ranking heuristic, not a collision oracle or proof of future safety."""
    state=observation['state'];body=observation['role'][0]
    p,r=body['center'],body['extents'];phase=state['physics'].split(':')[0].lower()
    dt=(state['time']-previous['state']['time']if 'time'in state and 'time'in previous['state']
        else(state['episodeFrame']-previous['state']['episodeFrame'])*.02)if previous else 0
    old={h['id']:h for h in previous.get('hazards',[])}if previous else{}
    if dt>0:
        a=previous['role'][0]['center'];velocity=((p['x']-a['x'])/dt,(p['y']-a['y'])/dt)
    else:
        support=observation.get('support',{});vx=state.get('speed',18.5)*support.get('slope_speed_ratio',1)
        a,b=support.get('start'),support.get('finish');vy=0.
        if phase in REST and a and b and b['x']>a['x']:vy=vx*(b['y']-a['y'])/(b['x']-a['x'])
        velocity=(vx,vy)
    role_acc=(0.,0.)
    if dt>0 and previous_quality:
        v=previous_quality['_role_velocity'];role_acc=tuple((velocity[i]-v[i])/dt for i in(0,1))
    motions={};risk=nominal_risk=0.;clearance=robust_clearance=32.;padding_x=padding_y=0.
    for h in observation.get('hazards',[]):
        q,e=h['center'],h['extents']
        vx=vy=growth_x=growth_y=0.
        if dt>0 and h['id']in old:
            prior=old[h['id']];a=prior['center'];vx=(q['x']-a['x'])/dt;vy=(q['y']-a['y'])/dt
            growth_x=abs(e['x']-prior['extents']['x'])/dt;growth_y=abs(e['y']-prior['extents']['y'])/dt
        motions[h['id']]=(vx,vy)
        relative=(vx-velocity[0],vy-velocity[1]);hazard_acc=(0.,0.)
        if dt>0 and previous_quality and h['id']in previous_quality['_hazard_velocities']:
            v=previous_quality['_hazard_velocities'][h['id']];hazard_acc=((vx-v[0])/dt,(vy-v[1])/dt)
        # Minkowski envelope of relative displacement over +/-40ms, plus
        # observed acceleration and shape growth. Padding is local ranking
        # geometry; original client colliders and native damage stay intact.
        px=(abs(relative[0])+growth_x)*jitter_seconds+abs(hazard_acc[0]-role_acc[0])*jitter_seconds**2/2
        py=(abs(relative[1])+growth_y)*jitter_seconds+abs(hazard_acc[1]-role_acc[1])*jitter_seconds**2/2
        padding_x=max(padding_x,px);padding_y=max(padding_y,py)
        gapx=max(0.,abs(q['x']-p['x'])-e['x']-r['x'])
        gapy=max(0.,abs(q['y']-p['y'])-e['y']-r['y'])
        clearance=min(clearance,hypot(gapx,gapy))
        robust_clearance=min(robust_clearance,hypot(max(0.,gapx-px),max(0.,gapy-py)))
        dx=q['x']-p['x'];half=e['x']+r['x'];weight=1. if h['enabled']else .3
        def contribution(pad_x,pad_y):
            t=contact_time(dx,half+pad_x,relative[0])
            if t is None or t>.65:return 0.
            vertical=max(0.,abs(q['y']-p['y']+relative[1]*min(t,.25))-e['y']-r['y']-pad_y)
            return(1-t/.65)*exp(-vertical/.55)*weight
        ordinary=contribution(0.,0.);nominal_risk+=ordinary
        risk+=max(ordinary,contribution(px,py))
    used=observation.get('jumps_used')
    if phase in REST:used=0
    elif phase in ('jump2','fall2')or 'jump2'in str(observation.get('last_physics','')).lower():used=2
    elif used is None:used=1
    air=phase not in REST
    mobility=(.12+.12*used)if air else 0.
    line=support_y(observation,p['x']);drop=0.
    if air and line is not None:drop=max(0.,line-p['y']-1.5)*.12
    return dict(risk=min(8.,risk),nominal_risk=min(8.,nominal_risk),clearance=clearance,
                robust_clearance=robust_clearance,timing_radius_ms=jitter_seconds*1000,
                timing_padding=dict(x=padding_x,y=padding_y),mobility=mobility,
                drop=min(3.,drop),phase=phase,jumps_used=used,
                _role_velocity=velocity,_hazard_velocities=motions)


def explain(quality):return{k:v for k,v in quality.items()if not k.startswith('_')}


def rank(node):
    q=node['quality']
    return (node['integral']+node['peak']*.4+q['risk']*.35+q['mobility']+q['drop']
            +node['inputs']*.06-node['progress']*.015+node.get('timing_cost',0.))


def timing_cost(path,feedback):
    """Soft direction from failed endpoints, only under identical earlier keys.

    A later suffix might rescue the same key, so this never bans that key or
    asserts a cause of damage. Conflicting endpoint failures favor changing
    the earlier trajectory instead of repeatedly nudging the final key.
    """
    operations=[r for r in path if r['action']!='none']
    keys=[(r['job']['before']['episodeFrame'],r['action'])for r in operations]
    cost=0.
    for f in feedback:
        i=len(f['before'])
        if len(keys)<=i or tuple(keys[:i])!=f['before']:continue
        frame,action=keys[i]
        if action!=f['action']or abs(frame-f['frame'])>10:continue
        if 'native_kind'in f:
            kind=tuple(operations[i]['job'][side].get('physics','').split(':')[0].lower()for side in ('before','after'))
            if kind!=f['native_kind']:continue
        direction=-1 if f['shift']>0 else 1
        cost+=.15*max(0.,1-direction*(frame-f['frame'])/2)
    return cost


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
                  warm_start=(),beam_width=3,retain_forecast=True,last_input_time=None,input_history=(),**unused):
    if not 1<=commit<=horizon<=24 or max_trials<1 or offset<0 or not 1<=beam_width<=4:
        raise ValueError('Invalid native trajectory beam bounds')
    root=gate.snapshot()['result']['id']if root_point is None else root_point
    if tree_cache is not None:tree_cache.bind(root,start,offset,horizon,last_input_frame)
    owned=set();started=time.monotonic();trials=[]
    stats=dict(trials=0,seconds=0,restores_ms=[],rejected_damage=0,rejected_invalid_interval=0,rejected_no_effect=0,
               prefix_cache_hits=0,decision_cache_hits=0,timing_spacing_pruned=0,transport_spacing_pruned=0,
               snapshots_created=0,snapshots_avoided=0,
               native_decisions=[],beam_trace=[],planner='native_trajectory_beam',beam_width=beam_width)
    observations=tree_cache.observations if tree_cache is not None else{}
    proposals=tree_cache.decisions if tree_cache is not None else{}
    unsafe=tree_cache.unsafe if tree_cache is not None else set()
    feedback=tree_cache.margin_feedback if tree_cache is not None else[]
    stats['timing_feedback_seen']=len(feedback)
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
            children=[];alternatives=0;ticks=2 if(offset+depth)%2==0 else 3
            for node in frontier:
                point=node['point'];obs=observations[point];p=proposal(point)
                order=tuple(p['order'])
                previous=next((r['job']['before']['episodeFrame']for r in reversed(node['path'])if r['action']!='none'),last_input_frame)
                previous_time=next((r['job']['before'].get('time')for r in reversed(node['path'])
                                    if r['action']!='none'),last_input_time)
                too_close=(obs['state']['time']-previous_time<.12-1e-5
                    if previous_time is not None and 'time'in obs['state']
                    else previous is not None and obs['state']['episodeFrame']-previous<=2)
                if too_close:
                    stats['timing_spacing_pruned']+=2;order=('none',)
                elif (p['reason']=='clear_native_corridor'and not p['nearest']
                      and node['quality']['phase']in REST and obs.get('support',{}).get('continues')):
                    order=('none',)
                elif depth%2 and all(h['ttc']>.18 for h in p['nearest']):
                    order=tuple(dict.fromkeys((order[0],'none')))
                # The warm continuation is only a tie ordering. It cannot
                # replace native trajectory scores or force a policy action.
                actions=tuple(r['action']for r in node['path'])
                if depth<len(warm_start)and actions==tuple(warm_start[:depth])and warm_start[depth]in order:
                    preferred=warm_start[depth];order=(preferred,*(a for a in order if a!=preferred))
                for action in order:
                    if action!='none'and 'time'in obs['state']:
                        delivered=transport_action(action,obs['state']['physics'])
                        prior=next((r for r in reversed([*input_history,*node['path']])
                            if r['action']!='none'and transport_key(transport_action(r['action'],
                                r['job']['before']['physics']))==transport_key(delivered)),None)
                        if prior is not None and 'time'in prior['job']['before']:
                            previous_action=transport_action(prior['action'],prior['job']['before']['physics'])
                            # Ranking guidance reserves both outward-quantized
                            # endpoints; actual reachable-prefix checks remain
                            # authoritative when the trajectory changes speed.
                            required=minimum_gap(previous_action)+2*(.04+1/60)
                            if obs['state']['time']-prior['job']['before']['time']<required-1e-5:
                                stats['transport_spacing_pruned']+=1;continue
                    if action=='jump'and native_pose(obs['state']['physics'])==('air',2):
                        continue
                    if excluded(actions+(action,))or(point,action)in unsafe:continue
                    row=tree_cache.transitions.get((point,action))if tree_cache is not None else None
                    cached=row is not None
                    if row is not None:
                        stats['prefix_cache_hits']+=1;child=row['point']
                        if child not in observations:restore(child);observe(child)
                        if observations[child]['state']!=row['job']['after']:
                            raise RuntimeError('Cached native trajectory differs from its original step state')
                        future=observations[child]
                        if action!='none'and not meaningful(contract(
                                row['job']['before']['physics'],action,row['job']['after']['physics'])):
                            stats['rejected_no_effect']+=1;unsafe.add((point,action));continue
                    else:
                        if stats['trials']>=max_trials:return failure('Native trajectory beam trial budget exhausted')
                        restore(point);error=None
                        try:job=gate.step(ticks,action)
                        except NativeIntervalError as e:job=e.job;error=str(e);stats['rejected_invalid_interval']+=1
                        stats['trials']+=1
                        safe=error is None and not job.get('terminated')and job['after']['health']==start['health']
                        no_effect=(safe and action!='none'and not meaningful(contract(
                            job['before']['physics'],action,job['after']['physics'])))
                        if no_effect:safe=False;stats['rejected_no_effect']+=1
                        trial=dict(depth=depth,action=action,ticks=ticks,safe=safe,job=job)
                        if error:trial['interval_error']=error
                        if no_effect:trial['rejection_reason']='nominal_operation_has_no_effect'
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
                        row=dict(action=action,ticks=ticks,job=job,board=board,point=None)
                    q=quality(future,obs,node['quality'])
                    item=dict(point=row['point'],path=node['path']+[row],quality=q,
                              integral=node['integral']+q['risk']*(
                                  future['state']['time']-obs['state']['time']
                                  if 'time'in future['state']and 'time'in obs['state']else ticks*.02),
                              peak=max(node['peak'],q['risk']),inputs=node['inputs']+int(action!='none'),
                              progress=future['state']['position']['x']-x0)
                    item['timing_cost']=timing_cost(item['path'],feedback)
                    goal=exit_kind(start['board'],row['board'])is not None
                    if not goal:alternatives+=1
                    retained=select((exits if goal else children)+[item],1 if goal else beam_width)
                    if all(n is not item for n in retained):
                        stats['snapshots_avoided']+=int(not cached)
                        continue
                    if not cached:
                        child=gate.snapshot()['result']['id'];owned.add(child);observations[child]=future
                        row['point']=item['point']=child;stats['snapshots_created']+=1
                        if tree_cache is not None:tree_cache.remember(point,action,row)
                    if goal:exits=retained
                    else:children=retained
            frontier=children
            stats['beam_trace'].append(dict(depth=depth,alternatives=alternatives,
                retained=[dict(point=n['point'],score=rank(n),**explain(n['quality']))for n in frontier]))
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
        stats['selected_trajectory']=dict(score=rank(best),inputs=best['inputs'],
                                          timing_cost=best['timing_cost'],**explain(best['quality']))
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
