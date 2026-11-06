"""深渊周五时间边界与实际延后动作回归，使用固定时钟而非游戏设备。"""
from datetime import datetime
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock
from zoneinfo import ZoneInfo

import pytest

from custom.action import deferred_tasks as scheduler
from custom.reco import time_check

RESOURCE = Path(__file__).resolve().parents[1] / 'assets/resource'


@pytest.mark.parametrize('when, wait, expected, delay', [
    ('2026-11-06T19:55:00', True, '深渊挑战挂起到八点', 300),
    ('2026-11-06T19:59:59', True, '深渊挑战挂起到八点', 1),
    ('2026-11-06T20:00:00', True, '深渊挑战在目标时间范围开始深渊挑战', None),
    ('2026-11-06T20:59:59', True, '深渊挑战在目标时间范围开始深渊挑战', None),
    ('2026-11-06T21:00:00', True, '深渊挑战当前时间大于21点00', None),
    ('2026-11-06T19:30:00', False, '深渊挑战挂起到八点', 1800),
    ('2026-11-06T19:59:59', False, '深渊挑战挂起到八点', 1),
    ('2026-11-06T20:00:00', False, '深渊挑战在目标时间范围开始深渊挑战', None),
    ('2026-11-05T19:30:00', True, '深渊挑战当前不为周五', None),
    ('2026-11-07T19:30:00', True, '深渊挑战当前不为周五', None),
])
def test_calendar_routes_release_queue_and_preserve_task_options(monkeypatch, when, wait, expected, delay):
    pipeline = json.loads((RESOURCE / 'pipeline/深渊挑战.json').read_text())
    tasks = json.loads((RESOURCE / 'tasks/常驻任务.json').read_text())
    case = next(c for c in tasks['option']['挂机等待至深渊挑战开启']['cases'] if c['name'] == ('Yes' if wait else 'No'))
    for name, value in case['pipeline_override'].items():
        pipeline[name].update(value)
    now = datetime.fromisoformat(when)
    monkeypatch.setattr(time_check, 'now_in_timezone', lambda tz: now.replace(tzinfo=ZoneInfo(tz)))
    class FixedDatetime(datetime):
        @classmethod
        def now(cls, tz=None):
            return now if tz is None else now.replace(tzinfo=tz)
    monkeypatch.setattr(scheduler, 'datetime', FixedDatetime)
    override = {'深渊挑战选卡时间': {'recognition': {'param': {'custom_recognition_param': {'time': '20:25'}}}}}
    monkeypatch.setattr(scheduler, 'pipeline_override_for_entry', lambda entry: override)
    arm = Mock()
    monkeypatch.setattr(scheduler.deferred_task_store, 'arm', arm)
    def matches(name):
        node = pipeline[name]
        if not node.get('enabled', True):
            return False
        recognition = node.get('recognition')
        if recognition is None:
            return True
        param = recognition['param']
        checker = getattr(time_check, param['custom_recognition'])()
        return checker.analyze(None, SimpleNamespace(custom_recognition_param=param['custom_recognition_param'])) is not None
    route = []
    name = next(n for n in pipeline['重置深渊挑战内部节点计数器']['next'] if matches(n))
    while True:
        route.append(name)
        node = pipeline[name]
        if name == '深渊挑战在目标时间范围开始深渊挑战':
            break
        if node.get('action', {}).get('type') == 'StopTask':
            break
        action = node.get('action', {}).get('param', {})
        if action.get('custom_action') == 'ScheduleDeferredTask':
            result = scheduler.ScheduleDeferredTask().run(None, SimpleNamespace(custom_action_param=action['custom_action_param']))
            assert result.success
        name = next(n.removeprefix('[JumpBack]') for n in node['next'] if matches(n.removeprefix('[JumpBack]')))
    assert expected in route
    if delay is not None:
        arm.assert_called_once_with(key='深渊挑战等待八点', entry='深渊挑战entry', delay_seconds=delay, pipeline_override=override)
        assert route[-1] == '深渊挑战挂起后结束'
        assert '登记深渊挑战每日完成' not in route
    else:
        arm.assert_not_called()
        if route[-1] != '深渊挑战在目标时间范围开始深渊挑战':
            assert '登记深渊挑战每日完成' in route
            completion = pipeline['登记深渊挑战每日完成']['action']['param']['custom_action_param']
            assert completion == {'entry': '深渊挑战entry', 'enabled': False, 'valid_until': 'next_daily_reset'}
    assert pipeline['深渊挑战调度未到八点']['next'] == ['深渊挑战挂起到八点']
    assert pipeline['深渊挑战当前时间小于20点']['recognition']['param']['custom_recognition_param']['time'] == '19:56'
    assert pipeline['停止深渊挑战任务']['action']['type'] == 'StopTask'
    assert pipeline['停止深渊挑战任务']['enabled'] is (not wait)
