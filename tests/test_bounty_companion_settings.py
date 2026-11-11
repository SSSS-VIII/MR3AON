"""xiaoli真实设置/主页标题回放：不在设置页时禁止继续滑动。"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('case', ['settings', 'home'])
def test_native_settings_title_guards_entry_and_scroll(case):
    result = subprocess.run([sys.executable, __file__, case], capture_output=True,
                            text=True, timeout=60, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-2000:] + result.stderr[-2000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report == {'entry': case == 'settings', 'scroll': case == 'settings'}


def test_settings_title_miss_is_handled_by_the_clicking_parent():
    pipeline = json.loads((ROOT/'assets/resource/pipeline/每日悬赏小号.json').read_text())
    # Maa的next识别失败走父节点on_error，而非未进入节点自身的on_error。
    opened = pipeline['悬赏小号打开设置']
    assert opened['next'] == ['悬赏小号确认设置页']
    assert opened['timeout'] == 5000
    assert opened['on_error'] == ['悬赏小号恢复设置入口']
    recovery = pipeline['悬赏小号恢复设置入口']
    assert recovery['max_hit'] == 2
    assert recovery['next'] == ['悬赏小号从主页重开设置', '[JumpBack]back']
    assert pipeline['悬赏小号查找邀请设置']['next'][-1] == '悬赏小号恢复设置入口'


def _replay(case):
    import tempfile
    import numpy as np
    from PIL import Image
    from maa.define import LoggingLevelEnum
    from maa.library import Library
    from maa.pipeline import JAnd
    from maa.resource import Resource
    from maa.tasker import Tasker

    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[25:139, 563:718] = np.asarray(Image.open(
        ROOT/'tests/fixtures/bounty_settings'/f'{case}_title.png').convert('RGB'))[:, :, ::-1]
    pipeline = json.loads((ROOT/'assets/resource/pipeline/每日悬赏小号.json').read_text())
    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory(prefix='mr3a-bounty-settings-') as logs:
        Tasker.set_log_dir(logs)
        resource = Resource()
        assert resource.post_bundle(str(ROOT/'assets/resource')).wait().succeeded
        tasker = Tasker()
        assert Library.framework().MaaTaskerBindResource(tasker._handle, resource._handle)
        report = {}
        for key, name in [('entry', '悬赏小号确认设置页'), ('scroll', '悬赏小号设置上滑')]:
            rule = pipeline[name]['recognition']['param']
            if key == 'scroll':
                # Count另有桥接测试；这里单独验证即使有滑动额度也必须先确认设置。
                rule['all_of'][1] = {'recognition': 'DirectHit'}
            result = tasker.post_recognition('And', JAnd(**rule), image).wait().get()
            report[key] = result.nodes[0].recognition.hit
        del tasker, resource
    print(json.dumps(report))


if __name__ == '__main__':
    _replay(sys.argv[1])
