"""失败结算真实画面回放：有本轮参与授权才能点确定，成功战报继续兼容。"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('case', ['failed', 'success', 'old_rule', 'inactive', 'no_title', 'no_button'])
def test_native_receiver_settlement_handles_short_failure_title(case):
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), case],
                            cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report['hit'] is (case in {'failed', 'success'})
    assert report['confirm_hit'] == report['hit']
    if report['hit']:
        x, y, width, height = report['box']
        assert 521 <= x < x + width <= 767
        assert 408 <= y < y + height <= 717


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
    label = 'success' if case == 'success' else 'failed'
    folder = ROOT / 'tests/fixtures/bounty_settlement'
    if case != 'no_title':
        image[20:140, 430:880] = np.asarray(Image.open(folder/f'{label}_title.png').convert('RGB'))[:, :, ::-1]
    if case != 'no_button':
        image[408:717, 521:767] = np.asarray(Image.open(folder/f'{label}_button.png').convert('RGB'))[:, :, ::-1]
    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory(prefix='mr3a-bounty-settlement-') as logs:
        Tasker.set_log_dir(logs)
        resource = Resource()
        assert resource.post_bundle(str(ROOT/'assets/resource')).wait().succeeded
        # IPC授权另由桥接单测验证；此处分别模拟有/无本轮参与资格。
        guard = {'type': 'DirectHit'} if case != 'inactive' else {
            'type': 'OCR', 'param': {'roi': [0,0,50,20], 'expected': ['^无本轮参与许可$']}}
        assert resource.override_pipeline({'悬赏小号本轮参与': {'recognition': guard}})
        if case == 'old_rule':
            assert resource.override_pipeline({'悬赏小号结算标题': {
                'recognition': {'param': {'expected': ['每日悬赏|讨伐失败|恭喜获得']}}}})
        tasker = Tasker()
        assert Library.framework().MaaTaskerBindResource(tasker._handle, resource._handle)
        pipeline = json.loads((ROOT/'assets/resource/pipeline/每日悬赏小号.json').read_text())
        def recognize(node):
            rule=pipeline[node]['recognition']
            return tasker.post_recognition('And', JAnd(**rule['param']), image).wait().get().nodes[0].recognition
        entry=recognize('悬赏小号战后确认入口')
        confirm=recognize('悬赏小号结算确认')
        report={'hit':entry.hit, 'confirm_hit':confirm.hit, 'box':list(entry.box) if entry.box else None}
        del tasker, resource
    print(json.dumps(report))


if __name__ == '__main__':
    _replay(sys.argv[1])
