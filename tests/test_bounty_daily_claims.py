"""耗尽悬赏次数后的领奖路线不依赖好友/家族补打开关。"""
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize('companion', [False, True])
@pytest.mark.parametrize('rewards', [0, 1, 3])
def test_exhausted_bounty_claims_all_available_tasks_before_exit(companion, rewards):
    pipeline = json.loads((ROOT/'assets/resource/pipeline/每日悬赏.json').read_text())
    if companion:
        for name in ['每日悬赏家族组队任务', '每日悬赏好友组队任务']:
            pipeline[name]['enabled'] = False
    scene = {'page': 'bounty', 'popup': False, 'remaining': rewards}
    trace = []

    def hit(name):
        if not pipeline[name].get('enabled', True):
            return False
        if name == '每日悬赏点击每日任务':
            return scene['page'] == 'bounty'
        if name == '每日悬赏收尾每日任务页面':
            return scene['page'] == 'tasks' and not scene['popup']
        if name == '每日悬赏每日任务领取奖励':
            return scene['page'] == 'tasks' and not scene['popup'] and scene['remaining'] > 0
        if name == '每日悬赏每日任务领取确定':
            return scene['popup']
        if name == '每日悬赏收尾关闭每日任务':
            return scene['page'] == 'tasks' and not scene['popup']
        return True

    def visit(name):
        trace.append(name)
        assert len(trace) < 50, trace
        if name == '每日悬赏返回悬赏令':
            assert scene == {'page': 'bounty', 'popup': False, 'remaining': 0}
            return
        if name == '每日悬赏点击每日任务':
            scene['page'] = 'tasks'
        elif name == '每日悬赏每日任务领取奖励':
            scene['remaining'] -= 1
            scene['popup'] = True
        elif name == '每日悬赏每日任务领取确定':
            scene['popup'] = False
        elif name == '每日悬赏收尾关闭每日任务':
            scene['page'] = 'bounty'
        while pipeline[name].get('next'):
            for candidate in pipeline[name]['next']:
                target = candidate.removeprefix('[JumpBack]')
                if hit(target):
                    visit(target)
                    if candidate.startswith('[JumpBack]'):
                        break  # 无next的领奖/确定返回当前分支列表。
                    return
            else:
                raise AssertionError(f'no matching next: {name}: {scene}')

    visit('每日悬赏奖励次数满了')
    assert '每日悬赏收尾每日任务页面' in trace
    assert trace.count('每日悬赏每日任务领取奖励') == rewards
    assert trace.count('每日悬赏每日任务领取确定') == rewards
    assert trace[-1] == '每日悬赏返回悬赏令'
    assert not set(trace) & {'每日悬赏家族组队任务', '每日悬赏好友组队任务', '开始每日悬赏'}
