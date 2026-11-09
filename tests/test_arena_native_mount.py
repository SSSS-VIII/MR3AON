"""Mount pickup owns one native item-type reference and never changes role speed."""
import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_native_mount_speed_and_pickup_reference_lifecycle(tmp_path):
    lua = shutil.which('luajit')
    if not lua:
        pytest.skip('LuaJIT unavailable')
    script = tmp_path / 'mount.lua'
    script.write_text('local SOURCE=' + json.dumps(str(ROOT / 'arena/Local/native_mount.lua')) + r'''
MR3A={mountTrainingObserver=true}
CS={UnityEngine={}}
dofile(SOURCE)
local function manager(existing)
 local m={refs=existing,adds=0,removes=0}
 function m:AddAttractItemType(kind)assert(kind==13);self.refs=self.refs+1;self.adds=self.adds+1 end
 function m:RemoveAttractItemType(kind)assert(kind==13 and self.refs>0);self.refs=self.refs-1;self.removes=self.removes+1 end
 return m
end
local a,b=manager(2),manager(0)
local function ninja()return setmetatable({},{__newindex=function()error('Role properties must stay unchanged')end})end
local n1,n2=ninja(),ninja()
local mount={_rushSpeed=30}
MR3A.update_mount_training(true,n1,mount,a)
assert(mount._rushSpeed==120 and a.refs==3 and a.adds==1)
for i=1,20 do MR3A.update_mount_training(true,n1,mount,a)end
assert(a.refs==3 and a.adds==1) -- Repeated rendered frames must not stack references.
MR3A.update_mount_training(false,n1,mount,a)
assert(a.refs==2 and a.removes==1) -- Preserve a pre-existing original ability.
MR3A.clear_mount_training();assert(a.refs==2 and a.removes==1)
MR3A.update_mount_training(true,n1,mount,a)
MR3A.update_mount_training(true,n2,mount,b)
assert(a.refs==2 and b.refs==1 and b.adds==1)
MR3A.clear_mount_training();assert(b.refs==0)
assert(MR3A.mountTraining.manager==nil and MR3A.mountTraining.ninja==nil)
io.write('ok')
''')
    assert subprocess.check_output([lua, str(script)], text=True) == 'ok'
