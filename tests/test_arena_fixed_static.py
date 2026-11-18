from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_fixed_static import expand,resolved_anchors,enemy_categories


def stage():
    return dict(_levelDataType=6,_stageID=1,_levelBlockInfos=[[
        dict(_pointStart=dict(x=100),_pointEnd=dict(x=132),_repeatTimesMin=2,_repeatTimesMax=2,
             enemyInfos=[dict(_enemyType=218,_localPosition=dict(x=4))])],[
        dict(_pointStart=dict(x=131.8),_pointEnd=dict(x=163.8),
             enemyInfos=[dict(_enemyType=103,_localPosition=dict(x=2))])]])


def test_repeat_expansion_retains_original_overlap_and_shifts_following_groups():
    value=expand(stage())
    assert value['finite']and value['length']==pytest.approx(95.8)
    assert [b['start_x']for b in value['blocks']]==pytest.approx([0,32,63.8])
    assert [b['source_group']for b in value['blocks']]==[0,0,1]
    assert resolved_anchors(value,{218:1,103:2})==[[1,4],[1,36],[2,65.8]]


def test_random_and_infinite_data_cannot_be_passed_off_as_a_finite_layout():
    data=stage();data['_levelBlockInfos'][0][0]['_infiniteLoop']=True
    assert expand(data)['length']is None
    data=stage();data['_levelBlockInfos'][0][0]['_repeatTimesMax']=3
    with pytest.raises(ValueError,match='fixed Gale'):expand(data)


def test_static_anchor_classes_come_from_original_config_and_exclude_moving_muppets():
    rows=[dict(values=[dict(ID=identity,resourceName=name,editInfoScriptName=script)])
          for identity,name,script in [(218,'EnemySpiderFire','EnemyInfoSpider'),
              (200,'EnemyMuppetBomb','EnemyInfoSpider'),(103,'EnemyHideBlade','EnemyInfoHideBlade'),
              (6037,'EnemySpiderBT','EnemyInfoBT')]]
    assert enemy_categories(rows)=={218:1,103:2}
