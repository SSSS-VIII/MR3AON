import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_fixed_validate import review

KEY='L5-M42-S1-B50012'
CASE=dict(key=KEY,level=5,map=42,slot=1,stage=50012)


def write_run(folder,*,damage=False,reactive=False,wrong_identity=False,progress_error=0):
    final=dict(map=42,stageIndex=1,health=4750 if damage else 5000,damage=250 if damage else 0,god=False,keys=dict(jump=1,down=0))
    report=dict(status='passed_with_damage'if damage else'passed',had_damage=damage,final=final,
                actions=[dict(reason='reactive'if reactive else'fixed_route_rope_up',action='jump',committed_time=.05)])
    setup=dict(level=5,map=42,start=1,goal_stage_index=1,pins={'1':50012},
               initial=dict(stageCount=9,god=False,health=5000),fixed_route_assets={'programs':'sha256'})
    (folder/'report.json').write_text(json.dumps(report))
    (folder/'setup.json').write_text(json.dumps(setup))
    (folder/'evaluation.jsonl').write_text('\n'.join(json.dumps(dict(monotonic=i*.1,
        map=42,stageIndex=0,stageID=50012,stageStartX=100,x=100+i,god=False))for i in range(24)))
    (folder/'vision.jsonl').write_text('\n'.join(json.dumps(dict(time=i*.1+.05,fixed_route=dict(
        mode='reactive'if reactive else'fixed',event=0 if i==0 else None,board=dict(key=KEY,identity=[5,42,1,999 if wrong_identity else 50012],
            localized=True,progress_x=i+.5+progress_error)),
        action='jump'if i==0 else None,reason='reactive'if reactive else'fixed_route_rope_up',
        action_commit=dict(committed_time=.05)if i==0 else None))for i in range(23)))
    return dict(events=[dict(action='jump')])


def test_native_health_and_actual_fixed_execution_are_separate_acceptance_checks(tmp_path):
    program=write_run(tmp_path)
    assert review(tmp_path,CASE,program)['live_runner_verified']
    write_run(tmp_path,damage=True)
    value=review(tmp_path,CASE,program)
    assert value['detector_verified'] and not value['live_runner_verified']
    write_run(tmp_path,reactive=True)
    assert not review(tmp_path,CASE,program)['live_runner_verified']


def test_wrong_visual_identity_or_stale_progress_cannot_be_promoted(tmp_path):
    program=write_run(tmp_path,wrong_identity=True)
    assert not review(tmp_path,CASE,program)['detector_verified']
    write_run(tmp_path,progress_error=.8)
    assert not review(tmp_path,CASE,program)['detector_verified']


def sequence_run(folder,indices):
    program=write_run(folder)
    program['events']=[dict(action=a)for a in('jump','down','jump')]
    rows=[json.loads(x)for x in(folder/'vision.jsonl').read_text().splitlines()]
    actions=[]
    for i,index in enumerate(indices):
        action=program['events'][index]['action'];stamp=i*.1+.05
        rows[i].update(action=action,action_commit=dict(committed_time=stamp))
        rows[i]['fixed_route']['event']=index
        actions.append(dict(action=action,reason='fixed_route_test',committed_time=stamp))
    if not indices:
        rows[0].update(action=None,action_commit=None);rows[0]['fixed_route']['event']=None
    (folder/'vision.jsonl').write_text('\n'.join(json.dumps(r)for r in rows))
    report=json.loads((folder/'report.json').read_text());report['actions']=actions
    report['final']['keys']={k:sum(('jump'if a['action']=='jump'else'down')==k for a in actions)for k in('jump','down')}
    (folder/'report.json').write_text(json.dumps(report))
    return program


def test_a_single_fixed_key_cannot_certify_a_longer_tape_and_indices_cannot_skip_or_repeat(tmp_path):
    for indices in([0],[0,2],[1,0,2],[0,1,1,2],[]):
        program=sequence_run(tmp_path,indices)
        result=review(tmp_path,CASE,program)
        assert not result['live_runner_verified']and not result['fixed_sequence']['complete']
    program=sequence_run(tmp_path,[0,1,2])
    assert review(tmp_path,CASE,program)['live_runner_verified']


def test_video_action_and_acknowledged_report_must_describe_the_same_submission(tmp_path):
    program=write_run(tmp_path)
    rows=[json.loads(s)for s in(tmp_path/'vision.jsonl').read_text().splitlines()]
    rows[0]['action_commit']=None
    (tmp_path/'vision.jsonl').write_text('\n'.join(json.dumps(r)for r in rows))
    result=review(tmp_path,CASE,program)
    assert not result['live_runner_verified']and not result['fixed_sequence']['report_matches_frames']


def test_an_enqueued_tape_that_never_reaches_original_input_cannot_pass(tmp_path):
    program=write_run(tmp_path)
    report=json.loads((tmp_path/'report.json').read_text());report['final']['keys']['jump']=0
    (tmp_path/'report.json').write_text(json.dumps(report))
    result=review(tmp_path,CASE,program)
    assert result['fixed_sequence']['complete']and not result['native_key_totals_match']
    assert not result['live_runner_verified']


def test_protection_or_off_tape_help_is_reported_even_when_health_never_drops(tmp_path):
    program=write_run(tmp_path)
    report=json.loads((tmp_path/'report.json').read_text())
    report['actions'].append(dict(action='down',reason='mpc_avoid',committed_time=.15))
    (tmp_path/'report.json').write_text(json.dumps(report))
    result=review(tmp_path,CASE,program)
    assert not result['live_runner_verified']and result['fixed_sequence']['off_tape_keys']==1
    write_run(tmp_path)
    setup=json.loads((tmp_path/'setup.json').read_text());setup['initial']['god']=True
    (tmp_path/'setup.json').write_text(json.dumps(setup))
    assert not review(tmp_path,CASE,program)['live_runner_verified']
    write_run(tmp_path)
    native=[json.loads(s)for s in(tmp_path/'evaluation.jsonl').read_text().splitlines()]
    native[10]['god']=True
    (tmp_path/'evaluation.jsonl').write_text('\n'.join(json.dumps(r)for r in native))
    assert not review(tmp_path,CASE,program)['unprotected_samples']
