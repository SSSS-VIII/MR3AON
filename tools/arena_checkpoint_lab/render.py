"""Keep the isolated software renderer small without skipping native frames."""
import json
from pathlib import Path
import shutil
import time

INFO = ('return {width=CS.UnityEngine.Screen.width,height=CS.UnityEngine.Screen.height,'
        'interval=CS.UnityEngine.Rendering.OnDemandRendering.renderFrameInterval}')


def selection_command(command):
    """Keep the isolated guest small while original reset/travel is busy.

    The gate cannot take another command until native selection finishes.
    Observe its original coroutine locally instead of overwriting an in-flight
    gate request. Reset can reapply 1920x1080 after the initial 320x180 request.
    This coroutine requests the same aspect, never additional game steps.
    """
    return r'''local result=(function()
''' + command + r'''
end)()
local E,U=MR3A,CS.UnityEngine
local travel=E.travel
local report={requests=0,observations=0,original_travel=travel}
E.checkpointSelectionRender=report
local runner=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger))
runner:StartCoroutine(require('common/util').cs_generator(function()
    while E.travel==travel and not travel.done do
        local w,h=U.Screen.width,U.Screen.height
        report.observations=report.observations+1
        report.effective={width=w,height=h,interval=U.Rendering.OnDemandRendering.renderFrameInterval}
        if report.effective.interval~=1 or w*180~=h*320 or w<=0 then
            report.error='Native selection requires every rendered frame and original 16:9 aspect'
            return
        end
        if w~=320 or h~=180 then
            U.Screen.SetResolution(320,180,true)
            report.requests=report.requests+1
        end
        coroutine.step()
    end
    report.done=true
end))
return result'''


def prepare(gate):
    before = gate.call('exec', code=INFO)
    if before['interval'] != 1 or before['width'] * 180 != before['height'] * 320:
        raise RuntimeError('Search requires every rendered frame and the original 16:9 aspect')
    if (before['width'], before['height']) != (320, 180):
        gate.call('exec', code='CS.UnityEngine.Screen.SetResolution(320,180,true);return true')
    # Unity applies its resolution request on the next original frame. Do not
    # manufacture an extra physics tick or replace the existing step driver.
    return dict(before=before, requested=dict(width=320, height=180, interval=1))


def verify(gate, output):
    """Compare native fields across the same 60-tick input branch at both sizes."""
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    original = gate.call('exec', code=INFO)
    if (original['width'], original['height'], original['interval']) != (1920, 1080, 1):
        raise ValueError('The parity check begins at the original 1920x1080 scene')
    root = gate.snapshot()
    report = dict(pass_=False, game_rollback_complete=False, uses_restart_replay=False,
                  root=root, original=original, branches=[], scope='Finite native fields; image resolution intentionally differs')
    actions = ['none', 'jump', 'none', 'down', 'none'] * 4
    try:
        for reduced in (False, True):
            gate.restore(root['result']['id'])
            if reduced:
                report['request'] = prepare(gate)
            rows = []
            started = time.monotonic()
            for index, action in enumerate(actions):
                job = gate.step(3, action)
                rows.append(dict(job=job, native=gate.call('probe')))
                if index % 5 == 4:
                    print(f'分辨率原生对照 {"320" if reduced else "1920"}: {index + 1}/20', flush=True)
            report['branches'].append(dict(reduced=reduced, seconds=time.monotonic() - started,
                                           effective=gate.call('exec', code=INFO), rows=rows))
        normal, small = report['branches']
        report['checks'] = dict(each_native_interval_equal=normal['rows'] == small['rows'],
                                requested_size_applied=small['effective'] == dict(width=320, height=180, interval=1))
        report['pass_'] = all(report['checks'].values())
        gate.restore(root['result']['id'])
        return report
    except BaseException as error:
        report['error'] = repr(error)
        gate.restore(root['result']['id'])
        raise
    finally:
        for name in ('render.py', 'gate.py', 'game_gate.lua', 'worker.rs'):
            shutil.copy2(Path(__file__).parent / name, output / name)
        (output / 'report.json').write_text(json.dumps(report, ensure_ascii=False, indent=2))
