#!/usr/bin/env python3
"""Run the pixels-only baseline in the isolated original arena client.

Evaluation telemetry is kept outside the policy. It can stop an experiment, but
cannot select an action. Frames, estimates and evaluation are logged separately.
"""
from __future__ import annotations
import argparse
import json
from pathlib import Path
import time
import threading
import queue
import os
import zlib
import hashlib
import subprocess
from collections import deque

# Tiny per-object regressions must not keep a BLAS worker pool spinning beside
# Waydroid. Set before NumPy/OpenCV import, only in this experiment process.
if __name__=='__main__':
    for variable in ('OPENBLAS_NUM_THREADS','OMP_NUM_THREADS','MKL_NUM_THREADS'):
        os.environ[variable]='1'

from arena_local import LocalClient, FOLDER, ROOT
from arena_capture import FastCapture, percentile
from arena_vision import Perception, serializable, overlay,extrapolate
from arena_policy import Avoider
from arena_mpc import MpcAvoider
from runtime import InstanceSession
import cv2
import numpy as np


class InitialPixels:
    """Wait once for the original scene's black entrance, without sending keys."""
    def __init__(self):
        self.first_visible_elapsed=None
        self.black_frames=0

    def check(self,rgba,elapsed):
        if self.first_visible_elapsed is not None:return 'ready'
        if np.any(rgba[:,:,:3]):
            self.first_visible_elapsed=elapsed
            return 'ready'
        self.black_frames+=1
        return 'timeout'if elapsed>=2 else'waiting'


class Recorder:
    """Bounded image queue: slow disk encoding cannot stall the control loop."""
    def __init__(self, folder):
        self.folder=folder
        self.queue=queue.Queue(maxsize=4)
        self.dropped=0
        self.error=None
        self.thread=threading.Thread(target=self._write,name='arena-frame-recorder')

    def _write(self):
        try:
            while True:
                item=self.queue.get()
                if item is None:
                    return
                index,raw,annotated=item
                if not cv2.imwrite(str(self.folder/f'{index:06d}.png'),raw):
                    raise OSError('Cannot save raw frame')
                if not cv2.imwrite(str(self.folder/f'{index:06d}-overlay.jpg'),annotated):
                    raise OSError('Cannot save annotated frame')
        except Exception as error:
            self.error=str(error)

    def submit(self,index,raw,annotated):
        try:
            self.queue.put_nowait((index,raw,annotated))
        except queue.Full:
            self.dropped+=1

    def close(self):
        if self.thread.is_alive():
            self.queue.put(None,timeout=3)
            self.thread.join(timeout=3)
        if self.thread.is_alive() or self.error:
            raise RuntimeError(self.error or 'Frame recorder did not stop')


class Evaluator:
    """Read privileged validation data on a separate thread; never passed to policy."""
    def __init__(self,session,initial):
        self.session,self.initial=session,initial
        self.rows=queue.SimpleQueue()
        self.stop=threading.Event()
        self.error=None
        self.thread=threading.Thread(target=self._read,name='arena-evaluation')

    def _read(self):
        while not self.stop.is_set():
            try:
                result=self.session.adb('shell','cat',FOLDER+'/vision-eval.json',timeout=2)
                value=json.loads(result.stdout)
                if value['time'] >= self.initial['time']:
                    self.rows.put(value)
            except (ValueError,UnicodeError,TimeoutError):
                pass
            except (subprocess.TimeoutExpired,RuntimeError)as error:
                self.error=str(error)
            self.stop.wait(.12)

    def close(self):
        self.stop.set()
        if self.thread.ident is not None:
            self.thread.join(timeout=3)
        if self.thread.is_alive():
            raise RuntimeError('Evaluation reader did not stop')


def prepare(client, seed, level, map_id, pins, *, start=1,sample_block=None,timeout=90,progress=None):
    spec = dict(level=level, map=map_id, start=start, pins=pins)
    if sample_block is not None:spec['sample_block']=sample_block
    client.execute('return MR3A.native_select(' + lua(spec) + ',' + str(seed) + ')')
    deadline = time.monotonic() + timeout
    next_progress=0
    while time.monotonic() < deadline:
        job = client.execute('return MR3A.travel', timeout=20)
        if progress is not None and time.monotonic()>=next_progress:
            progress(job or {});next_progress=time.monotonic()+5
        if job and job.get('done'):
            if job.get('error'):
                raise RuntimeError(job['error'])
            break
        time.sleep(.15)
    else:
        raise TimeoutError('Native selection did not complete')
    source = (ROOT / 'arena/Local/vision_eval.lua').read_text()
    return client.execute('assert(load(' + json.dumps(source) + '))();'
                          'MR3A.menu_suppressed=true;MR3A.hide_menu();MR3A.enable_keyboard();'
                          'MR3A.start_vision_evaluation();return MR3A.vision_evaluation()')


def lua(value):
    if isinstance(value, dict):
        return '{' + ','.join('['+json.dumps(str(k))+']=' + lua(v) for k, v in value.items()) + '}'
    return json.dumps(value)


def evaluation_status(initial,current,goal):
    if (current['health']<initial['health'] or current.get('damage',0)>0
            or current.get('minHealth',current['health'])<initial['health']):
        return 'damage'
    return 'passed' if current['stageIndex']>=goal else 'duration'


def run(args):
    # Small 640px kernels do not benefit from a large OpenCV worker pool. It
    # competes with the Android renderer and increases observation staleness.
    cv2.setNumThreads(1)
    session = InstanceSession('arena')
    client = LocalClient(session)
    pins = dict(item.split(':', 1) for item in args.pin)
    pins = {k: int(v) for k, v in pins.items()}
    args.output.mkdir(parents=True, exist_ok=False)
    detector_weights=getattr(args,'detector_weights',None)
    if detector_weights:
        from arena_yolo_detector import make_perception
        perception=make_perception(detector_weights)
        detector_info=dict(weights=str(detector_weights),sha256=hashlib.sha256(detector_weights.read_bytes()).hexdigest())
        from arena_obb_detector import profile_path
        metadata=profile_path(detector_weights)
        if metadata.is_file():
            detector_info.update(profile=str(metadata),profile_sha256=hashlib.sha256(metadata.read_bytes()).hexdigest())
    else:
        perception=Perception();detector_info=None
    policy=MpcAvoider() if detector_weights else Avoider()
    policy_samples={False:deque(maxlen=32),True:deque(maxlen=32)}
    policy_times,compute_priors=[],[]
    initial = prepare(client, args.seed, args.level, args.map, pins)
    sources=('tools/arena_vision.py','tools/arena_policy.py','tools/arena_terrain.py',
             'tools/arena_motion.py','arena/vision-motion-priors.json','arena/Local/vision_eval.lua',
             'tools/arena_capture.py','arena/Capture/FrameServer.java','tools/arena_yolo_detector.py',
             'tools/arena_yolo_data.py','tools/arena_visual_runner.py','tools/arena_projection.py',
             'arena/vision-camera.json','tools/arena_mpc.py','tools/arena_object_motion.py',
             'arena/vision-object-priors.json','arena/vision-detector.json','tools/arena_oriented.py',
             'tools/arena_obb_detector.py','tools/arena_support.py')
    source_hashes={name:hashlib.sha256((ROOT/name).read_bytes()).hexdigest()for name in sources}
    (args.output / 'setup.json').write_text(json.dumps(dict(seed=args.seed, level=args.level,
        map=args.map, pins=pins, observe=args.observe_only, initial=initial,sources=source_hashes,
        detector=detector_info), indent=2))
    capture_times, vision_times, action_times, intervals, fresh_intervals,ages = [], [], [], [], [], []
    fresh_vision_times=[]
    first_evaluation=None
    sent_keys={'jump':0,'down':0}
    receipts=set()
    consume_times=[];chain_times=[]
    board_entries=[];had_damage=False
    actions, count, max_stage, status, final = [], 0, -1, 'duration', initial
    initial_pixels=InitialPixels()
    begin = time.monotonic()
    with (args.output / 'vision.jsonl').open('w') as estimates, (args.output / 'evaluation.jsonl').open('w') as evaluations:
        with FastCapture(session, width=640, height=360) as cap:
            clock=cap.calibrate_clock()
            resumed = False
            recorder=Recorder(args.output)
            evaluator=Evaluator(session,initial)
            fresh=0
            try:
                recorder.thread.start();evaluator.thread.start()
                resumed = True
                client.execute('return MR3A.resume()',lease_held=True)
                begin = time.monotonic(); next_image = begin; previous_loop=None;last_eval=begin
                previous_crc=None;latest=None;fresh=0
                while time.monotonic() - begin < args.seconds:
                    loop = time.monotonic()
                    if previous_loop is not None:
                        intervals.append((loop-previous_loop)*1000)
                    previous_loop=loop
                    frame = cap.capture()
                    readiness=initial_pixels.check(frame.array(),loop-begin)
                    if readiness=='timeout':
                        status='initial_black_frame';break
                    start = time.perf_counter()
                    crc=zlib.crc32(frame.rgba)
                    is_fresh=crc!=previous_crc
                    if is_fresh:
                        if latest is not None:
                            fresh_intervals.append(frame.device_captured_ns/1e6-latest['time']*1000)
                        latest=perception.observe(frame.array(),frame.device_captured_ns/1e9)
                        capture_request=frame.request_ns
                        previous_crc=crc;fresh+=1
                    now=(time.perf_counter_ns()-clock['offset_ns'])/1e9
                    age=(now-latest['time'])*1000
                    ages.append(age)
                    if age>150 and readiness!='waiting':
                        status='stale_frame';break
                    # One native render-frame input prior, independently of actual
                    # measured pixel age. Neither number is a photon-time guarantee.
                    # Budget the remaining policy computation too; its expensive
                    # search samples must not be diluted by cheap reactive frames.
                    expensive=isinstance(policy,MpcAvoider)and policy.uses_search(latest)
                    samples=policy_samples[expensive]
                    compute_prior=percentile(samples,90)/1000 if samples else (.01 if expensive else 0.)
                    obs=extrapolate(latest,now+1/60+compute_prior)
                    decision_start=time.perf_counter()
                    action, reason = ((None,'waiting_initial_pixels')if readiness=='waiting'else policy.choose(obs))
                    compute_ms=(time.perf_counter()-decision_start)*1000
                    samples.append(compute_ms);policy_times.append(compute_ms)
                    compute_priors.append(compute_prior*1000)
                    vision_times.append((time.perf_counter() - start) * 1000)
                    if is_fresh:
                        fresh_vision_times.append(vision_times[-1])
                    capture_times.append(frame.request_ms)
                    if action and not args.observe_only:
                        ack = cap.tap(action)
                        perception.action(action, obs['time'],obs)
                        action_times.append(ack.request_ms)
                        key='down'if action in ('slide','down')else'jump'
                        sent_keys[key]+=1
                        actions.append(dict(t=time.monotonic()-begin,action=action,reason=reason,
                            key=key,key_count=sent_keys[key],request_ns=ack.request_ns,
                            capture_request_ns=capture_request))
                    row = serializable(obs)
                    executed=action if not args.observe_only else None
                    row.update(frame=count, elapsed=time.monotonic()-begin, action=executed,proposed_action=action,
                               reason=reason, capture_ms=frame.request_ms, vision_ms=vision_times[-1],
                               policy_compute_ms=compute_ms,policy_compute_prior_ms=compute_prior*1000)
                    estimates.write(json.dumps(row) + '\n')
                    if loop >= next_image:
                        recorder.submit(count,cv2.cvtColor(frame.array(),cv2.COLOR_RGBA2BGR),
                                        overlay(frame.array(),obs,executed,('observe:'if args.observe_only else'')+reason))
                        next_image = loop + .1
                    while not evaluator.rows.empty():
                        current=evaluator.rows.get()
                        if current:
                            final = current
                            if first_evaluation is None:
                                first_evaluation=current
                            last_eval=loop
                            evaluations.write(json.dumps(dict(elapsed=time.monotonic()-begin, **current))+'\n')
                            for key,receipt in current.get('keyReceipts',{}).items():
                                identity=(key,receipt['count'])
                                if identity in receipts:
                                    continue
                                event=next((a for a in actions if a['key']==key and a['key_count']==receipt['count']),None)
                                if event:
                                    native_host_ns=receipt['time']*1e9+clock['offset_ns']
                                    delay=(native_host_ns-event['request_ns'])/1e6
                                    if -1<delay<1000:
                                        event['unity_keydown_ms']=delay
                                        event['capture_to_unity_ms']=(native_host_ns-event['capture_request_ns'])/1e6
                                        consume_times.append(delay);chain_times.append(event['capture_to_unity_ms'])
                                        receipts.add(identity)
                            max_stage = max(max_stage, current['stageIndex'])
                            candidate=evaluation_status(initial,current,args.boards)
                            had_damage=had_damage or candidate=='damage'
                            if not board_entries or current['stageIndex']>board_entries[-1]['stageIndex']:
                                board_entries.append(dict(stageIndex=current['stageIndex'],stageID=current['stageID'],
                                    elapsed=time.monotonic()-begin,damage=current.get('damage',0),health=current['health']))
                            if current['health']<=0:
                                status='dead'
                            elif max_stage>=args.boards:
                                status='passed_with_damage'if had_damage else'passed'
                    if status != 'duration':
                        break
                    if loop-last_eval>1.5:
                        status='evaluation_timeout';break
                    count += 1
                    time.sleep(max(0, 1/args.fps-(time.monotonic()-loop)))
            except KeyboardInterrupt:
                status='interrupted'
            finally:
                try:
                    if resumed:
                        client.execute('MR3A.pause();MR3A.menu_suppressed=false;MR3A.enable_menu();return true',
                                       timeout=5,lease_held=cap._stack is not None)
                finally:
                    evaluator.close()
                    recorder.close()
    def timing(samples):
        return dict(median=percentile(samples, 50), p95=percentile(samples, 95), max=max(samples)) if samples else None
    report = dict(status=status, seconds=time.monotonic()-begin, frames=count,
                  max_stage=max_stage, final=final, actions=actions,
                  capture_ms=timing(capture_times), perception_policy_ms=timing(vision_times),
                  key_enqueue_ms=timing(action_times),loop_interval_ms=timing(intervals),
                  dropped_recording_frames=recorder.dropped,fresh_frames=fresh,
                  fresh_frame_interval_ms=timing(fresh_intervals),observation_age_ms=timing(ages),
                  input_delay_prior_ms=1000/60)
    report.update(initial_black_frames=initial_pixels.black_frames,
                  first_visible_elapsed=initial_pixels.first_visible_elapsed)
    report.update(sent_keys=sent_keys,observed_keys=final.get('keys',{}),
                  unity_keydown_ms=timing(consume_times),capture_to_unity_ms=timing(chain_times),
                  board_entries=board_entries,had_damage=had_damage)
    report['evaluation_error']=evaluator.error
    report['policy_compute_ms']=timing(policy_times)
    report['policy_compute_prior_ms']=timing(compute_priors)
    report['fresh_perception_policy_ms']=timing(fresh_vision_times)
    if first_evaluation and final['time']>first_evaluation['time']:
        report['native_render_fps']=(final['frame']-first_evaluation['frame'])/(final['time']-first_evaluation['time'])
    (args.output/'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps(report, ensure_ascii=False), flush=True)
    return report


def main():
    from arena_yolo_detector import DEFAULT_WEIGHTS
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--seed', type=int, default=42)
    p.add_argument('--level', type=int, default=1)
    p.add_argument('--map', type=int, default=1)
    p.add_argument('--pin', action='append', default=[], help='Native board pool choice position:variant')
    p.add_argument('--seconds', type=float, default=70)
    p.add_argument('--boards', type=int, default=3, help='Stop once grounded on this zero-based stage index')
    p.add_argument('--fps', type=int, default=40)
    p.add_argument('--observe-only', action='store_true')
    p.add_argument('--detector-weights',type=Path,default=DEFAULT_WEIGHTS,
                   help='Fine-tuned standard YOLO checkpoint; defaults to reviewed profile')
    p.add_argument('--output', type=Path,default=ROOT/'debug/arena-client/visual-runs'/str(time.time_ns()))
    args = p.parse_args()
    if not 1 <= args.fps <= 60 or not 0 < args.seconds <= 180 or args.boards < 1:
        p.error('Invalid experiment limits')
    report=run(args)
    if report['status']=='interrupted':
        raise SystemExit(130)
    if report['status']not in ('passed','passed_with_damage'):
        raise SystemExit(1)


if __name__ == '__main__':
    main()
