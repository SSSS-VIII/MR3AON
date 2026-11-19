"""Action prerequisites shared by native validation and compiled visual tapes."""


def native_pose(physics):
    name=physics.split(':')[0].lower()
    if name=='runonline':return 'rope_above',0
    if name=='runonlinedown':return 'rope_below',0
    if name in ('runonground','slideonground'):return 'ground',0
    if name in ('rolltolineon','airup'):return 'flip_up',None
    if name in ('rolltolinedown','rolltoground'):return 'flip_down',None
    if name in ('jump2','fall2'):return 'air',2
    if name in ('jump','jump1','fall'):return 'air',1
    return name,None


def contract(before,action,after):
    pre,used=native_pose(before);post,count=native_pose(after)
    return dict(before=pre,before_jumps=used,after=post,after_jumps=count,action=action,
                native_before=before.split(':')[0].lower(),native_after=after.split(':')[0].lower())


def prerequisite(expected,physics):
    phase,jumps=native_pose(physics)
    return phase==expected['before']and (expected['before_jumps']is None or jumps==expected['before_jumps'])


def effect_matches(expected,physics):
    phase,jumps=native_pose(physics)
    # A flip can finish inside the original 50ms recording interval. Its
    # intermediate state is an accepted effect, whereas a spent jump is not.
    allowed={expected['after']}
    if expected['action']=='down'and expected['after']in ('rope_below','ground'):
        allowed.add('flip_down')
    if expected['action']=='jump'and expected['before']=='rope_below'and expected['after']=='rope_above':
        allowed.add('flip_up')
    return phase in allowed and (phase!=expected['after']or expected['after_jumps']is None
                                 or jumps==expected['after_jumps'])


def meaningful(expected):
    if expected['action']=='jump'and expected['before']=='air'and expected['before_jumps']==2:
        return False
    if (expected['action']=='down'and expected['before']=='ground'
            and expected.get('native_after')=='slideonground'
            and expected.get('native_before')!='slideonground'):return True
    return ((expected['before'],expected['before_jumps'])!=
            (expected['after'],expected['after_jumps']))
