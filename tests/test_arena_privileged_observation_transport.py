"""Exercise packed observations through the actual native gate encoder in Lua."""
from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools/arena_checkpoint_lab'))
from privileged_search import observe,compare_observation_transport


def lua_value(v):
    if v is None:return 'nil'
    if isinstance(v,bool):return 'true'if v else 'false'
    if isinstance(v,(int,float)):return repr(v)
    if isinstance(v,str):return '"'+''.join('\\%03d'%ord(c)if ord(c)<32 else '\\'+c if c in ('"','\\')else c for c in v)+'"'
    pairs=enumerate(v,1)if isinstance(v,list)else v.items()
    return '{'+','.join('['+lua_value(k)+']='+lua_value(x)for k,x in pairs)+'}'


class LuaGate:
    def __init__(self,tmp_path,native):
        lua=shutil.which('luajit')
        if not lua:pytest.skip('LuaJIT unavailable')
        source=(ROOT/'tools/arena_checkpoint_lab/game_gate.lua').read_text()
        encoder=source[source.index('local function encode('):source.index('local function exchange(')]
        # The real gate calls json.stringify only for strings. This test
        # supplies that primitive; table/number encoding is the native code.
        primitive=r'''json={stringify=function(s)
            return '"'..s:gsub('[%z\1-\31\\"]',function(c)
                if c=='"'or c=='\\'then return '\\'..c end
                return string.format('\\u%04x',string.byte(c))
            end)..'"' end}
        '''
        harness=tmp_path/'gate.lua'
        harness.write_text(primitive+encoder+'\nlocal OBS='+lua_value(native)+r'''
            MR3A={privileged_state=function()return OBS end}
            for line in io.lines()do
                local request=assert(loadstring('return '..line))()
                local ok,result=pcall(assert(loadstring(request)))
                local payload=encode({ok=ok,result=result,state=OBS.state}, {},0)
                io.write(payload..'\n');io.flush()
            end
        ''')
        self.process=subprocess.Popen([lua,str(harness)],stdin=subprocess.PIPE,stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,text=True)
        self.view={};self.calls=0;self.payloads=[]

    def call(self,operation,**kw):
        assert operation=='exec'
        assert len(json.dumps(dict(op=operation,**kw)).encode())<4096
        self.calls+=1;self.process.stdin.write(lua_value(kw['code'])+'\n');self.process.stdin.flush()
        text=self.process.stdout.readline();assert text,self.process.stderr.read()
        self.payloads.append(len(text.encode()))
        assert len(text.encode())<262144
        value=json.loads(text);assert value['ok'],value.get('result')
        self.view['state']=value['state']
        return value['result']

    def close(self):
        self.process.stdin.close();self.process.wait(timeout=5)
        assert self.process.returncode==0,self.process.stderr.read()


@pytest.mark.parametrize('copies',[1,80])
def test_native_numbers_and_all_dense_records_survive_complete_or_packed_reads(tmp_path,copies):
    native=json.loads((ROOT/'tests/fixtures/arena-privileged-small-sword.json').read_text())['cases'][0]['before']
    enemy=native['enemies'][0]
    native['enemies']=[dict(deepcopy(enemy),id=i+1)for i in range(copies)]
    native['pending_enemies']=[dict(id=i,info=dict(_localPosition=dict(x=17.25,y=4.5,z=0)),source='native_enemyList')for i in range(copies*3)]
    native['pending_items']=[dict(id=i,info=dict(_itemType='ItemSpring: 15'),source='native_itemList')for i in range(copies)]
    native['note']='中文字段与引号 "、反斜线 \\、换行\n及制表\t'
    gate=LuaGate(tmp_path,native)
    try:
        result=observe(gate)
        expected=deepcopy(native)
        for key in ('enemies','mechanism_items','supports','platforms','terrain'):
            if expected.get(key)=={}:expected[key]=[]
        assert result==expected
        assert gate.observation_transport['calls']==gate.calls
        if copies==1:
            assert gate.calls==1 and gate.observation_transport['mode']=='complete'
        else:
            assert gate.observation_transport['mode']=='packed_pages'
            assert gate.calls<copies//2
        assert gate.call('exec',code='return MR3A.privilegedCached==nil and MR3A.privilegedSize==nil')
        comparison=compare_observation_transport(gate,result)
        assert comparison['equal']and comparison['packed']['calls']<comparison['reference']['calls']
    finally:gate.close()


def test_packing_still_rejects_a_changed_native_state(tmp_path):
    native=dict(state=dict(time=1.2345678901234567),enemies=[],mechanism_items=[],supports=[],platforms=[],terrain=[])
    class ChangedGate(LuaGate):
        def call(self,*a,**kw):
            out=super().call(*a,**kw);self.view['state']['time']+=1
            return out
    gate=ChangedGate(tmp_path,native)
    try:
        with pytest.raises(RuntimeError,match='native state changed'):observe(gate)
    finally:gate.close()


def test_one_oversize_record_is_rejected_instead_of_silently_truncated(tmp_path):
    native=dict(state=dict(time=1.),enemies=[dict(payload='x'*220000)],mechanism_items=[],supports=[],platforms=[],terrain=[])
    gate=LuaGate(tmp_path,native)
    try:
        with pytest.raises(AssertionError,match='Single observation record exceeds'):observe(gate)
    finally:gate.close()
