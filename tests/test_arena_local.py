import json
from pathlib import Path
import shutil
import subprocess
import sys
from types import SimpleNamespace
from contextlib import nullcontext

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
from arena_local import LocalClient


class Session:
    spec = SimpleNamespace(name="arena")

    def __init__(self):
        self.request = None
        self.calls = []
        self.reads = 0

    def control(self):
        return nullcontext()

    def adb(self, *args):
        self.calls.append(args)
        if args[0] == "push":
            self.request = json.loads(Path(args[1]).read_text())
        if args[:2] == ("shell", "cat"):
            self.reads += 1
            # An old result must not be accepted as this request's acknowledgement.
            identity = "old" if self.reads == 1 else self.request["id"]
            return subprocess.CompletedProcess(args, 0, json.dumps({"id": identity, "ok": True, "result": {"ack": True}}).encode())
        return subprocess.CompletedProcess(args, 0, b"")


def test_rpc_identity_atomic_publish_and_literal_code():
    s = Session()
    code = 'return "$(touch unwanted); `id`"'
    assert LocalClient(s).execute(code) == {"ack": True}
    assert s.request["code"] == code
    assert isinstance(s.request["id"], str)
    assert s.reads == 2
    assert s.calls[1][:2] == ("shell", "mv")
    assert not any(code in str(arg) for args in s.calls for arg in args)


def test_rejects_main_and_oversized_commands():
    s = Session()
    s.spec = SimpleNamespace(name="main")
    with pytest.raises(ValueError, match="isolated"):
        LocalClient(s)
    s.spec = SimpleNamespace(name="arena")
    with pytest.raises(ValueError, match="1 MiB"):
        LocalClient(s).execute("中" * 400000)
    assert not s.calls


@pytest.mark.parametrize("code,expected", [
    ("return {list={1,2,3},flag=true}", {"list": [1, 2, 3], "flag": True}),
    ("local u=newproxy(true);getmetatable(u).__tostring=function() return 'Game: 8' end;return {state=u}", {"state": "Game: 8"}),
    ("local t={};t.self=t;return t", None),
])
def test_lua_bridge_serializes_arrays_enums_and_cycles(code, expected, tmp_path):
    lua = shutil.which("luajit")
    if not lua:
        pytest.skip("LuaJIT is unavailable")
    # Run the production bridge with a minimal Unity/IO host, including its poll
    # coroutine, rather than reimplementing its serializer in the test.
    harness = r'''
package.preload['uLua/Coroutine']=function() coroutine.step=function() coroutine.yield() end end
package.preload['common/util']=function() return {cs_generator=function(f) return f end} end
local fn,output
local commandChecks=0
local runner={StartCoroutine=function(self,f) fn=f end}
local host={AddComponent=function() return runner end}
CS={UnityEngine={GameObject=setmetatable({},{__call=function() return host end}),
Object={DontDestroyOnLoad=function() end},EventSystems={EventTrigger={}},Application={persistentDataPath='/local'}},
System={IO={Directory={CreateDirectory=function() end},File={Exists=function(path) if not path:match("command.json$") then return false end;commandChecks=commandChecks+1;return commandChecks>1 end,
ReadAllText=function() return '' end,WriteAllText=function(path,data) if path:match('result.json$') then output=data end end}}}}
typeof=function(t) return t end
CheckLoadLuaComplete=function() return true end
json={parse=function() return {id='request',code=CODE} end,
stringify=function(v)
  if type(v)=='string' then return string.format('%q',v) end
  return '{"id":"request","ok":false,"error":"Result is not JSON serializable"}'
end}
print=function() end
dofile(BRIDGE)
local co=coroutine.create(fn)
local ok,err=coroutine.resume(co)
assert(ok,err)
io.write(output)
'''
    script = tmp_path / "test.lua"
    script.write_text("local CODE=" + json.dumps(code) + "\nlocal BRIDGE=" + json.dumps(str(ROOT / "arena/Local/client_bridge.lua")) + "\n" + harness)
    output = subprocess.check_output([lua, str(script)], text=True)
    result = json.loads(output)
    if expected is None:
        assert not result["ok"] and "serializable" in result["error"]
    else:
        assert result["ok"] and result["result"] == expected
