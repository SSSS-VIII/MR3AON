"""Search must undo whole oracle state and retain honest finite-window bounds."""
from copy import deepcopy
import importlib.util
from pathlib import Path
import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'tools/arena_checkpoint_lab/search.py'
spec = importlib.util.spec_from_file_location('arena_native_search', SOURCE)
search = importlib.util.module_from_spec(spec)
spec.loader.exec_module(search)


class Oracle:
    def __init__(self, *, impossible=False):
        self.native = dict(frame=0, hp=5000, lifted=False)
        self.points = {}
        self.sequence = 0
        self.impossible = impossible
        self.update()

    def update(self):
        n = self.native
        self.view = dict(state=dict(episodeFrame=n['frame'], health=n['hp'], physics='air' if n['lifted'] else 'rope'))

    def snapshot(self):
        self.sequence += 1
        self.points[self.sequence] = deepcopy(self.native)
        return dict(result=dict(id=self.sequence))

    def restore(self, point):
        self.native = deepcopy(self.points[point])
        self.update()
        return dict(ms=1)

    def drop(self, point):
        del self.points[point]

    def call(self, op, **args):
        if op == 'state':
            return deepcopy(self.view['state'])
        assert op == 'exec' and args['code'] == search.BOARD
        return dict(map=42, stage_index=int(self.native['frame'] >= 10), mounted=False)

    def step(self, ticks, action):
        before = deepcopy(self.view['state'])
        if action == 'jump' and self.native['frame'] < 3:
            self.native['lifted'] = True
        self.native['frame'] += ticks
        if self.impossible or (self.native['frame'] >= 7 and not self.native['lifted']):
            self.native['hp'] -= 250
        self.update()
        return dict(done=True, before=before, after=deepcopy(self.view['state']))


def start(oracle):
    return dict(health=5000, board=oracle.call('exec', code=search.BOARD))


def test_search_backtracks_before_an_unavoidable_late_collision():
    oracle = Oracle()
    result = search.search_window(oracle, start=start(oracle), offset=0, horizon=4, commit=2)
    assert result['found'] and result['crossed']
    assert [row['action'] for row in result['path']] == ['none', 'jump', 'none', 'none']
    assert result['stats']['rejected_damage'] > 0
    assert oracle.native == dict(frame=10, hp=5000, lifted=True)
    assert all(row['job']['after']['health'] == 5000 for row in result['path'])


def test_budget_exhaustion_restores_the_real_root_without_a_partial_success():
    oracle = Oracle()
    result = search.search_window(oracle, start=start(oracle), offset=0, horizon=4, commit=2, max_trials=2)
    assert not result['found']
    assert 'budget' in result['reason']
    assert oracle.native == dict(frame=0, hp=5000, lifted=False)
    assert result['root'] in oracle.points


def test_all_damaged_actions_leave_the_window_root_intact():
    oracle = Oracle(impossible=True)
    result = search.search_window(oracle, start=start(oracle), offset=0, horizon=2, commit=1)
    assert not result['found']
    assert result['stats']['rejected_damage'] == 3
    assert oracle.native == dict(frame=0, hp=5000, lifted=False)


def test_fifty_ms_parity_continues_after_a_committed_window():
    oracle = Oracle()
    result = search.search_window(oracle, start=start(oracle), offset=1, horizon=1, commit=1)
    assert result['path'][0]['ticks'] == 3
    assert oracle.native['frame'] == 3


@pytest.mark.parametrize('error', [RuntimeError('native transport failed'), KeyboardInterrupt()])
def test_native_failure_is_not_turned_into_a_bad_route(monkeypatch, error):
    oracle = Oracle()
    def fail(*_):
        oracle.native['hp'] = 0
        raise error
    monkeypatch.setattr(oracle, 'step', fail)
    with pytest.raises(type(error)):
        search.search_window(oracle, start=start(oracle), offset=0)
    assert oracle.native == dict(frame=0, hp=5000, lifted=False)
