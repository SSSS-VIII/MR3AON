"""真实断网截图回放：背景仍有继续时，优先点击网络框里的确认。"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]
NODE = '3v3网络异常点击重试'


@pytest.mark.parametrize('case', ['popup', 'no_title', 'no_message', 'no_button', 'only_continue'])
def test_network_popup_requires_dialog_and_targets_its_button(case):
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), case],
                            cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report['hit'] is (case == 'popup')
    # 保留原故障条件：普通继续仍能命中背景，必须由优先分支挡住。
    assert report['background_continue'] is True
    if case == 'popup':
        x, y, width, height = report['box']
        assert 535 <= x < x + width <= 750
        assert 495 <= y < y + height <= 565
        assert report['priority_box'] == report['box']


def test_network_branch_precedes_continues_and_returns_to_original_flow():
    pipeline = json.loads((ROOT / 'assets/resource/pipeline/3v3.json').read_text())
    parents = ['3v3确定进入了作战页面', '识别并点击3v3', '3v3观战返回等待消失']
    parents += [f'3v3_boss战斗循环_{i}' for i in range(5)]
    for parent in parents:
        assert pipeline[parent]['next'][0] == '[JumpBack]' + NODE
    assert pipeline[NODE]['action'] == {'type': 'Click'}
    assert pipeline[NODE]['next'] == []
    assert pipeline[NODE]['post_delay'] == 2000


def _replay(case):
    import tempfile
    import numpy as np
    from PIL import Image
    from maa.define import LoggingLevelEnum
    from maa.library import Library
    from maa.pipeline import JAnd, JOCR, JOr
    from maa.resource import Resource
    from maa.tasker import Tasker

    image = np.asarray(Image.open(ROOT / 'tests/fixtures/network_popup/3v3_timeout.png').convert('RGB'))[:, :, ::-1].copy()
    if case == 'no_title': image[245:320, 470:810] = 0
    if case == 'no_message': image[320:455, 350:930] = 0
    if case == 'no_button': image[480:575, 480:800] = 0
    if case == 'only_continue': image[:650] = 0
    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory(prefix='mr3a-3v3-network-') as logs:
        Tasker.set_log_dir(logs)
        resource = Resource()
        assert resource.post_bundle(str(ROOT / 'assets/resource')).wait().succeeded
        tasker = Tasker()
        assert Library.framework().MaaTaskerBindResource(tasker._handle, resource._handle)
        pipeline = json.loads((ROOT / 'assets/resource/pipeline/3v3.json').read_text())
        rule = pipeline[NODE]['recognition']
        detail = tasker.post_recognition('And', JAnd(**rule['param']), image).wait().get().nodes[0].recognition
        background_rule = pipeline['3v3继续0']['recognition']
        background = tasker.post_recognition('OCR', JOCR(**background_rule['param']), image).wait().get().nodes[0].recognition
        priority = tasker.post_recognition('Or', JOr(any_of=[NODE, '3v3继续0']), image).wait().get().nodes[0].recognition
        report = {'hit': detail.hit, 'box': list(detail.box) if detail.box else None,
                  'background_continue': background.hit, 'priority_box': list(priority.box) if priority.box else None}
        del tasker, resource
    print(json.dumps(report))


if __name__ == '__main__':
    _replay(sys.argv[1])
