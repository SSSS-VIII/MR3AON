import hashlib
import json
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
import arena_yolo_detector as factory


def test_reviewed_checkpoint_hash_is_checked_before_selecting_obb_backend(tmp_path,monkeypatch):
    weights=tmp_path/'weights'/'best.pt';weights.parent.mkdir();weights.write_bytes(b'changed')
    (tmp_path/'profile.json').write_text(json.dumps(dict(task='obb')))
    monkeypatch.setattr(factory,'DEFAULT_WEIGHTS',weights)
    monkeypatch.setattr(factory,'PROFILE',dict(sha256=hashlib.sha256(b'approved').hexdigest()))
    with pytest.raises(ValueError,match='checkpoint'):factory.make_perception(weights)


def test_reviewed_obb_metadata_cannot_change_even_when_the_weight_file_matches(tmp_path,monkeypatch):
    weights=tmp_path/'weights'/'best.pt';weights.parent.mkdir();weights.write_bytes(b'approved')
    (tmp_path/'profile.json').write_text(json.dumps(dict(task='obb')))
    monkeypatch.setattr(factory,'DEFAULT_WEIGHTS',weights)
    monkeypatch.setattr(factory,'PROFILE',dict(sha256=hashlib.sha256(b'approved').hexdigest(),profile_sha256='wrong'))
    with pytest.raises(ValueError,match='geometry metadata'):factory.make_perception(weights)


def test_local_phase_classifier_has_its_own_checkpoint_and_metadata_guard(tmp_path,monkeypatch):
    weights=tmp_path/'weights'/'best.pt';weights.parent.mkdir();weights.write_bytes(b'approved')
    profile=tmp_path/'profile.json';profile.write_text(json.dumps(dict(task='obb')))
    roi=tmp_path/'roi'/'weights'/'best.pt';roi.parent.mkdir(parents=True);roi.write_bytes(b'changed')
    (tmp_path/'roi'/'profile.json').write_text('{}')
    monkeypatch.setattr(factory,'DEFAULT_WEIGHTS',weights)
    monkeypatch.setattr(factory,'PROFILE',dict(sha256=hashlib.sha256(b'approved').hexdigest(),
        bamboo_phase=dict(weights=str(roi),sha256='wrong',profile_sha256='wrong',threshold=.8)))
    with pytest.raises(ValueError,match='Bamboo phase checkpoint'):factory.make_perception(weights)
