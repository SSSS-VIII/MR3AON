"""Exact physical best-of-k expectation of a one-card continuation, not a peek."""
import hashlib
import json
import subprocess
from .model import BY_NAME,CARDS,CATALOG,build_engine,prepare_state


def forecast_choices(raw,choices,policy, *, cumulative_damage=0):
    state=prepare_state(raw)
    if any(c['finishing'] for c in choices):return {'complete':True,'layouts':0,'elapsed_s':0,'skipped':'already_can_finish'}
    if state['round']==5 and not any(c['refresh_slots'] for c in choices):
        return {'complete':True,'layouts':0,'elapsed_s':0,'skipped':'no_remaining_draw'}
    eligible=[c for c in choices if not c['finishing']]
    if policy['lookahead_mode']=='rollout':
        groups={}
        for c in sorted(eligible,key=lambda c:(c['score'],c['damage']),reverse=True):
            groups.setdefault(tuple(c['cards']),[]).append(c)
        selected=list(groups)[:policy['rollout_candidates']]
        for extra in [next((key for key in groups if not key),None),tuple(max(eligible,key=lambda c:c['damage'])['cards'])]:
            if extra is not None and extra not in selected:
                if len(selected)>=policy['rollout_candidates']:selected.pop()
                selected.insert(0,extra)
        eligible=[c for key in selected for c in groups[key]]
    if not eligible:return {'complete':True,'layouts':0,'elapsed_s':0}
    heuristics=policy['heuristics']
    kernel=('finish_rollout.cpp' if policy['rollout_objective']=='finish' else 'rollout.cpp') if policy['lookahead_mode']=='rollout' else 'forecast.cpp'
    binary,_,build_s=build_engine(kernel,variant='diverse' if policy['rollout_beam_diversity'] else None)
    lines=[' '.join(map(str,[len(CARDS),state['round'],1,len(eligible),
        heuristics.get('passive_weight',1),heuristics.get('aura_weight',0),heuristics.get('vacancy_weight',0),
        policy['income_weight'],policy['lookahead_gold_scale'],policy['lookahead_seconds']]))]
    if policy['lookahead_mode']=='rollout':
        seed=int.from_bytes(hashlib.blake2b(json.dumps([state['round'],state['gold'],state['board'],state['pool']]).encode(),digest_size=8).digest(),'little')
        lines[0]+=' '+' '.join(map(str,[policy['rollout_samples'],policy['rollout_width'],heuristics.get('role_position_bias',0),int(policy['prioritize_finish']),seed,cumulative_damage,policy['rollout_safety_penalty'],policy['rollout_early_bonus']]))
    lines.extend(' '.join(map(str,policy[k])) for k in ['gold_before_refresh','gold_after_refresh'])
    lines.extend(' '.join(str(c[k]) for k in ['attack','cost','element','category','copies'])+
                 f" {CATALOG['effect_codes'].index(c['effect'])} {c['param']}" for c in CARDS)
    lines.append(' '.join(map(str,state['pool'])))
    lines.extend(' '.join(map(str,c)) for c in state['board'])
    for c in eligible:
        lines.append(f"{c['gold_left']} {c['refresh_slots']} {len(c['cards'])} {c['score']}")
        for old,name in zip(state['board'],c['board']):
            cell=old if old[0]>=0 or name is None else [BY_NAME[name]['id'],state['round'],0]
            lines.append(' '.join(map(str,cell)))
    result=subprocess.run([str(binary)],input='\n'.join(lines)+'\n',text=True,capture_output=True,
                          check=True,timeout=policy['lookahead_seconds']+5)
    out=json.loads(result.stdout);out['build_s']=build_s;out['objective']=policy['rollout_objective']
    if out.get('inventory_valid') is False:raise RuntimeError('rollout牌库张数失衡')
    if out['complete'] or out.get('samples_completed',0)>0:
        assert len(out['scores'])==len(eligible)
        for c in choices:c['decision_eligible']=any(c is selected for selected in eligible)
        if 'failure_rates' in out:
            assert len(out['failure_rates'])==len(eligible)
            for c,rate in zip(eligible,out['failure_rates']):c['predicted_failure_rate']=rate
        for c,value in zip(eligible,out['scores']):
            c['lookahead_score']=value
            c['score']=(1-policy['lookahead_weight'])*c['score']+policy['lookahead_weight']*value
    return {k:v for k,v in out.items() if k!='scores'}
