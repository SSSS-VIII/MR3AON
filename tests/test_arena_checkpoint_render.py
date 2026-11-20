"""Resolution requests must follow the same original selection coroutine."""
import json
from pathlib import Path
import shutil
import subprocess
import sys

import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools/arena_checkpoint_lab'))
from render import selection_command


@pytest.mark.parametrize('aspect,interval',[(True,1),(False,1),(True,2)])
def test_selection_reapplies_small_render_after_original_reset(tmp_path,aspect,interval):
    lua=shutil.which('luajit')
    if not lua:pytest.skip('LuaJIT unavailable')
    command=selection_command('return MR3A.native_select()')
    assert len(command.encode())<3800
    script=tmp_path/'render.lua'
    script.write_text('local COMMAND='+json.dumps(command)+'\nlocal valid='+str(aspect and interval==1).lower()+r'''
local sizes={};local gameTicks=0
local U={Screen={width=1920,height='''+str(1080 if aspect else 1200)+r'''},
 Rendering={OnDemandRendering={renderFrameInterval='''+str(interval)+r'''}}}
function U.Screen.SetResolution(w,h,full)
 assert(w==320 and h==180 and full)
 sizes[#sizes+1]={w,h};U.Screen.width=w;U.Screen.height=h
end
local thread
U.GameObject={Find=function()return {GetComponent=function()return {
 StartCoroutine=function(_,f)thread=coroutine.create(f);assert(coroutine.resume(thread))end}end}end}
U.EventSystems={EventTrigger={}}
CS={UnityEngine=U};typeof=function(v)return v end
coroutine.step=function()coroutine.yield()end
package.preload['common/util']=function()return {cs_generator=function(f)return f end}end
MR3A={native_select=function()MR3A.travel={done=false};return MR3A.travel end}
local result=assert(loadstring(COMMAND))()
assert(result==MR3A.travel and gameTicks==0)
local report=MR3A.checkpointSelectionRender
if valid then
 assert(#sizes==1)
 -- The original load reapplies its own resolution on a later frame.
 U.Screen.width=1920;U.Screen.height=1080
 assert(coroutine.resume(thread));assert(#sizes==2)
 MR3A.travel.done=true
 assert(coroutine.resume(thread));assert(report.done and not report.error)
else
 assert(#sizes==0 and report.error)
end
assert(gameTicks==0) -- Only the original caller advances the game.
io.write('ok')
''')
    assert subprocess.check_output([lua,str(script)],text=True)=='ok'
