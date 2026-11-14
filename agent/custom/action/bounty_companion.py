"""每日悬赏实例协同的生命周期和消息桥接，界面识别与操作由流水线执行。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import re

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition

from custom.pipeline_params import parse_pipeline_json_param
from custom.reco.landlady_qa import box_xywh, iter_ocr_boxes
from runtime.companion import companion_manager, publish_state, read_request, read_session
from utils.logger import logger

INVITE_ENTRY = '每日悬赏展开了邀请页面'
HOME_ENTRY = '每日悬赏确认在主页面'
DRAGON_NODES = ('每日悬赏家族组队任务', '每日悬赏好友组队任务')


def normalized_name(text):
    return re.sub(r'\s+', '', text)


def nickname_pattern(text):
    return '^\\s*' + '\\s*'.join(re.escape(char) for char in normalized_name(text)) + '\\s*$'


@dataclass
class _MainSession:
    task_id: int = 0
    enabled: bool = False
    leader: str = ''
    token: str = ''
    restore: dict = field(default_factory=dict)


@dataclass
class _SmallSession:
    task_id: int = 0
    nickname: str = ''
    token: str = ''
    pending_token: str = ''
    leader: str = ''
    phase: str = 'starting'


_main = _MainSession()
_small = _SmallSession()


def _fallback(context, reason):
    if _main.enabled:
        status = companion_manager.status()
        logger.warning(f'每日悬赏拉小号回退原组队流程，原因={reason}，小号状态={status.get("state")}，小号原因={status.get("reason", "未报告")}')
    _main.enabled = False
    try:
        companion_manager.stop(task_id=_main.task_id)
    except Exception as exc:
        logger.warning(f'小号异步回收请求失败，退出时重试 {exc}')
    if _main.restore:
        context.override_pipeline(deepcopy(_main.restore))


@AgentServer.custom_action('PrepareBountyCompanion')
class PrepareBountyCompanion(CustomAction):
    def run(self, context, argv):
        global _main
        task_id = argv.task_detail.task_id
        if _main.task_id == task_id:
            return True
        _main = _MainSession(task_id=task_id)
        try:
            config = (context.get_node_data('每日悬赏小号配置') or {}).get('attach', {})
            if config.get('enabled') is not True:
                return True
            if not companion_manager.start(str(config.get('instance', '')), task_id):
                logger.warning(f'每日悬赏小号无法启动，沿用原流程，原因={companion_manager.status().get("reason")}')
                return True
            for node in (INVITE_ENTRY, HOME_ENTRY, *DRAGON_NODES):
                data = context.get_node_data(node) or {}
                if node in (INVITE_ENTRY, HOME_ENTRY):
                    _main.restore[node] = {'next': deepcopy(data.get('next', []))}
                else:
                    enabled = data.get('enabled', data.get('enable', True))
                    _main.restore[node] = {'enabled': enabled, 'enable': enabled}
            patch = {node: {'enabled': False, 'enable': False} for node in DRAGON_NODES}
            patch[INVITE_ENTRY] = {'next': ['每日悬赏邀请小号']}
            patch[HOME_ENTRY] = {'next': ['每日悬赏记录大号昵称']}
            context.override_pipeline(patch)
            _main.enabled = True
            logger.info(f'每日悬赏已后台准备小号实例 {config.get("instance")}')
        except Exception as exc:
            _fallback(context, str(exc))
        return True


@AgentServer.custom_action('CaptureBountyLeader')
class CaptureBountyLeader(CustomAction):
    def run(self, context, argv):
        if argv.task_detail.task_id != _main.task_id or not _main.enabled:
            return False
        names = iter_ocr_boxes(argv.reco_detail)
        if len(names) != 1 or not normalized_name(names[0][0]):
            return False
        _main.leader = names[0][0]
        return True


@AgentServer.custom_action('InviteBountyCompanion')
class InviteBountyCompanion(CustomAction):
    def run(self, context, argv):
        if argv.task_detail.task_id != _main.task_id or not _main.enabled or not _main.leader:
            return False
        status = companion_manager.status()
        nickname = str(status.get('nickname', '')).strip()
        if status.get('state') != 'ready' or not normalized_name(nickname):
            return False
        return context.override_pipeline({'每日悬赏好友目标昵称': {
            'recognition': {'param': {'expected': [nickname_pattern(nickname)]}}}})


@AgentServer.custom_action('BindBountyFriendRow')
class BindBountyFriendRow(CustomAction):
    """将流水线识别到的唯一昵称行绑定给后续原生OCR复核节点。"""
    def run(self, context, argv):
        if argv.task_detail.task_id != _main.task_id or not _main.enabled:
            return False
        names = iter_ocr_boxes(argv.reco_detail)
        if len(names) != 1:
            return False
        _, y, _, height = box_xywh(names[0][1])
        center = y + height // 2
        if not 105 <= center <= 648:
            return False
        return context.override_pipeline({
            '每日悬赏复核小号昵称': {'recognition': {'param': {
                'roi': [915, center - 24, 165, 48], 'expected': [nickname_pattern(names[0][0])]}}},
            '每日悬赏小号行邀请按钮': {'recognition': {'param': {
                'roi': [1150, center - 28, 125, 56]}}},
        })


@AgentServer.custom_action('ArmBountyInvitation')
class ArmBountyInvitation(CustomAction):
    def run(self, context, argv):
        if argv.task_detail.task_id != _main.task_id or not _main.enabled:
            return False
        _main.token = companion_manager.permit_invitation(25, leader_name=_main.leader) or ''
        return bool(_main.token)


@AgentServer.custom_action('FinishBountyInvitation')
class FinishBountyInvitation(CustomAction):
    def run(self, context, argv):
        if argv.task_detail.task_id != _main.task_id or not _main.enabled:
            return False
        status = companion_manager.status()
        if not _main.token or status.get('token') != _main.token or status.get('state') not in {'teamed', 'fighting'}:
            return False
        companion_manager.revoke_invitation()
        context.override_pipeline({'每日悬赏设置小号等待时限': {'action': {'param': {
            'custom_action_param': {'scope': '悬赏小号就绪', 'duration_ms': 30000}}}}})
        logger.info(f'每日悬赏小号 {status.get("nickname")!r} 已加入并准备')
        return True


@AgentServer.custom_action('FallbackBountyCompanion')
class FallbackBountyCompanion(CustomAction):
    def run(self, context, argv):
        if argv.task_detail.task_id == _main.task_id:
            _fallback(context, '小号准备、搜索或邀请未完成')
        return True


@AgentServer.custom_recognition('BountyCompanionSession')
class BountyCompanionSession(CustomRecognition):
    """只提供当前CLI是否是父任务创建的小号会话，不读取或操作设备。"""
    def analyze(self, context, argv):
        session = read_session()
        if not session.get('name'):
            return None
        return CustomRecognition.AnalyzeResult(box=[0, 0, 1, 1], detail={})


@AgentServer.custom_recognition('BountyCompanionState')
class BountyCompanionState(CustomRecognition):
    def analyze(self, context, argv):
        param = parse_pipeline_json_param(argv.custom_recognition_param)
        if param.get('side') == 'small':
            if argv.task_detail.task_id != _small.task_id:
                return None
            state = {'state': _small.phase, 'token': _small.token}
        else:
            if argv.task_detail.task_id != _main.task_id or not _main.enabled:
                return None
            state = companion_manager.status()
            if param.get('match_token') and (not _main.token or state.get('token') != _main.token):
                return None
        if state.get('state') not in param.get('states', []):
            return None
        return CustomRecognition.AnalyzeResult(box=[0, 0, 1, 1], detail=state)


@AgentServer.custom_action('InitializeBountyCompanion')
class InitializeBountyCompanion(CustomAction):
    def run(self, context, argv):
        global _small
        _small = _SmallSession(task_id=argv.task_detail.task_id)
        if not read_session().get('name'):
            publish_state('failed', reason='请从大号拉小号模式调用')
            return False
        return True


@AgentServer.custom_action('RecordBountyCompanionNickname')
class RecordBountyCompanionNickname(CustomAction):
    def run(self, context, argv):
        names = iter_ocr_boxes(argv.reco_detail)
        if argv.task_detail.task_id != _small.task_id or len(names) != 1 or not normalized_name(names[0][0]):
            return False
        _small.nickname = names[0][0]
        logger.info(f'每日悬赏小号当前昵称 {_small.nickname!r}')
        return True


@AgentServer.custom_recognition('BountyInvitationPermit')
class BountyInvitationPermit(CustomRecognition):
    def analyze(self, context, argv):
        request = read_request()
        if argv.task_detail.task_id != _small.task_id or not request or not request.get('leader_name'):
            return None
        pattern = nickname_pattern(request['leader_name'])
        if not context.override_pipeline({
            '悬赏小号授权邀请人': {'recognition': {'param': {'expected': [pattern]}}},
            '悬赏小号授权队长': {'recognition': {'param': {'expected': [pattern]}}},
        }):
            return None
        _small.pending_token = request['token']
        return CustomRecognition.AnalyzeResult(box=[0, 0, 1, 1], detail={'token': request['token']})


@AgentServer.custom_action('BeginBountyCompanionJoin')
class BeginBountyCompanionJoin(CustomAction):
    def run(self, context, argv):
        request = read_request()
        if argv.task_detail.task_id != _small.task_id or not request or request['token'] != _small.pending_token:
            return False
        _small.token = request['token']
        _small.leader = request['leader_name']
        _small.phase = 'joining'
        return publish_state('joining', nickname=_small.nickname, token=_small.token)


@AgentServer.custom_action('ReportBountyCompanionState')
class ReportBountyCompanionState(CustomAction):
    def run(self, context, argv):
        if argv.task_detail.task_id != _small.task_id:
            return False
        phase = parse_pipeline_json_param(argv.custom_action_param).get('state')
        if phase not in {'ready', 'teamed', 'fighting', 'settling', 'returning'} or not _small.nickname:
            return False
        if _small.phase != phase:
            logger.info(f'每日悬赏小号状态 {_small.phase} -> {phase}')
        _small.phase = phase
        return publish_state(phase, nickname=_small.nickname, token=_small.token)


@AgentServer.custom_action('FailBountyCompanion')
class FailBountyCompanion(CustomAction):
    def run(self, context, argv):
        from runtime.run_result import invocation_result
        invocation_result.record('failed', 'companion_task_failed')
        publish_state('failed', reason='小号协同流水线失败')
        return True
