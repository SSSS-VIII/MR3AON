"""Original offline Lua bridge inside the leased arena-search guest.

The transport runs the guest and uses its private files; it does not attach to
Waydroid, forward ports, replace gameplay, or restore individual Lua fields.
"""
import base64
import json
from pathlib import Path
import re
import tempfile
import time
import uuid

PACKAGE = 'com.pandadastudio.ninjamustdie3'
CONTROL = f'/data/media/0/Android/data/{PACKAGE}/files/arena-control'
STAGING = '/data/local/tmp/arena-search'


class CheckpointClient:
    def __init__(self, vm):
        if vm.session.spec.name != 'arena-search':
            raise ValueError('Client transport requires the named search guest')
        self.vm = vm
        self._uid = None

    def shell(self, command, timeout=30):
        if getattr(self.vm, 'arena_game_gate', False):
            raise RuntimeError('Root mailbox is inactive after the Unity game gate is armed')
        result = self.vm.command(command, timeout=timeout)
        if result['exit_code']:
            raise RuntimeError(f"Guest command exited {result['exit_code']}: {result['text']}")
        return result['text']

    def uid(self):
        if self._uid is not None:
            return self._uid
        result = self.shell(f'cmd package list packages -U {PACKAGE}')
        match = re.search(rf'^package:{re.escape(PACKAGE)} uid:(\d+)$', result, re.M)
        if not match:
            raise RuntimeError('Original client is not installed in the search guest')
        self._uid = int(match[1])
        return self._uid

    def wait_android(self, timeout=240):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            self.vm.request('run', ms=5000)
            status = self.vm.command('@status')
            if 'runtime=0' not in status['text']:
                continue
            if self.shell('getprop sys.boot_completed').strip() == '1':
                return
        raise TimeoutError('Android did not complete boot; do not start package installation yet')

    def execute(self, code, timeout=30):
        if getattr(self.vm, 'arena_game_gate', False):
            raise RuntimeError('Root file bridge is inactive after game gate handover')
        if not isinstance(code, str) or len(code.encode()) >= 1048576:
            raise ValueError('Lua command must be smaller than 1 MiB')
        identity = uuid.uuid4().hex
        destination = f'{STAGING}/command-{identity}.json'
        with tempfile.TemporaryDirectory(prefix='mr3a-checkpoint-command-') as folder:
            source = Path(folder) / 'command.json'
            source.write_text(json.dumps(dict(id=identity, code=code)), encoding='utf8')
            self.vm.putfile(source, destination)
        owner = self.uid()
        temporary = f'{CONTROL}/command-{identity}.tmp'
        self.shell(f'cp {destination} {temporary} && chown {owner}:1078 {temporary} && '
                   f'chmod 660 {temporary} && mv {temporary} {CONTROL}/command.json && rm {destination}')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            text = self.shell(f'if test -f {CONTROL}/result.json; then cat {CONTROL}/result.json; fi')
            try:
                result = json.loads(text)
            except ValueError:
                continue
            if result.get('id') != identity:
                continue
            self.shell(f'rm -f {CONTROL}/command.json')
            if not result.get('ok'):
                raise RuntimeError(result.get('error', 'Original Lua bridge command failed'))
            return result.get('result')
        raise TimeoutError('Original client bridge did not acknowledge the command')

    def load_environment(self):
        modules = ('environment', 'native_mount', 'native_selection', 'native_boss', 'native_menu')
        # The provisioned resource image is immutable and can contain older
        # control scripts. Load the current host tools through the existing
        # pre-gate file bridge; never silently ignore initialization/clock fixes.
        source = Path(__file__).resolve().parents[2] / 'arena/Local'
        code = ';'.join('assert(load(' + json.dumps((source / f'{name}.lua').read_text(),ensure_ascii=False) +
                        ",'@mr3a-" + name + "'))()" for name in modules)
        return self.execute(code + ';return MR3A.state()')

    def screenshot(self):
        path = f'{STAGING}/frame.png'
        self.shell(f'screencap -p {path}')
        size = int(self.shell(f'stat -c %s {path}').strip())
        if not 8 <= size <= 16 * 1024 * 1024:
            raise ValueError('Unexpected guest screenshot size')
        chunks = []
        for offset in range(0, size, 65536):
            text = self.shell(f'dd if={path} bs=65536 skip={offset // 65536} count=1 2>/dev/null | base64')
            chunks.append(base64.b64decode(text))
        data = b''.join(chunks)
        if len(data) != size or not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Incomplete guest screenshot')
        return data

    def wait_job(self, name, timeout=120):
        if not re.fullmatch(r'[A-Za-z][A-Za-z0-9_]*', name):
            raise ValueError('Expected an original environment job name')
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.execute(f'return MR3A.{name}')
            if result and result.get('done'):
                if result.get('error'):
                    raise RuntimeError(result['error'])
                return result
        raise TimeoutError(f'Original {name} did not finish')

    def advance(self, ticks, action='none'):
        if type(ticks) is not int or not 1 <= ticks <= 600 or action not in ('none', 'jump', 'down'):
            raise ValueError('Use 1..600 original physics ticks and a supported action')
        self.execute(f'return MR3A.advance({ticks},{json.dumps(action)})')
        return self.wait_job('job')
