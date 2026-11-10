"""Catch an accidental 12 -> 4 px support migration before GPU training."""
import json,sys
from pathlib import Path
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_yolo_finetune import validate_transfer


def profiles(tmp_path,old_band,new_band):
    old=tmp_path/'old';new=tmp_path/'new';(old/'weights').mkdir(parents=True);new.mkdir()
    classes=[dict(name='platform',kind='platform')]
    for folder,band in [(old,old_band),(new,new_band)]:
        (folder/'profile.json').write_text(json.dumps(dict(task='obb',classes=classes,native_targets=dict(support_band_px=band))))
    return old/'weights/best.pt',new/'data.yaml'


def test_existing_support_width_cannot_silently_fall_back_to_builder_default(tmp_path):
    weights,data=profiles(tmp_path,12,4)
    with pytest.raises(ValueError,match='12 to 4'):
        validate_transfer(weights,data)


def test_appending_an_arrow_head_preserves_existing_support_representation(tmp_path):
    weights,data=profiles(tmp_path,12,12);p=data.parent/'profile.json';profile=json.loads(p.read_text())
    profile['classes'].append(dict(name='arrow',kind='hazard',supervision_band_px=8))
    p.write_text(json.dumps(profile));result=validate_transfer(weights,data)
    assert result['support_band_px']==12 and result['shared_supports']==['platform']
    assert len(result['profiles'])==2


def test_standard_base_without_native_profile_does_not_claim_inheritance(tmp_path):
    weights,data=profiles(tmp_path,12,12);(weights.parent.parent/'profile.json').unlink()
    assert validate_transfer(weights,data)is None
