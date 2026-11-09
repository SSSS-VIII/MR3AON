"""Privileged dataset exploration only; never imported by the visual actor."""


def choose_action(labels,rng,last_action):
    if labels['t']-last_action<.18:
        return 'none','cooldown'
    supports=labels.get('supports')or[]
    current=next((s for s in supports if s['id']==labels.get('support_id')),None)
    physics=labels['physics'].split(':',1)[0]
    if physics=='fall' and labels['role']['point']['y']>200 and any(
            s.get('floating')and not s.get('hidden')and s['finish']['x']>labels['role']['point']['x']for s in supports):
        return 'jump','native_floating_approach_double_jump'
    if current and current['kind']in('rope','platform'):
        end=current['finish'];role=labels['role']['point']
        continuation=any(s['id']!=current['id']and not s.get('hidden')and s['kind']in('rope','platform')
                         and s['start']['x']<=end['x']+3 and s['finish']['x']>end['x']+5
                         and abs(s['start']['y']-end['y'])<6 for s in supports)
        margin=220 if physics=='runOnLineDown'else 100
        if not continuation and -20<end['x']-role['x']<margin:
            if physics=='runOnLineDown':return 'down','native_support_edge'
            if physics in ('runOnLine','runOnGround','slideOnGround'):
                return 'jump','native_support_edge'
    if labels['t']-last_action>.65 and rng.random()<.12:
        return rng.choice(['jump','down']),'random_pose'
    return 'none','idle'
