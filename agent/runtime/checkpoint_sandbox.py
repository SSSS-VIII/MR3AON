"""Opt-in offline arena VM backend using the existing named-instance lease.

No Waydroid/ADB target or account configuration is created by this backend.
The VM control socket and all writable images belong to this named instance.
"""
from contextlib import contextmanager
import json
from pathlib import Path
import socket
import subprocess
import time

from runtime.instances import InstanceSession


class ArenaCheckpointSandbox:
    def __init__(self, session: InstanceSession):
        if session.spec.name != 'arena-search':
            raise ValueError('The experimental checkpoint backend only accepts arena-search')
        self.session = session
        self.root = session.spec.work_root / 'checkpoint'
        self.socket = self.root / 'control.sock'
        self.process = None
        self.arena_game_gate = False

    def request(self, operation, *, timeout=10, **args):
        if not self.session._owns_control:
            raise RuntimeError('Checkpoint operations require the named instance control lease')
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError('Checkpoint worker is not running')
        with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as transport:
            transport.settimeout(timeout)
            transport.connect(str(self.socket))
            transport.sendall((json.dumps(dict(op=operation, **args)) + '\n').encode())
            with transport.makefile('rb') as stream:
                payload = stream.readline(2_000_000)
        if not payload:
            raise RuntimeError('Checkpoint worker closed the transport; inspect its private worker.log')
        response = json.loads(payload)
        if not response.get('ok'):
            raise RuntimeError(response.get('error', 'Checkpoint worker failed'))
        return response

    @contextmanager
    def running(self, binary: Path):
        with self.session.control():
            config = self.root / 'vmconfig.json'
            data = json.loads(config.read_text())
            phase_file=self.root/'phase.json'
            phase=json.loads(phase_file.read_text()).get('phase') if phase_file.exists() else 'checkpoint'
            if data.get('network-interfaces') or data['machine-config']['vcpu_count'] != 1:
                raise ValueError('Offline checkpoint guest must have no network and one vCPU')
            for drive in data['drives']:
                initial_install=(phase=='provision' and drive.get('drive_id')=='userdata'
                                 and drive.get('io_engine')=='Sync')
                if ((drive.get('io_engine') != 'Cow' and not initial_install) or
                        not Path(drive['path_on_host']).resolve().is_relative_to(self.root.resolve())):
                    raise ValueError('Guest drives must be private COW images inside this instance')
            if self.socket.exists():
                raise RuntimeError('Existing checkpoint socket requires ownership inspection before recovery')
            with (self.root / 'worker.log').open('ab') as log:
                self.process = subprocess.Popen([str(Path(binary).resolve()), str(config), str(self.socket)],
                                                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                try:
                    deadline = time.monotonic() + 15
                    while not self.socket.exists():
                        if self.process.poll() is not None:
                            raise RuntimeError('Checkpoint worker exited; inspect worker.log')
                        if time.monotonic() >= deadline:
                            raise TimeoutError('Checkpoint worker did not open its private socket')
                        time.sleep(.05)
                    self.request('status')
                    yield self
                finally:
                    if self.process.poll() is None:
                        try:
                            self.request('shutdown')
                            self.process.wait(timeout=5)
                        except (OSError, ValueError, RuntimeError, subprocess.TimeoutExpired):
                            self.process.terminate()
                            try:
                                self.process.wait(timeout=5)
                            except subprocess.TimeoutExpired:
                                self.process.kill()
                                self.process.wait(timeout=5)
                    self.socket.unlink(missing_ok=True)
                    self.process = None
                    self.arena_game_gate = False

    def command(self, text, *, timeout=30):
        if self.arena_game_gate:
            raise RuntimeError('Root command transport is inactive after game gate handover')
        identifier = self.request('command', text=text)['result']['id']
        return self._finish(identifier, timeout)

    def _finish(self, identifier, timeout):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.request('run', ms=100, timeout=5)['result']
            output = result.get('output')
            if output and output['id'] == identifier:
                return output
        raise TimeoutError('Guest command timed out; the worker remains available for inspection')

    def putfile(self, source: Path, destination: str):
        """Initial provisioning through guest RAM; no external guest connection."""
        if self.arena_game_gate:
            raise RuntimeError('Root file transport is inactive after game gate handover')
        total = 0
        with Path(source).open('rb') as stream:
            while chunk := stream.read(128 * 1024):
                identifier = self.request('upload', path=destination, offset=total, hex=chunk.hex())['result']['id']
                result = self._finish(identifier, 30)
                if result['exit_code'] or int(result['text']) != len(chunk):
                    raise RuntimeError('Guest upload did not write the complete chunk')
                total += len(chunk)
        return total
