"""The opt-in VM backend must never acquire another account or host disk."""
import json
from pathlib import Path
import pytest
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
