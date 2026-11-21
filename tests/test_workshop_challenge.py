import json
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest


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
    import re
    pipeline = json.loads(Path('assets/resource/pipeline/工坊挑战.json').read_text())
    patterns = [pattern for label in ('三张游玩', '累计十次', '查看轮换', '分享地图')
                for pattern in pipeline[f'工坊{label}文案']['recognition']['param']['expected']]
    assert any(re.search(pattern, text) for pattern in patterns) is (kind is not None)


@pytest.mark.parametrize('date,target', [
    ('2026-11-02T10:00', '2026-11-07T05:00'),
    ('2026-11-07T10:00', '2026-11-14T05:00'),
    ('2026-11-08T10:00', '2026-11-14T05:00'),
])
def test_workshop_persists_until_next_saturday(date, target):
    from custom.persistent_task_state import next_weekly_reset
    pipeline = json.loads(Path('assets/resource/pipeline/工坊挑战.json').read_text())
    param = pipeline['登记工坊挑战本周结束']['action']['param']['custom_action_param']
    now = datetime.fromisoformat(date).replace(tzinfo=ZoneInfo('Asia/Shanghai'))
    assert param['enabled'] is False
    assert param['valid_until'] == 'next_weekly_reset'
    assert next_weekly_reset(now, param['weekday']).isoformat(timespec='minutes') == target + '+08:00'


@pytest.mark.parametrize('case', ['eligible', 'only_clear_reward', 'no_claim_button', 'claimed_row', 'missing_claimed_status', 'flags_pending', 'flags_three', 'flags_all', 'fallback_clear', 'no_rewards', 'intro', 'intro_without_button', 'entry_icon', 'entry_icon_lower', 'entry_icon_shifted', 'entry_live', 'entry_live_1121', 'entry_live_1121_old_template', 'entry_icon_lower_old_roi', 'detail_right', 'share_right', 'detail_old_roi', 'share_old_roi', 'share_channel_right', 'share_wide_1121', 'share_wide_old_roi_1121'])
def test_native_task_row_pairing(case):
    import subprocess
    import sys
    result = subprocess.run([sys.executable, str(Path(__file__).resolve()), case],
                            capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout[-3000:] + result.stderr[-3000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report['hit'] is (case in {'eligible', 'only_clear_reward', 'claimed_row', 'flags_all', 'fallback_clear', 'intro', 'entry_icon', 'entry_icon_lower', 'entry_icon_shifted', 'entry_live', 'entry_live_1121', 'detail_right', 'share_right', 'share_channel_right', 'share_wide_1121'})
    if case == 'eligible' and report['hit']:
        x, y, width, height = report['box']
        assert 980 <= x < x + width <= 1240
        assert 630 <= y < y + height <= 720


def _native_replay(case):
    import tempfile
    import numpy as np
    from PIL import Image
    from maa.define import LoggingLevelEnum
    from maa.library import Library
    from maa.pipeline import JAnd, JOr, JOCR, JTemplateMatch
    from maa.resource import Resource
    from maa.tasker import Tasker
    root = Path(__file__).resolve().parents[1]
    image = np.zeros((720, 1280, 3), dtype=np.uint8)
    image[65:720, 140:1170] = np.asarray(Image.open(
        root / 'tests/fixtures/workshop/task_window.png').convert('RGB'))[:, :, ::-1]
    if case in {'claimed_row', 'missing_claimed_status'}:
        image[140:595, 345:1130] = np.asarray(Image.open(
            root / 'tests/fixtures/workshop/claimed_rows.png').convert('RGB'))[:, :, ::-1]
    if case == 'only_clear_reward':
        image[140:335, 870:1130] = 0
    elif case == 'no_claim_button':
        image[630:720, 980:1240] = 0
    if case == 'fallback_clear':
        image[140:335, 870:1130] = 0
        image[630:720, 980:1240] = 0
    if case == 'no_rewards':
        image[140:595, 870:1130] = 0
        image[630:720, 980:1240] = 0
    if case.startswith('intro'):
        image[:] = 0
        image[120:650, 540:1255] = np.asarray(Image.open(
            root / 'tests/fixtures/workshop/intro.png').convert('RGB'))[:, :, ::-1]
        if case == 'intro_without_button':
            image[530:640, 940:1250] = 0
    if case.startswith('entry_icon'):
        image[:] = 0
        x,y={'entry_icon':(109,340),'entry_icon_lower':(109,425),'entry_icon_shifted':(229,500),'entry_icon_lower_old_roi':(109,425)}[case]
        image[y:y+45, x:x+57] = np.asarray(Image.open(
            root / 'assets/resource/image/工坊挑战入口.png').convert('RGB'))[:, :, ::-1]
    if case in {'entry_live', 'entry_live_1121', 'entry_live_1121_old_template'}:
        image[:] = 0
        crop=np.asarray(Image.open(root/'tests/fixtures/workshop'/('home_entry_moved.png' if case == 'entry_live' else 'home_entry_1121.png')).convert('RGB'))[:, :, ::-1]
        image[100:600, 0:400]=crop
    if case in {'detail_right','share_right','detail_old_roi','share_old_roi'}:
        image[:]=0
        image[620:720,700:1280]=np.asarray(Image.open(root/'tests/fixtures/workshop/right_map_buttons.png').convert('RGB'))[:,:,::-1]
    if case in {'share_wide_1121', 'share_wide_old_roi_1121'}:
        image[:]=0
        image[620:720,240:1280]=np.asarray(Image.open(root/'tests/fixtures/workshop/wide_map_buttons_1121.png').convert('RGB'))[:,:,::-1]
    if case == 'share_channel_right':
        image[:]=0
        image[540:645,700:1250]=np.asarray(Image.open(root/'tests/fixtures/workshop/right_share_menu.png').convert('RGB'))[:,:,::-1]
    if case == 'missing_claimed_status':
        image[450:545, 870:1130] = 0
    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory(prefix='mr3a-workshop-replay-') as log_dir:
        Tasker.set_log_dir(log_dir)
        resource = Resource()
        assert resource.post_bundle(str(root / 'assets/resource')).wait().succeeded
        tasker = Tasker()
        assert Library.framework().MaaTaskerBindResource(tasker._handle, resource._handle)
        pipeline = json.loads((root / 'assets/resource/pipeline/工坊挑战.json').read_text())
        node = '工坊记录三张游玩' if case in {'claimed_row', 'missing_claimed_status'} else '工坊一键领取奖励'
        if case in {'fallback_clear', 'no_rewards'}:
            node = '工坊逐项领取奖励'
        elif case.startswith('intro'):
            node = '工坊首次说明'
        elif case.startswith('entry_icon') or case.startswith('entry_live'):
            node = '工坊主页进入'
        if case in {'detail_right','detail_old_roi'}:
            node='工坊地图详情'
        elif case in {'share_right','share_old_roi','share_wide_1121','share_wide_old_roi_1121'}:
            node='工坊点击分享'
        elif case=='share_channel_right':
            node='工坊选择分享途径'
        if case.startswith('flags_'):
            node = '工坊四目标齐'
            flags = pipeline[node]['recognition']['param']['all_of']
            count = {'flags_pending': 0, 'flags_three': 3, 'flags_all': 4}[case]
            assert resource.override_pipeline({name: {'recognition': {'type': 'DirectHit'}} for name in flags[:count]})
            image[:] = 0
        rule = pipeline[node]['recognition']
        if case in {'entry_live_1121', 'entry_live_1121_old_template'}:
            rule=rule['param']['any_of'][1]['recognition']
            if case == 'entry_live_1121_old_template':
                rule['param']['template']=['工坊挑战入口.png']
        if case == 'entry_icon_lower_old_roi':
            rule['param']['any_of'][1]['recognition']['param']['roi']=[80,320,130,100]
        if case=='detail_old_roi':rule['param']['roi']=[860,630,205,80]
        if case=='share_wide_old_roi_1121':rule['param']['roi']=[700,620,580,100]
        if case=='share_old_roi':rule['param']['roi']=[300,640,80,80]
        detail = tasker.post_recognition(rule['type'], {'And':JAnd,'Or':JOr,'OCR':JOCR,'TemplateMatch':JTemplateMatch}[rule['type']](**rule['param']), image).wait().get().nodes[0].recognition
        report = {'hit': detail.hit, 'box': list(detail.box) if detail.box else None}
        del tasker, resource
    print(json.dumps(report))


if __name__ == '__main__':
    import sys
    _native_replay(sys.argv[1])


def test_workshop_uses_only_pipeline_and_existing_shared_actions():
    pipeline = json.loads(Path('assets/resource/pipeline/工坊挑战.json').read_text())
    allowed = {'NodeOverride', 'LoopDeadlineArm', 'ResetCount', 'AbortTasker',
               'SetManagedTaskPersistentState', 'ScheduleDeferredTask'}
    for node in pipeline.values():
        action = node.get('action', {})
        if isinstance(action, dict) and action.get('type') == 'Custom':
            assert action['param']['custom_action'] in allowed
    assert not Path('agent/custom/action/workshop_challenge.py').exists()
