"""A workspace patch cannot silently alter an active frozen policy function."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_revisions import freeze,load_module


def test_active_revision_keeps_its_code_after_workspace_edit_and_later_activation(tmp_path,monkeypatch):
    source=tmp_path/'src';source.mkdir();path=source/'policy.py'
    path.write_text('def decide(): return 1\n')
    first,folder,hashes=freeze(source,tmp_path/'frozen',('policy.py',))
    a=load_module('test_privileged_frozen_policy',folder/'policy.py')
    path.write_text('def decide(): return 2\n')
    second,folder2,_=freeze(source,tmp_path/'frozen',('policy.py',))
    b=load_module('test_privileged_frozen_policy',folder2/'policy.py')
    assert first!=second and a.decide()==1 and b.decide()==2
    assert (folder/'policy.py').read_text()=='def decide(): return 1\n'
    sys.modules.pop('test_privileged_frozen_policy',None)


def test_frozen_source_tampering_is_rejected(tmp_path):
    source=tmp_path/'src';source.mkdir();(source/'a.py').write_text('value=1\n')
    _,folder,_=freeze(source,tmp_path/'frozen',('a.py',))
    (folder/'a.py').write_text('value=9\n')
    with pytest.raises(ValueError,match='Immutable'):
        freeze(source,tmp_path/'frozen',('a.py',))


def test_guest_environment_uses_current_scripts_and_valid_Lua_UTF8_literals():
    import importlib.util
    path=Path(__file__).resolve().parents[1]/'tools/arena_checkpoint_lab/client.py'
    spec=importlib.util.spec_from_file_location('privileged_boot_client_test',path)
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    class Client:
        def execute(self,code):self.code=code;return True
    client=Client()
    assert module.CheckpointClient.load_environment(client)
    assert 'initializationTimeout' in client.code
    assert '从第' in client.code
    assert '\\u' not in client.code
    assert '/checkpoint-payload/environment.lua' not in client.code


def test_cold_transport_waits_for_exact_process_and_retains_attach_diagnostics():
    from arena_checkpoint_lab.boot_client import attach_transport
    class Client:
        pid='';result=dict(exit_code=0,text='')
        def shell(self,command):return self.pid
        @property
        def vm(self):return self
        def command(self,command,timeout):
            self.sent=command;return self.result
    client=Client()
    assert not attach_transport(client) and not hasattr(client,'sent')
    client.pid='1234';assert attach_transport(client)
    assert 'am attach-agent 1234 ' in client.sent and '2>&1' in client.sent
    client.result=dict(exit_code=255,text='Error: Unknown process: 1234')
    assert not attach_transport(client)
    client.result=dict(exit_code=255,text='Permission denied')
    with pytest.raises(RuntimeError,match='Permission denied'):
        attach_transport(client)
