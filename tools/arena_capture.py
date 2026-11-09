#!/usr/bin/env python3
"""Persistent Android pixels and explicit key pulses for the isolated arena."""
from __future__ import annotations

import argparse
from contextlib import ExitStack
from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import select
import struct
import subprocess
import sys
import time
import uuid
import zlib

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'agent'))
SOURCE = ROOT / 'arena/Capture/FrameServer.java'
PRIVATE = ROOT / 'debug/arena-client'
BUILD = PRIVATE / 'fast-capture/build'
HELLO = struct.Struct('>4sIIII')
REQUEST = struct.Struct('>IQ')
HEADER = struct.Struct('>4sIIIIIQQQQ')
VERSION = 1


def build_server():
    digest = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    report = BUILD / 'report.json'
    dex = BUILD / 'dex/classes.dex'
    if report.exists() and dex.exists():
        saved = json.loads(report.read_text())
        if (saved.get('source_sha256') == digest
                and saved.get('dex_sha256') == hashlib.sha256(dex.read_bytes()).hexdigest()):
            return dex
    sdk = PRIVATE / 'recovery-tools/android-build-tools'
    ecj = PRIVATE / 'recovery-tools/ecj-3.41.0.jar'
    for path in (ecj, sdk / 'android.jar', sdk / 'd8.jar'):
        if not path.is_file():
            raise FileNotFoundError(f'Local Android build dependency missing: {path}')
    classes = BUILD / 'classes'
    classes.mkdir(parents=True, exist_ok=True)
    dex.parent.mkdir(parents=True, exist_ok=True)
    outputs = classes / 'dev/mr3a/arena/capture'
    for old in outputs.glob('FrameServer*.class'):
        old.unlink()
    compile_command = ['java', '-jar', str(ecj), '-1.8', '-bootclasspath', str(sdk / 'android.jar'),
                       '-d', str(classes), str(SOURCE)]
    # Build D8's inputs after ECJ, including the key-release scheduler's classes.
    for command in (compile_command, None):
        if command is None:
            command = ['java', '-cp', str(sdk / 'd8.jar'), 'com.android.tools.r8.D8',
                       '--lib', str(sdk / 'android.jar'), '--min-api', '26', '--output', str(dex.parent),
                       *map(str, sorted(outputs.glob('FrameServer*.class')))]
        result = subprocess.run(command, capture_output=True, timeout=60)
        if result.returncode:
            raise RuntimeError(result.stderr.decode(errors='replace'))
    report.write_text(json.dumps(dict(source_sha256=digest,
                                     dex_sha256=hashlib.sha256(dex.read_bytes()).hexdigest()), indent=2))
    return dex


def read_exact(stream, size, deadline):
    """Read one bounded protocol field; never wait indefinitely for a partial frame."""
    chunks = []
    remaining = size
    while remaining:
        wait = deadline - time.monotonic()
        if wait <= 0 or not select.select([stream], [], [], max(0, wait))[0]:
            raise TimeoutError('Android capture stream timed out')
        part = os.read(stream.fileno(), remaining)
        if not part:
            raise EOFError('Android capture stream closed mid-frame')
        chunks.append(part)
        remaining -= len(part)
    return b''.join(chunks)


@dataclass(frozen=True)
class Frame:
    width: int
    height: int
    sequence: int
    request_ns: int
    received_ns: int
    device_start_ns: int
    device_captured_ns: int
    device_ready_ns: int
    rgba: bytes

    @property
    def request_ms(self):
        return (self.received_ns - self.request_ns) / 1e6

    def array(self):
        """Read-only RGBA8888 view, without a PNG or JPEG round trip."""
        import numpy as np
        return np.frombuffer(self.rgba, dtype=np.uint8).reshape(self.height, self.width, 4)


class FastCapture:
    """One owner, one outstanding request, one fresh Android capture per request.

    A held InstanceSession lease permits the same owner to use session.adb for
    other device commands. Key pulses use the original Android keyboard handler.
    """
    def __init__(self, session, *, width=1280, height=720, timeout=2):
        if session.spec.name != 'arena':
            raise ValueError('FastCapture is restricted to the isolated arena instance')
        if (type(width) is not int or type(height) is not int or min(width, height) < 16
                or max(width, height) > 4096 or width * height > 4194304):
            raise ValueError('Invalid capture dimensions')
        if isinstance(timeout, bool) or not isinstance(timeout, (int, float)) or not 0 < timeout <= 10:
            raise ValueError('Capture timeout must be in (0, 10] seconds')
        self.session, self.width, self.height, self.timeout = session, width, height, timeout
        self._stack = None
        self._process = None
        self._socket = None
        self._sequence = 0
        self.remote_stderr = ''
        self.warmup_ms = []

    def __enter__(self):
        if self._stack is not None:
            raise RuntimeError('Capture is already open')
        dex = build_server()
        self._sequence = 0
        self.token = uuid.uuid4().hex
        remote = '/data/local/tmp/mr3a-capture-' + hashlib.sha256(dex.read_bytes()).hexdigest()[:16] + '.dex'
        self._remote_log = '/data/local/tmp/mr3a-capture-' + self.token + '.log'
        self._stack = ExitStack()
        try:
            self._stack.enter_context(self.session.control())
            self.session.adb('push', str(dex), remote).check_returncode()
            self._stack.callback(self._cleanup_log)
            command = (f'CLASSPATH={remote} app_process / dev.mr3a.arena.capture.FrameServer '
                       f'{self.width} {self.height} {self.token} 2>{self._remote_log}')
            self._process = self._stack.enter_context(self.session.adb_stream('shell', '-T', command))
            raw = read_exact(self._process.stdout, HELLO.size, time.monotonic() + 5)
            magic, version, self.sdk, self.worker_pid, port = HELLO.unpack(raw)
            if magic != b'MR3H' or version != VERSION or self.sdk != 33 or self.worker_pid <= 0:
                raise ValueError('Invalid Android capture handshake')
            self._socket = self._stack.enter_context(self.session.device_socket(port, timeout=self.timeout))
            self._socket.sendall(self.token.encode('ascii'))
            if read_exact(self._socket, 4, time.monotonic() + self.timeout) != b'MR3A':
                raise ValueError('Android capture authentication failed')
            # First GPU capture/readback is cold (observed ~90ms); complete it
            # during startup so the first returned application frame is warm.
            self.warmup_ms = [self.capture().request_ms for _ in range(3)]
            return self
        except Exception as error:
            self.close()
            raise RuntimeError(f'Cannot start Android capture: {error}; {self.remote_stderr[-1000:]}') from error

    def _cleanup_log(self):
        try:
            pid = getattr(self, 'worker_pid', None)
            if pid:
                process = self.session.adb('shell', 'cat', f'/proc/{pid}/cmdline', timeout=2)
                if (self.token.encode('ascii') in process.stdout
                        and b'dev.mr3a.arena.capture.FrameServer' in process.stdout):
                    self.session.adb('shell', 'kill', '-TERM', str(pid), timeout=2)
            result = self.session.adb('shell', 'cat', self._remote_log, timeout=2)
            self.remote_stderr = result.stdout.decode(errors='replace')
            self.session.adb('shell', 'rm', '-f', self._remote_log, timeout=2)
        except (RuntimeError, subprocess.SubprocessError):
            pass  # Device disconnect must not mask the original capture error.

    def close(self):
        stack, self._stack = self._stack, None
        if stack:
            stack.close()  # Stream closes before its remote log and the control lease.
        self._process = None
        self._socket = None

    def __exit__(self, *exc):
        self.close()

    def _exchange(self, command,payload=b'',paired=False):
        if self._socket is None:
            raise RuntimeError('Open FastCapture before requesting a frame')
        self._sequence += 1
        sequence = self._sequence
        try:
            begin = time.perf_counter_ns()
            self._socket.sendall(REQUEST.pack(command, sequence)+payload)
            deadline = time.monotonic() + self.timeout
            values = HEADER.unpack(read_exact(self._socket, HEADER.size, deadline))
            magic, version, kind, width, height, size, seq, start, captured, ready = values
            image=command in (1,7)
            expected = self.width * self.height * 4 if image else 0
            if (magic != b'MR3F' or version != VERSION or kind != command or seq != sequence
                    or size != expected or not 0 < start <= captured <= ready
                    or (width, height) != ((self.width, self.height) if image else (0, 0))):
                raise ValueError('Invalid or out-of-order Android capture frame')
            data = read_exact(self._socket, size, deadline)
            if paired:
                length=struct.unpack('>I',read_exact(self._socket,4,deadline))[0]
                if not 0<length<=8*1024*1024:
                    raise ValueError('Invalid native paired label length')
                job=json.loads(read_exact(self._socket,length,deadline))
                identity=self.token+f'{sequence:016x}'
                if (not isinstance(job,dict)or job.get('identity')!=identity or not job.get('done')
                        or job.get('error')or not isinstance(job.get('labels'),dict)):
                    raise ValueError('Invalid or stale native paired labels')
                from arena_native_json import normalize_arrays
                labels=normalize_arrays(job['labels'])
            received = time.perf_counter_ns()
            frame=Frame(width, height, seq, begin, received, start, captured, ready, data)
            return (frame,labels)if paired else frame
        except Exception:
            self.close()
            raise

    def capture(self):
        return self._exchange(1)

    def paired_step(self,ticks,action='none'):
        """Advance original paused physics and return its paired image/labels."""
        actions={'none':0,'jump':1,'down':2}
        if type(ticks)is not int or not 1<=ticks<=10 or action not in actions:
            raise ValueError('Paired step requires ticks 1..10 and none/jump/down')
        return self._exchange(7,struct.pack('>II',ticks,actions[action]),paired=True)

    def tap(self, action):
        """Android key pulse (slide holds S for 500ms); ack is enqueue, not consumption."""
        commands = {'jump': 3, 'down': 4, 'pause': 5, 'slide': 6}
        if action not in commands:
            raise ValueError('Action must be jump, down, slide or pause')
        return self._exchange(commands[action])

    def calibrate_clock(self, count=8):
        """Offset estimate with an RTT/2 uncertainty; not an exposure timestamp."""
        if type(count) is not int or not 1 <= count <= 100:
            raise ValueError('Clock samples must be in 1..100')
        frames = [self._exchange(2) for _ in range(count)]
        best = min(frames, key=lambda f: f.request_ms)
        return dict(offset_ns=(best.request_ns + best.received_ns) // 2 - best.device_start_ns,
                    uncertainty_ns=(best.received_ns - best.request_ns) // 2)


def percentile(values, p):
    ordered = sorted(values)
    x = (len(ordered) - 1) * p / 100
    low = int(x)
    return ordered[low] + (ordered[min(low + 1, len(ordered) - 1)] - ordered[low]) * (x - low)


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--frames', type=int, default=300)
    p.add_argument('--width', type=int, default=1280)
    p.add_argument('--height', type=int, default=720)
    p.add_argument('--output', type=Path, default=PRIVATE / 'fast-capture/latest')
    a = p.parse_args()
    if not 10 <= a.frames <= 10000:
        p.error('frames must be in 10..10000')
    from runtime import InstanceSession
    samples = []
    with FastCapture(InstanceSession('arena'), width=a.width, height=a.height) as capture:
        clock = capture.calibrate_clock()
        for _ in range(a.frames):
            frame = capture.capture()
            samples.append(dict(sequence=frame.sequence, request_ms=frame.request_ms,
                                android_capture_ms=(frame.device_captured_ns-frame.device_start_ns)/1e6,
                                android_readback_ms=(frame.device_ready_ns-frame.device_captured_ns)/1e6,
                                ready_to_host_estimate_ms=(frame.received_ns-frame.device_ready_ns-clock['offset_ns'])/1e6,
                                crc32=zlib.crc32(frame.rgba)))
        worker = capture.worker_pid
        warmup = capture.warmup_ms
    keys = ('request_ms', 'android_capture_ms', 'android_readback_ms', 'ready_to_host_estimate_ms')
    summary = {k: dict(p50=percentile([v[k] for v in samples], 50),
                       p95=percentile([v[k] for v in samples], 95),
                       p99=percentile([v[k] for v in samples], 99),
                       maximum=max(v[k] for v in samples)) for k in keys}
    a.output.parent.mkdir(parents=True, exist_ok=True)
    from PIL import Image
    Image.frombytes('RGBA', (frame.width, frame.height), frame.rgba).save(a.output.with_suffix('.png'))
    result = dict(width=frame.width, height=frame.height, samples=samples, summary=summary,
                  clock=clock, worker_pid=worker, startup_capture_ms=warmup,
                  unique_images=len({s['crc32'] for s in samples}),
                  display_environment={k: os.environ.get(k) for k in ('DISPLAY', 'WAYLAND_DISPLAY', 'DESKTOP_SESSION')},
                  timing_scope='request to complete RGBA on host; excludes original render/present age',
                  protocol='request/reply, no preproduced-frame queue')
    a.output.with_suffix('.json').write_text(json.dumps(result, indent=2))
    print(json.dumps(dict(summary=summary, unique_images=result['unique_images'],
                          worker_pid=worker, report=str(a.output.with_suffix('.json'))), indent=2))


if __name__ == '__main__':
    main()
