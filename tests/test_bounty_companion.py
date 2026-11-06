"""每日悬赏协同业务的离线边界；界面结果来自夹具，不代表实机验收。"""
from copy import deepcopy
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest

from custom.action import bounty_companion as bounty
from runtime import companion
from runtime.task_options import build_task_config, load_task_interface

ROOT = Path(__file__).resolve().parents[1]
BOX = [1165, 250, 80, 36]


class Clock:
    def __init__(self):
        self.now = 100.0

    def monotonic(self):
        return self.now

    def sleep(self, seconds):
        self.now += seconds


@pytest.fixture
def scene(monkeypatch):
    clock = Clock()
    manager = SimpleNamespace(
        start=Mock(return_value=True), stop=Mock(return_value=True),
        wait_ready=Mock(return_value=True),
        status=Mock(return_value={'state': 'ready', 'nickname': '小号'}),
        permit_invitation=Mock(return_value='new-token'), revoke_invitation=Mock(),
    )
    monkeypatch.setattr(bounty, '_main', bounty._MainSession())
    monkeypatch.setattr(bounty, '_small', bounty._SmallSession(progress_at=clock.now))
    monkeypatch.setattr(bounty, 'time', clock)
    monkeypatch.setattr(bounty, 'companion_manager', manager)
    monkeypatch.setattr(bounty, 'publish_state', Mock(return_value=True))
    monkeypatch.setattr(bounty, 'save_image_array', Mock(return_value=Path('/test/reward.png')))
    monkeypatch.setattr(bounty, 'read_request', Mock(return_value=None))
    monkeypatch.setattr(bounty, 'read_session', Mock(return_value={'name': 'small'}))
    monkeypatch.setattr(bounty, '_frame', Mock(return_value=np.zeros((720, 1280, 3), dtype=np.uint8)))
    for name in ('_tap', '_click_box', '_swipe'):
        monkeypatch.setattr(bounty, name, Mock())
    monkeypatch.setattr(bounty, '_ocr', Mock(return_value=[]))
    monkeypatch.setattr(bounty, '_text', Mock(return_value=''))
    monkeypatch.setattr(bounty, '_hit', Mock(return_value=None))
    monkeypatch.setattr(bounty, '_click_text', Mock(return_value=False))
    nodes = {
        '每日悬赏小号配置': {'attach': {'enabled': True, 'instance': 'small'}},
        bounty.INVITE_ENTRY: {'next': ['原有自定义邀请', '每日悬赏地区组队']},
        bounty.DRAGON_NODES[0]: {'enabled': False},
        bounty.DRAGON_NODES[1]: {'enable': True},
    }

    def override(patch):
        for name, value in patch.items():
            nodes[name].update(deepcopy(value))

    context = SimpleNamespace(
        tasker=SimpleNamespace(stopping=False),
        get_node_data=lambda name: deepcopy(nodes.get(name)),
        override_pipeline=Mock(side_effect=override), run_action=Mock(),
    )
    return SimpleNamespace(context=context, nodes=nodes, manager=manager, clock=clock)


def args(task_id=7):
    return SimpleNamespace(task_detail=SimpleNamespace(task_id=task_id))


def prepare(scene):
    assert bounty.PrepareBountyCompanion().run(scene.context, args())
    return bounty._main


def invitation(scene, monkeypatch):
    main = prepare(scene)
    main.leader = '大号'
    monkeypatch.setattr(bounty, '_find_friend', Mock(return_value=BOX))
    bounty._click_text.return_value = True
    return main


def test_disabled_mode_leaves_original_pipeline_untouched(scene):
    scene.nodes['每日悬赏小号配置']['attach']['enabled'] = False
    before = deepcopy(scene.nodes)
    prepare(scene)
    scene.manager.start.assert_not_called()
    scene.manager.stop.assert_not_called()
    scene.context.override_pipeline.assert_not_called()
    assert scene.nodes == before


@pytest.mark.parametrize('reason', ['非法实例名', '实例名为空', '实例被另一控制者占用'])
def test_rejected_start_preserves_main_flow_without_repeated_attempts(scene, reason):
    scene.manager.start.return_value = False
    scene.manager.status.return_value = {'state': 'failed', 'reason': reason}
    before = deepcopy(scene.nodes)
    prepare(scene)
    prepare(scene)
    assert not bounty._main.enabled
    scene.manager.start.assert_called_once_with('small', 7)
    scene.context.override_pipeline.assert_not_called()
    assert scene.nodes == before


def test_prepare_restores_effective_account_options_and_does_not_restart_same_task(scene):
    original_next = deepcopy(scene.nodes[bounty.INVITE_ENTRY]['next'])
    main = prepare(scene)
    assert main.enabled
    assert scene.nodes[bounty.INVITE_ENTRY]['next'] == ['每日悬赏邀请小号']
    assert all(scene.nodes[name]['enabled'] is False for name in bounty.DRAGON_NODES)
    prepare(scene)
    scene.manager.start.assert_called_once()
    bounty._fallback(scene.context, '目标离线')
    assert scene.nodes[bounty.INVITE_ENTRY]['next'] == original_next
    assert scene.nodes[bounty.DRAGON_NODES[0]]['enabled'] is False
    assert scene.nodes[bounty.DRAGON_NODES[1]]['enabled'] is True
    assert scene.nodes[bounty.DRAGON_NODES[1]]['enable'] is True
    assert not main.enabled
    prepare(scene)
    scene.manager.start.assert_called_once()


def friend_page(nickname='小号', *, second_name=None):
    names = [(nickname, [920, 250, 90, 36])]
    if second_name is not None:
        names.append((second_name, [920, 350, 90, 36]))

    def ocr(context, image, roi, pattern='.'):
        if pattern == '^邀请$':
            return [('邀请', BOX)]
        return names

    return ocr


@pytest.mark.parametrize('nickname', ['小卫鲤', '今天换个名字', 'Player 42'])
def test_friend_search_uses_live_nickname_without_opening_profiles(scene, nickname):
    bounty._ocr.side_effect = friend_page(nickname)
    bounty._text.return_value = nickname
    assert bounty._find_friend(scene.context, nickname, scene.clock.now + 30) == BOX
    bounty._tap.assert_called_once_with(scene.context, 885, 57)  # 只选择好友页签。
    bounty._click_text.assert_not_called()
    bounty._click_box.assert_not_called()  # 搜索只返回按钮，许可后才邀请。


@pytest.mark.parametrize('ready,before,after,allowed', [
    ('小号', '小号', '小号', True),
    ('小 号', '小号', '小 号', True),
    ('', '小号', '小号', False),
    ('小号', '', '', False),
    ('小号', '小', '小', False),
    ('小号', '小号', '', False),
    ('小号', '小号', '新上线好友', False),
])
def test_friend_invitation_rechecks_matching_nonempty_row_names(scene, ready, before, after, allowed):
    bounty._ocr.side_effect = friend_page('小号')
    bounty._text.side_effect = [before, after]
    assert bounty._find_friend(scene.context, ready, scene.clock.now + 30) == (BOX if allowed else None)
    bounty._click_box.assert_not_called()
    assert all(call.args[1:] == (885, 57) for call in bounty._tap.call_args_list)


def test_friend_remark_without_matching_visible_nickname_is_not_invited(scene):
    bounty._ocr.side_effect = friend_page('我的小号备注')
    bounty._text.return_value = '我的小号备注'
    assert bounty._find_friend(scene.context, '真实昵称', scene.clock.now + 30) is None
    bounty._text.assert_not_called()
    bounty._click_box.assert_not_called()


def test_reordered_friend_row_is_not_invited(scene):
    bounty._ocr.side_effect = friend_page()
    bounty._text.side_effect = ['小号', '新上线好友']
    assert bounty._find_friend(scene.context, '小号', scene.clock.now + 30) is None
    bounty._click_box.assert_not_called()


def test_changed_avatar_in_same_named_row_is_not_invited(scene):
    before = bounty._frame.return_value
    after = before.copy()
    after[236:300, 824:886] = 255
    bounty._frame.side_effect = [before, after]
    bounty._ocr.side_effect = friend_page()
    bounty._text.return_value = '小号'
    assert bounty._find_friend(scene.context, '小号', scene.clock.now + 30) is None
    bounty._click_box.assert_not_called()


def test_duplicate_visible_nicknames_are_rejected(scene):
    bounty._ocr.side_effect = friend_page(second_name='小 号')
    bounty._text.return_value = '小号'
    assert bounty._find_friend(scene.context, '小号', scene.clock.now + 30) is None
    bounty._text.assert_not_called()
    bounty._click_box.assert_not_called()


def test_new_duplicate_before_click_is_rejected(scene):
    before = bounty._frame.return_value
    after = before.copy()
    bounty._frame.side_effect = [before, after]
    bounty._ocr.side_effect = lambda context, image, roi, pattern='.': friend_page(
        second_name='小号' if image is after else None)(context, image, roi, pattern)
    bounty._text.return_value = '小号'
    assert bounty._find_friend(scene.context, '小号', scene.clock.now + 30) is None
    bounty._click_box.assert_not_called()


@pytest.mark.parametrize('reason', ['deadline', 'stopping'])
def test_friend_search_stops_without_scanning_when_cancelled_or_expired(scene, reason):
    deadline = scene.clock.now - 1 if reason == 'deadline' else scene.clock.now + 30
    scene.context.tasker.stopping = reason == 'stopping'
    assert bounty._find_friend(scene.context, '小号', deadline) is None
    bounty._frame.assert_not_called()
    bounty._click_box.assert_not_called()


@pytest.mark.parametrize('failure', ['not_ready', 'missing_nickname', 'worker_failed', 'old_token', 'no_ack'])
def test_invite_failure_restores_main_flow_and_releases_owner(scene, monkeypatch, failure):
    invitation(scene, monkeypatch)
    ready = {'state': 'ready', 'nickname': '小号'}
    if failure == 'not_ready':
        scene.manager.wait_ready.return_value = False
        scene.manager.status.return_value = {'state': 'failed', 'reason': 'instance busy'}
    elif failure == 'missing_nickname':
        scene.manager.status.return_value = {**ready, 'nickname': '  '}
    elif failure == 'worker_failed':
        scene.manager.status.side_effect = [ready, {'state': 'failed', 'reason': 'disconnected'}]
    elif failure == 'old_token':
        scene.manager.status.return_value = {**ready, 'state': 'teamed', 'token': 'previous-round'}
    assert bounty.InviteBountyCompanion().run(scene.context, args()) is False
    assert not bounty._main.enabled
    scene.manager.stop.assert_called_with(task_id=7)
    assert scene.nodes[bounty.INVITE_ENTRY]['next'] == ['原有自定义邀请', '每日悬赏地区组队']
    assert scene.nodes[bounty.DRAGON_NODES[1]]['enabled'] is True
    if failure in {'not_ready', 'missing_nickname'}:
        bounty._find_friend.assert_not_called()
        scene.manager.permit_invitation.assert_not_called()
    assert scene.clock.now < 126


def test_async_cleanup_error_does_not_prevent_restoring_main_options(scene, monkeypatch):
    invitation(scene, monkeypatch)
    scene.manager.wait_ready.return_value = False
    scene.manager.stop.side_effect = RuntimeError('worker channel unavailable')
    assert bounty.InviteBountyCompanion().run(scene.context, args()) is False
    assert not bounty._main.enabled
    assert scene.nodes[bounty.DRAGON_NODES[1]]['enabled'] is True
    assert scene.nodes[bounty.INVITE_ENTRY]['next'] == ['原有自定义邀请', '每日悬赏地区组队']


def test_invite_wait_uses_only_remaining_startup_budget(scene, monkeypatch):
    invitation(scene, monkeypatch)
    scene.clock.now += 149
    scene.manager.wait_ready.return_value = False
    assert bounty.InviteBountyCompanion().run(scene.context, args()) is False
    assert scene.manager.wait_ready.call_args.args == (1,)
    cancelled = scene.manager.wait_ready.call_args.kwargs['cancelled']
    assert not cancelled()
    scene.context.tasker.stopping = True
    assert cancelled()


def test_matching_ack_token_completes_invitation(scene, monkeypatch):
    invitation(scene, monkeypatch)
    scene.manager.status.side_effect = [
        {'state': 'ready', 'nickname': '小号'},
        {'state': 'teamed', 'token': 'new-token'},
    ]
    assert bounty.InviteBountyCompanion().run(scene.context, args()) is True
    scene.manager.permit_invitation.assert_called_once_with(25, leader_name='大号')
    scene.manager.revoke_invitation.assert_called_once()
    scene.manager.stop.assert_not_called()
    bounty._click_box.assert_called_once_with(scene.context, BOX)


@pytest.mark.parametrize('inviter,leader,allowed', [
    ('大号', '大号', True), ('大 号', '大号', True),
    ('大号2', '大号', False), ('别人', '大号', False),
])
def test_small_accepts_only_exact_expected_inviter(scene, inviter, leader, allowed):
    bounty.read_request.return_value = {'token': 'round2', 'leader_name': leader}
    bounty._ocr.return_value = [('每日悬赏', BOX)]
    bounty._text.return_value = inviter
    bounty._click_text.return_value = True
    bounty._small.token = 'round1'
    assert bounty._accept_invite(scene.context, bounty._frame.return_value)
    click_pattern = bounty._click_text.call_args.args[3]
    assert click_pattern == ('^同意$' if allowed else '^拒绝$')
    assert bounty._small.token == ('round2' if allowed else 'round1')
    if allowed:
        assert bounty._small.phase == 'joining'
        assert bounty.publish_state.call_args.kwargs['token'] == 'round2'
    else:
        bounty.publish_state.assert_not_called()


@pytest.mark.parametrize('permit', ['missing', 'expired', 'revoked'])
def test_small_rejects_invite_without_current_permit(scene, monkeypatch, tmp_path, permit):
    monkeypatch.setenv('MR3A_COMPANION_DIR', str(tmp_path))
    if permit != 'missing':
        request = {} if permit == 'revoked' else {
            'token': 'old', 'leader_name': '大号', 'expires_at': 0,
        }
        (tmp_path / 'request.json').write_text(json.dumps(request))
    monkeypatch.setattr(bounty, 'read_request', companion.read_request)
    bounty._ocr.return_value = [('每日悬赏', BOX)]
    bounty._text.return_value = '大号'
    bounty._click_text.return_value = True
    assert bounty._accept_invite(scene.context, bounty._frame.return_value)
    assert bounty._click_text.call_args.args[3] == '^拒绝$'
    bounty.publish_state.assert_not_called()


def test_other_invitation_type_never_receives_accept_click(scene):
    bounty.read_request.return_value = {'token': 'round', 'leader_name': '大号'}
    bounty._text.return_value = '大号'
    bounty._ocr.return_value = []
    bounty._accept_invite(scene.context, bounty._frame.return_value)
    assert not any(call.args[3] == '^同意$' for call in bounty._click_text.call_args_list)
    bounty.publish_state.assert_not_called()


@pytest.mark.parametrize('nickname', ['小卫鲤', '临时更名', 'Player 42'])
def test_small_reads_current_home_nickname_without_opening_profile(scene, monkeypatch, nickname):
    bounty._hit.return_value = SimpleNamespace(box=BOX)
    bounty._text.return_value = nickname
    unblock = Mock()
    monkeypatch.setattr(bounty, '_unblock_invites', unblock)
    assert bounty.InitializeBountyCompanion().run(scene.context, args()) is True
    bounty._text.assert_called_once_with(scene.context, bounty._frame.return_value, [140, 24, 210, 46])
    assert bounty._small.nickname == nickname
    bounty.publish_state.assert_called_once_with('ready', nickname=nickname, token='')
    unblock.assert_called_once_with(scene.context)
    bounty._tap.assert_not_called()
    bounty._click_text.assert_not_called()
    bounty._click_box.assert_not_called()


@pytest.mark.parametrize('failure', ['unmanaged', 'not_home', 'empty_nickname'])
def test_small_readiness_requires_managed_session_home_and_nickname(scene, monkeypatch, failure):
    bounty._hit.return_value = SimpleNamespace(box=BOX)
    bounty._text.return_value = '小号'
    if failure == 'unmanaged':
        bounty.read_session.return_value = {}
    elif failure == 'not_home':
        bounty._hit.return_value = None
    else:
        bounty._text.return_value = '  '
    unblock = Mock()
    monkeypatch.setattr(bounty, '_unblock_invites', unblock)
    assert bounty.InitializeBountyCompanion().run(scene.context, args()) is False
    assert [call.args[0] for call in bounty.publish_state.call_args_list] == ['failed']
    unblock.assert_not_called()
    bounty._tap.assert_not_called()


def test_unconfirmed_invitation_setting_does_not_publish_ready(scene, monkeypatch):
    bounty._hit.return_value = SimpleNamespace(box=BOX)
    bounty._text.return_value = '小号'
    monkeypatch.setattr(bounty, '_unblock_invites', Mock(side_effect=RuntimeError('屏蔽仍然勾选')))
    assert bounty.InitializeBountyCompanion().run(scene.context, args()) is False
    assert [call.args[0] for call in bounty.publish_state.call_args_list] == ['failed']


@pytest.mark.parametrize('phase,allowed', [
    ('ready', False), ('joining', False), ('returning', False),
    ('teamed', True), ('fighting', True), ('settling', True),
])
def test_settlement_confirmation_requires_a_joined_battle(scene, phase, allowed):
    bounty._small.phase = phase
    bounty._ocr.side_effect = lambda context, image, roi, pattern='.': (
        [('每日悬赏', BOX)] if roi == [430, 20, 450, 170] else [])
    bounty._hit.side_effect = lambda context, image, name: (
        SimpleNamespace(box=BOX) if name == '每日悬赏结算截图' else None)
    assert bounty.PollBountyCompanion().run(scene.context, args())
    actions = [call.args[0] for call in scene.context.run_action.call_args_list]
    assert actions == (['每日悬赏结算确定'] if allowed else [])
    assert bounty.save_image_array.call_count == (1 if allowed else 0)
    bounty._tap.assert_not_called()
    if allowed:
        assert bounty._small.phase == 'settling'


def test_confirmation_text_without_reward_scene_is_not_clicked(scene):
    bounty._small.phase = 'fighting'
    bounty._hit.side_effect = lambda context, image, name: (
        SimpleNamespace(box=BOX) if name == '每日悬赏结算截图' else None)
    assert bounty.PollBountyCompanion().run(scene.context, args())
    assert all(call.args[2] not in {'每日悬赏结算截图', '每日悬赏点击空白处关闭'}
               for call in bounty._hit.call_args_list)
    scene.context.run_action.assert_not_called()
    bounty.save_image_array.assert_not_called()
    bounty._tap.assert_not_called()
    bounty._click_box.assert_not_called()


def test_reward_popup_then_summary_are_saved_and_dismissed_in_order(scene):
    bounty._small.phase = 'fighting'
    bounty._small.token = 'this-battle'
    events = []
    bounty.save_image_array.side_effect = lambda *args, **kwargs: (
        events.append('save') or Path('/test/reward.png'))
    scene.context.run_action.side_effect = lambda name, *args: events.append(name)
    bounty._ocr.side_effect = lambda context, image, roi, pattern='.': (
        [('恭喜获得', BOX)] if roi == [430, 20, 450, 170] else [])
    bounty._hit.side_effect = lambda context, image, name: (
        SimpleNamespace(box=BOX) if name == '每日悬赏点击空白处关闭' else None)
    assert bounty.PollBountyCompanion().run(scene.context, args())
    assert bounty._small.phase == 'settling'
    assert scene.clock.now == 101.5
    bounty._hit.side_effect = lambda context, image, name: (
        SimpleNamespace(box=BOX) if name == '每日悬赏结算截图' else None)
    assert bounty.PollBountyCompanion().run(scene.context, args())
    assert events == [
        'save', '每日悬赏点击空白处关闭', 'save', '每日悬赏结算确定',
    ]
    assert bounty.save_image_array.call_count == 2
    for call in bounty.save_image_array.call_args_list:
        assert call.args[0] is bounty._frame.return_value
        assert (call.args[1] if len(call.args) > 1 else call.kwargs['dir_name']) == '每日悬赏'
        assert call.kwargs['burst_replace'] is True
        assert call.kwargs['burst_entry'] == 'this-battle'
        assert call.kwargs['node_name'] == '每日悬赏小号结算'


@pytest.mark.parametrize('node', ['每日悬赏点击空白处关闭', '每日悬赏结算截图'])
@pytest.mark.parametrize('failure', [None, OSError('disk full')])
def test_reward_save_failure_fails_small_session_before_clicking(scene, node, failure):
    bounty._small.phase = 'fighting'
    bounty._ocr.side_effect = lambda context, image, roi, pattern='.': (
        [('每日悬赏', BOX)] if roi == [430, 20, 450, 170] else [])
    bounty._hit.side_effect = lambda context, image, name: (
        SimpleNamespace(box=BOX) if name == node else None)
    if isinstance(failure, Exception):
        bounty.save_image_array.side_effect = failure
    else:
        bounty.save_image_array.return_value = failure
    assert bounty.PollBountyCompanion().run(scene.context, args()) is False
    assert [call.args[0] for call in bounty.publish_state.call_args_list] == ['failed']
    assert bounty.publish_state.call_args.kwargs['reason']
    scene.context.run_action.assert_not_called()
    bounty._tap.assert_not_called()


@pytest.mark.parametrize('phase', ['ready', 'joining', 'fighting'])
def test_unknown_or_paid_relay_screen_does_not_receive_blind_clicks(scene, phase):
    bounty._small.phase = phase
    # 无实际战斗/结算命中，即使 OCR 有复活/接力页面也不靠固定点继续。
    bounty._hit.return_value = None
    assert bounty.PollBountyCompanion().run(scene.context, args())
    scene.context.run_action.assert_not_called()
    bounty._tap.assert_not_called()
    bounty._click_box.assert_not_called()


@pytest.mark.parametrize('action', ['CaptureBountyLeader', 'InviteBountyCompanion', 'FallbackBountyCompanion'])
def test_late_callback_does_not_modify_new_task_owner(scene, action):
    prepare(scene)
    bounty._main.task_id = 99
    bounty._main.leader = '新大号'
    scene.context.override_pipeline.reset_mock()
    instance = getattr(bounty, action)()
    instance.run(scene.context, args(task_id=7))
    scene.manager.stop.assert_not_called()
    scene.context.override_pipeline.assert_not_called()
    assert bounty._main.leader == '新大号'
    assert bounty._main.enabled


def test_real_options_default_off_and_enable_only_transient_small_configuration():
    interface = load_task_interface(ROOT / 'assets/interface.json')
    original = {'task': [{'name': '每日悬赏', 'option': [
        {'name': '完成每日龙血任务', 'value': 'No'},
    ]}]}
    before = deepcopy(original)
    defaults = build_task_config(interface, original, ['每日悬赏'], {})[0]
    options = {item['name']: item for item in defaults['option']}
    assert options['拉小号模式']['value'] == 'No'
    assert '小号配置' not in options
    enabled = build_task_config(interface, original, ['每日悬赏'], {'每日悬赏': {
        '拉小号模式': True, '小号配置': {'实例名称': 'small'},
    }})[0]
    options = {item['name']: item for item in enabled['option']}
    assert options['拉小号模式']['value'] == 'Yes'
    assert options['小号配置']['inputs'] == {'实例名称': 'small'}
    assert options['完成每日龙血任务']['value'] == 'No'
    assert original == before


def test_real_enabled_options_allow_empty_fields_for_runtime_fallback():
    interface = load_task_interface(ROOT / 'assets/interface.json')
    task = build_task_config(interface, {}, ['每日悬赏'], {'每日悬赏': {'拉小号模式': True}})[0]
    options = {item['name']: item for item in task['option']}
    assert options['小号配置']['inputs'] == {'实例名称': ''}


def test_standalone_companion_failure_is_not_reported_as_completed(scene, monkeypatch):
    from runtime.run_result import invocation_result
    record = Mock()
    monkeypatch.setattr(invocation_result, 'record', record)
    assert bounty.FailBountyCompanion().run(scene.context, args())
    record.assert_called_once_with('failed', 'companion_task_failed')


def test_next_round_waits_for_return_home_independent_of_cold_start_budget(scene, monkeypatch):
    main = invitation(scene, monkeypatch)
    main.has_invited = True
    main.started_at = scene.clock.now - 400
    scene.manager.wait_ready.return_value = False
    assert not bounty.InviteBountyCompanion().run(scene.context, args())
    assert scene.manager.wait_ready.call_args.args == (30,)
    assert scene.manager.wait_ready.call_args.kwargs['states'] == {'ready'}


@pytest.mark.parametrize('phase,elapsed', [
    ('joining', 121), ('teamed', 121), ('settling', 121), ('returning', 121), ('fighting', 481),
])
def test_phase_timeout_precedes_all_early_return_actions(scene, phase, elapsed):
    bounty._small.phase = phase
    bounty._small.progress_at = scene.clock.now - elapsed
    # Even if the next frame would offer preparation or settlement, expiry wins.
    bounty._hit.return_value = SimpleNamespace(box=BOX)
    bounty._ocr.return_value = [('取消准备', BOX)]
    bounty._click_text.return_value = True
    assert bounty.PollBountyCompanion().run(scene.context, args()) is False
    bounty._frame.assert_not_called()
    bounty._tap.assert_not_called()
    bounty._click_box.assert_not_called()
    bounty._click_text.assert_not_called()
    bounty.save_image_array.assert_not_called()
    scene.context.run_action.assert_not_called()
    bounty.publish_state.assert_called_once_with('failed', reason='小号组队/战斗超过限定时间无状态进展')


def test_ready_wait_is_exempt_from_phase_timeout(scene):
    bounty._small.phase = 'ready'
    bounty._small.progress_at = scene.clock.now - 1000
    bounty._hit.side_effect = lambda context, image, node: (
        SimpleNamespace(box=BOX) if node == '每日悬赏确认在主页面' else None)
    assert bounty.PollBountyCompanion().run(scene.context, args()) is True
    assert bounty.publish_state.call_args.args == ('ready',)
    bounty._click_box.assert_not_called()
    bounty._tap.assert_not_called()


def test_repeated_phase_publish_does_not_reset_deadline_but_real_transition_does(scene):
    bounty._small.phase = 'joining'
    bounty._small.progress_at = scene.clock.now - 110
    bounty._publish('teamed')
    assert bounty._small.progress_at == scene.clock.now
    scene.clock.now += 119
    bounty._publish('teamed')
    assert bounty._small.progress_at == scene.clock.now - 119
    scene.clock.now += 2
    assert bounty.PollBountyCompanion().run(scene.context, args()) is False
    bounty._frame.assert_not_called()


def test_fighting_uses_eight_minute_budget_instead_of_two_minute_team_budget(scene):
    bounty._small.phase = 'fighting'
    bounty._small.progress_at = scene.clock.now - 121
    bounty._hit.side_effect = lambda context, image, node: (
        SimpleNamespace(box=BOX) if node == '每日悬赏识别到进入了战斗' else None)
    assert bounty.PollBountyCompanion().run(scene.context, args()) is True
    bounty._tap.assert_called_once_with(scene.context, 80, 360, .1)
    assert bounty._small.progress_at == scene.clock.now - 121


def test_stop_during_screenshot_is_normal_cleanup_not_business_failure(scene, monkeypatch):
    def interrupted_frame(context):
        context.tasker.stopping = True
        raise RuntimeError('协同截图失败')

    bounty._frame.side_effect = interrupted_frame
    warning = Mock()
    monkeypatch.setattr(bounty.logger, 'warning', warning)
    assert bounty.PollBountyCompanion().run(scene.context, args()) is True
    bounty.publish_state.assert_not_called()
    warning.assert_not_called()
