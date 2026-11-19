"""Control original physics through the guest's Unity-thread VM barrier."""
from copy import deepcopy
import base64
import json
import time
from arena_checkpoint_errors import NativeIntervalError

GATE_CODE = 0x47415445
CONTROL = '/data/media/0/Android/data/com.pandadastudio.ninjamustdie3/files/arena-control'


class GameGate:
    def __init__(self, vm):
        if vm.session.spec.name != 'arena-search':
            raise ValueError('The game gate requires the named search guest')
        self.vm = vm
        self.view = None
        self.points = {}
        self.waiting = False

    def _wait(self, identity=None, timeout=60):
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline:
            result = self.vm.request('run', ms=100, timeout=5)['result']
            output = result.get('output')
            if not output or output.get('code') != GATE_CODE:
                continue
            if identity is not None and output['id'] != identity:
                raise RuntimeError('The game gate acknowledged an unexpected command')
            if output['exit_code']:
                raise RuntimeError(output['text'])
            self.view = json.loads(output['text'])
            if self.view.get('schema') != 1:
                raise ValueError('Unexpected game gate schema')
            self.waiting = False
            return self.view
        raise TimeoutError('Unity did not reach its game gate; inspect the last native job')

    def connect(self):
        # Do not wait on a root-agent response after arming: registration can
        # switch the selected mailbox before that response arrives.
        self.vm.arena_game_gate = True
        self.waiting = True
        self.vm.request('command', text=f'touch {CONTROL}/gate-arm')
        return self._wait()

    def call(self, operation, **arguments):
        if self.view is None:
            raise RuntimeError('Connect the game gate first')
        if self.waiting:
            raise RuntimeError('A game command is unfinished; restore a known gate point first')
        text = json.dumps(dict(op=operation, **arguments), ensure_ascii=True)
        if len(text.encode()) >= 4096:
            raise ValueError('Game gate command exceeds mailbox capacity')
        identity = self.vm.request('command', text=text)['result']['id']
        self.waiting = True
        self._wait(identity)
        last = self.view.get('last') or {}
        if not last.get('ok'):
            raise RuntimeError(last.get('error', 'Game gate operation failed'))
        return last.get('result')

    def step(self, ticks, action='none'):
        if type(ticks) is not int or not 1 <= ticks <= 600 or action not in ('none', 'jump', 'down'):
            raise ValueError('Use original ticks and an original input action')
        result = self.call('step', ticks=ticks, action=action)
        if result.get('error'):
            raise RuntimeError(result['error'])
        before = result.get('before', {}).get('episodeFrame')
        after = result.get('after', {}).get('episodeFrame')
        stopped = (self.view.get('state') or {}).get('episodeFrame')
        if type(before) is not int or type(after) is not int or not result.get('done'):
            raise RuntimeError('Native step did not return a completed physics interval')
        elapsed = after - before
        if stopped != after or not 0 <= elapsed <= ticks or (not result.get('terminated') and elapsed != ticks):
            raise NativeIntervalError(
                f'Native physics interval mismatch: requested {ticks}, advanced {elapsed}, stopped {stopped}',result)
        return result

    def render_step(self, frames, action='none'):
        """Validation clock; never convert the game's counter into milliseconds."""
        if type(frames)is not int or not 1<=frames<=120 or action not in ('none','jump','down'):
            raise ValueError('Use render frames and an original input action')
        job=self.call('exec',code=f'return MR3A.advance_render({frames},{json.dumps(action)})')
        if job.get('error'):raise RuntimeError(job['error'])
        before,after=job.get('before',{}),job.get('after',{})
        elapsed=after.get('frame',0)-before.get('frame',0)
        if (not job.get('done')or job.get('unit')!='unity_render_frame'
                or elapsed<1 or(not job.get('exited')and elapsed<frames)or elapsed>max(frames,2)
                or after.get('time',0)<=before.get('time',0)
                or self.view.get('state')!=after):
            raise NativeIntervalError('Invalid original render-clock interval',job)
        return job

    def screenshot(self):
        # Debug evidence from the guest renderer; normal search does not encode
        # images. Request chunks so a dense PNG cannot overflow the mailbox.
        self.call('exec', code="local E,U=MR3A,CS.UnityEngine;local C=E.checkpointGate;"
                  "C.image=nil;C.imageError=nil;E.busy=true;"
                  "local r=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger));"
                  "r:StartCoroutine(require('common/util').cs_generator(function()"
                  "coroutine.yield(U.WaitForEndOfFrame());local ok,err=pcall(function()"
                  "local t=U.Texture2D(U.Screen.width,U.Screen.height,U.TextureFormat.RGB24,false);"
                  "local previous=U.RenderTexture.active;U.RenderTexture.active=nil;"
                  "t:ReadPixels(U.Rect(0,0,U.Screen.width,U.Screen.height),0,0,false);"
                  "U.RenderTexture.active=previous;t:Apply(false,false);"
                  "C.image=CS.System.Convert.ToBase64String(U.ImageConversion.EncodeToPNG(t));"
                  "U.Object.Destroy(t)end);if not ok then C.imageError=tostring(err)end;E.busy=false end));return true")
        meta = self.call('exec', code="local C=MR3A.checkpointGate;assert(not C.imageError,C.imageError);"
                         "return {bytes=#C.image,width=CS.UnityEngine.Screen.width,height=CS.UnityEngine.Screen.height}")
        if not 8 <= meta['bytes'] <= 24 * 1024 * 1024:
            raise ValueError('Unexpected guest screenshot size')
        parts = []
        for offset in range(0, meta['bytes'], 160000):
            parts.append(self.call('exec', code=f'return string.sub(MR3A.checkpointGate.image,{offset + 1},{offset + 160000})'))
        encoded = ''.join(parts)
        if len(encoded) != meta['bytes']:
            raise ValueError('Incomplete guest screenshot')
        data = base64.b64decode(encoded, validate=True)
        if not data.startswith(b'\x89PNG\r\n\x1a\n'):
            raise ValueError('Invalid native PNG')
        return data

    def snapshot(self):
        if self.view is None or self.waiting:
            raise RuntimeError('Snapshot only after reaching the game gate')
        result = self.vm.request('snapshot', timeout=20)
        self.points[result['result']['id']] = deepcopy(self.view)
        return result

    def restore(self, identity):
        if identity not in self.points:
            raise ValueError('Only snapshots taken through this active game gate may be restored')
        # Cold file-backed histories have measured seconds-long tails. Keep
        # waiting on this one request instead of dropping its socket and then
        # enqueuing a second restore whose ordering is no longer known.
        timeout=180 if getattr(self.vm,'capabilities',{}).get('file_ram')else 20
        result = self.vm.request('restore', id=identity, timeout=timeout)
        self.view = deepcopy(self.points[identity])
        self.waiting = False
        return result

    def drop(self, identity):
        if identity not in self.points:
            raise ValueError('Unknown game gate snapshot')
        self.vm.request('drop', id=identity)
        del self.points[identity]

    def rebase(self):
        if self.view is None or self.waiting:
            raise RuntimeError('Rebase only at a stopped game gate')
        if not self.vm.request('status')['result'].get('can_rebase'):
            raise RuntimeError('This running worker does not support RAM rebasing')
        config = json.loads((self.vm.root / 'vmconfig.json').read_text())
        needed = config['machine-config']['mem_size_mib'] * 1024 * 1024 + 512 * 1024 * 1024
        with open('/proc/meminfo') as stream:
            info = dict(line.split(':', 1) for line in stream)
        available = int(info['MemAvailable'].split()[0]) * 1024
        if available < needed:
            raise RuntimeError('Insufficient spare RAM to build a new baseline safely')
        result = self.vm.request('rebase', timeout=30)
        self.points = {result['result']['id']: deepcopy(self.view)}
        return result
