import json
from pathlib import Path
import shutil
import subprocess
import pytest

ROOT = Path(__file__).resolve().parents[1]


def test_native_choice_keeps_full_map_and_separates_loop_pool(tmp_path):
    lua = shutil.which('luajit')
    if not lua:
        pytest.skip('LuaJIT unavailable')
    script = tmp_path / 'native.lua'
    script.write_text('local SOURCE=' + json.dumps(str(ROOT / 'arena/Local/native_selection.lua')) + r'''
local function list(values)
 local t={Count=#values};for i,v in ipairs(values)do t[i-1]=v end
 function t:RemoveAt(i)for k=i,self.Count-2 do self[k]=self[k+1]end;self[self.Count-1]=nil;self.Count=self.Count-1 end
 return t
end
local function group(ids)
 local a={};for _,id in ipairs(ids)do a[#a+1]={_stageID=id}end
 return setmetatable({_stageRandomList=list(a)},{__newindex=function()error('unknown field')end})
end
local catalog={mode=6,routes={{id=1,levels={{id=1,maps={7}}}}},
 levels={{id=1,maps={{id=7,chapter=1,level=1}}}},maps={['7']={absoluteLevel=1,
 opening={{group=1,pool={{id=90}}}},slots={
 {position=1,group=2,pool={{id=11},{id=12}}},
 {position=2,group=3,pool={{id=21},{id=22}}},
 {position=3,group=4,pool={{id=31},{id=32}}}},loop={{id=81},{id=82}}}}}
MR3A={nativePinHooks=true,role_defaults=function()end,reset=function()end}
CS={System={IO={File={ReadAllText=function()return '' end}},Reflection={BindingFlags={__CastFrom=function(v)return v end}}},
 UnityEngine={Application={persistentDataPath='/local'}},GameManager={Instance={GameInfo={GetRealCombatType=function()return 6 end}}}}
json={parse=function()return catalog end}
dofile(SOURCE)
local s=MR3A.validate_selection({level=1,map=7,start=2,pins={['2']=22,['4']=82}})
assert(s.chapter==1 and s.level==1 and s.absoluteLevel==1)
MR3A.nativeSelection=s
local groups=list({group({90}),group({11,12}),group({21,22}),group({31,32})})
local loop=group({81,82})
local calls=0
local controller={GetLoadStageStream=function(self,kind,g,l,changes)
 assert(g==groups and l==loop);calls=calls+1;return 'original-enumerator'
end}
assert(MR3A.native_pin_groups(controller,6,groups,loop,nil)=='original-enumerator')
assert(calls==1 and groups.Count==4) -- Earlier boards must NEVER be cropped.
assert(groups[0]._stageRandomList[0]._stageID==90)
assert(groups[1]._stageRandomList.Count==2 and groups[1]._stageRandomList[0]._stageID==11)
assert(groups[2]._stageRandomList.Count==1 and groups[2]._stageRandomList[0]._stageID==22)
assert(groups[3]._stageRandomList.Count==2)
assert(loop._stageRandomList.Count==1 and loop._stageRandomList[0]._stageID==82)
-- A future map may share its entry board, but must retain its own pools.
local other=list({group({90}),group({41,42}),group({51,52}),group({61,62})})
local original=controller.GetLoadStageStream
controller.GetLoadStageStream=function(self,kind,g,l,changes)
 assert(g==other and l==loop);return 'future-map-enumerator'
end
assert(MR3A.native_pin_groups(controller,6,other,loop,nil)=='future-map-enumerator')
assert(other[2]._stageRandomList.Count==2 and other[2]._stageRandomList[0]._stageID==51)
controller.GetLoadStageStream=original
for _,bad in ipairs({{level=1,map=8},{level=1,map=7,start=5},
 {level=1,map=7,pins={['1']=22}},{level=1,map=7,pins={['4']=11}}})do
 assert(not pcall(MR3A.validate_selection,bad))
end
local removed={}
CS.GameBuffManager={Instance={RemoveBuff=function(self,n,id)removed[#removed+1]=id end}}
MR3A.remove_carrier_buffs({}, {['100']={id=100,fromRole=true}}, {
 ['100']={id=100,fromRole=true},['200']={id=200,fromRole=true},['300']={id=300,fromRole=false}})
assert(#removed==1 and removed[1]==200) -- Preserve existing role and new scene/trap buffs.
io.write('ok')
''')
    assert subprocess.check_output([lua, str(script)], text=True) == 'ok'
