"""Render original poleaxe poses in a paused, isolated preview camera.

This offline asset tool never advances game physics or supplies state to actors.
"""
from contextlib import ExitStack
import argparse
import hashlib
import json
import math
from pathlib import Path
import uuid
import numpy as np
from arena_local import LocalClient, ROOT, FOLDER
from arena_projection import SCALE

SOURCE=ROOT/'arena/Local/poleaxe_preview.lua'
PAUSED_FIELDS=('health','episodeFrame','mode','timeScale','position','physics')


def unchanged_battle(before,after):
    return (all(before['state'][key]==after['state'][key]for key in PAUSED_FIELDS)
            and before['enemies']==after['enemies'])


def composite_pair(black,white,background):
    """Use measured per-channel transmission, not an assumed PNG alpha.

    The original Gamma-space renderer's readback forces alpha to one. Rendering
    the same pose over black/white measures C = black + transmission * bg.
    Keeping RGB transmission also preserves the original colored edge blending.
    """
    black=np.asarray(black);white=np.asarray(white);background=np.asarray(background)
    if (black.dtype!=np.uint8 or white.dtype!=np.uint8 or background.dtype!=np.uint8
            or black.ndim!=3 or black.shape[-1]!=3 or white.shape!=black.shape
            or background.shape not in ((3,),black.shape)):
        raise ValueError('Expected equal uint8 RGB renders and an RGB background')
    a=black.astype(np.float32);delta=white.astype(np.float32)-a
    if delta.min() < -2:raise ValueError('Black/white poses differ beyond render quantization')
    transmission=np.clip(delta/255.,0.,1.)
    return np.rint(np.clip(a+transmission*background,0,255)).astype(np.uint8)


class OriginalPoleaxePreview:
    """Own one arena lease and verify the original battle after every exit."""
    def __init__(self,session=None,client=None):
        if session is None:
            from runtime import InstanceSession
            session=InstanceSession('arena')
        self.session=session;self.client=client or LocalClient(session)
        self.stack=None;self.held=False;self.loaded=False;self.before=None;self.after=None
        self.animations={};self.remote_files=[]

    def execute(self,code):return self.client.execute(code,lease_held=True)

    def snapshot(self):
        return self.execute('return {state=MR3A.state(),enemies=CS.UnityEngine.Object.FindObjectsOfType(typeof(CS.EnemyBase)).Length}')

    def __enter__(self):
        if self.stack is not None:raise RuntimeError('Preview is already open')
        self.stack=ExitStack();self.before=None;self.after=None
        try:
            self.stack.enter_context(self.session.control());self.held=True;self.before=self.snapshot()
            if self.before['state']['timeScale']!=0:raise RuntimeError('Pause arena before rendering original poses')
            self.execute('assert(load('+json.dumps(SOURCE.read_text())+'))();return true');self.loaded=True
            self.info=self.execute(f'return MR3A.poleaxe_preview_begin({SCALE!r})')
            self.animations={a['name']:a['duration']for a in self.info['animations']}
            return self
        except BaseException as error:
            try:self.close()
            except Exception as cleanup:error.add_note('Preview cleanup: '+repr(cleanup))
            raise

    def render(self,name,seconds,*,background=(0.,0.,0.)):
        if self.stack is None or not self.loaded:raise RuntimeError('Open the preview context first')
        seconds=float(seconds);background=tuple(map(float,background))
        if (name not in self.animations or not math.isfinite(seconds)
                or not 0<=seconds<=self.animations[name]):raise ValueError('Invalid original animation phase')
        if len(background)!=3 or any(not math.isfinite(x)or not 0<=x<=1 for x in background):
            raise ValueError('Expected a finite RGB background in [0,1]')
        self.execute('return MR3A.poleaxe_preview_background('+','.join(map(repr,background))+')')
        filename='pose_'+uuid.uuid4().hex+'.png';remote=FOLDER+'/'+filename;self.remote_files.append(remote)
        metadata=self.execute('return MR3A.poleaxe_preview_render('+json.dumps(name)+','+repr(seconds)+','+json.dumps(filename)+')')
        result=self.session.adb('exec-out','cat',remote);result.check_returncode();png=result.stdout
        if not png.startswith(b'\x89PNG\r\n\x1a\n'):raise RuntimeError('Original pose readback is not PNG')
        return png,metadata

    def close(self):
        stack,self.stack=self.stack,None
        if stack is None:return
        errors=[]
        try:
            if self.held:
                operations=[]
                if self.loaded:operations.append(lambda:self.execute('return MR3A.poleaxe_preview_end()'))
                if self.before is not None:
                    def verify():
                        self.after=self.snapshot()
                        if not unchanged_battle(self.before,self.after):raise RuntimeError('Preview changed original battle state')
                    operations.append(verify)
                if self.remote_files:
                    operations.append(lambda:self.session.adb('shell','rm','-f',*self.remote_files).check_returncode())
                for operation in operations:
                    try:operation()
                    except Exception as error:errors.append(error)
        finally:
            try:
                stack.close()
            finally:
                self.remote_files=[];self.loaded=False;self.held=False
        if errors:
            for error in errors[1:]:errors[0].add_note('Additional cleanup failure: '+repr(error))
            raise errors[0]

    def __exit__(self,kind,error,tb):
        try:self.close()
        except Exception as cleanup:
            if error is None:raise
            error.add_note('Preview cleanup: '+repr(cleanup))
        return False


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--clip',default='attack_down');parser.add_argument('--phase',type=float,default=.4)
    parser.add_argument('--output',type=Path,required=True);args=parser.parse_args()
    args.output.mkdir(parents=True,exist_ok=False);preview=OriginalPoleaxePreview();renders=[]
    (args.output/'sources.json').write_text(json.dumps({str(path.relative_to(ROOT)):hashlib.sha256(path.read_bytes()).hexdigest()
        for path in (Path(__file__).resolve(),SOURCE,ROOT/'tools/arena_projection.py')},indent=2)+'\n')
    try:
        with preview:
            for label,color in [('black',(0.,0.,0.)),('white',(1.,1.,1.))]:
                png,meta=preview.render(args.clip,args.phase,background=color)
                (args.output/(label+'.png')).write_bytes(png);renders.append(dict(meta,image=label+'.png'))
    finally:
        (args.output/'state-check.json').write_text(json.dumps(dict(before=preview.before,after=preview.after,
            unchanged=preview.before is not None and preview.after is not None and unchanged_battle(preview.before,preview.after)),indent=2)+'\n')
    (args.output/'renders.json').write_text(json.dumps(renders,indent=2)+'\n')
    print('Rendered original poses; battle state unchanged.')


if __name__=='__main__':main()
