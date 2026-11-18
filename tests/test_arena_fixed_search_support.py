"""Protect full Gale inventory, true exits and speculative capture isolation."""
import importlib.util
import json
from pathlib import Path
import shutil
import subprocess
import sys
from copy import deepcopy
import pytest

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'tools'))
from arena_fixed_catalog import inventory
from arena_fixed_goal import exit_kind

spec=importlib.util.spec_from_file_location('route_collector',ROOT/'tools/arena_checkpoint_lab/collector.py')
collector=importlib.util.module_from_spec(spec);spec.loader.exec_module(collector)


def test_native_exits_distinguish_board_map_and_new_loop_instance():
    before=dict(map=42,stage_index=1,stage_count=3)
    assert exit_kind(before,dict(map=42,stage_index=2))=='stage_advance'
    assert exit_kind(before,dict(map=43,stage_index=0))is None
    assert exit_kind(dict(before,stage_index=2),dict(map=43,stage_index=0))=='map_advance'
    loop=dict(map=71,stage_index=1,stage_count=1,loop=True,instance=100,stage_start=50)
    assert exit_kind(loop,dict(loop,instance=101,stage_start=114))=='loop_advance'
    assert exit_kind(loop,dict(loop,stage_start=114))is None
    assert exit_kind(loop,dict(loop,instance=101))is None


def test_inventory_includes_fixed_loop_and_keeps_aliases_and_random_out(tmp_path):
    for stage in (11,12,13):
        (tmp_path/f'stage_endless_gale_{stage}.json').write_text(json.dumps(dict(
            _stageID=stage,_levelDataType=6,_levelBlockInfos=[[dict(_pointStart=dict(x=0,y=0),
                _pointEnd=dict(x=32,y=0),_groundType=0,_repeatTimesMin=3,_repeatTimesMax=3)]])))
    fixed=lambda i:dict(id=i,classification=dict(layout='fixed',motion='unspecified'))
    random=dict(id=12,classification=dict(layout='random',motion='unspecified'))
    world=dict(id=1,slots=[dict(position=1,pool=[fixed(11),random])],loop=[fixed(13)])
    raw=dict(mode=6,levels=[dict(id=8,maps=[dict(id=1,chapter=1,level=8)])],
             maps={'1':world,'2':dict(world,id=2,menuMap=1)})
    result=inventory(raw,tmp_path)
    assert result['counts']==dict(unique_fixed=2,contexts=2)
    assert [c['stage']for c in result['contexts']]==[11,13]
    assert result['contexts'][-1]['loop']
    assert result['stages']['11']['groups'][0]['repeats'][0]['min']==3
    assert result['contexts'][-1]['selection']['start']==2


def test_lua_source_transport_round_trips_unicode_quotes_and_long_inputs(tmp_path):
    interpreter=shutil.which('luajit')
    if not interpreter:pytest.skip('LuaJIT unavailable')
    class Gate:
        def __init__(self):self.commands=[]
        def call(self,op,code):
            assert len(json.dumps(dict(op=op,code=code)).encode())<4096
            self.commands.append(code)
    gate=Gate();value='中英混合\\路径\n"quote"'*1500
    source='MR3A.roundtrip='+json.dumps(value,ensure_ascii=False)
    collector.install_lua(gate,source)
    script='MR3A={};local load=loadstring\n'+'\n'.join(
        'assert(loadstring('+json.dumps(c,ensure_ascii=False)+'))()'for c in gate.commands)
    script+='\nassert(MR3A.roundtrip=='+json.dumps(value,ensure_ascii=False)+')\n'
    path=tmp_path/'transport.lua';path.write_text(script)
    subprocess.run([interpreter,str(path)],check=True,capture_output=True)


def test_reference_capture_restores_selected_branch_even_if_annotation_fails(tmp_path,monkeypatch):
    class Gate:
        def __init__(self):self.current=1;self.hidden=0;self.points={1:0,2:5}
        def restore(self,p):self.current=p;self.hidden=self.points[p]
        def screenshot(self):self.hidden=999;return b'png'
        def call(self,op,**args):
            if op=='state':return dict(episodeFrame=10,position=dict(x=1))
            if 'vision_resolved_layout' in args['code']:raise RuntimeError('missing label')
            return dict(map=42,stage_index=0)
    sys.path.insert(0,str(ROOT/'tools/arena_checkpoint_lab'))
    gate=Gate();refs=collector.References(tmp_path/'references')
    refs.start=dict(board=dict(map=42,stage_index=0))
    refs.window(gate,[dict(point=1,action='jump',job=dict(after=dict(episodeFrame=10))),
                      dict(point=2,action='none',job=dict(after=dict(episodeFrame=12)))],0)
    assert gate.current==2 and gate.hidden==5
    assert refs.errors and not refs.rows


def test_abandoned_reference_images_do_not_overwrite_or_publish_as_accepted(tmp_path):
    refs=collector.References(tmp_path/'references')
    class Gate:
        def restore(self,p):self.point=p
        def screenshot(self):return b'png'+str(self.point).encode()
        def call(self,op,**args):
            if op=='state':return dict(episodeFrame=self.point,position=dict(x=1))
            if 'vision_resolved_layout' in args['code']:return {}
            return dict(map=42,stage_index=0,stage_start=0)
    gate=Gate();context=dict(map=42,stage_index=0)
    refs.capture(gate,1,context)
    refs.capture(gate,2,context)
    rejected=(refs.folder/'00001.png').read_bytes()
    refs.rewind(1)
    refs.capture(gate,3,context)
    assert [r['tick']for r in refs.rows]==[1,3]
    assert [r['tick']for r in refs.abandoned]==[2]
    assert (refs.folder/'00001.png').read_bytes()==rejected
    assert refs.rows[-1]['image']=='00002.png'
