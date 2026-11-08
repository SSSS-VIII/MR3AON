"""Training adapter contracts; no device, account, or client assets required."""
import copy
from pathlib import Path
import sys
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import arena_env


def state(**updates):
    value = dict(state='Game: 8', timeScale=0, health=100, score=25,
                 episodeFrame=10, frame=30)
    value.update(updates)
    return value


class Client:
    def __init__(self):
        self.current = state()
        self.calls = []
        self.session = SimpleNamespace(screenshot=lambda: b'original-png')

    def load_environment(self):
        self.calls.append('load')

    def execute(self, code, **kwargs):
        self.calls.append(code)
        return copy.deepcopy(self.current)


def ready_env(monkeypatch):
    client = Client()
    monkeypatch.setattr(arena_env, 'wait_job', lambda *a, **k: {'done': True})
    env = arena_env.ArenaEnv(auto_start=False, client=client)
    observation, info = env.reset(seed=42, level=4)
    assert observation.image_png == b'original-png'
    assert info == {'seed': 42, 'chapter': 1, 'level': 4}
    assert 'return MR3A.reset(42,1,4)' in client.calls
    return env, client


def test_step_uses_client_score_and_stops_episode_on_death(monkeypatch):
    env, client = ready_env(monkeypatch)
    after = state(score=71.5, health=0, episodeFrame=13, frame=34)
    monkeypatch.setattr(arena_env, 'wait_job', lambda *a, **k: {
        'done': True, 'before': state(), 'after': after,
        'terminated': True, 'samples': [{'episodeFrame': 13}]})
    observation, reward, terminated, truncated, info = env.step(1, ticks=30)
    assert client.calls[-1] == 'return MR3A.advance(30,"jump")'
    assert observation.state is after
    assert reward == 46.5 and terminated and not truncated
    assert info['ticks'] == 3 and info['render_frames'] == 4
    assert info['health_delta'] == -100
    with pytest.raises(RuntimeError, match='Reset'):
        env.step('none')
    # Reset must reopen the episode, even after death.
    monkeypatch.setattr(arena_env, 'wait_job', lambda *a, **k: {'done': True})
    env.reset(seed=43)
    assert not env._terminated


def test_reset_rejects_unhealthy_or_unpaused_result(monkeypatch):
    env, client = ready_env(monkeypatch)
    client.current['timeScale'] = 1
    with pytest.raises(RuntimeError, match='paused'):
        env.reset()
    with pytest.raises(RuntimeError, match='Reset'):
        env.step('none')


@pytest.mark.parametrize('action,ticks', [(True, 1), ('fly', 1), (0, 0), (0, 601), (0, 1.5)])
def test_invalid_step_does_not_send_commands(monkeypatch, action, ticks):
    env, client = ready_env(monkeypatch)
    calls = list(client.calls)
    with pytest.raises(ValueError):
        env.step(action, ticks=ticks)
    assert client.calls == calls
