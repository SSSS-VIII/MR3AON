import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_boss_health_changes_only_offline_gale_boss_through_original_setters(tmp_path):
    lua = shutil.which('luajit')
    if not lua:
        pytest.skip('LuaJIT unavailable')
    script = tmp_path / 'boss.lua'
    script.write_text('local SOURCE=' + json.dumps(str(ROOT / 'arena/Local/native_boss.lua')) + r'''
MR3A={nativeBossHook=true}
local mode=6
local g={OfflineGame=true,GetRealCombatType=function()return mode end}
CS={GameManager={Instance={_isOnlyGame=true,GameInfo=g}},CfgBonusType={__CastFrom=function(v)return v end}}
dofile(SOURCE)
local calls={}
local b={CurrentHp=50000}
function b:InitBonus(kind,base,add,mul)assert(kind==3 and base==1 and add==0 and mul==0);calls[#calls+1]='bonus'end
function b:InitStageHp()calls[#calls+1]='phase'end
function b:SetHealth(value)assert(value==1);calls[#calls+1]='health'end
MR3A.training_boss_health(b);assert(table.concat(calls,',')=='bonus,phase,health')
calls={};mode=3;MR3A.training_boss_health(b);assert(#calls==0)
mode=6;b.CurrentHp=0;MR3A.training_boss_health(b);assert(#calls==0)
io.write('ok')
''')
    assert subprocess.check_output([lua, str(script)], text=True) == 'ok'
