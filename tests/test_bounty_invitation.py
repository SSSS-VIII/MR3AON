"""按11-16日志坐标构造的邀请弹窗回放；合成夹具，不是实机截图。"""
import json
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('case', ['authorized', 'old_roi', 'other_leader', 'no_permit'])
def test_native_invitation_preserves_full_left_edge_nickname(case):
    result = subprocess.run([sys.executable, __file__, case], capture_output=True,
                            text=True, timeout=60, cwd=ROOT)
    assert result.returncode == 0, result.stdout[-2500:] + result.stderr[-2500:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report['legal'] is (case == 'authorized')
    assert report['accept'] == report['legal']
    if case == 'authorized':
        assert report['inviter'] and report['friend_title']
        x, y, w, h = report['box']
        assert 700 <= x < x+w <= 920 and 490 <= y < y+h <= 570
    elif case == 'old_roi':
        assert not report['inviter']


def _replay(case):
    import tempfile
    import numpy as np
    from PIL import Image
    from maa.define import LoggingLevelEnum
    from maa.library import Library
    from maa.pipeline import JAnd, JOCR
    from maa.resource import Resource
    from maa.tasker import Tasker

    pipeline = json.loads((ROOT/'assets/resource/pipeline/每日悬赏小号.json').read_text())
    image = np.asarray(Image.open(ROOT/'tests/fixtures/bounty_invitation/left_edge_synthetic.png').convert('RGB'))[:, :, ::-1].copy()
    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory(prefix='mr3a-bounty-invitation-') as logs:
        Tasker.set_log_dir(logs)
        resource = Resource()
        assert resource.post_bundle(str(ROOT/'assets/resource')).wait().succeeded
        # 消息授权的真伪/期限另由桥接单测覆盖，此处只替换IPC识别。
        permit = {'type': 'DirectHit'} if case != 'no_permit' else {
            'type': 'OCR', 'param': {'roi': [0, 0, 20, 20], 'expected': ['不存在的许可']}}
        patch = {'悬赏小号邀请许可': {'recognition': permit},
                 '悬赏小号授权邀请人': {'recognition': {'param': {'expected': [
                     ('^其他队长$' if case == 'other_leader' else '^上杉家の红豆$')]}}}}
        if case == 'old_roi':
            patch['悬赏小号授权邀请人']['recognition']['param']['roi'] = [100, 242, 350, 44]
        assert resource.override_pipeline(patch)
        tasker = Tasker()
        assert Library.framework().MaaTaskerBindResource(tasker._handle, resource._handle)
        rule = pipeline['悬赏小号合法邀请']['recognition']['param']
        legal = tasker.post_recognition('And', JAnd(**rule), image).wait().get().nodes[0].recognition
        accept = tasker.post_recognition('And', JAnd(**pipeline['悬赏小号同意邀请']['recognition']['param']), image).wait().get().nodes[0].recognition
        inviter = pipeline['悬赏小号授权邀请人']['recognition']['param'].copy()
        inviter.update(patch['悬赏小号授权邀请人']['recognition']['param'])
        hit = tasker.post_recognition('OCR', JOCR(**inviter), image).wait().get().nodes[0].recognition.hit
        title = pipeline['悬赏小号好友邀请标题']['recognition']['param']
        friend = tasker.post_recognition('OCR', JOCR(**title), image).wait().get().nodes[0].recognition.hit
        report = {'legal': legal.hit, 'accept': accept.hit, 'inviter': hit, 'friend_title': friend,
                  'box': list(legal.box) if legal.box else None}
        del tasker, resource
    print(json.dumps(report))


if __name__ == '__main__':
    _replay(sys.argv[1])
