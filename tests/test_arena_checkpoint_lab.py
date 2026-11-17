"""Prevent synthetic checkpoint evidence from silently accepting unsafe/failed runs."""
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import pytest

spec = importlib.util.spec_from_file_location(
    'arena_checkpoint_lab_run', Path(__file__).resolve().parents[1] / 'tools/arena_checkpoint_lab/run.py')
lab = importlib.util.module_from_spec(spec)
spec.loader.exec_module(lab)


@pytest.fixture
def fixture(tmp_path):
    (tmp_path / 'rootfs').mkdir()
    (tmp_path / 'rootfs/init').write_bytes(b'guest fixture')
    disk = tmp_path / 'rootfs.ext4'
    disk.write_bytes(b'base image')
    binary = tmp_path / 'benchmark'
    binary.write_bytes(b'benchmark fixture')
    config = {'network-interfaces': [], 'machine-config': {'vcpu_count': 1},
              'drives': [{'path_on_host': str(disk), 'io_engine': 'Cow'}]}
    manifest = {'scope': 'synthetic only', 'base_disk_sha256': lab.sha(disk),
                'guest_sha256': lab.sha(tmp_path / 'rootfs/init')}
    (tmp_path / 'vmconfig.json').write_text(json.dumps(config))
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    return tmp_path, binary, disk, config, manifest


def fake_result(monkeypatch, code=0, mutate=None, timeout=False, clocks=True, expired=False):
    def execute(*args, **kwargs):
        if clocks:
            for index in (0, 15, 30):
                row = dict(metric='clock_and_pending_timer', index=index,
                           clock_error_ns=1000, timer_error_ns=2000, expired=1 if expired else 0)
                kwargs['stdout'].write((json.dumps(row) + '\n').encode())
        kwargs['stdout'].write(b'{"result":"pass"}\n')
        if mutate:
            mutate()
        if timeout:
            raise lab.subprocess.TimeoutExpired(args[0], kwargs['timeout'])
        return SimpleNamespace(returncode=code)
    monkeypatch.setattr(lab.subprocess, 'run', execute)


@pytest.mark.parametrize('condition', ['nonzero', 'disk_mutated', 'timeout', 'missing_binder',
                                       'missing_clock', 'expired_timer'])
def test_success_text_cannot_mask_missing_evidence(fixture, monkeypatch, condition):
    folder, binary, disk, _, manifest = fixture
    if condition == 'missing_binder':
        manifest['android_primitives'] = True
        (folder / 'manifest.json').write_text(json.dumps(manifest))
    fake_result(monkeypatch, code=1 if condition == 'nonzero' else 0,
                mutate=(lambda: disk.write_bytes(b'changed')) if condition == 'disk_mutated' else None,
                timeout=condition == 'timeout', clocks=condition != 'missing_clock',
                expired=condition == 'expired_timer')
    assert lab.run(binary, folder, rounds=1) == 1
    report = json.loads((folder / 'report.json').read_text())
    assert report['pass'] is False
    assert report['game_rollback_complete'] is False


def test_disk_outside_fixture_is_refused_before_execution(fixture, monkeypatch):
    folder, binary, _, config, _ = fixture
    config['drives'][0]['path_on_host'] = str(folder.parent / 'other-instance.img')
    (folder / 'vmconfig.json').write_text(json.dumps(config))
    monkeypatch.setattr(lab.subprocess, 'run', lambda *a, **kw: pytest.fail('must not execute'))
    with pytest.raises(ValueError, match='inside'):
        lab.run(binary, folder, rounds=1)


def test_only_a_successful_isolated_unchanged_fixture_passes(fixture, monkeypatch):
    folder, binary, _, _, _ = fixture
    fake_result(monkeypatch)
    assert lab.run(binary, folder, rounds=1) == 0
    report = json.loads((folder / 'report.json').read_text())
    assert report['pass'] and report['base_disk_unchanged']
    assert report['game_rollback_complete'] is False
