"""Large native reader installation must keep the JSON control request short."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_privileged_runner as runner


@pytest.mark.parametrize('fail',[False,True])
def test_exact_sources_use_managed_file_transfer_and_are_removed_on_error(tmp_path,monkeypatch,fail):
    paths=[tmp_path/'tools/arena_privileged_state.lua',tmp_path/'tools/arena_checkpoint_lab/clock_step.lua']
    for i,p in enumerate(paths):
        p.parent.mkdir(parents=True,exist_ok=True);p.write_text('-- 中文字段\n'*(10000 if i==0 else 1)+'return true\n')
    monkeypatch.setattr(runner,'ROOT',tmp_path)
    remote={};transferred=[];executed=[]
    def adb(*args):
        if args[0]=='push':
            remote[args[2]]=Path(args[1]).read_bytes();transferred.append(args[2])
        elif args[:3]==('shell','rm','-f'):remote.pop(args[3])
        else:raise AssertionError(args)
        return SimpleNamespace(check_returncode=lambda:None)
    def execute(code):
        # The short request reads the exact transferred source; the source
        # itself never passes through another escaped JSON command string.
        assert len(json.dumps(dict(code=code)).encode())<1024
        path=json.loads(code.split('ReadAllText(',1)[1].split(');',1)[0])
        executed.append(remote[path])
        if fail:raise RuntimeError('native loader rejected source')
        return True
    client=SimpleNamespace(session=SimpleNamespace(adb=adb),execute=execute)
    if fail:
        with pytest.raises(RuntimeError,match='native loader rejected'):runner.install(client)
    else:runner.install(client)
    assert not remote
    assert executed==[p.read_bytes()for p in paths[:len(executed)]]
    assert len(transferred)==(1 if fail else 2)and len(set(transferred))==len(transferred)
