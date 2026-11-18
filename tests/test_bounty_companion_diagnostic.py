"""准备失败诊断复用原生识别帧，不追加设备请求或改变组队期限。"""
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
from PIL import Image

from custom.action.loop_deadline import LoopDeadlineArm, LoopDeadlineReset
from custom.loop_deadline.store import LoopDeadlineStore
from custom.reco.loop_deadline import LoopDeadlineExpired

PIPELINE = json.loads((Path(__file__).resolve().parents[1] /
                       'assets/resource/pipeline/每日悬赏小号.json').read_text())
ARM = PIPELINE['悬赏小号设置准备截图时限']
DUMP = PIPELINE['悬赏小号准备未完成截图']


def test_diagnostic_runs_before_repeated_prepare_and_before_parent_timeout():
    assert PIPELINE['悬赏小号设置组队时限']['next'] == ['悬赏小号设置准备截图时限']
    assert ARM['next'] == ['悬赏小号等待队伍']
    branches = PIPELINE['悬赏小号等待队伍']['next']
    assert branches.index('悬赏小号战斗开始') < branches.index('悬赏小号准备未完成截图')
    assert branches.index('悬赏小号准备未完成截图') < branches.index('悬赏小号点击准备')
    assert ARM['action']['param']['custom_action_param']['duration_ms'] == 5000
    assert DUMP['next'] == DUMP['on_error'] == ARM['on_error'] == ['悬赏小号等待队伍']
    assert PIPELINE['悬赏小号设置组队时限']['action']['param']['custom_action_param']['duration_ms'] == 120000


@pytest.mark.parametrize('save_fails', [False, True])
def test_stalled_preparation_saves_full_frame_once_and_continues(monkeypatch, tmp_path, save_fails):
    now = [100.0]
    monkeypatch.setattr('custom.loop_deadline.store.time.perf_counter', lambda: now[0])
    monkeypatch.setattr('custom.reco.loop_deadline._EXPIRED_DUMP_DIR', tmp_path)
    if save_fails:
        monkeypatch.setattr(Image.Image, 'save', lambda *_: (_ for _ in ()).throw(OSError('disk full')))
    from custom.reco import loop_deadline
    save = Mock(wraps=loop_deadline._save_expired_screenshot)
    monkeypatch.setattr(loop_deadline, '_save_expired_screenshot', save)
    task_id = 981119
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[:] = [11, 22, 33]  # Maa识别帧是BGR，保存为RGB。
    args = SimpleNamespace(task_detail=SimpleNamespace(task_id=task_id), image=image,
                           custom_action_param=ARM['action']['param']['custom_action_param'],
                           custom_recognition_param=DUMP['recognition']['param']['custom_recognition_param'])
    try:
        for expected_saves, round_start in enumerate((100.0, 110.0), start=1):
            now[0] = round_start
            assert LoopDeadlineArm().run(None, args).success
            now[0] += 4.99
            assert LoopDeadlineExpired().analyze(None, args) is None
            now[0] = round_start + 5.0
            assert LoopDeadlineExpired().analyze(None, args) is not None
            assert LoopDeadlineExpired().analyze(None, args) is not None
            assert save.call_count == expected_saves
            args.custom_action_param = DUMP['action']['param']['custom_action_param']
            assert LoopDeadlineReset().run(None, args).success
            assert LoopDeadlineExpired().analyze(None, args) is None
            args.custom_action_param = ARM['action']['param']['custom_action_param']
        screenshots = list(tmp_path.glob('*.png'))
        if save_fails:
            assert not screenshots
        else:
            assert 1 <= len(screenshots) <= 2  # 测试冻结在同一毫秒时允许同名覆盖。
            with Image.open(screenshots[-1]) as saved:
                assert saved.size == (1280, 720)
                assert saved.getpixel((1279, 719)) == (33, 22, 11)
    finally:
        LoopDeadlineStore.reset(task_id)
