"""Only intact contiguous committed paths may become board route artifacts."""
import importlib.util
import json
from pathlib import Path
import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'tools/arena_checkpoint_lab/route.py'
spec = importlib.util.spec_from_file_location('arena_native_route', SOURCE)
route = importlib.util.module_from_spec(spec)
spec.loader.exec_module(route)


def sources(tmp_path):
    board = dict(map=42, stage_id=50012, stage_index=0, stage_start=0, mounted=False)
    next_board = dict(board, stage_id=50021, stage_index=1, stage_start=5)
    a = dict(episodeFrame=0, health=5000, position=dict(x=0), physics='rope')
    b = dict(a, episodeFrame=2, position=dict(x=.74))
    c = dict(a, episodeFrame=5, position=dict(x=5.1), physics='air')
    def row(before, after, action, context):
        return dict(action=action, ticks=after['episodeFrame'] - before['episodeFrame'], board=context,
                    job=dict(done=True, before=before, after=after))
    first = dict(complete=False, uses_restart_replay=False,
                 start=dict(state=a, health=5000, board=board), route=[row(a, b, 'none', board)])
    second = dict(complete=True, uses_restart_replay=False,
                  start=dict(state=b, health=5000, board=board), route=[row(b, c, 'jump', next_board)],
                  end=dict(state=c, board=next_board))
    paths = [tmp_path / 'first.json', tmp_path / 'second.json']
    for path, data in zip(paths, (first, second)):
        path.write_text(json.dumps(data))
    return paths


def change(path, modify):
    data = json.loads(path.read_text())
    modify(data)
    path.write_text(json.dumps(data))


def test_join_requires_exact_native_seam_and_exports_board_local_events(tmp_path):
    reports = sources(tmp_path)
    result = route.export(reports, tmp_path / 'route.json')
    assert result['complete'] and result['duration_ticks'] == 5
    assert len(result['steps']) == 2
    event, = result['action_events']
    assert (event['relative_tick'], event['local_x'], event['stage_id']) == (2, .74, 50012)
    assert not result['entry_prefix_covered'] and not result['visual_execution_validated']


def test_partial_path_is_never_marked_as_a_completed_board(tmp_path):
    reports = sources(tmp_path)
    result = route.export(reports[:1], tmp_path / 'partial.json')
    assert not result['complete'] and result['duration_ticks'] == 2


@pytest.mark.parametrize('tamper', [
    lambda data: data['start']['state'].update(health=4750),
    lambda data: data['route'][0]['job']['after'].update(health=4750),
    lambda data: data['route'][0]['job'].update(done=False),
    lambda data: data['route'][0]['job'].update(terminated=True),
    lambda data: data['route'][0]['board'].update(stage_index=0),
    lambda data: data['route'][0]['board'].update(map=43),
])
def test_changed_or_damaged_seam_cannot_be_published_as_a_route(tmp_path, tamper):
    reports = sources(tmp_path)
    change(reports[1], tamper)
    with pytest.raises(ValueError):
        route.export(reports, tmp_path / 'invalid.json')
    assert not (tmp_path / 'invalid.json').exists()


def test_rejected_trial_actions_are_excluded_from_export(tmp_path):
    reports = sources(tmp_path)
    change(reports[0], lambda data: data.update(trials=[dict(action='down', safe=False)]))
    result = route.export(reports, tmp_path / 'route.json')
    assert [event['action'] for event in result['action_events']] == ['jump']
