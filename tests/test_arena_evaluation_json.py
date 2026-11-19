"""Native evaluation JSON caching preserves witnesses and bounded ownership."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT=Path(__file__).resolve().parents[1]
HARNESS=r'''
MR3A={}
CS={UnityEngine={Application={persistentDataPath='/tmp'}},System={
 Reflection={BindingFlags={__CastFrom=function(v)return v end}},Diagnostics={Stopwatch={}}}}
typeof=function()return {GetField=function()return {}end}end
local calls={}
local function quote(s)
 return '"'..string.gsub(tostring(s),'[%z\1-\31\\"]',function(c)
  if c=='"'then return '\\"'elseif c=='\\'then return '\\\\'end
  return string.format('\\u%04x',string.byte(c))
 end)..'"'
end
local function encode(value)
 local kind=type(value)
 if kind=='table'then
  if value.invalid then error('Synthetic serialization failure')end
  local parts={};for k,v in pairs(value)do parts[#parts+1]=quote(k)..':'..encode(v)end
  return '{'..table.concat(parts,',')..'}'
 elseif kind=='string'then return quote(value)
 elseif kind=='boolean'or kind=='number'then return tostring(value)
 elseif kind=='nil'then return 'null'end
 error('Unsupported synthetic value')
end
json={stringify=function(value,as_key)
 if type(value)=='table'then calls[value]=(calls[value]or 0)+1 end
 return as_key and quote(value)or encode(value)
end}
dofile(SOURCE)
'''


def run_lua(tmp_path,body):
    lua=shutil.which('luajit')
    if not lua:pytest.skip('LuaJIT unavailable')
    script=tmp_path/'evaluation.lua'
    script.write_text('local SOURCE='+json.dumps(str(ROOT/'arena/Local/vision_eval.lua'))+'\n'+HARNESS+body)
    return subprocess.check_output([lua,str(script)],text=True).splitlines()


def test_repeated_polls_preserve_exact_events_and_refresh_live_fields(tmp_path):
    output=run_lua(tmp_path,r'''
local a={before=5000,after=4520,geometry={x=1.125,note='引号"\\\n'}}
local b={before=4520,after=4280,geometry={x=-3.5}}
local history={a,b};local row={health=4280,health_drops=history,last_health_drop=b,monotonic=12.5}
local original=json.stringify(row)
local first=MR3A.encode_vision_evaluation(row)
row.health=4290;row.monotonic=12.6
local second=MR3A.encode_vision_evaluation(row)
assert(calls[a]==1 and calls[b]==1)
assert(row.health_drops==history and row.last_health_drop==b and history[1]==a)
assert(a.geometry.x==1.125 and b.geometry.x==-3.5)
io.write(original..'\n'..first..'\n'..second)
''')
    original,first,second=map(json.loads,output)
    assert first==original
    assert second==dict(first,health=4290,monotonic=12.6)


def test_retired_events_are_evicted_and_absent_fields_stay_absent(tmp_path):
    output=run_lua(tmp_path,r'''
local a={before=5000,after=4800};local b={before=4800,after=4600}
MR3A.encode_vision_evaluation({health_drops={a,b},last_health_drop=b})
MR3A.encode_vision_evaluation({health_drops={b},last_health_drop=b})
MR3A.encode_vision_evaluation({health_drops={a},last_health_drop=a})
assert(calls[a]==2 and calls[b]==1)
io.write(MR3A.encode_vision_evaluation({health_drops={}})..'\n')
io.write(MR3A.encode_vision_evaluation({health=5000}))
''')
    assert list(map(json.loads,output))==[dict(health_drops={}),dict(health=5000)]


def test_serializer_failure_leaves_witnesses_owned_by_the_caller(tmp_path):
    output=run_lua(tmp_path,r'''
local event={invalid=true};local history={event};local row={health_drops=history,last_health_drop=event}
local ok=pcall(MR3A.encode_vision_evaluation,row)
assert(not ok and row.health_drops==history and row.last_health_drop==event)
event.invalid=nil;event.before=5000;event.after=4900
io.write(MR3A.encode_vision_evaluation(row))
''')
    row=json.loads(output[0])
    assert row['health_drops']['1']==row['last_health_drop']==dict(before=5000,after=4900)


def test_input_history_retains_the_native_board_for_each_key_when_the_board_changes(tmp_path):
    output=run_lua(tmp_path,r'''
local t={}
function t:GetField(k)return {GetValue=function(_,o)return o[k]end}end
local stage0={_stageBaseInfo={_stageID=50022},GetType=function()return t end}
local stage1={_stageBaseInfo={_stageID=50031},GetType=function()return t end}
local level={_stageList={[0]=stage0,[1]=stage1,Count=2},_levelBaseInfo={_levelID=42},GetType=function()return t end}
local n={CurrentHp=5000,_GroundCollider={BelongToStageIndex=0},__ninjaPhysicsState='runOnLine: 1',GetType=function()return t end,IsGodMode=function()return false end}
CS.NinjaController={Instance={NinjaScript=n}};CS.LevelManager={Instance={GameLevelInfo=level}}
CS.UnityEngine.Time={frameCount=10,realtimeSinceStartup=1}
CS.UnityEngine.KeyCode={K=1,S=2}
local pressed,stamp=1,1.
CS.UnityEngine.Input={GetKeyDown=function(k)return k==pressed end}
CS.System.Diagnostics.Stopwatch.GetTimestamp=function()return stamp end
CS.System.Diagnostics.Stopwatch.Frequency=1
MR3A.visionEvalKeys={jump=0,down=0};MR3A.visionEvalReceipts={}
MR3A.sample_vision_health()
n._GroundCollider.BelongToStageIndex=1;pressed=2;stamp=2.
MR3A.sample_vision_health()
assert(#MR3A.visionInputEvents==2 and n.CurrentHp==5000)
assert(MR3A.visionEvalReceipts.jump==MR3A.visionInputEvents[1])
io.write(MR3A.encode_vision_evaluation({input_events=MR3A.visionInputEvents}))
''')
    events=json.loads(output[0])['input_events']
    assert events['1']['stageID']==50022 and events['1']['key']=='jump'
    assert events['2']['stageID']==50031 and events['2']['key']=='down'
