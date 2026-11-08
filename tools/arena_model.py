"""Deterministic local runner model built from extracted client resources.

The static map and serialized parameters are original. Integration, input
windows, flips and obstacle shapes below are an explicit approximation, pending
comparison with the client. This module never accesses Android or the network.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import json
from pathlib import Path

FIXED_DT = 1 / 120


@dataclass
class Physics:
    jump1: float = 23.5
    jump2: float = 12.5
    up1: float = -25
    down1: float = -9
    up2: float = -9.8
    down2: float = -9.8
    gravity: float = -19.8
    flip_ground: float = 8
    flip_air: float = 28
    base_speed: float = 8
    radius: float = 0.2
    height: float = 1.8
    jump_height: float = 1.2
    roll_radius: float = 0.1
    roll_height: float = 0.1
    scale: float = 0.52

    @classmethod
    def from_export(cls, path):
        rows = [json.loads(line) for line in (Path(path) / 'resources.jsonl').read_text().splitlines()]
        entries = [x for row in rows for x in row.get('ninja_parameters', [])]
        ninja = next(x for x in entries if x['script'] == 'Ninja' and x.get('game_object_name') == 'Role1')
        data = ninja['ninja_data']
        collider = next(x['collider_data'] for x in entries
                        if x['component_path_id'] == ninja['main_collider_component_path_id'])
        scale = 0.52
        object_files = list((Path(path) / 'objects').glob('*.json'))
        for object_file in object_files:
            for obj in json.loads(object_file.read_text()):
                d = obj.get('data', {})
                if obj.get('type') == 'Transform' and d.get('m_GameObject', {}).get('m_PathID') == ninja.get('game_object_path_id'):
                    scale = d.get('m_LocalScale', {}).get('y', scale)
        return cls(scale=scale, jump1=data['_jumpForce1'], jump2=data['_jumpForce2'],
                   up1=data['_upGravity1'], down1=data['_downGravity1'],
                   up2=data['_upGravity2'], down2=data['_downGravity2'],
                   gravity=data['_normalGravity'], flip_ground=data['_rollDownUpSpeed'],
                   flip_air=data['_rollAirDownUpSpeed'], base_speed=data['_moveSpeed'],
                   radius=collider['_normalColliderRadius'], height=collider['_normalColliderHeight'],
                   jump_height=collider['_jumpColliderHeight'], roll_radius=collider['_rollColliderRadius'],
                   roll_height=collider['_rollColliderHeight'])


@dataclass
class Surface:
    x1: float
    y1: float
    x2: float
    y2: float
    kind: int
    speed: float
    hidden: bool = False

    def y_at(self, x):
        if abs(self.x2 - self.x1) < 1e-6:
            return self.y1
        return self.y1 + (self.y2 - self.y1) * (x - self.x1) / (self.x2 - self.x1)

    def contains(self, x):
        return self.x1 - 1e-6 <= x <= self.x2 + 1e-6 and self.x2 > self.x1


@dataclass
class Entity:
    x: float
    y: float
    kind: int
    name: str
    scale_x: float = 1
    scale_y: float = 1
    angle: float = 0
    custom: dict = field(default_factory=dict)
    item: bool = False
    collected: bool = False
    activated_at: float | None = None

    def position(self, now):
        # Only explicit ballistic parameters are applied. Behavior-tree actions,
        # curves and spawn rules remain simplified; no invented attack patterns.
        if self.item or self.activated_at is None:
            return self.x, self.y
        t = max(0, now - self.activated_at)
        if 'Arrow' in self.name or 'Bullut' in self.name or 'Bullet' in self.name:
            return (self.x + self.custom.get('_speedX', 0) * t,
                    self.y + self.custom.get('_speedY', 0) * t - abs(self.custom.get('_gravity', 0)) * t * t / 2)
        return self.x, self.y

    def radius(self):
        return max(0.12, min(1.4, 0.38 * max(abs(self.scale_x), abs(self.scale_y))))


@dataclass
class Stage:
    mode: str
    stage_id: int
    surfaces: list[Surface]
    enemies: list[Entity]
    items: list[Entity]
    length: float
    source: str

    @classmethod
    def load(cls, path):
        path = Path(path)
        data = json.loads(path.read_text())
        blocks = [b for group in data['_levelBlockInfos'] for b in group]
        physical = [b for b in blocks if b.get('_groundType', 0) != 3
                    and b.get('_pointEnd', {}).get('x', 0) > b.get('_pointStart', {}).get('x', 0)]
        if not physical:
            raise ValueError('该段没有可用地形')
        origin_x = min(b.get('_pointStart', {}).get('x', 0) for b in physical)
        first = min(physical, key=lambda b: b.get('_pointStart', {}).get('x', 0))
        origin_y = first.get('_pointStart', {}).get('y', 0)
        surfaces, enemies, items = [], [], []
        for b in blocks:
            a, z = b.get('_pointStart', {}), b.get('_pointEnd', {})
            x, y = a.get('x', 0) - origin_x, a.get('y', 0) - origin_y
            kind = b.get('_groundType', 0)
            if kind != 3 and z.get('x', 0) > a.get('x', 0):
                surfaces.append(Surface(x, y, z.get('x', 0) - origin_x,
                                        z.get('y', 0) - origin_y, kind,
                                        b.get('_ninjaSpeed', 0), b.get('_hideGround', False)))
            for key, target, item in [('enemyInfos', enemies, False), ('itemInfos', items, True)]:
                for info in b.get(key, []):
                    loc, scale = info.get('_localPosition', {}), info.get('_localScale', {})
                    custom = info.get('_itemInfoCustom' if item else '_enemyInfoCustom', {})
                    name = custom.get('$type', 'Item' if item else 'Enemy').removesuffix('DataStruct')
                    target.append(Entity(x + loc.get('x', 0), y + loc.get('y', 0),
                                         info.get('_itemType' if item else '_enemyType', 0), name,
                                         scale.get('x', 1), scale.get('y', 1),
                                         info.get('_localEulerAngles', {}).get('z', 0), custom, item))
        surfaces.sort(key=lambda s: (s.x1, s.x2))
        return cls(path.parent.name, data['_stageID'], surfaces, enemies, items,
                   max(s.x2 for s in surfaces), str(path))

    @classmethod
    def training(cls):
        return cls('training', 0,
                   [Surface(0, 0, 28, 0, 0, 9), Surface(28, 0, 58, 0, 1, 10),
                    Surface(62, 0, 96, 0, 0, 11), Surface(96, 0, 135, 0, 1, 12)],
                   [Entity(15, 0.5, 101, 'EnemyBlade'), Entity(24, 2.2, 101, 'EnemyBlade'),
                    Entity(42, 0.5, 101, 'EnemyBlade'), Entity(76, 0.5, 101, 'EnemyBlade')],
                   [Entity(float(x), 2.2, 50, 'Coin', item=True) for x in range(6, 126, 3)],
                   135, '本地生成的动作实验场，非客户端原图')


class Catalog:
    def __init__(self, dataset):
        root = Path(dataset) / 'assets/assets/gameresources/binarydatas/leveldata'
        self.paths = {}
        self.unplayable = []
        self.source_count = 0
        for mode in ('endless', 'endless_gale', 'singleendlessreserved1'):
            paths = list((root / mode).glob('stage_*.json'))
            self.paths[mode] = {}
            self.source_count += len(paths)
            for path in paths:
                data = json.loads(path.read_text())
                has_surface = any(b.get('_groundType', 0) != 3 and
                                  b.get('_pointEnd', {}).get('x', 0) > b.get('_pointStart', {}).get('x', 0)
                                  for group in data.get('_levelBlockInfos', []) for b in group)
                stage_id = int(path.stem.rsplit('_', 1)[1])
                if has_surface:
                    self.paths[mode][stage_id] = path
                else:
                    self.unplayable.append((mode, stage_id))
        if not any(self.paths.values()):
            raise ValueError(f'找不到已提取的关卡：{root}')

    def ids(self, mode):
        return sorted(self.paths.get(mode, {}))

    def load(self, mode, stage_id):
        return Stage.training() if mode == 'training' else Stage.load(self.paths[mode][stage_id])


class Runner:
    def __init__(self, stage, physics=None):
        self.physics = physics or Physics()
        self.stage = stage
        self.invincible = False
        self.speed_override = 0
        self.reset()

    def reset(self, checkpoint=None):
        self.time = 0.0
        self.x = self.stage.surfaces[0].x1 + 1.2 if checkpoint is None else checkpoint
        support = self.surface(self.x) or self.stage.surfaces[0]
        self.y = support.y_at(self.x)
        self.vy = 0.0
        self.jumps = 0
        self.grounded = True
        self.underside = False
        self.flip_target = None
        self.roll_left = 0.0
        self.support = support
        self.dead = False
        self.finished = False
        self.paused = True
        self.death_reason = ''
        self.hits = 0
        self.coins = 0
        self.hit_cooldown = 0.0
        self.peak = self.y
        self.start_y = self.y
        self.checkpoint = self.x
        self.accumulator = 0.0
        self.actions = []
        self.trail = []
        for entity in self.stage.enemies + self.stage.items:
            entity.collected = False
            entity.activated_at = None

    @property
    def body_height(self):
        p = self.physics
        return (p.roll_height if self.roll_left > 0 else p.jump_height if not self.grounded else p.height) * p.scale

    @property
    def body_radius(self):
        return (self.physics.roll_radius if self.roll_left > 0 else self.physics.radius) * self.physics.scale

    @property
    def speed(self):
        support = self.surface(self.x)
        return self.speed_override or (support.speed if support and support.speed > 0 else self.physics.base_speed)

    def surface(self, x):
        available = [s for s in self.stage.surfaces if s.contains(x)]
        return min(available, key=lambda s: abs(s.y_at(x) - getattr(self, 'y', s.y1))) if available else None

    def action(self, action):
        if self.dead or self.finished or self.paused:
            return False
        accepted = False
        if action == 'jump' and self.jumps < 2 and self.flip_target is None:
            self.jumps += 1
            self.vy = self.physics.jump1 if self.jumps == 1 else self.physics.jump2
            self.grounded = False
            self.underside = False
            self.start_y = self.y
            accepted = True
        elif action == 'flip' and self.flip_target is None:
            surface = self.surface(self.x)
            if surface and surface.kind == 0:
                to_bottom = not self.underside
                self.flip_target = (surface, to_bottom, self.grounded)
                self.grounded = False
                self.vy = 0
                self.roll_left = 0.24  # Model duration, not a recovered client constant.
                accepted = True
            elif self.grounded:
                self.roll_left = 0.35  # Approximate ground dodge window.
                accepted = True
            else:
                self.vy = -self.physics.flip_air
                accepted = True
        self.actions.append({'t': round(self.time, 6), 'action': action, 'accepted': accepted})
        return accepted

    def advance(self, elapsed):
        if self.paused or self.dead or self.finished:
            return
        self.accumulator += min(max(elapsed, 0), 0.25)
        while self.accumulator + 1e-12 >= FIXED_DT:
            self.step(FIXED_DT)
            self.accumulator -= FIXED_DT
            if self.dead or self.finished:
                break

    def fail(self, reason):
        if not self.invincible:
            self.dead = True
            self.death_reason = reason
        self.hits += 1
        self.hit_cooldown = 0.8

    def step(self, dt):
        self.time += dt
        self.hit_cooldown = max(0, self.hit_cooldown - dt)
        self.roll_left = max(0, self.roll_left - dt)
        old_y = self.y
        self.x += self.speed * dt
        surface = self.surface(self.x)
        if self.flip_target:
            rope, bottom, from_ground = self.flip_target
            if not rope.contains(self.x):
                self.flip_target = None
            else:
                height = self.physics.height * self.physics.scale
                target = rope.y_at(self.x) - height if bottom else rope.y_at(self.x)
                delta = target - self.y
                velocity = self.physics.flip_ground if from_ground else self.physics.flip_air
                self.y += max(-velocity * dt, min(velocity * dt, delta))
                if abs(delta) <= velocity * dt + 1e-8:
                    self.y = target
                    self.grounded = True
                    self.underside = bottom
                    self.jumps = 0
                    self.support = rope
                    self.flip_target = None
                    self.roll_left = 0
        elif self.grounded:
            if surface:
                self.support = surface
                self.y = surface.y_at(self.x) - (self.physics.height * self.physics.scale if self.underside and surface.kind == 0 else 0)
                if surface.kind != 0:
                    self.underside = False
                self.checkpoint = max(self.stage.surfaces[0].x1 + 1.2, surface.x1 + 0.5)
            else:
                self.grounded = False
                self.underside = False
                self.vy = 0
        else:
            p = self.physics
            gravity = ((p.up1 if self.vy > 0 else p.down1) if self.jumps == 1
                       else (p.up2 if self.vy > 0 else p.down2) if self.jumps == 2 else p.gravity)
            self.vy += gravity * dt
            self.y += self.vy * dt
            if surface and self.vy <= 0:
                floor = surface.y_at(self.x)
                if old_y >= floor - 1e-5 and self.y <= floor:
                    self.y, self.vy = floor, 0
                    self.grounded, self.underside = True, False
                    self.jumps = 0
                    self.support = surface
        self.peak = max(self.peak, self.y)
        self.trail.append((self.x, self.y + self.body_height / 2))
        if len(self.trail) > 240:
            self.trail.pop(0)
        for enemy in self.stage.enemies:
            if enemy.activated_at is None and enemy.x - self.x < enemy.custom.get('_activeDistance', 20):
                enemy.activated_at = self.time
            ex, ey = enemy.position(self.time)
            radius = enemy.radius()
            if abs(ex - self.x) <= radius + self.body_radius and self.y - radius <= ey <= self.y + self.body_height + radius:
                if self.hit_cooldown <= 0:
                    self.fail(f'{enemy.name} · 类型 {enemy.kind}')
        for item in self.stage.items:
            if not item.collected and abs(item.x - self.x) < 0.7 and self.y - 0.7 < item.y < self.y + self.body_height + 0.7:
                item.collected = True
                if item.kind == 50:
                    self.coins += 1
        if self.y < (surface.y_at(self.x) if surface else self.support.y_at(min(self.support.x2, self.x))) - 24:
            self.fail('掉落地形')
            if self.invincible:
                self.y = (surface or self.support).y_at(self.x)
                self.vy, self.jumps, self.grounded = 0, 0, True
        if self.x >= self.stage.length:
            self.finished = True

    def snapshot(self):
        return {'time': self.time, 'x': self.x, 'y': self.y, 'vy': self.vy,
                'jumps': self.jumps, 'grounded': self.grounded, 'underside': self.underside,
                'flipping': self.flip_target is not None, 'dead': self.dead,
                'finished': self.finished, 'hits': self.hits, 'coins': self.coins,
                'mode': self.stage.mode, 'stage_id': self.stage.stage_id}
