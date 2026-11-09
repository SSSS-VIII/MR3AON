import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_collect_coverage import audit_rows,jobs_for,summarize


def test_native_family_counts_preserve_compound_parts_without_pool_reference_claims():
    def obj(i,source,visible=True):
        return dict(id=i,source_type_id=source,family_type_id=238,name='child',
                    resource_family='EnemyRotateElectricBall(Clone)',renderers=[{}]if visible else [],
                    colliders=[dict(owner_id=i,type='SphereCollider',box=[100,150,120,170])])
    result=audit_rows([dict(label_schema=3,physics='runOnLine: 1',health=5000,t=0,
                           objects=[obj(1,238),obj(2,0),obj(3,257,False)],supports=[dict(kind='rope')])])
    assert result['visible_target_frame_counts_by_family_type']=={'238':2}
    assert result['spawned_object_frame_counts_by_source_type']=={'238':1,'0':1,'257':1}
    assert result['visible_collider_frame_counts_by_shape']=={'SphereCollider':2}
    assert result['visible_target_frame_counts_by_resource_family']=={'EnemyRotateElectricBall':2}


def test_invalid_ownership_and_legacy_labels_cannot_enter_coverage():
    with pytest.raises(ValueError,match='schema 3'):audit_rows([dict(label_schema=2)])
    with pytest.raises(ValueError,match='another native enemy'):
        audit_rows([dict(label_schema=3,physics='fall',health=5000,
                        objects=[dict(id=1,colliders=[dict(owner_id=2)])])])


def test_whole_episode_seeds_are_disjoint_between_splits_and_resume_order_is_stable():
    plan=dict(mode=6,selected=[dict(spec=dict(board=b),resources=['A'],enemy_types=[1])for b in(10,20)])
    jobs=jobs_for(plan,['train','val','test'],100)
    assert len({j['seed']for j in jobs})==6
    assert [j for j in jobs if j['split']=='train']==jobs_for(plan,['train'],100)
    with pytest.raises(ValueError):jobs_for(plan,['train','train'],100)


def test_summary_does_not_turn_requested_types_or_a_short_death_into_coverage():
    coverage=dict(frames=11,final_health=0,seconds=.6,visible_target_frame_counts_by_family_type={'226':5},
                  visible_target_frame_counts_by_resource_family={'EnemyDart2Fire':5})
    state=dict(configuration=dict(seconds=10,splits=['train','val','test']),
               jobs={'one':dict(status='complete',split='train',expected_types=[226,238],
                                attempts=[dict(status='complete',coverage=coverage)])})
    plan=dict(selected=[{}],reachable_enemy_types=[226,238])
    report=summarize(state,plan)
    assert report['completed_jobs']==1 and report['planned_jobs']==3
    assert report['unobserved_native_types']==[238]
    assert report['death_episodes']==report['short_episodes']==['one']
