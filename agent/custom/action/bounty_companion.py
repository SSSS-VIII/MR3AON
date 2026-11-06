"""每日悬赏协同。实例生命周期在 runtime，界面动作只在当前任务回调执行。"""
from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass, field
import re
import time

import numpy as np
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction

from custom.reco.landlady_qa import iter_ocr_boxes, box_xywh
from custom.reward_shots import save_image_array
from runtime.companion import companion_manager, publish_state, read_request, read_session
from utils.logger import logger

INVITE_ENTRY = '每日悬赏展开了邀请页面'
DRAGON_NODES = ('每日悬赏家族组队任务', '每日悬赏好友组队任务')
PROFILE_ID = [928, 202, 190, 48]
PROFILE_NAME = [786, 155, 190, 45]


def normalized_name(text):
    return re.sub(r'\s+', '', text)


def exact_game_id(text):
    match = re.fullmatch(r'(?:ID[:：]?)?([0-9]{1,20})', re.sub(r'\s+', '', text), re.I)
    return match.group(1) if match else None


def _frame(context):
    job = context.tasker.controller.post_screencap().wait()
    if not job.succeeded:
        raise RuntimeError('协同截图失败')
    return context.tasker.controller.cached_image


def _ocr(context, image, roi, expected='.'):
    name = '小号协同OCR'
    detail = context.run_recognition(name, image, {name: {'recognition': {
        'type': 'OCR', 'param': {'roi': roi, 'expected': [expected]}}}})
    return iter_ocr_boxes(detail)


def _text(context, image, roi):
    return ''.join(text for text, _ in _ocr(context, image, roi))


def _hit(context, image, node):
    detail = context.run_recognition(node, image)
    return detail if detail and detail.hit else None


def _tap(context, x, y, delay=.35):
    if context.tasker.stopping:
        raise RuntimeError('任务正在停止')
    if not context.tasker.controller.post_click(int(x), int(y)).wait().succeeded:
        raise RuntimeError('协同点击失败')
    if delay:
        time.sleep(delay)


def _click_box(context, box, delay=.35):
    x, y, w, h = box_xywh(box)
    _tap(context, x + w // 2, y + h // 2, delay)


def _click_text(context, image, roi, expected, delay=.35):
    items = _ocr(context, image, roi, expected)
    if not items:
        return False
    _click_box(context, items[0][1], delay)
    return True


def _swipe(context, upward=True):
    begin, end = (575, 175) if upward else (150, 620)
    if not context.tasker.controller.post_swipe(1100, begin, 1100, end, 350).wait().succeeded:
        raise RuntimeError('协同滑动失败')
    time.sleep(.35)


def _profile(context):
    # 邀请列表点头像默认进入“搭配”；必须先切到个人信息，再读完整ID。
    deadline = time.monotonic() + 4
    opened = False
    while time.monotonic() < deadline and not context.tasker.stopping:
        image = _frame(context)
        if _click_text(context, image, [78, 48, 205, 80], '个人信息'):
            opened = True
            break
        time.sleep(.2)
    if not opened:
        raise RuntimeError('未打开个人信息')
    deadline = time.monotonic() + 4
    game_id, nickname = None, ''
    while time.monotonic() < deadline and not context.tasker.stopping:
        image = _frame(context)
        game_id = exact_game_id(_text(context, image, PROFILE_ID))
        nickname = _text(context, image, PROFILE_NAME).strip()
        if game_id and nickname:
            break
        time.sleep(.2)  # 好友资料需要网络加载，不能把翻页中的背景当作ID。
    _tap(context, 1165, 87)
    if not game_id or not nickname:
        raise RuntimeError('个人信息ID或昵称识别失败')
    return game_id, nickname


@dataclass
class _MainSession:
    task_id: int = 0
    enabled: bool = False
    game_id: str = ''
    leader: str = ''
    restore: dict = field(default_factory=dict)
    started_at: float = 0
    has_invited: bool = False


_main = _MainSession()


def _fallback(context, reason):
    if _main.enabled:
        logger.warning(f'每日悬赏拉小号回退原组队流程，原因={reason}')
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
            return True  # 同一顶层任务出错重进，不重复冷启动或再次尝试失败的小号。
        _main = _MainSession(task_id=task_id)
        try:
            config = (context.get_node_data('每日悬赏小号配置') or {}).get('attach', {})
            if config.get('enabled') is not True:
                return True
            _main.game_id = str(config.get('game_id', '')).strip()
            if not companion_manager.start(str(config.get('instance', '')), _main.game_id, task_id):
                logger.warning(f'每日悬赏小号无法启动，沿用原流程，原因={companion_manager.status().get("reason")}')
                return True
            # 只覆盖本次任务。回退时恢复该账号原来的龙血开关及邀请顺序。
            for node in (INVITE_ENTRY, *DRAGON_NODES):
                data = context.get_node_data(node) or {}
                if node == INVITE_ENTRY:
                    _main.restore[node] = {'next': deepcopy(data.get('next', []))}
                else:
                    enabled = data.get('enabled', data.get('enable', True))
                    _main.restore[node] = {'enabled': enabled, 'enable': enabled}
            patch = {node: {'enabled': False, 'enable': False} for node in DRAGON_NODES}
            patch[INVITE_ENTRY] = {'next': ['每日悬赏邀请小号']}
            context.override_pipeline(patch)
            _main.enabled = True
            _main.started_at = time.monotonic()
            logger.info(f'每日悬赏已后台准备小号实例 {config.get("instance")}')
        except Exception as exc:
            _fallback(context, str(exc))
        return True


@AgentServer.custom_action('CaptureBountyLeader')
class CaptureBountyLeader(CustomAction):
    def run(self, context, argv):
        if argv.task_detail.task_id != _main.task_id:
            return True
        if _main.enabled:
            try:
                # 主页固定昵称区域，与邀请弹窗中的邀请人交叉确认。
                _main.leader = _text(context, _frame(context), [140, 24, 210, 46]).strip()
                if not _main.leader:
                    _fallback(context, '未识别大号昵称')
            except Exception as exc:
                _fallback(context, str(exc))
        return True


def _find_friend(context, game_id, nickname, deadline):
    """查在线候选，点头像核对ID，再验证原行未变化；不群邀、不加好友。"""
    expected_name = normalized_name(nickname)
    if not expected_name:
        return None
    _tap(context, 885, 57)
    # 每次列表打开会记住滚动位置，先回顶。限定总搜索时间与页数。
    _swipe(context, upward=False)
    _swipe(context, upward=False)
    previous_page = None
    for _ in range(6):
        if time.monotonic() >= deadline or context.tasker.stopping:
            return None
        image = _frame(context)
        buttons = _ocr(context, image, [1150, 90, 125, 580], '^邀请$')
        fingerprint = tuple((text, tuple(box_xywh(box))) for text, box in _ocr(context, image, [915, 90, 165, 580]))
        if fingerprint == previous_page:
            return None
        previous_page = fingerprint
        for _, box in buttons:
            if time.monotonic() >= deadline:
                return None
            x, y, w, h = box_xywh(box)
            cy = y + h // 2
            if not 105 <= cy <= 648:
                continue  # 部分露出的行不做头像/邀请配对。
            before = _frame(context)
            row_name = normalized_name(_text(context, before, [916, cy - 24, 162, 48]))
            # 备注、截断或空白 OCR 都不能证明该行对应小号；只检查昵称完整匹配的候选。
            if not row_name or row_name != expected_name:
                continue
            _tap(context, 852, cy)
            found_id, profile_name = _profile(context)
            if found_id != game_id or normalized_name(profile_name) != expected_name:
                continue
            after = _frame(context)
            # 列表在线排序可变化，个人信息关闭后必须确认仍是同一行。
            if normalized_name(_text(context, after, [916, cy - 24, 162, 48])) != expected_name:
                continue
            a, b = before[cy-32:cy+32, 824:886], after[cy-32:cy+32, 824:886]
            if a.shape != b.shape or np.mean(np.abs(a.astype(float) - b.astype(float))) > 12:
                continue
            current = _ocr(context, after, [1150, cy-28, 125, 56], '^邀请$')
            if current:
                return current[0][1]
        if not buttons:
            return None
        _swipe(context)
    return None


@AgentServer.custom_action('InviteBountyCompanion')
class InviteBountyCompanion(CustomAction):
    def run(self, context, argv):
        if argv.task_detail.task_id != _main.task_id:
            return False
        try:
            if not _main.enabled or not _main.leader:
                raise RuntimeError('本次协同未就绪')
            # Android 与大号导航并行；到邀请点仅等待剩余准备预算。
            remaining = 30 if _main.has_invited else max(0, 150 - (time.monotonic() - _main.started_at))
            if not companion_manager.wait_ready(remaining, cancelled=lambda: context.tasker.stopping, states={'ready'}):
                raise RuntimeError(f'小号未就绪 {companion_manager.status().get("reason", "等待超时")}')
            status = companion_manager.status()
            if status.get('game_id') != _main.game_id:
                raise RuntimeError('小号实际登录ID与配置不一致')
            # 小号冷启动期间，列表可能仍保留离线结果。关开一次刷新。
            _tap(context, 703, 44)
            image = _frame(context)
            if not _click_text(context, image, [517, 233, 244, 251], '点击邀请好友', .7):
                raise RuntimeError('主队伍邀请入口未出现')
            box = _find_friend(context, _main.game_id, status.get('nickname', ''), time.monotonic() + 30)
            if box is None:
                raise RuntimeError('未在好友列表找到可邀请的目标ID')
            token = companion_manager.permit_invitation(25, leader_name=_main.leader)
            if not token:
                raise RuntimeError('小号已退出')
            _click_box(context, box)
            _tap(context, 703, 44)
            deadline = time.monotonic() + 25
            while time.monotonic() < deadline and not context.tasker.stopping:
                status = companion_manager.status()
                if status.get('state') == 'teamed' and status.get('token') == token:
                    companion_manager.revoke_invitation()
                    _main.has_invited = True
                    logger.info(f'每日悬赏小号已按ID {_main.game_id} 加入并准备')
                    return True
                if status.get('state') in {'failed', 'stopped', 'stopping'}:
                    break
                time.sleep(.15)
            raise RuntimeError('小号未在限时内加入并准备')
        except Exception as exc:
            _fallback(context, str(exc))
            return False


@AgentServer.custom_action('FallbackBountyCompanion')
class FallbackBountyCompanion(CustomAction):
    def run(self, context, argv):
        if argv.task_detail.task_id != _main.task_id:
            return True
        _fallback(context, '定向组队未完成')
        # 只收起已确认的信息/邀请面板，然后交原“退出队伍”链回任务页重建龙血时限。
        image = _frame(context)
        if _ocr(context, image, [78, 48, 205, 80], '个人信息'):
            _tap(context, 1165, 87)
            image = _frame(context)
        if _hit(context, image, '每日悬赏展开了邀请页面'):
            _tap(context, 703, 44)
        return True


@dataclass
class _SmallSession:
    game_id: str = ''
    nickname: str = ''
    token: str = ''
    leader: str = ''
    phase: str = 'starting'
    progress_at: float = 0


_small = _SmallSession()


def _publish(state, **details):
    if _small.phase != state:
        _small.progress_at = time.monotonic()
        logger.info(f'每日悬赏小号状态 {_small.phase} -> {state}')
    _small.phase = state
    return publish_state(state, game_id=_small.game_id, nickname=_small.nickname,
                         token=_small.token, **details)


def _unblock_invites(context):
    image = _frame(context)
    setting = _hit(context, image, '关闭游戏打开设置')
    if not setting:
        raise RuntimeError('小号主页设置入口未识别')
    _click_box(context, setting.box, .7)
    for _ in range(10):
        image = _frame(context)
        label = _hit(context, image, '关闭游戏屏蔽所有组队邀请')
        if label:
            checked = _hit(context, image, '点击取消勾选屏蔽')
            if checked:
                _click_box(context, checked.box)
                image = _frame(context)
                if _hit(context, image, '点击取消勾选屏蔽'):
                    raise RuntimeError('取消屏蔽组队邀请未生效')
            # 设置页的右上叉，使用现有关闭设置识别与动作，避免Android返回退出游戏。
            close = _hit(context, image, '启动阶段关闭设置')
            if not close:
                raise RuntimeError('设置页关闭按钮未识别')
            context.run_action('启动阶段关闭设置', close.box, '')
            time.sleep(.5)
            return
        # 设置的滚动区较短，原快速长滑会直接惯性到底并越过邀请项。
        context.tasker.controller.post_swipe(1100, 420, 1100, 350, 600).wait()
        time.sleep(.4)
    raise RuntimeError('未确认小号组队邀请设置，取消协同')


@AgentServer.custom_action('InitializeBountyCompanion')
class InitializeBountyCompanion(CustomAction):
    def run(self, context, argv):
        global _small
        _small = _SmallSession(progress_at=time.monotonic())
        try:
            session = read_session()
            if not session.get('game_id'):
                raise RuntimeError('此任务由每日悬赏拉小号模式管理，请从大号启用')
            if not _hit(context, _frame(context), '每日悬赏确认在主页面'):
                raise RuntimeError('小号启动未到主页')
            _tap(context, 230, 45)
            _small.game_id, _small.nickname = _profile(context)
            if _small.game_id != session['game_id']:
                raise RuntimeError('实例当前登录账号ID与配置小号ID不一致')
            _unblock_invites(context)
            if not _hit(context, _frame(context), '每日悬赏确认在主页面'):
                raise RuntimeError('小号设置后未返回主页')
            _publish('ready')
            return True
        except Exception as exc:
            publish_state('failed', reason=str(exc))
            logger.warning(f'每日悬赏小号准备失败 {exc}')
            return False


def _accept_invite(context, image):
    request = read_request()
    # 接受必须同时满足本次短期许可、邀请人、每日悬赏类型，不能被其它组队弹窗带走。
    if not _ocr(context, image, [555, 185, 220, 55], '每日悬赏'):
        if _ocr(context, image, [100, 205, 270, 42], '来自好友'):
            return _click_text(context, image, [365, 490, 220, 80], '^拒绝$')
        return False
    inviter = _text(context, image, [100, 242, 350, 44])
    if not request or normalized_name(inviter) != normalized_name(request.get('leader_name', '')):
        _click_text(context, image, [365, 490, 220, 80], '^拒绝$')
        return True
    if _click_text(context, image, [700, 490, 220, 80], '^同意$'):
        _small.token = request['token']
        _small.leader = request['leader_name']
        _publish('joining')
        return True
    return False


def _leave_team(context, image):
    if _ocr(context, image, [525, 340, 240, 65], '确定离开队伍'):
        _click_text(context, image, [690, 490, 230, 80], '^确定$')
        return True
    button = _hit(context, image, '每日悬赏没人打则点击退出')
    if button:
        _click_box(context, button.box)
        return True
    return False


def _save_reward(image):
    # 同步复用截图存储，避免嵌套Custom动作因不存在的reco_id而丢失图片。
    if save_image_array(image, '每日悬赏', burst_replace=True,
                        burst_entry=_small.token, node_name='每日悬赏小号结算') is None:
        raise RuntimeError('小号奖励截图保存失败')


@AgentServer.custom_action('PollBountyCompanion')
class PollBountyCompanion(CustomAction):
    def run(self, context, argv):
        try:
            if context.tasker.stopping:
                return True
            # 必须先检查再执行动作，准备/结算等分支提前 return 也不能绕过时限。
            limit = 480 if _small.phase == 'fighting' else 120
            if _small.phase != 'ready' and time.monotonic() - _small.progress_at > limit:
                raise RuntimeError('小号组队/战斗超过限定时间无状态进展')
            image = _frame(context)
            if _accept_invite(context, image):
                return True
            if _small.phase in {'joining', 'teamed'}:
                # 队长位昵称必须与发出本轮邀请的大号一致，换队长或掉队则回主页。
                leader = _text(context, image, [339, 148, 169, 48])
                prepare = _ocr(context, image, [965, 628, 300, 80], '^准备$|^取消准备$')
                if prepare:
                    if normalized_name(leader) != normalized_name(_small.leader):
                        _publish('returning')
                    elif prepare[0][0] == '准备':
                        _click_box(context, prepare[0][1])
                        return True
                    else:
                        _publish('teamed')
                        return True
                # 队长退出时小号成为队长，底部会变为“至少需要二人/出发”。
                if _ocr(context, image, [965, 628, 300, 80], '至少需要二人|出发'):
                    _publish('returning')
            in_result = bool(_ocr(context, image, [430, 20, 450, 170], '每日悬赏|讨伐失败|恭喜获得'))
            reward_popup = _hit(context, image, '每日悬赏点击空白处关闭') if in_result else None
            if reward_popup and _small.phase in {'teamed', 'fighting', 'settling'}:
                _save_reward(image)
                context.run_action('每日悬赏点击空白处关闭', reward_popup.box, '')
                time.sleep(1.5)
                _publish('settling')
                return True
            settlement = _hit(context, image, '每日悬赏结算截图') if in_result else None
            if settlement and _small.phase in {'teamed', 'fighting', 'settling'}:
                _save_reward(image)
                context.run_action('每日悬赏结算确定', settlement.box, '')
                _publish('settling')
                return True
            if _hit(context, image, '每日悬赏确认在主页面'):
                _publish('ready')
                return True
            if _small.phase in {'settling', 'returning'}:
                _publish('returning')
                _leave_team(context, image)
            elif _small.phase in {'teamed', 'fighting'}:
                # 复用真实战内识别，只有确认战斗画面才点技能，不点付费接力。
                if _hit(context, image, '每日悬赏识别到进入了战斗'):
                    _publish('fighting')
                    _tap(context, 80, 360, .1)
            return True
        except Exception as exc:
            if context.tasker.stopping:
                return True  # 正常回收可打断正在进行的截图/点击，不登记为业务失败。
            publish_state('failed', reason=str(exc))
            logger.warning(f'每日悬赏小号异常 {exc}')
            return False


@AgentServer.custom_action('FailBountyCompanion')
class FailBountyCompanion(CustomAction):
    def run(self, context, argv):
        from runtime.run_result import invocation_result
        invocation_result.record('failed', 'companion_task_failed')
        publish_state('failed', reason='小号协同任务失败')
        return True
