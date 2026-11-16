import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from arena_board_failures import action_timeline, audit_run, build_audit, main


def sample(stamp, *, stage=5101, index=0, map_id=41, damage=0, drop=None, **extra):
    return dict(monotonic=stamp, map=map_id, stageIndex=index, stageID=stage, damage=damage,
                health=5000-damage, physics='runOnLine:1', last_health_drop=drop, **extra)


def drop(stamp=11, before=5000, after=4900):
    return dict(monotonic=stamp, frame=int(stamp*60), before=before, after=after, physics='jump:14',
                last_hurt_reference=dict(type='EnemyFlyBamboo', scope='May retain an older enemy'))


def vision(stamp, frame, *, age=100, **extra):
    return dict(time=stamp+age/1000, observation_age_ms=age, frame=frame,
                phase='jump2_falling', jumps=2, reason='mpc_wait', action=None, **extra)


def write_run(tmp_path, *, rows=None, visuals=None, actions=None, final=None, initial=None):
    tmp_path.mkdir(exist_ok=True)
    event = drop()
    if rows is None:
        rows = [sample(10.9), sample(11.1, damage=100, drop=event),
                sample(11.5, damage=100, drop=event)]
    if final is None:
        final = sample(12, stage=5102, index=1, damage=100, drop=event)
    setup = dict(initial=initial or sample(10), observe=False, level=5, seed=42,
                 map=41, start=1, pins={'1': 5101}, goal_stage_index=1,
                 sources={'tools/arena_motion.py': 'recorded-sha'})
    report = dict(status='passed_with_damage', final=final, actions=actions or [], boards_requested=1,
                  board_entries=[dict(stageIndex=0, stageID=5101), dict(stageIndex=1, stageID=5102)])
    for name, value in (('setup.json', setup), ('report.json', report)):
        (tmp_path/name).write_text(json.dumps(value))
    for name, values in (('evaluation.jsonl', rows), ('vision.jsonl', visuals or [vision(10.95, 1)])):
        (tmp_path/name).write_text(''.join(json.dumps(value)+'\n' for value in values))
    return tmp_path


def test_sticky_event_deduplication_and_original_stage_bracket(tmp_path):
    result = audit_run(write_run(tmp_path))
    assert len(result['hits']) == 1
    hit = result['hits'][0]
    assert hit['reference_count'] == 3  # Two polls plus report.final retain the same event.
    assert hit['board_assignment']['status'] == 'attributed'
    assert hit['board_assignment']['board'] == dict(native_map=41, native_stage_index=0, stage_id=5101)
    assert hit['native_event']['physics'] == 'jump:14'
    assert hit['native_event']['last_hurt_reference']['scope'] == 'May retain an older enemy'
    assert result['boards'][0]['witnessed_attributed_loss'] == 100
    assert result['boards'][1]['witnessed_attributed_loss'] == 0  # Later sticky record is not a later-board hit.
    assert result['damage']['unwitnessed_loss'] == 0
    assert result['actor_sources_recorded']['tools/arena_motion.py'] == 'recorded-sha'
    assert set(result['input_sha256']) == {'setup.json', 'report.json', 'evaluation.jsonl', 'vision.jsonl'}


@pytest.mark.parametrize('new_map,new_index,new_stage', [(41, 1, 5102), (99, 0, 0)])
def test_cross_board_or_boss_transition_is_never_split(tmp_path, new_map, new_index, new_stage):
    event = drop()
    after = sample(11.1, stage=new_stage, index=new_index, map_id=new_map, damage=100, drop=event)
    result = audit_run(write_run(tmp_path, rows=[sample(10.9), after], final=dict(after, monotonic=12)))
    assignment = result['hits'][0]['board_assignment']
    assert assignment['status'] == 'boundary_ambiguous'
    assert assignment['board'] is None
    assert result['damage']['witnessed_unassigned_loss'] == 100
    assert sum(board['witnessed_attributed_loss'] for board in result['boards']) == 0
    assert result['boards'][0]['ambiguous_event_indices'] == [0]


def test_unknown_support_without_transition_stays_unresolved(tmp_path):
    after = sample(11.1, stage=0, index=-1, damage=100, drop=drop())
    result = audit_run(write_run(tmp_path, rows=[sample(10.9), after], final=dict(after, monotonic=12)))
    assignment = result['hits'][0]['board_assignment']
    assert assignment['status'] == 'unresolved'
    assert assignment['after']['native_stage'] == dict(map=41, stageIndex=-1, stageID=0)
    assert result['damage']['witnessed_unassigned_loss'] == 100


def test_two_native_hits_are_not_conflated_when_hp_regenerates(tmp_path):
    a, b = drop(10.5, 5000, 4500), drop(11.5, 4800, 4700)
    rows = [sample(10.6, damage=500, drop=a), sample(11.4, damage=500, drop=a),
            sample(11.6, damage=600, drop=b)]
    result = audit_run(write_run(tmp_path, rows=rows, final=sample(12, damage=600, drop=b)))
    assert [hit['health_loss'] for hit in result['hits']] == [500, 100]
    assert result['damage']['witnessed_event_loss'] == result['damage']['episode'] == 600


def test_overwritten_native_events_are_reported_as_unwitnessed_not_invented(tmp_path):
    event = drop(11, 4800, 4700)
    result = audit_run(write_run(tmp_path, rows=[sample(10.9), sample(11.1, damage=300, drop=event)],
                                final=sample(12, damage=300, drop=event)))
    assert len(result['hits']) == 1
    assert result['damage']['unwitnessed_loss'] == 200
    assert result['boards'][0]['witnessed_attributed_loss'] == 100


def test_prestart_retained_hit_is_excluded_and_initial_counter_subtracted(tmp_path):
    old = drop(9.5)
    rows = [sample(10.9, damage=100, drop=old), sample(11.1, damage=200, drop=drop())]
    result = audit_run(write_run(tmp_path, initial=sample(10, damage=100, drop=old), rows=rows,
                                final=sample(12, damage=200, drop=drop())))
    assert len(result['hits']) == 1
    assert len(result['evidence']['excluded_events']) == 1
    assert result['damage']['episode'] == result['damage']['witnessed_event_loss'] == 100


def test_capture_clock_is_not_decision_clock_and_saved_image_can_differ(tmp_path):
    # The first decision timestamp is at the hit; its actual pixels are older.
    frames = [vision(10.8, 1, age=200), vision(10.99, 2, age=200), vision(11.02, 3, age=200)]
    write_run(tmp_path, visuals=frames)
    (tmp_path/'000001.png').write_bytes(b'raw fixture')
    (tmp_path/'000003.png').write_bytes(b'raw fixture')
    (tmp_path/'000003-overlay.jpg').write_bytes(b'overlay fixture')
    visual = audit_run(tmp_path)['hits'][0]['visual']
    assert visual['nearest_observation']['frame'] == 2
    assert visual['nearest_observation']['alignment_ms'] == pytest.approx(-10)
    assert visual['nearest_observation']['images']['raw'] is None
    assert visual['nearest_saved_image']['frame'] == 3
    assert visual['preceding_saved_image']['frame'] == 1
    assert visual['nearest_saved_image']['images']['overlay'].endswith('000003-overlay.jpg')
    assert visual['nearest_observation']['phase_at_decision'] == 'jump2_falling'


def test_unknown_capture_clock_is_not_guessed_from_elapsed_or_time(tmp_path):
    row = vision(10.99, 1)
    del row['observation_age_ms']
    result = audit_run(write_run(tmp_path, visuals=[dict(row, elapsed=.5)]))
    assert result['hits'][0]['visual']['nearest_observation'] is None
    assert result['hits'][0]['visual']['unknown_capture_clock_rows'] == 1


def test_action_clock_prefers_native_receipts_and_preserves_primitive(tmp_path):
    actions = [dict(action='jump', key='jump', key_count=1, committed_time=10.9, enqueued_time=10.8,
                    committed_primitive='air_up', reason='mpc_air_up'),
               dict(action='down', key='down', key_count=1, committed_time=11.15,
                    committed_anchor_error_ms=50, committed_primitive='air_down'),
               dict(action='jump', key='jump', key_count=2, enqueued_time=11.2),
               dict(action='jump', request_ns=10_950_000_000, t=.95)]
    rows = [sample(10.9, keyReceipts={'jump': dict(count=1, time=10.85)}),
            sample(11.1, damage=100, drop=drop())]
    result = audit_run(write_run(tmp_path, rows=rows, actions=actions))
    inputs = result['hits'][0]['actions']
    assert inputs['previous']['monotonic'] == 10.85
    assert inputs['previous']['clock'] == 'native_key_receipt'
    assert inputs['previous']['committed_primitive'] == 'air_up'
    assert inputs['next']['monotonic'] == pytest.approx(11.1)
    assert inputs['next']['clock'] == 'native_receipt_from_anchor_error'
    timeline, unknown = action_timeline(actions, [])
    assert timeline[-1]['clock'] == 'enqueued_time_no_native_receipt'
    assert unknown == result['evidence']['actions_without_native_clock'] == [3]


def test_damage_counter_inconsistency_is_exposed(tmp_path):
    result = audit_run(write_run(tmp_path, rows=[sample(10.9, damage=200), sample(11.1, damage=100, drop=drop())],
                                final=sample(12, damage=50, drop=drop())))
    assert result['damage']['counter_monotonic'] is False
    assert result['damage']['events_exceed_counter'] == 50


@pytest.mark.parametrize('bad_kind', ['observe', 'collection', 'invalid_json'])
def test_collection_and_malformed_inputs_are_errors_not_actor_hits(tmp_path, bad_kind):
    write_run(tmp_path)
    if bad_kind == 'invalid_json':
        (tmp_path/'evaluation.jsonl').write_text('{broken\n')
    else:
        path = tmp_path/('setup.json' if bad_kind == 'observe' else 'report.json')
        value = json.loads(path.read_text())
        if bad_kind == 'observe':
            value['observe'] = True
        else:
            del value['actions']
        path.write_text(json.dumps(value))
    result = build_audit([tmp_path])
    assert result['summary']['errors'] == 1
    assert result['summary']['events'] == 0


def test_zero_damage_completed_report_does_not_accept_all_entered_boards(tmp_path):
    write_run(tmp_path, rows=[sample(11)], final=sample(12, stage=5102, index=1))
    path = tmp_path/'report.json'
    report = json.loads(path.read_text())
    report['status'] = 'passed'
    path.write_text(json.dumps(report))
    result = build_audit([tmp_path, tmp_path])
    assert result['summary'] == dict(runs=1, errors=0, events=0, episode_damage=0, unwitnessed_loss=0,
                                     unassigned_event_loss=0)
    run = result['runs'][0]
    assert len(run['boards']) == 2
    assert all('accepted' not in board for board in run['boards'])
    assert any('zero is not a no-hit acceptance' in scope for scope in run['scope'])


def test_cli_refuses_to_overwrite_saved_actor_evidence(tmp_path, monkeypatch):
    write_run(tmp_path)
    output = tmp_path/'report.json'
    original = output.read_bytes()
    monkeypatch.setattr(sys, 'argv', ['arena_board_failures', str(tmp_path), '--output', str(output)])
    with pytest.raises(FileExistsError):
        main()
    assert output.read_bytes() == original


def test_dropped_key_cannot_shift_native_clock_or_reuse_legacy_anchor_error():
    actions=[dict(key='down',key_count=i,enqueued_time=float(i),
                  committed_time=float(i)+.016,committed_anchor_error_ms=-900)
             for i in range(1,5)]
    samples=[{'row':dict(monotonic=t,keyReceipts={'down':dict(count=c,time=t)})}
             for c,t in [(1,1.02),(2,3.02),(3,4.02)]]
    timeline,unknown=action_timeline(actions,samples)
    assert not unknown
    by_count={a['key_count']:a for a in timeline}
    assert by_count[1]['monotonic']==1.02
    assert by_count[2]['clock']=='enqueued_time_no_native_receipt'
    assert by_count[3]['clock']=='enqueued_time_no_native_receipt'
    assert by_count[4]['monotonic']==4.02
    assert by_count[4]['clock']=='native_key_receipt'


@pytest.mark.parametrize('as_object',[False,True])
def test_native_event_history_recovers_multiple_hits_between_polls(tmp_path,as_object):
    a,b=drop(10.95,5000,4800),drop(11.,4800,4700)
    ring={'1':a,'2':b}if as_object else[a,b]
    after=sample(11.1,damage=300,drop=b,health_drops=ring)
    result=audit_run(write_run(tmp_path,rows=[sample(10.9),after],final=dict(after,monotonic=12)))
    assert [hit['health_loss']for hit in result['hits']]==[200,100]
    assert result['damage']['unwitnessed_loss']==0
    assert result['damage']['witnessed_event_loss']==300  # Sticky+ring are never counted twice.
    assert result['evidence']['invalid_event_origins']==[]


def test_malformed_native_history_does_not_hide_the_legacy_event(tmp_path):
    after=sample(11.1,damage=100,drop=drop(),health_drops={'wrong':drop()})
    result=audit_run(write_run(tmp_path,rows=[sample(10.9),after],final=dict(after,monotonic=12)))
    assert len(result['hits'])==1
    assert result['evidence']['invalid_event_origins']==['evaluation.jsonl:2.health_drops','report.final.health_drops']
