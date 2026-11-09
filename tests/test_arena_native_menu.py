"""Interactive starts resume exactly once; API episodes remain paused."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_menu_start_resumes_only_its_completed_successful_job(tmp_path):
    lua = shutil.which('luajit')
    if not lua:
        pytest.skip('LuaJIT unavailable')
    script = tmp_path / 'menu.lua'
    script.write_text('local SOURCE=' + json.dumps(str(ROOT / 'arena/Local/native_menu.lua')) + r'''
local resumes=0
local active=true
CS={UnityEngine={UI={},Color=function(...)return {...}end}}
MR3A={menuObserver=true,menu={absoluteLevel=7,map=61,seed=42,pins={['1']=7001},
 root={gameObject={SetActive=function(self,v)active=v end}}},
 resume=function()resumes=resumes+1 end}
function MR3A.native_select(spec,seed)
 assert(spec.level==7 and spec.map==61 and spec.start==1 and spec.pins['1']==7001 and seed==42)
 MR3A.travel={done=false}
end
dofile(SOURCE)
MR3A.menu_start(1)
assert(MR3A.finish_menu_start()==nil and resumes==0 and active)
local pending=MR3A.menu.pendingStart
MR3A.busy=true
assert(MR3A.menu_start(1)==false and MR3A.menu.pendingStart==pending)
MR3A.busy=false
MR3A.travel.done=true
assert(MR3A.finish_menu_start()==true and resumes==1 and not active)
assert(MR3A.finish_menu_start()==nil and resumes==1)
-- A failed reset must stay paused and return control to the menu.
active=true
MR3A.menu_start(1)
MR3A.travel.done=true;MR3A.travel.error='Reset did not enter the battle'
assert(MR3A.finish_menu_start()==false and resumes==1 and active)
assert(MR3A.menu.error and not string.find(MR3A.menu.error,'Reset'))
-- API-created jobs have no pending interactive start and must NOT resume.
MR3A.travel={done=true}
assert(MR3A.finish_menu_start()==nil and resumes==1 and active)
MR3A.menu.pendingStart={done=true}
assert(MR3A.finish_menu_start()==nil and resumes==1 and MR3A.menu.pendingStart==nil)
io.write('ok')
''')
    assert subprocess.check_output([lua, str(script)], text=True) == 'ok'
