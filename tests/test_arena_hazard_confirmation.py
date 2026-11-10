"""Repeated strong evidence survives a short weak exposure, not indefinitely."""
import sys
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,Detection,Tracker
from arena_policy import VisualAvoider


def visible(confidences):
    tracker=Tracker(adaptive=True)
    for i,c in enumerate(confidences):
        stamp=i*.025
        tracks=tracker.update([Detection(Box(500-500*stamp,220,70,10),'trap',c)],stamp,(0,0))
    return dict(player=Box(172,210,16,37),time=stamp,tracks=tracks)


def test_recently_confirmed_hazard_remains_in_collision_planning_on_one_weak_frame():
    obs=visible([.9]*7+[.55]);assert obs['tracks'][0].confidence==.55
    assert len(VisualAvoider()._objects(obs))==1
    obs['time']+=.4
    assert VisualAvoider()._objects(obs)==[]


def test_consistently_weak_and_persistently_fading_tracks_are_not_promoted():
    assert VisualAvoider()._objects(visible([.55]*12))==[]
    assert VisualAvoider()._objects(visible([.9]*7+[.55]*6))==[]
