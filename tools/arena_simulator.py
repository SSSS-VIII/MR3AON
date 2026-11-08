#!/usr/bin/env python3
"""Native local arena sandbox. All input is confined to this pygame window."""
from __future__ import annotations

import argparse
from dataclasses import asdict
import json
import math
import os
from pathlib import Path
import time

from arena_model import Catalog, Physics, Runner, Stage

ROOT = Path(__file__).resolve().parents[1]
BG = (13, 19, 29)
PANEL = (20, 29, 42)
BORDER = (40, 54, 71)
INK = (227, 237, 244)
MUTED = (157, 177, 194)
TEAL = (83, 225, 186)
ORANGE = (255, 178, 107)
RED = (255, 108, 122)
BLUE = (111, 169, 248)
MODE_NAMES = {'endless': '经典竞技场', 'endless_gale': '疾风资源池',
              'singleendlessreserved1': '竞技场扩展池', 'training': '动作实验场'}


class App:
    def __init__(self, args):
        if args.headless:
            os.environ['SDL_VIDEODRIVER'] = 'dummy'
            os.environ['SDL_AUDIODRIVER'] = 'dummy'
        os.environ['PYGAME_HIDE_SUPPORT_PROMPT'] = '1'
        import pygame
        self.pg = pygame
        pygame.init()
        self.screen = pygame.display.set_mode((1320, 820), pygame.RESIZABLE)
        pygame.display.set_caption('忍三 · 动作参数调试器（不可用于视觉训练）')
        font = '/usr/share/fonts/google-noto-sans-cjk-vf-fonts/NotoSansCJK-VF.ttc'
        if not Path(font).exists():
            font = pygame.font.match_font('notosanscjksc,notosanscjk,wqyzenhei,dejavusans')
        self.fonts = {n: pygame.font.Font(font, n) for n in (12, 14, 15, 16, 18, 20, 24, 30, 40)}
        for face in self.fonts.values():
            face.set_bold(True)
        self.catalog = Catalog(args.dataset)
        self.physics = Physics.from_export(args.physics)
        self.original_physics = Physics(**asdict(self.physics))
        self.args = args
        self.clock = pygame.time.Clock()
        self.mode = args.mode
        self.stage_id = args.stage
        if self.mode != 'training' and self.stage_id not in self.catalog.paths[self.mode]:
            self.stage_id = self.catalog.ids(self.mode)[0]
        self.runner = Runner(self.catalog.load(self.mode, self.stage_id), self.physics)
        self.buttons = []
        self.show_boxes = True
        self.picker = False
        self.query = ''
        self.picker_offset = 0
        self.rate = 1.0
        self.camera_y = 0.0
        self.camera_x = -4.0
        self.zoom = 25.0
        self.running = True
        self.notice = '原始地图与角色配置已载入 · 按空格开始'
        self.notice_until = time.monotonic() + 5
        self.dragging = None
        self.parameter_rows = [('jump1', '一段跳参数', 5, 35), ('jump2', '二段跳参数', 5, 24),
                               ('up1', '一段上升重力', -50, -5), ('down1', '一段下降重力', -30, -3)]
        sw, sh = self.screen.get_size()
        self.viewport = pygame.Rect(24, 148, sw-312, sh-290)
        self.frames = 0
        self.input_events = []

    def text(self, text, x, y, size=16, color=INK, center=False):
        surface = self.fonts[size].render(str(text), True, color)
        rect = surface.get_rect(center=(int(x), int(y))) if center else surface.get_rect(topleft=(int(x), int(y)))
        self.screen.blit(surface, rect)
        return rect

    def box(self, rect, color=PANEL, radius=12, border=None):
        rect = self.pg.Rect(rect)
        self.pg.draw.rect(self.screen, color, rect, border_radius=radius)
        if border:
            self.pg.draw.rect(self.screen, border, rect, 1, border_radius=radius)
        return rect

    def button(self, label, rect, action, active=False, accent=False):
        rect = self.pg.Rect(rect)
        hover = rect.collidepoint(self.pg.mouse.get_pos()) and not self.picker
        color = (40, 73, 75) if active else (33, 48, 65) if hover else (26, 39, 55)
        self.box(rect, color, 9, TEAL if active or accent else BORDER)
        self.text(label, rect.centerx, rect.centery, 15, TEAL if active or accent else INK, True)
        self.buttons.append((rect, action))

    def load(self, mode, stage_id):
        god = self.runner.invincible
        override = self.runner.speed_override
        self.mode, self.stage_id = mode, stage_id
        self.runner = Runner(self.catalog.load(mode, stage_id), self.physics)
        self.runner.invincible, self.runner.speed_override = god, override
        self.camera_y, self.camera_x = self.runner.y, -4
        self.picker = False
        self.pg.key.stop_text_input()
        self.query = ''
        self.picker_offset = 0
        self.notice = '地图已切换 · 按空格开始'
        self.notice_until = time.monotonic() + 3

    def select_relative(self, direction):
        if self.mode == 'training':
            self.load('endless', 1031 if 1031 in self.catalog.paths['endless'] else self.catalog.ids('endless')[0])
            return
        ids = self.catalog.ids(self.mode)
        index = ids.index(self.stage_id)
        self.load(self.mode, ids[(index + direction) % len(ids)])

    def dispatch(self, action):
        r = self.runner
        if action == 'play':
            if r.dead or r.finished:
                r.reset()
            r.paused = not r.paused
            self.notice_until = 0
        elif action in ('jump', 'flip'):
            if r.paused and not r.dead and not r.finished:
                r.paused = False
            r.action(action)
            self.notice_until = 0
        elif action == 'restart':
            r.reset()
            self.camera_y = r.y
        elif action == 'checkpoint':
            point = r.checkpoint
            r.reset(point)
            self.camera_y = r.y
        elif action == 'next':
            self.select_relative(1)
        elif action == 'prev':
            self.select_relative(-1)
        elif action == 'picker':
            self.picker = not self.picker
            if self.picker:
                self.pg.key.start_text_input()
            else:
                self.pg.key.stop_text_input()
        elif action == 'boxes':
            self.show_boxes = not self.show_boxes
        elif action == 'god':
            r.invincible = not r.invincible
        elif action == 'slower':
            self.rate = max(0.25, self.rate - 0.25)
        elif action == 'faster':
            self.rate = min(2, self.rate + 0.25)
        elif action == 'reset_physics':
            for key, value in asdict(self.original_physics).items():
                setattr(self.physics, key, value)
            r.speed_override = 0
        elif action == 'record':
            out = ROOT / 'debug/arena-client/simulator'
            out.mkdir(parents=True, exist_ok=True)
            stamp = time.strftime('%Y%m%d-%H%M%S')
            replay = {'schema': 1, 'stage_source': r.stage.source, 'state': r.snapshot(),
                      'physics': asdict(self.physics), 'speed_override': r.speed_override,
                      'actions': r.actions, 'simulation_model': 'approximate; not client validated'}
            (out / f'run-{stamp}.json').write_text(json.dumps(replay, ensure_ascii=False, indent=2) + '\n')
            self.notice, self.notice_until = f'操作记录已保存：run-{stamp}.json', time.monotonic() + 4
        elif isinstance(action, tuple) and action[0] == 'mode':
            mode = action[1]
            self.load(mode, 0 if mode == 'training' else (1031 if mode == 'endless' and 1031 in self.catalog.paths[mode] else self.catalog.ids(mode)[0]))
        elif isinstance(action, tuple) and action[0] == 'stage':
            self.load(self.mode if self.mode != 'training' else 'endless', action[1])
        self.input_events.append(str(action))

    def handle(self, event):
        pg, r = self.pg, self.runner
        if event.type == pg.QUIT:
            self.running = False
        elif event.type == pg.VIDEORESIZE:
            self.screen = pg.display.set_mode((max(1280, event.w), max(800, event.h)), pg.RESIZABLE)
        elif event.type == pg.KEYDOWN:
            if self.picker:
                if event.key == pg.K_ESCAPE:
                    self.dispatch('picker')
                elif event.key == pg.K_BACKSPACE:
                    self.query = self.query[:-1]
                    self.picker_offset = 0
                elif event.key in (pg.K_RETURN, pg.K_KP_ENTER):
                    ids = self.filtered_ids()
                    if ids:
                        self.dispatch(('stage', ids[0]))
                elif event.key == pg.K_DOWN:
                    self.picker_offset += 1
                elif event.key == pg.K_UP:
                    self.picker_offset = max(0, self.picker_offset - 1)
                return
            mappings = {pg.K_SPACE: 'jump', pg.K_w: 'jump', pg.K_UP: 'jump',
                        pg.K_s: 'flip', pg.K_DOWN: 'flip', pg.K_p: 'play',
                        pg.K_r: 'restart', pg.K_c: 'checkpoint', pg.K_n: 'next',
                        pg.K_b: 'prev', pg.K_TAB: 'picker', pg.K_h: 'god',
                        pg.K_f: 'boxes', pg.K_MINUS: 'slower', pg.K_EQUALS: 'faster',
                        pg.K_F5: 'record'}
            if event.key == pg.K_ESCAPE:
                r.paused = True
            elif event.key in mappings:
                self.dispatch(mappings[event.key])
        elif event.type == pg.TEXTINPUT and self.picker:
            self.query += ''.join(c for c in event.text if c.isdigit())[:12]
            self.picker_offset = 0
        elif event.type == pg.MOUSEWHEEL:
            if self.picker:
                self.picker_offset = max(0, self.picker_offset - event.y * 4)
            else:
                self.zoom = min(40, max(16, self.zoom + event.y))
        elif event.type == pg.MOUSEBUTTONDOWN:
            if event.button == 3 and not self.picker:
                self.dispatch('flip')
                return
            if event.button != 1:
                return
            for rect, action in reversed(self.buttons):
                if rect.collidepoint(event.pos):
                    if isinstance(action, tuple) and action[0] == 'slider':
                        self.dragging = action[1:]
                        self.update_slider(event.pos[0])
                    else:
                        self.dispatch(action)
                    return
            if not self.picker and self.viewport.collidepoint(event.pos):
                self.dispatch('jump')
        elif event.type == pg.MOUSEMOTION and self.dragging:
            self.update_slider(event.pos[0])
        elif event.type == pg.MOUSEBUTTONUP:
            self.dragging = None

    def update_slider(self, x):
        field, left, width, lo, hi = self.dragging
        value = lo + min(1, max(0, (x - left) / width)) * (hi - lo)
        if field == 'speed':
            self.runner.speed_override = 0 if value < 1 else round(value, 1)
        else:
            setattr(self.physics, field, round(value, 1))

    def filtered_ids(self):
        mode = self.mode if self.mode != 'training' else 'endless'
        return [x for x in self.catalog.ids(mode) if self.query in str(x)]

    def world_pos(self, x, y):
        v = self.viewport
        return int(v.x + (x - self.camera_x) * self.zoom), int(v.y + v.height * 0.71 - (y - self.camera_y) * self.zoom)

    def draw_world(self):
        pg, r, v = self.pg, self.runner, self.viewport
        self.screen.set_clip(v)
        self.screen.fill((15, 26, 38), v)
        # Quiet world grid with world coordinates; the scene stays readable at pause.
        for x in range(math.floor(self.camera_x / 5) * 5, math.ceil((self.camera_x + v.width / self.zoom) / 5) * 5 + 1, 5):
            sx, _ = self.world_pos(x, self.camera_y)
            pg.draw.line(self.screen, (26, 40, 54), (sx, v.top), (sx, v.bottom))
            self.text(str(x), sx + 5, v.bottom - 23, 12, (77, 104, 124))
        for y in range(math.floor((self.camera_y - 20) / 5) * 5, math.ceil((self.camera_y + 25) / 5) * 5, 5):
            _, sy = self.world_pos(0, y)
            pg.draw.line(self.screen, (23, 37, 50), (v.left, sy), (v.right, sy))
        for s in r.stage.surfaces:
            a, b = self.world_pos(s.x1, s.y1), self.world_pos(s.x2, s.y2)
            if b[0] < v.left or a[0] > v.right:
                continue
            if s.kind == 0:
                pg.draw.line(self.screen, (38, 78, 77), (a[0], a[1] + 4), (b[0], b[1] + 4), 5)
                pg.draw.line(self.screen, TEAL, a, b, 3)
                if self.show_boxes:
                    for sx in range(max(a[0], v.left), min(b[0], v.right), 24):
                        pg.draw.line(self.screen, (60, 110, 108), (sx, a[1] - 3), (sx + 6, a[1] + 3))
            else:
                pg.draw.polygon(self.screen, (40, 46, 54), [a, b, (b[0], v.bottom + 300), (a[0], v.bottom + 300)])
                pg.draw.line(self.screen, ORANGE, a, b, 4)
            if a[0] > v.left + 10:
                self.text(f'{s.speed:g}', a[0] + 6, a[1] + 13, 12, MUTED)
        for item in r.stage.items:
            if item.collected:
                continue
            x, y = self.world_pos(item.x, item.y)
            if not v.inflate(40, 40).collidepoint(x, y):
                continue
            if item.kind == 50:
                pg.draw.circle(self.screen, (111, 83, 46), (x, y), 6)
                pg.draw.circle(self.screen, (249, 204, 119), (x, y), 4, 2)
            else:
                pg.draw.polygon(self.screen, (160, 137, 230), [(x, y-5), (x+5, y), (x, y+5), (x-5, y)], 1)
        for enemy in r.stage.enemies:
            ex, ey = enemy.position(r.time)
            x, y = self.world_pos(ex, ey)
            radius = max(5, int(enemy.radius() * self.zoom))
            if not v.inflate(radius*2, radius*2).collidepoint(x, y):
                continue
            if 'Blade' in enemy.name or enemy.kind == 101:
                points = []
                for k in range(16):
                    angle = k * math.pi / 8 + math.radians(enemy.angle) + r.time * 2
                    rad = radius if k % 2 == 0 else radius * .58
                    points.append((x + math.cos(angle) * rad, y + math.sin(angle) * rad))
                pg.draw.polygon(self.screen, RED, points)
                pg.draw.circle(self.screen, (72, 39, 49), (x, y), max(2, radius // 4))
            else:
                pg.draw.polygon(self.screen, RED, [(x-radius, y), (x, y-radius), (x+radius, y), (x, y+radius)])
                pg.draw.circle(self.screen, (60, 35, 47), (x, y), max(2, radius//3))
            if self.show_boxes:
                pg.draw.circle(self.screen, (156, 79, 95), (x, y), radius + 3, 1)
                self.text(str(enemy.kind), x + radius + 4, y - 9, 12, (198, 127, 136))
        if len(r.trail) > 2:
            points = [self.world_pos(x, y) for x, y in r.trail[::3]]
            pg.draw.lines(self.screen, (47, 102, 103), False, points, 2)
        x, feet = self.world_pos(r.x, r.y)
        height = max(10, int(r.body_height * self.zoom))
        width = max(16, int(r.body_radius * 2 * self.zoom + 11))
        rect = pg.Rect(x-width//2, feet-height, width, height)
        blink = r.hit_cooldown > 0 and int(r.time * 15) % 2
        if not blink:
            # A simple local avatar, not redistributed game art.
            self.box(rect.inflate(8, 4), (21, 39, 53), 8, (90, 139, 151))
            head = (x, rect.top + max(6, height//4))
            pg.draw.circle(self.screen, (35, 49, 63), head, max(7, width//2))
            pg.draw.line(self.screen, INK, (x-5, head[1]), (x+5, head[1]), 3)
            pg.draw.line(self.screen, ORANGE, (x-8, head[1]+4), (x+8, head[1]+4), 3)
            scarf = [(x-6, head[1]+5), (x-24, head[1]+2+math.sin(r.time*12)*3), (x-19, head[1]+9)]
            pg.draw.polygon(self.screen, ORANGE, scarf)
        if self.show_boxes:
            pg.draw.rect(self.screen, TEAL, rect.inflate(4, 2), 1, border_radius=4)
            pg.draw.circle(self.screen, TEAL, (x, feet), 3)
        self.text('小黑', x, rect.top - 19, 12, TEAL, True)
        # Compact overview of the original segment, including gaps.
        mx, my, mw = v.x + 20, v.bottom - 48, v.width - 40
        self.box((mx-8, my-12, mw+16, 24), (14, 23, 34), 6)
        for s in r.stage.surfaces:
            a = mx + s.x1 / max(r.stage.length, 1) * mw
            b = mx + s.x2 / max(r.stage.length, 1) * mw
            pg.draw.line(self.screen, TEAL if s.kind == 0 else ORANGE, (a, my), (b, my), 3)
        pg.draw.circle(self.screen, INK, (int(mx + min(1, r.x/max(r.stage.length,1))*mw), my), 4)
        self.screen.set_clip(None)

    def slider(self, field, label, value, x, y, lo, hi, width=208):
        self.text(label, x, y, 14, MUTED)
        self.text('自动' if field == 'speed' and not value else f'{value:g}', x + width, y, 14, TEAL)
        y += 30
        self.pg.draw.line(self.screen, BORDER, (x, y), (x+width, y), 4)
        t = min(1, max(0, (value-lo)/(hi-lo)))
        self.pg.draw.line(self.screen, TEAL, (x, y), (x+width*t, y), 4)
        self.pg.draw.circle(self.screen, INK, (int(x+width*t), y), 6)
        self.buttons.append((self.pg.Rect(x-8, y-12, width+16, 24), ('slider', field, x, width, lo, hi)))

    def draw(self):
        pg, r = self.pg, self.runner
        w, h = self.screen.get_size()
        self.buttons = []
        self.screen.fill(BG)
        self.text('NINJA / LOCAL LAB', 26, 18, 12, TEAL)
        self.text('动作参数调试器', 24, 39, 30)
        self.text('小黑基础动作  ·  本地运行', 250, 53, 15, MUTED)
        self.box((w-260, 31, 232, 33), (45, 40, 32), 8)
        self.text('非还原环境 · 不可视觉训练', w-144, 47, 14, ORANGE, True)
        labels = [('动作实验场', 'training'), ('经典竞技场', 'endless'), ('疾风资源池', 'endless_gale'), ('扩展资源池', 'singleendlessreserved1')]
        for index, (label, mode) in enumerate(labels):
            self.button(label, (24 + index*132, 92, 122, 36), ('mode', mode), self.mode == mode)
        self.button('选择地图  Tab', (w-260, 92, 232, 36), 'picker', accent=True)
        self.viewport = pg.Rect(24, 148, w-312, h-290)
        self.draw_world()
        pg.draw.rect(self.screen, BORDER, self.viewport, 1, border_radius=8)
        self.text(f'{MODE_NAMES[self.mode]}  /  {"动作实验场" if self.mode == "training" else "Stage " + str(self.stage_id)}', 42, 163, 18)
        state = '地面下闪' if r.roll_left > 0 else '翻绳中' if r.flip_target else '绳下' if r.underside else '跑动' if r.grounded else f'第{r.jumps}段跳' if r.jumps else '下落'
        self.text(f'{state}  ·  x {r.x:.1f}  y {r.y:.2f}  vy {r.vy:+.2f}', 42, 191, 14, MUTED)
        # Sidebar: telemetry, practice toggles and calibration controls.
        x, sidew = w-264, 236
        self.box((x, 148, sidew, h-290), PANEL, 10, BORDER)
        self.text('本次练习', x+17, 163, 18)
        self.text(f'{r.time:05.2f}', x+17, 191, 30, TEAL)
        self.text('秒', x+126, 209, 14, MUTED)
        self.text(f'速度 {r.speed:.1f}   金币 {r.coins}   碰撞 {r.hits}', x+17, 236, 14, MUTED)
        self.button('无敌练习', (x+14, 268, 100, 32), 'god', r.invincible)
        self.button('碰撞框 F', (x+122, 268, 100, 32), 'boxes', self.show_boxes)
        self.slider('speed', '水平速度覆盖', r.speed_override, x+16, 318, 0, 25, 185)
        for index, (field, label, lo, hi) in enumerate(self.parameter_rows):
            self.slider(field, label, getattr(self.physics, field), x+16, 380+index*58, lo, hi, 185)
        self.button('恢复提取值', (x+14, h-183, 100, 30), 'reset_physics')
        self.button('保存记录 F5', (x+122, h-183, 100, 30), 'record')
        # Bottom controls offer fully mouse-driven operation.
        y = h-122
        self.button('暂停 P' if not r.paused and not r.dead and not r.finished else '开始 / 继续 P', (24, y, 150, 46), 'play', accent=True)
        self.button('重开 R', (184, y, 88, 46), 'restart')
        self.button('检查点 C', (282, y, 104, 46), 'checkpoint')
        self.button('上一段 B', (396, y, 94, 46), 'prev')
        self.button('下一段 N', (500, y, 94, 46), 'next')
        self.button('−', (604, y, 35, 46), 'slower')
        self.text(f'{self.rate:.2f}×', 668, y+23, 15, MUTED, True)
        self.button('+', (699, y, 35, 46), 'faster')
        self.button('跳跃  SPACE / ↑', (w-548, y, 254, 46), 'jump', accent=True)
        self.button('下翻  S / ↓', (w-284, y, 256, 46), 'flip', accent=True)
        self.text('左键 / 空格：跳跃、二段跳     右键 / S：下翻     滚轮：缩放     Esc：暂停', 26, h-61, 14, MUTED)
        self.text('障碍使用简化碰撞形状；翻绳、时序与动态行为待实机校准。参数调整仅作用于本地。', 26, h-35, 12, (112, 132, 150))
        if time.monotonic() < self.notice_until:
            self.text(self.notice, self.viewport.centerx, self.viewport.bottom-77, 14, TEAL, True)
        if r.dead or r.finished or r.paused:
            self.draw_overlay()
        if self.picker:
            self.draw_picker()
        pg.display.flip()

    def draw_overlay(self):
        r, v = self.runner, self.viewport
        cx, cy = v.centerx, v.centery
        self.box((cx-210, cy-95, 420, 190), (20, 32, 46), 14, BORDER)
        if r.dead:
            title, sub = '本次练习结束', r.death_reason
        elif r.finished:
            title, sub = '本段完成', f'用时 {r.time:.2f} 秒 · 金币 {r.coins} · 碰撞 {r.hits}'
        else:
            title, sub = '准备好再出发' if r.time == 0 else '已暂停', '空格开始并起跳，P 开始跑动'
        self.text(title, cx, cy-53, 24, RED if r.dead else TEAL, True)
        self.text(sub[:38], cx, cy-13, 14, MUTED, True)
        if r.dead:
            self.button('从检查点继续 C', (cx-178, cy+29, 170, 39), 'checkpoint')
            self.button('重新开始 R', (cx+8, cy+29, 170, 39), 'restart')
        elif r.finished:
            self.button('再来一次 R', (cx-178, cy+29, 170, 39), 'restart')
            self.button('下一段 N', (cx+8, cy+29, 170, 39), 'next')
        else:
            self.button('开始 / 继续 P', (cx-90, cy+29, 180, 39), 'play', accent=True)

    def draw_picker(self):
        pg = self.pg
        w, h = self.screen.get_size()
        shade = pg.Surface((w, h), pg.SRCALPHA)
        shade.fill((3, 8, 15, 210))
        self.screen.blit(shade, (0, 0))
        # Underlying buttons cannot receive clicks while the modal is open.
        self.buttons = []
        x, y, width = w//2-320, 105, 640
        self.box((x, y, width, h-190), PANEL, 16, BORDER)
        self.text('选择客户端地图段', x+24, y+21, 24)
        self.button('关闭 Esc', (x+500, y+21, 112, 33), 'picker')
        mode = self.mode if self.mode != 'training' else 'endless'
        self.text(f'{MODE_NAMES[mode]} · 输入编号搜索，Enter 载入', x+25, y+64, 14, MUTED)
        self.box((x+24, y+96, 592, 43), BG, 9, TEAL)
        self.text(self.query or '输入 Stage 编号…', x+38, y+105, 18, INK if self.query else MUTED)
        ids = self.filtered_ids()
        visible = max(1, (h-390)//42)
        self.picker_offset = min(self.picker_offset, max(0, len(ids)-visible))
        for index, stage_id in enumerate(ids[self.picker_offset:self.picker_offset+visible]):
            row_y = y+157+index*42
            self.button(f'Stage {stage_id}     →', (x+24, row_y, 592, 35), ('stage', stage_id), stage_id == self.stage_id)
        self.text(f'{len(ids)} 个可练习地图段 · 空段已过滤 · 滚轮翻页', x+25, h-117, 14, MUTED)

    def run(self):
        while self.running:
            dt = (1/60 if self.args.headless else self.clock.tick(60)/1000)
            for event in self.pg.event.get():
                self.handle(event)
            self.runner.advance(dt * self.rate)
            self.camera_x += (self.runner.x - 8 - self.camera_x) * min(1, dt*8)
            target_y = self.runner.y + self.runner.body_height/2 - 1
            self.camera_y += (target_y-self.camera_y) * min(1, dt*3)
            self.draw()
            self.frames += 1
            if self.args.smoke:
                self.smoke_events()
            if self.args.frames and self.frames >= self.args.frames:
                break
        if self.args.capture:
            path = Path(self.args.capture)
            path.parent.mkdir(parents=True, exist_ok=True)
            self.pg.image.save(self.screen, str(path))
        if self.args.state_output:
            path = Path(self.args.state_output)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({'state': self.runner.snapshot(), 'frames': self.frames,
                                        'input_events': self.input_events, 'physics': asdict(self.physics),
                                        'speed_override': self.runner.speed_override}, ensure_ascii=False, indent=2)+'\n')
        self.pg.quit()

    def smoke_events(self):
        pg = self.pg
        # Exercise the real pygame event path, not direct calls to the model.
        keys = {2: pg.K_h, 3: pg.K_p, 24: pg.K_SPACE, 38: pg.K_SPACE,
                88: pg.K_s, 120: pg.K_p, 125: pg.K_p, 142: pg.K_f,
                156: pg.K_TAB, 162: pg.K_ESCAPE, 180: pg.K_r,
                184: pg.K_p, 200: pg.K_s, 240: pg.K_p}
        if self.frames in keys:
            pg.event.post(pg.event.Event(pg.KEYDOWN, key=keys[self.frames]))
        extra_keys = {260: pg.K_TAB, 267: pg.K_RETURN, 340: pg.K_F5}
        if self.frames in extra_keys:
            pg.event.post(pg.event.Event(pg.KEYDOWN, key=extra_keys[self.frames]))
        if self.frames == 263:
            pg.event.post(pg.event.Event(pg.TEXTINPUT, text='1038'))
        if self.frames in (280, 300):
            action = 'jump' if self.frames == 280 else 'flip'
            button = next(rect for rect, target in self.buttons if target == action)
            pg.event.post(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=button.center))
        if self.frames == 320:
            rect = next(rect for rect, target in self.buttons if isinstance(target, tuple) and target[:2] == ('slider', 'jump1'))
            pg.event.post(pg.event.Event(pg.MOUSEBUTTONDOWN, button=1, pos=(rect.centerx, rect.centery)))
        if self.frames == 322:
            pg.event.post(pg.event.Event(pg.MOUSEMOTION, pos=(self.screen.get_width()-100, 410), rel=(5, 0), buttons=(1, 0, 0)))
        if self.frames == 324:
            pg.event.post(pg.event.Event(pg.MOUSEBUTTONUP, button=1, pos=(0, 0)))



def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--dataset', type=Path, default=ROOT/'debug/arena-client/dataset')
    parser.add_argument('--physics', type=Path, default=ROOT/'debug/arena-client/xiaohei')
    parser.add_argument('--mode', choices=list(MODE_NAMES), default='endless')
    parser.add_argument('--stage', type=int, default=1031)
    parser.add_argument('--headless', action='store_true')
    parser.add_argument('--frames', type=int, default=0)
    parser.add_argument('--smoke', action='store_true')
    parser.add_argument('--capture', type=Path)
    parser.add_argument('--state-output', type=Path)
    args = parser.parse_args()
    try:
        App(args).run()
    except (FileNotFoundError, ValueError, StopIteration) as error:
        parser.exit(1, f'模拟器启动失败：{error}\n请先按 docs/develop/竞技场客户端数据.md 提取地图和小黑本体。\n')


if __name__ == '__main__':
    main()
