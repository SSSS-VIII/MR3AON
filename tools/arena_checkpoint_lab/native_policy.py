"""Privileged action proposals; original-engine rollouts decide actual safety."""
REST=frozenset(('runonline','runonlinedown','runonground','slideonground'))


def read(gate):
    return gate.call('exec',code='return MR3A.native_search_observation()')


def support_y(observation,x):
    support=observation.get('support')
    if not support:return None
    a,b=support['start'],support['finish']
    if b['x']<=a['x']:return None
    return a['y']+(b['y']-a['y'])*(x-a['x'])/(b['x']-a['x'])


def decision(observation):
    state=observation['state'];phase=state['physics'].split(':')[0].lower()
    prior=[observation.get(k,'').split(':')[0].lower()for k in ('last_physics','previous_physics')]
    used=observation.get('jumps_used')
    if phase=='jump2'or phase=='fall'and 'jump2'in prior:used=2
    role=observation.get('role',[])
    if not role:raise ValueError('The original hurt collider is required by the native policy')
    body=role[0];p=body['center'];r=body['extents']
    speed=max(.1,state.get('speed',18.5)*observation.get('support',{}).get('slope_speed_ratio',1))
    threats=[]
    for hazard in observation.get('hazards',[]):
        h,e=hazard['center'],hazard['extents']
        if h['x']+e['x']<p['x']-r['x']-.4:continue
        t=max(0,(h['x']-e['x']-p['x']-r['x'])/speed)
        if t> .8:continue
        line=support_y(observation,h['x'])
        if line is None:line=state['position']['y']
        threats.append(dict(ttc=t,low=h['y']-e['y']-line,high=h['y']+e['y']-line,
                            world_top=h['y']+e['y'],active=hazard['enabled'],id=hazard['id']))
    threats.sort(key=lambda h:h['ttc'])
    # This is a proposal from actual geometry, including dormant colliders.
    # Its horizon intentionally precedes contact. It never certifies safety.
    above=any(h['ttc']<=.65 and h['high']>.28 and h['low']<1.5 for h in threats)
    below=any(h['ttc']<=.65 and h['low']<-.28 and h['high']>-1.5 for h in threats)
    soon_above=any(h['ttc']<=.3 and h['high']>.28 and h['low']<1.5 for h in threats)
    soon_below=any(h['ttc']<=.3 and h['low']<-.28 and h['high']>-1.5 for h in threats)
    order=('none','jump','down');reason='clear_native_corridor'
    if phase=='runonline'and above:
        order=('down','jump','none')if not soon_below else('jump','none','down')
        reason='anticipate_upper_hurt_volume'
    elif phase=='runonlinedown'and below and not soon_above:
        order=('jump','none','down');reason='anticipate_lower_hurt_volume'
    elif phase in ('runonground','slideonground')and above:
        order=('jump','down','none');reason='anticipate_ground_obstacle'
    elif phase in ('fall','fallfromrun','jump','jump2'):
        if phase in ('jump','jump2')and threats and all(p['y']-r['y']>h['world_top']+.3 for h in threats):
            reason='original_jump_already_clears_native_volumes'
        elif above and threats[0]['ttc']<.4:
            order=(('none','down','jump')if used is not None and used>=2 else('jump','down','none'))
            reason='airborne_native_threat'
        elif observation.get('support',{}).get('is_line')and not above and not below:
            order=('down','none','jump');reason='recover_original_rope_jump_budget'
    support=observation.get('support')
    if phase in REST and support and not support.get('continues')and support['finish']['x']-p['x']<speed*.45:
        order=('jump','none','down');reason='anticipate_original_support_end'
    if phase.startswith(('rollto','airup')):order=('none','jump','down');reason='let_original_transfer_finish'
    return dict(order=list(order),reason=reason,phase=phase,nearest=threats[:4],
                jumps_used=used,uses_original_colliders=True)
