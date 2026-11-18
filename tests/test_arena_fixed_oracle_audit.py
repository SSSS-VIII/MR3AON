from copy import deepcopy
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from arena_fixed_oracle_audit import plan,entry_comparison,delay_events


def route():
    state=lambda t,x:dict(episodeFrame=t,health=5000,physics='runOnLine: 1',position=dict(x=x,y=.75))
    a,b,c=state(10,0),state(12,.74),state(15,1.85)
    board=dict(map=42,stage_index=0,stage_id=50012,stage_start=0)
    return dict(complete=True,uses_restart_replay=False,start=dict(state=a,board=board),steps=[
        dict(before=a,after=b,ticks=2,action='none',relative_tick=0),
        dict(before=b,after=c,ticks=3,action='jump',relative_tick=2)])


def test_oracle_plan_preserves_source_ticks_and_rejects_invented_timing():
    r=route()
    assert plan(r)==dict(duration_ticks=5,events=[dict(relative_tick=2,action='jump')])
    bad=deepcopy(r);bad['steps'][1]['relative_tick']=3
    with pytest.raises(ValueError):plan(bad)
    bad=deepcopy(r);bad['steps'][1]['after']['health']=4750
    with pytest.raises(ValueError):plan(bad)


def test_entry_similarity_is_reported_without_claiming_identical_full_state():
    r=route();actual=deepcopy(r['start']['state']);actual['position']['x']=100.1
    actual['episodeFrame']=20
    board=dict(r['start']['board'],stage_start=100)
    result=entry_comparison(r,actual,board)
    assert result['context_equal']and result['physics_equal']
    assert result['local_x_error']==pytest.approx(.1)and result['episode_frame_delta']==10
    assert 'no claim'in result['scope']


def test_delay_experiment_preserves_source_timing_and_cannot_reorder_keys():
    original=dict(duration_ticks=10,events=[dict(relative_tick=3,action='jump'),dict(relative_tick=6,action='down')])
    changed=delay_events(original,{0:2})
    assert changed['events'][0]['relative_tick']==5 and changed['events'][0]['source_tick']==3
    assert original['events'][0]['relative_tick']==3
    with pytest.raises(ValueError):delay_events(original,{0:3})
    with pytest.raises(ValueError):delay_events(original,{2:1})


@pytest.mark.parametrize('stride',[1,2])
def test_lua_executor_records_actual_ticks_and_releases_original_inputs(tmp_path,stride):
    interpreter=shutil.which('luajit')
    if not interpreter:pytest.skip('LuaJIT unavailable')
    source=ROOT/'tools/arena_checkpoint_lab/oracle_route.lua'
    script='''
local tick,pressed,releases=0,{},0
local U={Time={timeScale=0,realtimeSinceStartup=0,captureFramerate=0},
    Vector3={zero={}},EventSystems={EventTrigger={}}}
typeof=function(v)return v end
local runner={}
local ninja={_GroundCollider={BelongToStageIndex=0}}
local level={}
function level:GetType()return self end
function level:GetField()return self end
function level:GetValue()return {_levelID=42}end
local ui={}
function ui:OnRightDown()pressed[#pressed+1]={'jump',tick}end
function ui:OnLeftDown()pressed[#pressed+1]={'down',tick}end
function ui:OnRightReleased()releases=releases+1 end
function ui:OnLeftReleased()releases=releases+1 end
function runner:StartCoroutine(co)self.co=co;assert(coroutine.resume(co))end
U.GameObject={Find=function()return {GetComponent=function()return runner end}end}
CS={UnityEngine=U,System={Reflection={BindingFlags={__CastFrom=function(x)return x end}}},
    LevelManager={Instance={GameLevelInfo=level}},NinjaController={Instance={NinjaScript=ninja}},
    UIContorller={Instance={GameOperate=ui}}}
MR3A={}
function MR3A.state()return {episodeFrame=tick,time=tick*.02,episodeTime=tick*.02,
    position={x=tick*.37,y=.75},physics='runOnLine: 1',health=5000,fixedDeltaTime=.02,frame=tick}end
function MR3A.vision_evaluation()return {health=5000,damage=0}end
package.preload['common/util']=function()return {cs_generator=coroutine.create}end
coroutine.step=coroutine.yield
assert(loadfile(SOURCE))()
MR3A.run_fixed_oracle({mode='continuous_ticks',capture_fps=0,duration_ticks=10,
    events={{relative_tick=3,action='jump'},{relative_tick=6,action='down'}}})
for i=1,20 do
    if MR3A.fixedOracleAudit.done then break end
    tick=tick+STRIDE;U.Time.realtimeSinceStartup=U.Time.realtimeSinceStartup+.02
    if tick>=10 then ninja._GroundCollider.BelongToStageIndex=1 end
    assert(coroutine.resume(runner.co))
end
local r=MR3A.fixedOracleAudit
assert(r.done and r.exit and not r.error and not MR3A.busy and U.Time.timeScale==0)
assert(#r.actions==2 and releases==2)
assert(r.actions[1].actual_tick==(STRIDE==1 and 3 or 4))
assert(r.actions[1].after_release.frame>r.actions[1].before.frame)
assert(r.actions[2].actual_tick==6)
'''
    script=script.replace('SOURCE',repr(str(source))).replace('STRIDE',str(stride))
    p=tmp_path/'executor.lua';p.write_text(script)
    subprocess.run([interpreter,str(p)],check=True,capture_output=True)
