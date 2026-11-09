import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision_coverage import build_plan


def test_coverage_plan_selects_real_loop_position_and_does_not_claim_missing_assets():
    catalog=dict(mode=6,levels=[dict(id=2,maps=[dict(id=11)])],
                 maps={'11':dict(slots=[dict(pool=[dict(id=100)])],loop=[dict(id=101)])})
    entities=[dict(kind='enemies',type_id=i,resource_name=name,config={}if i!=4 else None)
              for i,name in[(1,'A'),(2,'B'),(3,'C'),(4,None)]]
    placements=[dict(kind='enemies',stage=stage,type_id=i)
                for stage,i in[(100,1),(100,2),(101,2),(101,3),(101,4)]]
    result=build_plan(catalog,entities,placements,{'A':120,'B':13})
    assert len(result['selected'])==1
    assert result['selected'][0]['spec']==dict(level=2,map=11,start=2,board=101)
    assert result['selected'][0]['new_resources']==['B','C']
    assert result['missing_current_config']==[4]and not result['not_planned']
    assert result['target_resources']==['B','C']


def test_normal_mode_cannot_be_mixed_into_gale_training_plan():
    with pytest.raises(ValueError,match='Gale'):
        build_plan(dict(mode=1),[],[],{})
