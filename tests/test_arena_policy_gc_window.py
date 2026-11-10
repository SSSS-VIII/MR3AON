"""Real-time decisions defer cycle tracing, then reclaim after native pause."""
import gc
import sys
import weakref
from pathlib import Path
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_visual_runner import PausedCollections


def test_unreachable_cycles_are_reclaimed_after_the_control_window():
    class Cycle:pass
    original=gc.isenabled()
    try:
        gc.enable()
        with PausedCollections()as window:
            assert not gc.isenabled()
            obj=Cycle();obj.self=obj;ref=weakref.ref(obj);del obj
            assert ref()is not None
        assert gc.isenabled()and ref()is None and window.collected>=1
    finally:
        if not original:gc.disable()


def test_exception_restores_the_preexisting_collector_state():
    original=gc.isenabled()
    try:
        gc.enable()
        with pytest.raises(ValueError):
            with PausedCollections():raise ValueError('controller interrupted')
        assert gc.isenabled()
        gc.disable()
        with PausedCollections():assert not gc.isenabled()
        assert not gc.isenabled()
    finally:
        if original:gc.enable()
