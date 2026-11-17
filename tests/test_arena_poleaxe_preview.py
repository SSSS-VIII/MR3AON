"""Keep offline source rendering isolated even when bridge/readback fails."""
from contextlib import contextmanager
from copy import deepcopy
import subprocess
import numpy as np
import pytest
from arena_poleaxe_preview import OriginalPoleaxePreview,composite_pair


class Session:
    def __init__(self):self.held=False;self.removed=[];self.read_error=False
    @contextmanager
    def control(self):
        self.held=True
        try:yield self
        finally:self.held=False
    def adb(self,*args):
        assert self.held
        if args[:2]==('exec-out','cat'):
            if self.read_error:raise OSError('readback disconnected')
            return subprocess.CompletedProcess(args,0,b'\x89PNG\r\n\x1a\n')
        assert args[:3]==('shell','rm','-f');self.removed.extend(args[3:])
        return subprocess.CompletedProcess(args,0,b'')


class Client:
    def __init__(self,session):
        self.session=session;self.active=False;self.end_count=0;self.begin_error=False;self.changed=False;self.snapshots=0
    def execute(self,code,*,lease_held):
        assert lease_held and self.session.held
        if code.startswith('return {state='):
            self.snapshots+=1
            return deepcopy(dict(state=dict(health=4999 if self.changed and self.snapshots>1 else 5000,
                episodeFrame=51,mode=6,timeScale=0,position=dict(x=1,y=2),physics='runOnLine: 1'),enemies=0))
        if code.startswith('assert(load('):return True
        if code.startswith('return MR3A.poleaxe_preview_begin('):
            if self.begin_error:raise RuntimeError('missing original asset')
            self.active=True;return dict(animations=[dict(name='attack_up',duration=1)])
        if code=='return MR3A.poleaxe_preview_end()':self.end_count+=1;self.active=False;return True
        if code.startswith('return MR3A.poleaxe_preview_background('):return True
        if code.startswith('return MR3A.poleaxe_preview_render('):return dict(name='attack_up')
        raise AssertionError(code)


def test_readback_failure_cleans_clone_files_and_lease():
    session=Session();session.read_error=True;client=Client(session);preview=OriginalPoleaxePreview(session,client)
    with pytest.raises(OSError,match='readback disconnected'):
        with preview:preview.render('attack_up',.4)
    assert not session.held and not client.active
    assert client.end_count==1 and client.snapshots==2 and len(session.removed)==1
    assert preview.before==preview.after
    preview.close();assert client.end_count==1


def test_begin_failure_still_cleans_partial_native_preview():
    session=Session();client=Client(session);client.begin_error=True
    with pytest.raises(RuntimeError,match='missing original asset'):
        with OriginalPoleaxePreview(session,client):pytest.fail('begin should fail')
    assert not session.held and not client.active and client.end_count==1 and client.snapshots==2


def test_state_mismatch_is_reported_and_lease_released():
    session=Session();client=Client(session);client.changed=True
    with pytest.raises(RuntimeError,match='changed original battle state'):
        with OriginalPoleaxePreview(session,client):pass
    assert not session.held and not client.active


def test_acquiring_lease_failure_does_not_touch_device():
    class Busy(Session):
        @contextmanager
        def control(self):
            raise RuntimeError('arena busy')
            yield
    session=Busy();client=Client(session)
    with pytest.raises(RuntimeError,match='arena busy'):
        with OriginalPoleaxePreview(session,client):pytest.fail('lease should fail')
    assert client.snapshots==0 and client.end_count==0


def test_mismatched_pose_pair_is_rejected():
    with pytest.raises(ValueError,match='poses differ'):
        composite_pair(np.full((2,2,3),200,np.uint8),np.zeros((2,2,3),np.uint8),np.zeros(3,np.uint8))


def test_composite_matches_independent_original_colored_renders():
    import json
    from pathlib import Path
    fixture=json.loads((Path(__file__).parent/'fixtures/arena-poleaxe-preview-composite.json').read_text())
    errors=[]
    for row in fixture['rows']:
        black=np.asarray([[s['black']for s in row['samples']]],np.uint8)
        white=np.asarray([[s['white']for s in row['samples']]],np.uint8)
        actual=np.asarray([[s['actual']for s in row['samples']]],np.int16)
        predicted=composite_pair(black,white,np.asarray(row['background'],np.uint8))
        errors.extend(np.abs(predicted.astype(np.int16)-actual).ravel().tolist())
    # Original render/readback quantization is measured independently; this
    # checks actual colored pixels, not reconstruction of the two inputs.
    assert max(errors)<=6
    assert np.mean(errors)<.25
