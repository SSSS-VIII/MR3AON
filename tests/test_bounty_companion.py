"""协同桥接仅消费流水线识别结果、管理实例消息，不直接操作游戏。"""
import json
import re
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from custom.action import bounty_companion as bounty


@pytest.fixture
def scene(monkeypatch):
    monkeypatch.setattr(bounty, '_main', bounty._MainSession())
    monkeypatch.setattr(bounty, '_small', bounty._SmallSession())
    manager = SimpleNamespace(start=Mock(return_value=True), stop=Mock(),
                              status=Mock(return_value={'state': 'ready', 'nickname': '小号'}),
                              permit_invitation=Mock(return_value='invitation-token'),
                              revoke_invitation=Mock())
    monkeypatch.setattr(bounty, 'companion_manager', manager)
    monkeypatch.setattr(bounty, 'read_session', Mock(return_value={'name': 'small'}))
    monkeypatch.setattr(bounty, 'read_request', Mock(return_value=None))
    monkeypatch.setattr(bounty, 'publish_state', Mock(return_value=True))
    monkeypatch.setattr(bounty, 'iter_ocr_boxes', lambda detail: detail.items)
    context = Mock()
    context.override_pipeline.return_value = True
    data = {'每日悬赏小号配置': {'attach': {'enabled': True, 'instance': 'small'}},
            bounty.INVITE_ENTRY: {'next': ['邀请家族', '邀请好友', '邀请地区']},
            bounty.HOME_ENTRY: {'next': ['每日悬赏进入集会所']},
            bounty.DRAGON_NODES[0]: {'enable': False}, bounty.DRAGON_NODES[1]: {'enabled': True}}
    context.get_node_data.side_effect = data.get
    return SimpleNamespace(context=context, manager=manager, data=data)


def args(task_id=42, items=(), param=None):
    return SimpleNamespace(task_detail=SimpleNamespace(task_id=task_id),
                           reco_detail=SimpleNamespace(items=list(items)),
                           custom_action_param=param or {}, custom_recognition_param=param or {})


def prepare(scene):
    assert bounty.PrepareBountyCompanion().run(scene.context, args())
    assert bounty.CaptureBountyLeader().run(scene.context, args(items=[('大号', [140, 24, 90, 30])]))


def test_disabled_mode_preserves_original_routes(scene):
    scene.data['每日悬赏小号配置']['attach']['enabled'] = False
    assert bounty.PrepareBountyCompanion().run(scene.context, args())
    scene.manager.start.assert_not_called()
    scene.context.override_pipeline.assert_not_called()


def test_start_rejection_preserves_routes_without_repeated_cold_start(scene):
    scene.manager.start.return_value = False
    assert bounty.PrepareBountyCompanion().run(scene.context, args())
    assert bounty.PrepareBountyCompanion().run(scene.context, args())
    scene.manager.start.assert_called_once_with('small', 42)
    scene.context.override_pipeline.assert_not_called()


def test_prepare_patches_home_capture_only_when_enabled_and_fallback_restores(scene):
    prepare(scene)
    assert bounty._main.restore[bounty.HOME_ENTRY]['next'] == ['每日悬赏进入集会所']
    assert bounty._main.restore[bounty.DRAGON_NODES[0]] == {'enabled': False, 'enable': False}
    assert bounty._main.restore[bounty.DRAGON_NODES[1]] == {'enabled': True, 'enable': True}
    assert bounty.FallbackBountyCompanion().run(scene.context, args())
    assert not bounty._main.enabled
    scene.manager.stop.assert_called_once_with(task_id=42)
    assert scene.context.override_pipeline.call_args.args[0] == bounty._main.restore


@pytest.mark.parametrize('nickname', ['临时更名', 'Player 42', 'Main[42]'])
def test_dynamic_nickname_escapes_regex_and_binds_native_ocr(scene, nickname):
    prepare(scene)
    scene.manager.status.return_value = {'state': 'ready', 'nickname': nickname}
    assert bounty.InviteBountyCompanion().run(scene.context, args())
    patch = scene.context.override_pipeline.call_args.args[0]
    pattern = patch['每日悬赏好友目标昵称']['recognition']['param']['expected'][0]
    assert re.fullmatch(pattern, nickname)
    assert re.fullmatch(pattern, ' '.join(bounty.normalized_name(nickname)))
    assert not re.fullmatch(pattern, '其他好友')


@pytest.mark.parametrize('status', [{'state': 'starting', 'nickname': '小号'}, {'state': 'ready', 'nickname': ''}])
def test_not_ready_or_empty_nickname_cannot_bind_target(scene, status):
    prepare(scene)
    scene.manager.status.return_value = status
    assert not bounty.InviteBountyCompanion().run(scene.context, args())


def test_binding_uses_only_unique_native_row_and_keeps_invitation_in_same_row(scene):
    prepare(scene)
    assert bounty.BindBountyFriendRow().run(scene.context, args(items=[('小号', [950, 230, 90, 30])]))
    patch = scene.context.override_pipeline.call_args.args[0]
    assert patch['每日悬赏小号行邀请按钮']['recognition']['param']['roi'] == [1150, 217, 125, 56]
    assert patch['每日悬赏复核小号昵称']['recognition']['param']['roi'] == [915, 221, 165, 48]


@pytest.mark.parametrize('items', [[], [('同名', [920, 230, 90, 30]), ('同名', [920, 330, 90, 30])], [('残行', [920, 40, 90, 30])]])
def test_ambiguous_or_clipped_native_row_is_rejected(scene, items):
    prepare(scene)
    assert not bounty.BindBountyFriendRow().run(scene.context, args(items=items))


def test_invitation_permit_and_matching_ack_complete_handshake(scene):
    prepare(scene)
    assert bounty.ArmBountyInvitation().run(scene.context, args())
    scene.manager.permit_invitation.assert_called_once_with(25, leader_name='大号')
    scene.manager.status.return_value = {'state': 'teamed', 'token': 'wrong'}
    assert not bounty.FinishBountyInvitation().run(scene.context, args())
    scene.manager.status.return_value['token'] = 'invitation-token'
    assert bounty.FinishBountyInvitation().run(scene.context, args())
    scene.manager.revoke_invitation.assert_called_once()
    patch = scene.context.override_pipeline.call_args.args[0]
    assert patch['每日悬赏设置小号等待时限']['action']['param']['custom_action_param']['duration_ms'] == 30000


@pytest.mark.parametrize('action', [bounty.CaptureBountyLeader, bounty.InviteBountyCompanion,
                                    bounty.BindBountyFriendRow, bounty.ArmBountyInvitation,
                                    bounty.FinishBountyInvitation])
def test_late_callback_cannot_control_new_owner(scene, action):
    prepare(scene)
    assert not action().run(scene.context, args(task_id=41))
    scene.manager.permit_invitation.assert_not_called()
    scene.manager.revoke_invitation.assert_not_called()


def test_late_fallback_does_not_stop_new_owner(scene):
    prepare(scene)
    assert bounty.FallbackBountyCompanion().run(scene.context, args(task_id=41))
    scene.manager.stop.assert_not_called()
    assert bounty._main.enabled


def test_unmanaged_small_task_is_rejected(scene, monkeypatch):
    monkeypatch.setattr(bounty, 'read_session', lambda: {})
    assert not bounty.InitializeBountyCompanion().run(scene.context, args())
    bounty.publish_state.assert_called_once_with('failed', reason='请从大号拉小号模式调用')


def test_small_reads_native_nickname_and_publishes_ready(scene):
    assert bounty.InitializeBountyCompanion().run(scene.context, args())
    assert bounty.RecordBountyCompanionNickname().run(scene.context, args(items=[('当前小号', [140, 24, 120, 30])]))
    assert bounty.ReportBountyCompanionState().run(scene.context, args(param={'state': 'ready'}))
    bounty.publish_state.assert_called_once_with('ready', nickname='当前小号', token='')


def test_expired_permit_or_changed_token_cannot_accept_invitation(scene, monkeypatch):
    assert bounty.InitializeBountyCompanion().run(scene.context, args())
    assert bounty.BountyInvitationPermit().analyze(scene.context, args()) is None
    request = {'token': 'first', 'leader_name': '大号'}
    monkeypatch.setattr(bounty, 'read_request', lambda: request)
    assert bounty.BountyInvitationPermit().analyze(scene.context, args()) is not None
    request['token'] = 'second'
    assert not bounty.BeginBountyCompanionJoin().run(scene.context, args())
    request['token'] = 'first'
    assert bounty.BeginBountyCompanionJoin().run(scene.context, args())
    bounty.publish_state.assert_called_with('joining', nickname='', token='first')


def test_ack_recognition_requires_current_task_and_token(scene):
    prepare(scene)
    bounty._main.token = 'expected'
    scene.manager.status.return_value = {'state': 'teamed', 'token': 'old'}
    query = args(param={'states': ['teamed'], 'match_token': True})
    assert bounty.BountyCompanionState().analyze(scene.context, query) is None
    scene.manager.status.return_value['token'] = 'expected'
    assert bounty.BountyCompanionState().analyze(scene.context, query) is not None


def test_bridge_contains_no_game_controller_calls():
    from pathlib import Path
    source = Path(bounty.__file__).read_text()
    for forbidden in ('post_click', 'post_swipe', 'post_screencap', 'run_action(', 'run_recognition(', 'time.sleep', 'while '):
        assert forbidden not in source
