"""Protect mailbox handover and prevent restoring a different guest agent."""
import importlib.util
import json
import io
from pathlib import Path
from types import SimpleNamespace
import pytest

BASE = Path(__file__).resolve().parents[1] / 'tools/arena_checkpoint_lab'
spec = importlib.util.spec_from_file_location('arena_game_gate', BASE / 'gate.py')
module = importlib.util.module_from_spec(spec)
spec.loader.exec_module(module)


class VM:
    def __init__(self, outputs=()):
        self.session = SimpleNamespace(spec=SimpleNamespace(name='arena-search'))
        self.outputs = iter(outputs)
        self.calls = []
        self.can_rebase = False

    def request(self, operation, **args):
        self.calls.append((operation, args))
        if operation == 'command':
            return dict(result=dict(id=11))
        if operation == 'run':
            return dict(result=dict(output=next(self.outputs)))
        if operation == 'snapshot':
            return dict(result=dict(id=42), ms=1)
        if operation == 'status':
            return dict(result=dict(can_rebase=self.can_rebase))
        if operation == 'rebase':
            return dict(result=dict(id=43), ms=1)
        return dict(result=args, ms=1)


def reply(code=module.GATE_CODE, identity=11, **view):
    return dict(id=identity, code=code, exit_code=0, text=json.dumps(dict(schema=1, **view)))


def test_late_root_reply_cannot_complete_a_game_command():
    vm = VM([reply(code=0, last=dict(ok=True, result='stale root')),
             reply(last=dict(ok=True, result='actual Unity boundary'))])
    gate = module.GameGate(vm)
    gate.view = dict(schema=1)
    assert gate.call('state') == 'actual Unity boundary'
    assert [op for op, _ in vm.calls] == ['command', 'run', 'run']


def test_handover_does_not_wait_for_a_root_acknowledgement():
    vm = VM([reply(identity=0, state=dict(episodeFrame=71))])
    gate = module.GameGate(vm)
    assert gate.connect()['state']['episodeFrame'] == 71
    assert vm.arena_game_gate


def test_unexpected_game_reply_is_an_error():
    vm = VM([reply(identity=10)])
    gate = module.GameGate(vm)
    gate.view = dict(schema=1)
    with pytest.raises(RuntimeError, match='unexpected command'):
        gate.call('state')


def test_pre_gate_or_foreign_snapshots_are_refused_before_restore():
    vm = VM()
    gate = module.GameGate(vm)
    gate.view = dict(schema=1, state=dict(episodeFrame=71))
    with pytest.raises(ValueError, match='active game gate'):
        gate.restore(7)
    assert not vm.calls
    gate.snapshot()
    gate.view['state']['episodeFrame'] = 99
    gate.restore(42)
    assert gate.view['state']['episodeFrame'] == 71


def test_original_job_error_is_not_reported_as_a_successful_step():
    vm = VM([reply(state=dict(episodeFrame=54),
                   last=dict(ok=True, result=dict(error='Physics ticks stopped advancing')))])
    gate = module.GameGate(vm)
    gate.view = dict(schema=1)
    with pytest.raises(RuntimeError, match='Physics ticks'):
        gate.step(3)
    assert gate.view['state']['episodeFrame'] == 54


@pytest.mark.parametrize('after,stopped,terminated,accepted', [
    (74, 74, False, True),
    (72, 72, True, True),
    (72, 72, False, False),
    (75, 75, False, False),
    (70, 70, True, False),
    (74, 75, False, False),
])
def test_step_checks_actual_tick_interval_and_allows_early_death(after, stopped, terminated, accepted):
    job = dict(done=True, before=dict(episodeFrame=71), after=dict(episodeFrame=after), terminated=terminated)
    vm = VM([reply(state=dict(episodeFrame=stopped), last=dict(ok=True, result=job))])
    gate = module.GameGate(vm)
    gate.view = dict(schema=1)
    if accepted:
        assert gate.step(3) == job
    else:
        with pytest.raises(RuntimeError, match='interval mismatch'):
            gate.step(3)


def test_root_file_commands_are_refused_after_handover():
    spec = importlib.util.spec_from_file_location('arena_gate_client', BASE / 'client.py')
    client_module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(client_module)
    vm = VM()
    vm.arena_game_gate = True
    with pytest.raises(RuntimeError, match='inactive'):
        client_module.CheckpointClient(vm).shell('echo should not run')
    with pytest.raises(RuntimeError, match='inactive'):
        client_module.CheckpointClient(vm).execute('return true')
    assert not vm.calls


def test_unfinished_game_operation_cannot_be_overwritten_or_snapshotted():
    vm = VM()
    gate = module.GameGate(vm)
    gate.view = dict(schema=1)
    gate.waiting = True
    with pytest.raises(RuntimeError, match='unfinished'):
        gate.call('state')
    with pytest.raises(RuntimeError, match='after reaching'):
        gate.snapshot()
    assert not vm.calls


def test_rebase_invalidates_previous_tree_and_preserves_the_stopped_view(tmp_path, monkeypatch):
    vm = VM()
    vm.can_rebase = True
    vm.root = tmp_path
    (tmp_path / 'vmconfig.json').write_text(json.dumps({'machine-config': {'mem_size_mib': 3072}}))
    monkeypatch.setattr(module, 'open', lambda _: io.StringIO('MemAvailable: 8388608 kB\n'), raising=False)
    gate = module.GameGate(vm)
    gate.view = dict(schema=1, state=dict(episodeFrame=71))
    gate.snapshot()
    gate.rebase()
    assert list(gate.points) == [43]
    assert gate.view['state']['episodeFrame'] == 71
    with pytest.raises(ValueError, match='active game gate'):
        gate.restore(42)


def test_rebase_refuses_insufficient_spare_ram_before_mutation(tmp_path, monkeypatch):
    vm = VM()
    vm.can_rebase = True
    vm.root = tmp_path
    (tmp_path / 'vmconfig.json').write_text(json.dumps({'machine-config': {'mem_size_mib': 3072}}))
    monkeypatch.setattr(module, 'open', lambda _: io.StringIO('MemAvailable: 1024 kB\n'), raising=False)
    gate = module.GameGate(vm)
    gate.view = dict(schema=1)
    with pytest.raises(RuntimeError, match='spare RAM'):
        gate.rebase()
    assert [operation for operation, _ in vm.calls] == ['status']


@pytest.mark.parametrize('native_ticks',[0,1])
def test_render_clock_does_not_convert_native_counter_ticks_to_elapsed_time(native_ticks):
    before=dict(frame=100,time=2.,episodeFrame=50)
    after=dict(frame=101,time=2.+1/60,episodeFrame=50+native_ticks)
    job=dict(done=True,unit='unity_render_frame',before=before,after=after)
    gate=module.GameGate(VM([reply(state=after,last=dict(ok=True,result=job))]))
    gate.view=dict(schema=1,state=before)
    assert gate.render_step(1)==job


def test_render_clock_rejects_a_stopped_clock_and_a_wrong_stopped_state():
    before=dict(frame=100,time=2.,episodeFrame=50)
    for after,stopped in [(dict(frame=101,time=2.,episodeFrame=51),None),
                          (dict(frame=101,time=2.+1/60,episodeFrame=51),before)]:
        job=dict(done=True,unit='unity_render_frame',before=before,after=after)
        gate=module.GameGate(VM([reply(state=stopped or after,last=dict(ok=True,result=job))]))
        gate.view=dict(schema=1,state=before)
        with pytest.raises(RuntimeError,match='render-clock'):gate.render_step(1)


def test_completed_paused_physics_stall_keeps_its_evidence_for_real_parent_restore():
    from arena_checkpoint_errors import NativeIntervalError
    before=dict(episodeFrame=624,timeScale=0,health=5000)
    after=dict(episodeFrame=626,timeScale=0,health=5000)
    job=dict(done=True,error='mr3a-environment:131: Physics ticks stopped advancing',
             before=before,after=after,samples=[after])
    gate=module.GameGate(VM([reply(state=after,last=dict(ok=True,result=job))]))
    gate.view=dict(schema=1,state=before)
    with pytest.raises(NativeIntervalError)as caught:gate.step(3)
    assert caught.value.job==job


def test_a_still_running_or_inconsistent_stall_is_not_a_recoverable_candidate():
    from arena_checkpoint_errors import NativeIntervalError
    after=dict(episodeFrame=626,timeScale=1)
    job=dict(done=True,error='Physics ticks stopped advancing',before=dict(episodeFrame=624),after=after)
    gate=module.GameGate(VM([reply(state=after,last=dict(ok=True,result=job))]))
    gate.view=dict(schema=1)
    with pytest.raises(RuntimeError)as caught:gate.step(3)
    assert not isinstance(caught.value,NativeIntervalError)
