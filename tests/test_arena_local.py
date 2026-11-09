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
    assert s.calls[-1] == ("shell","rm","-f",f"/sdcard/Android/data/com.pandadastudio.ninjamustdie3/files/arena-control/command.json")
    assert s.calls.index(s.calls[-1])>s.calls.index(next(c for c in s.calls if c[:2]==('shell','cat')))
    assert not any(code in str(arg) for args in s.calls for arg in args)


def test_acknowledged_error_also_removes_expensive_command():
    s=Session()
    original=s.adb
    def adb(*args):
        result=original(*args)
        if args[:2]==('shell','cat') and s.reads>1:
            return subprocess.CompletedProcess(args,0,json.dumps(dict(id=s.request['id'],ok=False,error='bad script')).encode())
        return result
    s.adb=adb
    with pytest.raises(RuntimeError,match='bad script'):
        LocalClient(s).execute('error("bad script")')
    assert s.calls[-1][:3]==('shell','rm','-f')


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


def test_reset_recycles_native_objects_before_scene_and_game_info_teardown(tmp_path):
    lua = shutil.which('luajit')
    if not lua:
        pytest.skip('LuaJIT unavailable')
    script = tmp_path / 'recycle.lua'
    script.write_text('local SOURCE=' + json.dumps(str(ROOT / 'arena/Local/environment.lua')) + r'''
MR3A={seedHook=true}
local old={OfflineGame=true}
local attract,blocks,items,enemies,effects,platforms,scene=false,false,false,false,false,false,false
local gm={_isOnlyGame=true,GameInfo=old}
function gm:PauseGameContent()assert(self.GameInfo==old)end
function gm:ClearAllObjectsInScene()assert(blocks and items and enemies and effects and platforms);scene=true end
function gm:InitGameData()assert(items and enemies and scene and self.GameInfo~=old)end
function gm:InitTestBonus()end
function gm:PreloadLevelData()end
function gm:EnterGameScene()end
CS={System={Reflection={BindingFlags={__CastFrom=function(v)return v end}}},
 UnityEngine={Time={},Random={InitState=function()end}},GameManager={Instance=gm},
 LevelPoolManager={Instance={RecycleAllBlock=function()assert(attract and gm.GameInfo==old and not scene);blocks=true end,
 RecycleAllMainAirGround=function()assert(effects and not scene);platforms=true end}},
 ItemManager={Instance={ClearAllActiveItem=function()assert(blocks and gm.GameInfo==old and not scene);items=true end}},
 EnemyManager={Instance={ClearAllActiveEnemy=function()assert(items and gm.GameInfo==old and not scene);enemies=true end}},
 InGameResourceFactory={Instance={SpawnPool={DespawnAll=function()assert(enemies and not scene);effects=true end}}}}
dofile(SOURCE)
MR3A.clear_mount_training=function()assert(gm.GameInfo==old and not scene);attract=true end
MR3A.new_info=function()assert(items and enemies and scene);return {OfflineGame=true}end
MR3A.role_defaults=function()end
MR3A.wait_ready=function()end
local r=MR3A.reset(42,1,1)
assert(r.resetting and items and enemies and scene)
io.write('ok')
''')
    assert subprocess.check_output([lua, str(script)], text=True) == 'ok'


def test_reset_readiness_waits_for_new_living_ninja(tmp_path):
    lua = shutil.which('luajit')
    if not lua:
        pytest.skip('LuaJIT unavailable')
    script = tmp_path / 'ready.lua'
    script.write_text('local SOURCE=' + json.dumps(str(ROOT / 'arena/Local/environment.lua')) + r'''
MR3A={seedHook=true}
local old={CurrentHp=5000};local new={CurrentHp=5000}
local state,content='Game: 8','Running: 1'
local controller={NinjaScript=old}
local co
local runner={StartCoroutine=function(self,f)co=coroutine.create(f);assert(coroutine.resume(co))end}
CS={System={Reflection={BindingFlags={__CastFrom=function(v)return v end}}},
 UnityEngine={Time={timeScale=1,realtimeSinceStartup=0},EventSystems={EventTrigger={}},
 GameObject={Find=function()return {GetComponent=function()return runner end}end}},
 NinjaController={Instance=controller},GameManager={Instance={GetCurFSMStateID=function()return state end}}}
setmetatable(CS.GameManager.Instance,{__index=function(_,k)if k=='CurrContentState'then return content end end})
typeof=function(t)return t end
package.preload['common/util']=function()return {cs_generator=function(f)return f end}end
coroutine.step=function()coroutine.yield()end
dofile(SOURCE)
MR3A.state=function()return {}end
MR3A.wait_ready(old)
assert(not MR3A.resetJob.done and CS.UnityEngine.Time.timeScale==1)
controller.NinjaScript=new;state='LoadingGame: 9'
assert(coroutine.resume(co));assert(not MR3A.resetJob.done)
state='Game: 8';new.CurrentHp=0
assert(coroutine.resume(co));assert(not MR3A.resetJob.done)
new.CurrentHp=5000;content='WaitGameStart: 0'
assert(coroutine.resume(co));assert(not MR3A.resetJob.done)
content='Running: 1'
assert(coroutine.resume(co));assert(MR3A.resetJob.done and not MR3A.resetJob.error)
assert(CS.UnityEngine.Time.timeScale==0)
io.write('ok')
''')
    assert subprocess.check_output([lua, str(script)], text=True) == 'ok'
