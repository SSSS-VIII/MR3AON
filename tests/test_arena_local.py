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


@pytest.mark.parametrize("death_tick,expected_ticks", [(0, 7), (2, 2)])
def test_advance_counts_physics_ticks_and_holds_tap_until_consumed(tmp_path, death_tick, expected_ticks):
    lua = shutil.which("luajit")
    if not lua:
        pytest.skip("LuaJIT is unavailable")
    harness = r'''
MR3A={seedHook=true}
local game={_totalFrameCount=0,_totalTime=0}
local ninja={CurrentHp=100,transform={position={x=0,y=0,z=0}},GetType=function()
 return {GetField=function() return {GetValue=function() return 'runOnGround: 5' end} end}
end}
local releaseTick=-1
local ui={OnRightDown=function() end,OnRightReleased=function() releaseTick=game._totalFrameCount end}
local co
local runner={StartCoroutine=function(self,f) co=coroutine.create(f);assert(coroutine.resume(co)) end}
CS={System={Reflection={BindingFlags={__CastFrom=function(v) return v end}}},
UnityEngine={Time={timeScale=0,frameCount=0,time=0,realtimeSinceStartup=0},
GameObject={Find=function() return {GetComponent=function() return runner end} end},
EventSystems={EventTrigger={}},Vector3={zero={}}},
GameManager={Instance={GameInfo=game,GetCurFSMStateID=function() return 'Game: 8' end}},
NinjaController={Instance={NinjaScript=ninja}},UIContorller={Instance={GameOperate=ui}}}
typeof=function(v) return v end
package.preload['common/util']=function() return {cs_generator=function(f) return f end} end
coroutine.step=function() coroutine.yield() end
dofile(ENVIRONMENT)
MR3A.state=function() return {episodeFrame=game._totalFrameCount} end
MR3A.advance(7,'jump')
local renders=0
while MR3A.busy do
 renders=renders+1
 assert(renders<20,'Advance never completed')
 local t=CS.UnityEngine.Time
 t.frameCount=renders;t.realtimeSinceStartup=renders/60;t.time=renders/60
 -- 60 rendered frames carry only 50 original fixed updates.
 if renders%6~=0 then game._totalFrameCount=game._totalFrameCount+1;game._totalTime=game._totalFrameCount/50 end
 if DEATH_TICK>0 and game._totalFrameCount>=DEATH_TICK then ninja.CurrentHp=0 end
 assert(coroutine.resume(co))
end
assert(not MR3A.job.error,MR3A.job.error)
io.write(string.format('%d|%d|%d|%d|%s',game._totalFrameCount,renders,releaseTick,#MR3A.job.samples,tostring(MR3A.job.terminated)))
'''
    script = tmp_path / "ticks.lua"
    script.write_text("local ENVIRONMENT=" + json.dumps(str(ROOT / "arena/Local/environment.lua")) + f"\nlocal DEATH_TICK={death_tick}\n" + harness)
    output = subprocess.check_output([lua, str(script)], text=True).split("|")
    ticks, renders, release_tick, samples = map(int, output[:4])
    assert ticks == samples == expected_ticks
    assert release_tick == 1
    assert renders == (8 if death_tick == 0 else 2)
    assert output[4] == ("true" if death_tick else "nil")


def test_k_key_uses_original_jump_press_and_release(tmp_path):
    lua = shutil.which('luajit')
    if not lua:
        pytest.skip('LuaJIT unavailable')
    script = tmp_path / 'keyboard.lua'
    script.write_text('local SOURCE=' + json.dumps(str(ROOT / 'arena/Local/environment.lua')) + r'''
MR3A={seedHook=true}
local pressed,released=0,0
local down,up=true,false
CS={System={Reflection={BindingFlags={__CastFrom=function(v)return v end}}},
 UnityEngine={Time={timeScale=1},Vector3={zero={}},
 KeyCode={P='P',R='R',N='N',Period='.',Space='space',K='K',W='W',UpArrow='up',S='S',DownArrow='down'},
 Input={GetKeyDown=function(k)return down and k=='K' end,GetKeyUp=function(k)return up and k=='K' end}},
 GameManager={Instance={GetCurFSMStateID=function()return 'Game: 8' end}},
 UIContorller={Instance={GameOperate={OnRightDown=function()pressed=pressed+1 end,
 OnRightReleased=function()released=released+1 end}}}}
dofile(SOURCE)
MR3A.poll_keys();assert(pressed==1 and released==0 and MR3A.lastKey=='jump')
down=false;up=true
MR3A.poll_keys();assert(pressed==1 and released==1)
io.write('ok')
''')
    assert subprocess.check_output([lua, str(script)], text=True) == 'ok'
