"""工坊周任务，按任务页确认进度，通关任务不作为完成条件。"""
from __future__ import annotations

import re
import time

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction

from custom.reco.landlady_qa import box_xywh, iter_ocr_boxes
from custom.reward_shots import save_image_array
from utils.logger import logger


def quest_kind(text):
    text = re.sub(r'\s+', '', text)
    if '通关' in text:
        return None
    if '游玩' in text and '10' in text:
        return 'repeat'
    if '游玩' in text and '3' in text:
        return 'maps'
    if '查看' in text and '轮换' in text:
        return 'view'
    if '分享' in text and '地图' in text:
        return 'share'
    return None


class WorkshopUI:
    def __init__(self, context):
        self.context = context
        self.deadline = time.monotonic() + 3600

    def frame(self):
        if self.context.tasker.stopping or time.monotonic() > self.deadline:
            raise RuntimeError('工坊挑战中断或超过一小时')
        job = self.context.tasker.controller.post_screencap().wait()
        if not job.succeeded:
            raise RuntimeError('工坊挑战截图失败')
        return self.context.tasker.controller.cached_image

    def ocr(self, image, roi, expected='.'):
        name = '工坊挑战OCR'
        result = self.context.run_recognition(name, image, {name: {
            'recognition': {'type': 'OCR', 'param': {'roi': roi, 'expected': [expected]}}}})
        return iter_ocr_boxes(result)

    def tap(self, x, y, delay=.7):
        if self.context.tasker.stopping:
            raise RuntimeError('工坊挑战正在停止')
        if not self.context.tasker.controller.post_click(x, y).wait().succeeded:
            raise RuntimeError('工坊挑战点击失败')
        time.sleep(delay)

    def click(self, image, roi, expected):
        hits = self.ocr(image, roi, expected)
        if not hits:
            return False
        x, y, w, h = box_xywh(hits[0][1])
        self.tap(x + w // 2, y + h // 2)
        return True

    def swipe(self, up=True):
        start, end = (540, 230) if up else (230, 550)
        if not self.context.tasker.controller.post_swipe(1000, start, 1000, end, 600).wait().succeeded:
            raise RuntimeError('工坊任务列表滑动失败')
        time.sleep(.6)

    def wait_text(self, roi, expected, seconds=15):
        end = time.monotonic() + seconds
        while time.monotonic() < end:
            image = self.frame()
            if self.ocr(image, roi, expected):
                return image
            time.sleep(.5)
        raise RuntimeError(f'工坊页面等待超时 {expected}')

    def dismiss_reward(self):
        image = self.frame()
        if self.ocr(image, [450, 65, 390, 95], '恭喜获得'):
            if save_image_array(image, '工坊挑战', node_name='工坊任务奖励物品') is None:
                raise RuntimeError('工坊奖励物品截图失败')
            if not self.click(image, [500, 595, 290, 100], '^确定$'):
                raise RuntimeError('工坊奖励确定按钮未识别')

    def leave_result(self, image):
        if not self.ocr(image, [650, 220, 610, 180], '本次收集|最高排名|挑战榜排名'):
            return False
        if not self.ocr(image, [660, 525, 230, 105], '^返回$'):
            return False
        if save_image_array(image, '工坊挑战', node_name='工坊挑战结算') is None:
            raise RuntimeError('工坊结算截图失败')
        self.click(image, [660, 525, 230, 105], '^返回$')
        self.wait_text([860, 630, 205, 80], '^单人挑战$')
        # 结算可能回到地图作品的资料面板，重新切回本周挑战。
        if self.ocr(self.frame(), [860, 630, 205, 80], '单人挑战'):
            self.tap(240, 400)
        self.tap(110, 450)
        self.wait_text([260, 95, 990, 200], '本周挑战|每周轮换')
        return True

    def enter(self):
        self.dismiss_reward()
        self.leave_result(self.frame())
        image = self.frame()
        if self.ocr(image, [860, 630, 205, 80], '单人挑战'):
            self.tap(240, 400)
            image = self.frame()
        if self.ocr(image, [500, 70, 330, 60], '每周任务'):
            self.tap(1148, 77)
            image = self.frame()
        if self.ocr(image, [90, 10, 300, 90], '集会所'):
            self.tap(60, 45)
            image = self.wait_text([0, 100, 330, 450], '工坊挑战')
        if not self.ocr(image, [90, 10, 230, 80], '创意工坊'):
            if not self.click(image, [0, 100, 330, 450], '工坊挑战'):
                raise RuntimeError('主页未找到工坊挑战入口')
            self.wait_text([90, 10, 230, 80], '创意工坊')
        self.tap(110, 450)
        self.wait_text([260, 95, 990, 200], '本周挑战|每周轮换')

    def tasks(self):
        self.tap(1065, 45)
        self.wait_text([500, 70, 330, 60], '每周任务')
        self.swipe(False)
        states = {}
        # 领取后任务行会重新排序，每次重新从头扫描。
        for _ in range(12):
            claimed = False
            for page in range(2):
                image = self.frame()
                rows = self.ocr(image, [345, 140, 510, 440])
                for text, box in rows:
                    kind = quest_kind(text)
                    if kind is None:
                        continue
                    _, y, _, h = box_xywh(box)
                    cy = y + h // 2
                    if not 163 <= cy <= 565:
                        continue
                    status = self.ocr(image, [870, cy - 42, 245, 82])
                    label = ''.join(item[0] for item in status)
                    if any(item[0] == '领取' for item in status):
                        if save_image_array(image, '工坊挑战', node_name='工坊任务奖励') is None:
                            raise RuntimeError('工坊奖励截图失败')
                        self.click(image, [870, cy - 42, 245, 82], '^领取$')
                        self.dismiss_reward()
                        claimed = True
                        break
                    progress = re.search(r'(\d+)\s*/\s*(\d+)', label)
                    states[kind] = ('已领取' in label or '已完成' in label or
                                    bool(progress and int(progress[1]) >= int(progress[2])))
                if claimed:
                    break
                if page == 0:
                    self.swipe()
            if not claimed:
                break
            self.swipe(False)
        else:
            raise RuntimeError('工坊任务领取次数异常')
        self.tap(1148, 77)
        if set(states) != {'maps', 'repeat', 'view', 'share'}:
            raise RuntimeError(f'工坊任务未识别完整 {states}')
        logger.info(f'工坊挑战任务进度 {states}')
        self.share_done = states['share']
        return all(states.values())

    def play(self, column):
        self.tap((414, 752, 1090)[column], 659)
        image = self.wait_text([860, 630, 205, 80], '单人挑战')
        if not self.share_done:
            self.tap(340, 670)
            self.tap(386, 608)
            self.wait_text([400, 190, 540, 110], '分享成功', 5)
            image = self.frame()
        if not self.click(image, [860, 630, 205, 80], '^单人挑战$'):
            raise RuntimeError('未找到单人挑战按钮')
        image = self.wait_text([970, 620, 295, 90], '^完成$', 25)
        self.click(image, [970, 620, 295, 90], '^完成$')
        logger.info(f'工坊挑战地图第{column + 1}列开始挂机')
        end = time.monotonic() + 480
        while time.monotonic() < end:
            image = self.frame()
            if self.leave_result(image):
                return
            # 死亡接力只走结束出口，不点击角色或付费复活。
            if self.ocr(image, [300, 100, 700, 360], '接力'):
                self.click(image, [200, 400, 900, 310], '^放弃$|^结束挑战$|^结算$')
            time.sleep(1)
        raise RuntimeError('工坊单局挂机超过8分钟仍未结算')


@AgentServer.custom_action('RunWorkshopChallenge')
class RunWorkshopChallenge(CustomAction):
    def run(self, context, argv):
        try:
            ui = WorkshopUI(context)
            ui.enter()
            for attempt in range(18):
                if ui.tasks():
                    ui.tap(60, 45)
                    end = time.monotonic() + 15
                    while time.monotonic() < end:
                        result = context.run_recognition('每日悬赏确认在主页面', ui.frame())
                        if result and result.hit:
                            return True
                        image = ui.frame()
                        if ui.ocr(image, [90, 10, 300, 90], '集会所'):
                            ui.tap(60, 45)
                        time.sleep(.5)
                    raise RuntimeError('工坊完成后未回到主页')
                ui.play(attempt % 3)
            raise RuntimeError('工坊游玩18轮后任务仍未全部完成')
        except Exception as exc:
            logger.warning(f'工坊挑战未完成 {exc}')
            return False
