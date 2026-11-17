"""Explicit stock-model part labels preserve independent pixel histories."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_obb_detector import decode
from arena_vision import Box,Detection,Tracker,serializable


def test_decoding_keeps_body_and_weapon_provenance_without_changing_geometry():
    common=dict(kind='hazard',shape='BoxCollider',motion_kind='trap',resource='EnemyPoleaxeWarrior')
    profile=dict(classes=[dict(common,source_part='body'),
                          dict(common,source_damage_callback='EnemyAttackModule')])
    quads=[((300,170),(400,170),(400,195),(300,195)),
           ((220,130),(255,130),(255,220),(220,220))]
    _,detections,_,_=decode(quads,[0,1],[.9,.8],profile)
    body,weapon=detections
    assert body.resource==weapon.resource=='EnemyPoleaxeWarrior'
    assert body.source_part=='body'and body.source_damage_callback is None
    assert weapon.source_part is None and weapon.source_damage_callback=='EnemyAttackModule'
    assert [d.quad for d in detections]==quads
    tracker=Tracker();tracks=tracker.update(detections,1.,(180,200))
    saved=serializable(dict(tracks=tracks))['tracks']
    assert saved[0]['source_part']=='body'
    assert saved[1]['source_damage_callback']=='EnemyAttackModule'
    assert tracks[1].at(.1).source_damage_callback=='EnemyAttackModule'


@pytest.mark.parametrize('part,callback',[
    ('body',None),(None,'EnemyAttackModule'),('attack_module','EnemyAttackModule')])
def test_nearby_other_parts_cannot_take_over_an_existing_unknown_body_track(part,callback):
    tracker=Tracker();box=Box(350,150,40,80)
    unknown=Detection(box,'trap',.9,resource='EnemyPoleaxeWarrior',collider_shape='BoxCollider')
    old=tracker.update([unknown],1.,(180,200))[0]
    explicit=Detection(Box(349,150,40,80),'trap',.9,resource='EnemyPoleaxeWarrior',
                       collider_shape='BoxCollider',source_part=part,source_damage_callback=callback)
    tracks=tracker.update([explicit],1.04,(180,200))
    fresh=next(t for t in tracks if t.seen==1.04)
    assert fresh.id!=old.id and fresh.observations==1
    # Repeated detections of the same proven part keep their own history.
    latest=next(t for t in tracker.update([explicit],1.08,(180,200))if t.seen==1.08)
    assert latest.id==fresh.id and latest.observations==2


def test_legacy_untyped_detections_keep_their_existing_association():
    tracker=Tracker()
    a=tracker.update([Detection(Box(350,150,40,80),'trap',.9)],1.,(180,200))[0]
    b=tracker.update([Detection(Box(345,150,40,80),'trap',.9)],1.04,(180,200))[0]
    assert a.id==b.id and b.observations==2
