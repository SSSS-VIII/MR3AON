"""Bounded frame protocol: partial packets, stale replies, disconnects and timeout."""
import os
from pathlib import Path
import socket
import sys
import threading
import time
from types import SimpleNamespace
from unittest.mock import Mock
import subprocess

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from arena_capture import FastCapture, HEADER, REQUEST, read_exact


def session(name='arena'):
    return SimpleNamespace(spec=SimpleNamespace(name=name))


def test_partial_frames_preserve_rgba_and_sequence():
    capture = FastCapture(session(), width=16, height=16)
    client, server = socket.socketpair()
    pixels = bytes(range(256)) * 4
    def producer():
        with server:
            command, sequence = REQUEST.unpack(server.recv(REQUEST.size))
            packet = HEADER.pack(b'MR3F', 1, command, 16, 16, len(pixels), sequence, 100, 200, 300) + pixels
            for pos in range(0, len(packet), 7):
                server.sendall(packet[pos:pos+7])
    thread = threading.Thread(target=producer)
    thread.start()
    try:
        capture._socket = client
        frame = capture.capture()
        assert frame.rgba == pixels and frame.sequence == 1
        assert frame.device_start_ns == 100 and frame.device_ready_ns == 300
        assert frame.request_ms >= 0
    finally:
        client.close()
        thread.join(timeout=2)
    assert not thread.is_alive()


@pytest.mark.parametrize('size,seq', [(0xffffffff, 1), (1024, 99)])
def test_rejects_invalid_length_and_stale_frame_without_reading_payload(size, seq):
    capture = FastCapture(session(), width=16, height=16)
    client, server = socket.socketpair()
    capture._socket = client
    server.sendall(HEADER.pack(b'MR3F', 1, 1, 16, 16, size, seq, 1, 2, 3))
    try:
        with pytest.raises(ValueError, match='out-of-order'):
            capture.capture()
        assert capture._socket is None  # Failed channel is not reused.
    finally:
        client.close()
        server.close()


def test_read_timeout_and_eof_are_bounded():
    reader, writer = os.pipe()
    with os.fdopen(reader, 'rb', buffering=0) as stream:
        try:
            with pytest.raises(TimeoutError):
                read_exact(stream, 4, time.monotonic() + .02)
            os.close(writer)
            with pytest.raises(EOFError):
                read_exact(stream, 4, time.monotonic() + 1)
        finally:
            try:
                os.close(writer)
            except OSError:
                pass


def test_rejects_main_and_invalid_dimensions():
    with pytest.raises(ValueError, match='arena'):
        FastCapture(session('main'))
    with pytest.raises(ValueError, match='dimensions'):
        FastCapture(session(), width=4096, height=4096)
    with pytest.raises(ValueError, match='timeout'):
        FastCapture(session(), timeout=True)


@pytest.mark.parametrize('same_token', [True, False])
def test_cleanup_only_signals_verified_own_worker(same_token):
    own = session()
    token = 'a' * 32
    command = ('dev.mr3a.arena.capture.FrameServer ' + (token if same_token else 'b' * 32)).encode()
    own.adb = Mock(side_effect=[subprocess.CompletedProcess([], 0, command, b'')]
                   + ([subprocess.CompletedProcess([], 0, b'', b'')] if same_token else [])
                   + [subprocess.CompletedProcess([], 0, b'device diagnostic', b''),
                      subprocess.CompletedProcess([], 0, b'', b'')])
    capture = FastCapture(own)
    capture.token = token
    capture.worker_pid = 123
    capture._remote_log = '/data/local/tmp/mr3a-capture-' + token + '.log'
    capture._cleanup_log()
    kills = [c for c in own.adb.call_args_list if c.args[1] == 'kill']
    assert len(kills) == int(same_token)
    assert capture.remote_stderr == 'device diagnostic'
