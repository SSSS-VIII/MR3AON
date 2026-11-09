import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_coverage_revisit import select
from arena_collect_coverage import jobs_for


def test_revisit_uses_actual_generated_index_and_preserves_original_training_seed():
    profile=dict(families={'Banana':{}},type_bindings={'280':'Banana'})
    setup=dict(seed=21003,level=3,map=22,start=2,board=30024,sample_block=1)
    blocks=[dict(index=i,start_x=i*100,finish_x=(i+1)*100,enemies=[])for i in range(4)]
    blocks[3]['enemies']=[dict(source_type_id=280)]
    p=select(profile,{},[(Path('training'),setup,dict(stage_id=30024,blocks=blocks))])
    assert p['selected'][0]['spec']['sample_block']==3
    assert jobs_for(p,['train'],23000)[0]['seed']==21003
    with pytest.raises(ValueError,match='training split'):jobs_for(p,['train','val'],23000)
    assert not select(profile,{'Banana':5},[(Path('training'),setup,dict(stage_id=30024,blocks=blocks))])['selected']


def test_zero_width_target_uses_preceding_block_and_never_claims_unplanned_resource_complete():
    profile=dict(families={'A':{},'B':{}},type_bindings={'1':'A','2':'B'})
    setup=dict(seed=1,level=1,map=1,start=1,board=10,sample_block=0)
    blocks=[dict(start_x=0,finish_x=100,enemies=[]),dict(start_x=100,finish_x=200,enemies=[]),
            dict(start_x=200,finish_x=200,enemies=[dict(source_type_id=1)])]
    p=select(profile,{},[(Path('training'),setup,dict(stage_id=10,blocks=blocks))])
    assert p['selected'][0]['spec']['sample_block']==1 and p['not_planned']==['B']
    assert p['selected'][0]['native_target_blocks']==[2]
