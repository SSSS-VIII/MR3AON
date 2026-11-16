"""Optional same-frame Unity readback, with the original Android key transport.

Only rendered pixels/timestamps cross this channel. A shell-UID relay reaches
an authenticated game socket over loopback; game network prohibition remains.
"""
from pathlib import Path
import hashlib
import json
import math
import subprocess
import time

from arena_capture import FastCapture,Frame,read_exact,ROOT,PRIVATE
from arena_local import LocalClient

LUA=ROOT/'arena/Local/render_capture.lua'
JAVA=ROOT/'arena/Capture/RenderRelay.java'
BUILD=PRIVATE/'render-capture/build'


def build_relay():
    digest=hashlib.sha256(JAVA.read_bytes()).hexdigest()
    report=BUILD/'report.json';dex=BUILD/'dex/classes.dex'
    if report.is_file()and dex.is_file():
        saved=json.loads(report.read_text())
        if saved.get('source_sha256')==digest and saved.get('dex_sha256')==hashlib.sha256(dex.read_bytes()).hexdigest():
            return dex
    sdk=PRIVATE/'recovery-tools/android-build-tools'
    classes=BUILD/'classes';classes.mkdir(parents=True,exist_ok=True);dex.parent.mkdir(parents=True,exist_ok=True)
    subprocess.run(['java','-jar',str(PRIVATE/'recovery-tools/ecj-3.41.0.jar'),'-1.8',
                    '-bootclasspath',str(sdk/'android.jar'),'-d',str(classes),str(JAVA)],check=True,capture_output=True)
    inputs=sorted((classes/'dev/mr3a/arena').glob('RenderRelay*.class'))
    subprocess.run(['java','-cp',str(sdk/'d8.jar'),'com.android.tools.r8.D8','--lib',str(sdk/'android.jar'),
                    '--min-api','26','--output',str(dex.parent),*map(str,inputs)],check=True,capture_output=True)
    report.write_text(json.dumps(dict(source_sha256=digest,dex_sha256=hashlib.sha256(dex.read_bytes()).hexdigest()),indent=2)+'\n')
    return dex


def validate_header(header,expected_sequence):
    if not isinstance(header,dict):raise ValueError('Expected a render frame header')
    for key in ('sequence','frame','size'):
        if type(header.get(key))is not int:raise ValueError('Invalid integer render header')
    if header['sequence']!=expected_sequence or header['frame']<0 or header['size']!=640*360*4:
        raise ValueError('Invalid render geometry or sequence')
    for key in ('requested','eof','read_end','ready'):
        value=header.get(key)
        if isinstance(value,bool)or not isinstance(value,(int,float))or not math.isfinite(value):
            raise ValueError('Invalid render timestamp')
    if not 0<header['requested']<=header['eof']<=header['read_end']<=header['ready']:
        raise ValueError('Out-of-order render timestamps')
    return header


class RenderCapture(FastCapture):
    """Explicit research backend. The default runner still uses FastCapture.

    The native source clock is readback begin after WaitForEndOfFrame, not an
    exposure timestamp. Color orientation matches the old top-down RGBA frame.
    Key injection and clock calibration retain FastCapture's Android transport.
    """
    source_name='unity_render_readback'

    def __init__(self,session,*,width=640,height=360,timeout=2):
        if (width,height)!=(640,360):raise ValueError('Render capture requires 640x360')
        super().__init__(session,width=width,height=height,timeout=timeout)
        self._render_ready=False;self._render_sequence=0;self.render_cleanup=None
        self.render_cleanup_error=None

    def _cleanup_render(self):
        self._render_ready=False
        # ExitStack still owns the InstanceSession lease during this callback.
        try:
            self.render_cleanup=LocalClient(self.session).execute(
                'local r;if MR3A.render_capture_stop then r=MR3A.render_capture_stop()end;'
                'if MR3A.render_capture_uninstall then MR3A.render_capture_uninstall()end;return r',
                lease_held=True)
        except Exception as error:
            self.render_cleanup_error=repr(error)

    def __enter__(self):
        if self._stack is not None:raise RuntimeError('Capture is already open')
        self._render_ready=False;self._render_sequence=0
        dex=build_relay()
        super().__enter__()
        try:
            client=LocalClient(self.session)
            self._stack.callback(self._cleanup_render)
            client.execute('if MR3A.render_capture_uninstall then MR3A.render_capture_uninstall()end;return true',lease_held=True)
            info=client.execute(LUA.read_text().replace('token=TOKEN','token='+json.dumps(self.token)),lease_held=True)
            if not isinstance(info,dict)or(info.get('width'),info.get('height'))!=(640,360):
                raise ValueError('Invalid render capture handshake')
            port=info.get('port')
            if type(port)is not int or not 1024<=port<=65535:raise ValueError('Invalid game loopback port')
            remote='/data/local/tmp/mr3a-render-relay-'+hashlib.sha256(dex.read_bytes()).hexdigest()[:16]+'.dex'
            self.session.adb('push',str(dex),remote).check_returncode()
            command=f'CLASSPATH={remote} app_process / dev.mr3a.arena.RenderRelay {port} {self.token}'
            relay=self._stack.enter_context(self.session.adb_stream('shell','-T',command))
            deadline=time.monotonic()+5;line=b''
            while not line.endswith(b'\n')and len(line)<16:line+=read_exact(relay.stdout,1,deadline)
            relay_port=int(line.strip())
            self._render_socket=self._stack.enter_context(self.session.device_socket(relay_port,timeout=self.timeout))
            self._render_file=self._stack.enter_context(self._render_socket.makefile('rb'))
            self._render_socket.sendall(self.token.encode('ascii'))
            self._render_ready=True
            self.render_warmup_ms=[self.capture().request_ms for _ in range(3)]
            return self
        except Exception:
            self.close()
            raise

    def capture(self):
        if not self._render_ready:
            # FastCapture starts and warms its Android key/clock worker before
            # the render channel is installed. This is initialization only.
            return super().capture()
        try:
            self._sequence+=1;self._render_sequence+=1
            begin=time.perf_counter_ns();self._render_socket.sendall(b'\1')
            line=self._render_file.readline(4096)
            if not line.endswith(b'\n'):raise EOFError('Incomplete render header')
            header=validate_header(json.loads(line),self._render_sequence)
            self.last_render_header=dict(header)
            raw=self._render_file.read(header['size'])
            if len(raw)!=header['size']:raise EOFError('Incomplete render image')
            import numpy as np
            rgba=np.frombuffer(raw,np.uint8).reshape(360,640,4)[::-1].tobytes()
            end=time.perf_counter_ns()
            return Frame(640,360,self._sequence,begin,end,
                         round(header['requested']*1e9),round(header['eof']*1e9),round(header['ready']*1e9),rgba)
        except Exception:
            self.close()
            raise

    def paired_step(self,*args,**kwargs):
        raise RuntimeError('Render capture does not provide native paired collection')
