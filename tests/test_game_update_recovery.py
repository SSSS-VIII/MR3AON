"""11-19真实重启更新弹窗的原生识别与恢复路由。"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('case', ['present', 'no_title', 'no_button'])
def test_native_restart_update_requires_title_and_button(case):
    result = subprocess.run([sys.executable, __file__, case], cwd=ROOT,
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    assert json.loads(result.stdout.strip().splitlines()[-1]) == [case == 'present'] * 3


def test_update_recovery_preserves_startup_boundary_and_restarts_timed_out_business():
    def load(name):
        return json.loads((ROOT/'assets/resource/pipeline'/name).read_text())
    startup = load('启动游戏.json')
    assert '启动游戏处理重启更新' in startup['启动流程']['next']
    assert startup['启动游戏处理重启更新']['action']['param']['custom_action'] == 'DisarmGameProcessWatch'
    assert startup['启动游戏处理重启更新']['next'] == ['启动游戏点击重启更新']
    assert startup['启动游戏点击重启更新']['action']['type'] == 'Click'
    assert startup['启动游戏点击重启更新']['next'] == ['闪退后重新拉起应用']
    back = load('back.json')
    assert back['游戏有更新需重启']['next'] == ['重启游戏']
    assert back['重启游戏']['next'] == ['AgentSchedulerRecoveryStop']
    assert load('Default_on_error.json')['Default_on_error']['next'][0] == '游戏有更新需重启'
    intelligence = load('情报模拟战.json')
    assert intelligence['情报模拟战导航']['next'][0] == '游戏有更新需重启'
    timeout = intelligence['情报模拟战总超时']
    assert timeout.get('action', {}).get('param', {}).get('custom_action') != 'AbortTasker'
    assert timeout['next'] == ['重启游戏']


def _replay(case):
    import tempfile
    import numpy as np
    from PIL import Image
    from maa.define import LoggingLevelEnum
    from maa.library import Library
    from maa.pipeline import JAnd
    from maa.resource import Resource
    from maa.tasker import Tasker

    image = np.asarray(Image.open(ROOT/'tests/fixtures/game_update/restart_required.png').convert('RGB'))[:, :, ::-1].copy()
    if case == 'no_title':
        image[270:360, 400:900] = 0
    elif case == 'no_button':
        image[475:575, 480:810] = 0
    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory(prefix='mr3a-game-update-') as logs:
        Tasker.set_log_dir(logs)
        resource = Resource()
        assert resource.post_bundle(str(ROOT/'assets/resource')).wait().succeeded
        tasker = Tasker()
        assert Library.framework().MaaTaskerBindResource(tasker._handle, resource._handle)
        back = json.loads((ROOT/'assets/resource/pipeline/back.json').read_text())
        startup = json.loads((ROOT/'assets/resource/pipeline/启动游戏.json').read_text())
        hits = []
        for node in [back['游戏有更新需重启'], startup['启动游戏处理重启更新'], startup['启动游戏点击重启更新']]:
            result = tasker.post_recognition('And', JAnd(**node['recognition']['param']), image).wait().get().nodes[0].recognition
            hits.append(result.hit)
            if result.hit:
                x, y, w, h = result.box
                assert 480 <= x < x+w <= 810 and 475 <= y < y+h <= 575
        del tasker, resource
    print(json.dumps(hits))


if __name__ == '__main__':
    _replay(sys.argv[1])
