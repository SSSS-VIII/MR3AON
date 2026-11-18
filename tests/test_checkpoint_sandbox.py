"""The opt-in VM backend must never acquire another account or host disk."""
import json
from pathlib import Path
import pytest
import subprocess
import socket
import threading
from types import SimpleNamespace
from runtime import InstanceSession
from runtime.instances import InstanceRegistry
from runtime.checkpoint_sandbox import ArenaCheckpointSandbox


def test_checkpoint_backend_rejects_other_named_instances(tmp_path):
    registry=InstanceRegistry(tmp_path)
    for name in ('main','arena','xiaoli'):
        with pytest.raises(ValueError,match='arena-search'):
            ArenaCheckpointSandbox(InstanceSession(name,registry=registry))


def test_control_commands_require_the_existing_named_lease(tmp_path):
    session=InstanceSession('arena-search',registry=InstanceRegistry(tmp_path))
    backend=ArenaCheckpointSandbox(session)
    with pytest.raises(RuntimeError,match='lease'):
        backend.request('status')


@pytest.mark.parametrize('unsafe', ['network','multiple_cpus','outside_disk','non_cow','provision_wrong_disk'])
def test_unsafe_guest_config_is_rejected_before_launch(tmp_path,monkeypatch,unsafe):
    session=InstanceSession('arena-search',registry=InstanceRegistry(tmp_path))
    backend=ArenaCheckpointSandbox(session)
    backend.root.mkdir(parents=True)
    config={'network-interfaces':[],'machine-config':{'vcpu_count':1},
            'drives':[{'path_on_host':str(backend.root/'disk.img'),'io_engine':'Cow'}]}
    if unsafe=='network':config['network-interfaces']=[{'iface_id':'host'}]
    if unsafe=='multiple_cpus':config['machine-config']['vcpu_count']=2
    if unsafe=='outside_disk':config['drives'][0]['path_on_host']=str(tmp_path/'main.img')
    if unsafe=='non_cow':config['drives'][0]['io_engine']='Sync'
    if unsafe=='provision_wrong_disk':
        (backend.root/'phase.json').write_text(json.dumps({'phase':'provision'}))
        config['drives'][0].update(io_engine='Sync',drive_id='system')
    (backend.root/'vmconfig.json').write_text(json.dumps(config))
    monkeypatch.setattr('runtime.checkpoint_sandbox.subprocess.Popen',
                        lambda *a,**kw:pytest.fail('must not start the worker'))
    with pytest.raises(ValueError):
        with backend.running(Path('unused')):
            pytest.fail('must not enter the guest')
    assert session._owns_control is False


def test_slow_worker_kill_releases_socket_after_confirmed_exit_and_preserves_original_error(tmp_path,monkeypatch):
    session=InstanceSession('arena-search',registry=InstanceRegistry(tmp_path))
    backend=ArenaCheckpointSandbox(session);backend.root.mkdir(parents=True)
    (backend.root/'vmconfig.json').write_text(json.dumps(dict(**{'network-interfaces':[],
        'machine-config':dict(vcpu_count=1)},drives=[dict(path_on_host=str(backend.root/'disk.img'),io_engine='Cow')])))
    events=[]
    class Child:
        dead=False
        def poll(self):return -9 if self.dead else None
        def wait(self,timeout):
            events.append(('wait',timeout))
            if timeout==30:self.dead=True;return -9
            raise subprocess.TimeoutExpired('private worker',timeout)
        def terminate(self):events.append(('terminate',))
        def kill(self):events.append(('kill',))
    def launch(*_args,**_kwargs):backend.socket.write_bytes(b'private socket placeholder');return Child()
    monkeypatch.setattr('runtime.checkpoint_sandbox.subprocess.Popen',launch)
    monkeypatch.setattr(backend,'request',lambda op,**args:dict(result=dict(file_ram=True)))
    with pytest.raises(RuntimeError,match='original restore failed'):
        with backend.running(Path('private-worker')):
            assert backend.capabilities['file_ram']
            raise RuntimeError('original restore failed')
    assert events==[('wait',5),('terminate',),('wait',5),('kill',),('wait',30)]
    assert not backend.socket.exists()and backend.process is None and not session._owns_control


def test_only_a_recorded_dead_worker_and_refused_socket_are_recovered(tmp_path,tmp_path_factory,monkeypatch):
    session=InstanceSession('arena-search',registry=InstanceRegistry(tmp_path));backend=ArenaCheckpointSandbox(session)
    backend.root.mkdir(parents=True)
    backend.socket=tmp_path_factory.mktemp('s')/'control.sock'
    backend.owner_file.write_text(json.dumps(dict(pid=1234,start='old')))
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)as server:server.bind(str(backend.socket))
    with session.control():
        monkeypatch.setattr(backend,'process_start',lambda _: 'old')
        assert not backend.recover_orphan()and backend.socket.exists()
        monkeypatch.setattr(backend,'process_start',lambda _: None)
        assert backend.recover_orphan()
    assert not backend.socket.exists()and not backend.owner_file.exists()


def test_a_live_listener_cannot_be_recovered_even_if_the_pid_record_is_stale(tmp_path,tmp_path_factory,monkeypatch):
    session=InstanceSession('arena-search',registry=InstanceRegistry(tmp_path));backend=ArenaCheckpointSandbox(session)
    backend.root.mkdir(parents=True);backend.owner_file.write_text(json.dumps(dict(pid=1234,start='old')))
    backend.socket=tmp_path_factory.mktemp('s')/'control.sock'
    monkeypatch.setattr(backend,'process_start',lambda _: None)
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)as server:
        server.bind(str(backend.socket));server.listen(1)
        with session.control():assert not backend.recover_orphan()
    assert backend.socket.exists()and backend.owner_file.exists()


def test_timed_out_restore_cannot_be_followed_by_another_worker_command(tmp_path,tmp_path_factory):
    session=InstanceSession('arena-search',registry=InstanceRegistry(tmp_path));backend=ArenaCheckpointSandbox(session)
    backend.socket=tmp_path_factory.mktemp('u')/'worker.sock'
    backend.process=SimpleNamespace(poll=lambda:None)
    finished=threading.Event();accepted=[]
    with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)as listener:
        listener.bind(str(backend.socket));listener.listen(1);listener.settimeout(2)
        def serve():
            with listener.accept()[0]as connection:
                accepted.append(connection.recv(4096));finished.wait(2)
        thread=threading.Thread(target=serve,daemon=True);thread.start()
        try:
            with session.control():
                with pytest.raises(TimeoutError):backend.request('restore',id=7,timeout=.02)
                with pytest.raises(RuntimeError,match='unfinished restore'):backend.request('restore',id=1)
                assert backend.uncertain_operation=='restore'
        finally:finished.set();thread.join(2)
    assert len(accepted)==1
