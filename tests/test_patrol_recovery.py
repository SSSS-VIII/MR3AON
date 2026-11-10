"""巡逻循环使用真实截止时间存储，重试不能延长总期限或误记完成。"""
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from custom.action.loop_deadline import LoopDeadlineArm
from custom.loop_deadline.store import LoopDeadlineStore
from custom.reco.loop_deadline import LoopDeadlineExpired

ROOT = Path(__file__).resolve().parents[1]
PIPELINE = json.loads((ROOT/'assets/resource/pipeline/通灵巡逻.json').read_text())


def test_repeated_home_navigation_expires_without_rearming(monkeypatch):
    now = [100.0]
    monkeypatch.setattr('custom.loop_deadline.store.time.perf_counter', lambda: now[0])
    monkeypatch.setattr('custom.reco.loop_deadline._save_expired_screenshot', lambda *_: None)
    task = SimpleNamespace(task_id=981031)
    arm = PIPELINE['通灵巡逻entry']['action']['param']
    args = SimpleNamespace(task_detail=task,
                           custom_action_param=json.dumps(arm['custom_action_param']))
    assert LoopDeadlineArm().run(None, args).success
    guard = PIPELINE['重置通灵巡逻内部节点计数器']['next'][0]
    rule = PIPELINE[guard]
    reco_args = SimpleNamespace(task_detail=task, image=None,
                               custom_recognition_param=json.dumps(
                                   rule['recognition']['param']['custom_recognition_param']))
    try:
        for seconds in (0, 60, 120, 179):
            now[0] = 100 + seconds
            assert LoopDeadlineExpired().analyze(None, reco_args) is None
        now[0] = 281
        assert LoopDeadlineExpired().analyze(None, reco_args) is not None
        assert rule['next'] == ['Default_on_error']
        # Guard is revisited on return from back; only the top-level entry arms.
        assert '通灵巡逻entry' not in PIPELINE['重置通灵巡逻内部节点计数器']['next']
    finally:
        LoopDeadlineStore.reset(task.task_id)


@pytest.mark.parametrize('node', ['忍阶任务页面_巡逻', '直接去巡逻', '选择额外食物'])
def test_crash_recovery_precedes_business_fallback(node):
    branch = PIPELINE[node]['on_error']
    assert branch[:2] == ['通灵巡逻总超时', '处理游戏闪退']
    assert PIPELINE['通灵巡逻任务出错']['next'] == ['Default_on_error']
