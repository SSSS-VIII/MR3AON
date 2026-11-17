"""Prevent frame skipping and aspect changes in the privileged search guest."""
import importlib.util
from pathlib import Path
import pytest

SOURCE = Path(__file__).resolve().parents[1] / 'tools/arena_checkpoint_lab/render.py'
spec = importlib.util.spec_from_file_location('arena_search_render', SOURCE)
render = importlib.util.module_from_spec(spec)
spec.loader.exec_module(render)


class Gate:
    def __init__(self, width, height, interval):
        self.info = dict(width=width, height=height, interval=interval)
        self.mutations = []

    def call(self, op, code):
        assert op == 'exec'
        if code == render.INFO:
            return self.info.copy()
        self.mutations.append(code)


@pytest.mark.parametrize('width,height,interval', [(1920, 1080, 60), (800, 600, 1), (320, 180, 2)])
def test_unsafe_render_settings_are_rejected_before_any_guest_mutation(width, height, interval):
    gate = Gate(width, height, interval)
    with pytest.raises(RuntimeError, match='every rendered frame'):
        render.prepare(gate)
    assert not gate.mutations


def test_small_renderer_is_idempotent_without_game_frame_advance():
    gate = Gate(320, 180, 1)
    result = render.prepare(gate)
    assert result['requested'] == result['before']
    assert not gate.mutations


def test_deferred_resolution_request_is_not_reported_as_already_applied():
    gate = Gate(1920, 1080, 1)
    result = render.prepare(gate)
    assert result['before']['width'] == gate.info['width'] == 1920
    assert result['requested'] == dict(width=320, height=180, interval=1)
    assert len(gate.mutations) == 1
