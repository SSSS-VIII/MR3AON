import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from custom.action.workshop_challenge import quest_kind
from custom.persistent_task_state import next_weekly_reset


@pytest.mark.parametrize('text,kind', [
    ('单人游玩3张本周挑战地图', 'maps'),
    ('累计单人游玩10次本周挑战地图', 'repeat'),
    ('查看本周轮换的地图', 'view'),
    ('分享一次本周挑战地图', 'share'),
    ('单人通关3张本周挑战地图', None),
    ('单人通关任意1张本周挑战地图', None),
    ('累计单人通关10次', None),
])
def test_workshop_goals_exclude_clear_requirements(text, kind):
    assert quest_kind(text) == kind


@pytest.mark.parametrize('date,target', [
    ('2026-11-02T10:00', '2026-11-07T05:00'),
    ('2026-11-07T10:00', '2026-11-14T05:00'),
    ('2026-11-08T10:00', '2026-11-14T05:00'),
])
def test_workshop_persists_until_next_saturday(date, target):
    pipeline = json.loads(Path('assets/resource/pipeline/工坊挑战.json').read_text())
    param = pipeline['登记工坊挑战本周结束']['action']['param']['custom_action_param']
    now = datetime.fromisoformat(date).replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    assert param['enabled'] is False
    assert param['valid_until'] == 'next_weekly_reset'
    assert next_weekly_reset(now, param['weekday']).isoformat(timespec='minutes') == target + '+08:00'
