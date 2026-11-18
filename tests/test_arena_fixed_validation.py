import json
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_fixed_validate import review

KEY='L5-M42-S1-B50012'
CASE=dict(key=KEY,level=5,map=42,slot=1,stage=50012)


def write_run(folder,*,damage=False,reactive=False,wrong_identity=False,progress_error=0):
    final=dict(map=42,stageIndex=1,health=4750 if damage else 5000,damage=250 if damage else 0,god=False)
    report=dict(status='passed_with_damage'if damage else'passed',had_damage=damage,final=final,
                actions=[dict(reason='reactive'if reactive else'fixed_route_rope_up')])
    setup=dict(level=5,map=42,start=1,goal_stage_index=1,pins={'1':50012},
               initial=dict(stageCount=9),fixed_route_assets={'programs':'sha256'})
    (folder/'report.json').write_text(json.dumps(report))
    (folder/'setup.json').write_text(json.dumps(setup))
    (folder/'evaluation.jsonl').write_text('\n'.join(json.dumps(dict(monotonic=i*.1,
        map=42,stageIndex=0,stageID=50012,stageStartX=100,x=100+i))for i in range(24)))
    (folder/'vision.jsonl').write_text('\n'.join(json.dumps(dict(time=i*.1+.05,fixed_route=dict(
        mode='reactive'if reactive else'fixed',board=dict(identity=[5,42,1,999 if wrong_identity else 50012],
            localized=True,progress_x=i+.5+progress_error))))for i in range(23)))
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
