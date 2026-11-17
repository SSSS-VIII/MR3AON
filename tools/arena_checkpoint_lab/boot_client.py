"""Reproducible original-client startup in the existing leased KVM guest.

Cold initialization is separate from rollback: after the game gate connects,
search restores VM snapshots and never calls this startup/reset path.
"""
import json
from pathlib import Path
import time

from build_bridge import build
from client import CheckpointClient, PACKAGE, CONTROL, STAGING
from gate import GameGate

HERE = Path(__file__).resolve().parent
PRIVATE = f'/data/data/{PACKAGE}'


def provision(vm):
    """One initial installation; the caller must stop and switch to COW next."""
    if vm.request('status')['result']['checkpoint_enabled']:
        raise RuntimeError('Initial provisioning requires the explicit private Sync phase')
    client = CheckpointClient(vm)
    client.wait_android()
    client.shell(f'pm install -r -g --abi arm64-v8a /checkpoint-payload/client.apk 2>&1', timeout=240)
    uid = client.uid()
    files = f'/data/media/0/Android/data/{PACKAGE}/files'
    client.shell(f'set -e; set -o pipefail; mkdir -p {files}/DynamicContent {CONTROL} {STAGING}; '
                 f'cat /checkpoint-payload/assets.tar.* | tar -xf - -C {files}/DynamicContent; '
                 f'cp /checkpoint-payload/resource-key /checkpoint-payload/catalog-native.json {CONTROL}/; '
                 f'touch {CONTROL}/offline.json; chown -R {uid}:1078 {files}; '
                 f'chmod 2770 {CONTROL}; chmod 600 {CONTROL}/resource-key; sync', timeout=240)


def install_file(client, source, name, mode=400):
    staging = f'{STAGING}/{name}'
    client.vm.putfile(Path(source), staging)
    uid = client.uid()
    client.shell(f'cp {staging} {PRIVATE}/{name} && chown {uid}:{uid} {PRIVATE}/{name} && '
                 f'chmod {mode} {PRIVATE}/{name}')


def start(vm, *, seed=55200, chapter=1, level=5):
    if not vm.request('status')['result']['checkpoint_enabled']:
        raise RuntimeError('Start the search client only after all guest drives use COW')
    artifacts = build()
    client = CheckpointClient(vm)
    print('等待 arena-search 的 Android 完成启动……', flush=True)
    client.wait_android()
    if client.shell('getprop ro.debuggable').strip() != '1':
        raise RuntimeError('The native Java transport requires this userdebug Android guest')
    uid = client.uid()
    client.shell(f'set -e; test -s {CONTROL}/resource-key; test -s {CONTROL}/catalog-native.json; '
                 f'test -s /checkpoint-payload/bootstrap.lua; mkdir -p {STAGING}; '
                 f'am force-stop {PACKAGE}; rm -f {CONTROL}/command.json {CONTROL}/ready.json '
                 f'{CONTROL}/boot-launch.txt {CONTROL}/boot-loaded.txt {CONTROL}/boot-state.txt '
                 f'{CONTROL}/gate-arm; touch {CONTROL}/offline.json; chown {uid}:1078 {CONTROL}/offline.json')
    install_file(client, artifacts / 'java-transport.so', 'checkpoint-transport.so', 500)
    install_file(client, HERE / 'client_bootstrap.lua', 'checkpoint-early.lua')
    activity = client.shell(f'cmd package resolve-activity --brief {PACKAGE}').strip().splitlines()[-1]
    if not activity.startswith(PACKAGE + '/'):
        raise RuntimeError('Unexpected original client activity')
    print('启动原客户端与本地资源……', flush=True)
    result = client.shell(f'am start -n {activity} 2>&1')
    if 'Error:' in result:
        raise RuntimeError(result)
    for _ in range(4):
        vm.request('run', ms=5000)
    deadline = time.monotonic() + 180
    sent = False
    while time.monotonic() < deadline:
        if not sent:
            client.shell(f'am attach-agent {PACKAGE} {PRIVATE}/checkpoint-transport.so={PRIVATE}/checkpoint-early.lua')
        vm.request('run', ms=1000)
        text = client.shell(f'if test -s {CONTROL}/boot-launch.txt; then cat {CONTROL}/boot-launch.txt; fi')
        if text.startswith('ERROR'):
            raise RuntimeError(text)
        if text:
            break
        state = client.shell(f'if test -s {CONTROL}/boot-state.txt; then cat {CONTROL}/boot-state.txt; fi')
        sent = 'manifest=true' in state and (state.startswith('Logo: 2') or state.startswith('CheckPermission: 1'))
    else:
        raise TimeoutError('Original client did not initialize its local manifest')
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        vm.request('run', ms=1000)
        ready = client.shell(f'if test -s {CONTROL}/ready.json; then cat {CONTROL}/ready.json; fi')
        if ready:
            if not json.loads(ready).get('ready'):
                raise ValueError('Unexpected local bridge readiness file')
            break
    else:
        raise TimeoutError('Original Lua resource bridge did not load')
    client.execute('CS.Patch.Instance.CurrentState=CS.Patch.State.__CastFrom(100);return true')
    client.load_environment()
    # Preserve the aspect/frustum; native field parity is checked independently.
    client.execute('CS.UnityEngine.Screen.SetResolution(320,180,true);return true')
    client.execute(f'MR3A.seed={int(seed)};return MR3A.prepare({int(chapter)},{int(level)})')
    client.execute('return MR3A.load_audio()')
    client.wait_job('audio', timeout=180)
    print('加载原疾风关卡……', flush=True)
    client.execute('return MR3A.enter()')
    for attempt in range(3):
        try:
            client.wait_job('resetJob', timeout=180)
            break
        except RuntimeError as error:
            state = client.execute('return MR3A.state()')
            if 'Reset did not enter' not in str(error) or state['state'] != 'LoadingGame: 9' or attempt == 2:
                raise
            # Continue the same original asynchronous load, without a reset.
            client.execute('CS.UnityEngine.Time.timeScale=1;MR3A.wait_ready();return true')
    client.execute("assert(load(CS.System.IO.File.ReadAllText('/checkpoint-payload/rewind_probe.lua'),'@rewind-probe'))();return true")
    install_file(client, artifacts / 'game-gate.so', 'checkpoint-gate.so')
    install_file(client, artifacts / 'gate.jar', 'checkpoint-gate.jar')
    client.shell(f'am attach-agent {PACKAGE} {PRIVATE}/checkpoint-gate.so={PRIVATE}/checkpoint-gate.jar')
    vm.request('run', ms=1000)
    client.execute((HERE / 'game_gate.lua').read_text())
    gate = GameGate(vm)
    gate.connect()
    print('原游戏主线程已停在 VM gate，后续只用 gate.step / snapshot / restore。', flush=True)
    return gate
