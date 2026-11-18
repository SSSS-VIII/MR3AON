"""Opt-in offline arena VM backend using the existing named-instance lease.

No Waydroid/ADB target or account configuration is created by this backend.
The VM control socket and all writable images belong to this named instance.
"""
from contextlib import contextmanager
import json
import errno
import os
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
        self.owner_file = self.root / 'worker-owner.json'
        self.process = None
        self.arena_game_gate = False
        self.capabilities = {}
        self.uncertain_operation = None

    @staticmethod
    def process_start(pid):
        try:return Path(f'/proc/{pid}/stat').read_text().rsplit(') ',1)[1].split()[19]
        except (FileNotFoundError,ProcessLookupError):return None

    def recover_orphan(self):
        """Remove a refused socket only after its recorded worker has exited."""
        if not self.session._owns_control:raise RuntimeError('Orphan recovery requires the named control lease')
        if not self.owner_file.exists():return False
        owner=json.loads(self.owner_file.read_text())
        actual=self.process_start(owner['pid'])
        if actual is not None and (owner.get('start')is None or actual==owner['start']):return False
        if self.socket.exists():
            with socket.socket(socket.AF_UNIX,socket.SOCK_STREAM)as probe:
                probe.settimeout(1)
                try:probe.connect(str(self.socket))
                except OSError as error:
                    if error.errno!=errno.ECONNREFUSED:raise
                else:return False
            self.socket.unlink()
        self.owner_file.unlink()
        return True

    def request(self, operation, *, timeout=10, **args):
        if not self.session._owns_control:
            raise RuntimeError('Checkpoint operations require the named instance control lease')
        if self.process is None or self.process.poll() is not None:
            raise RuntimeError('Checkpoint worker is not running')
        if self.uncertain_operation is not None:
            raise RuntimeError('Checkpoint transport has an unfinished '+self.uncertain_operation+'; stop this worker epoch')
        try:
            with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as transport:
                transport.settimeout(timeout)
                transport.connect(str(self.socket))
                transport.sendall((json.dumps(dict(op=operation, **args)) + '\n').encode())
                with transport.makefile('rb') as stream:
                    payload = stream.readline(2_000_000)
        except TimeoutError:
            self.uncertain_operation = operation
            raise
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
            if (self.socket.exists()or self.owner_file.exists())and not self.recover_orphan():
                raise RuntimeError('Existing checkpoint socket requires ownership inspection before recovery')
            with (self.root / 'worker.log').open('ab') as log:
                self.process = subprocess.Popen([str(Path(binary).resolve()), str(config), str(self.socket)],
                                                stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL)
                if getattr(self.process,'pid',None)is not None:
                    self.owner_file.write_text(json.dumps(dict(pid=self.process.pid,
                        start=self.process_start(self.process.pid),owner_pid=os.getpid())))
                try:
                    deadline = time.monotonic() + 15
                    while not self.socket.exists():
                        if self.process.poll() is not None:
                            raise RuntimeError('Checkpoint worker exited; inspect worker.log')
                        if time.monotonic() >= deadline:
                            raise TimeoutError('Checkpoint worker did not open its private socket')
                        time.sleep(.05)
                    self.capabilities = self.request('status')['result']
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
                                self.process.wait(timeout=30)
                    if self.process.poll() is not None:
                        self.socket.unlink(missing_ok=True)
                        self.process = None
                        self.arena_game_gate = False
                        self.capabilities = {}
                        self.uncertain_operation = None
                        self.owner_file.unlink(missing_ok=True)

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
