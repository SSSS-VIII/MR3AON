"""Local deterministic simulation; never requires a running Android instance."""
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from arena_model import Physics, Runner, Stage, Surface, Entity, Catalog


def flat(kind=0, enemies=None, items=None):
    return Stage('test', 1, [Surface(0, 0, 1000, 0, kind, 9)],
                 enemies or [], items or [], 1000, 'synthetic fixture')


def running(stage=None):
    runner = Runner(stage or flat())
    runner.paused = False
    return runner


def advance(runner, frames, fps=60):
    for _ in range(frames):
        runner.advance(1/fps)


def test_fixed_step_is_consistent_at_different_render_rates():
    a, b = running(), running()
    a.action('jump')
    b.action('jump')
    advance(a, 90, 60)
    advance(b, 45, 30)
    assert (a.x, a.y, a.vy, a.time) == pytest.approx((b.x, b.y, b.vy, b.time))


def test_two_jumps_reset_velocity_and_land_back_on_the_rope():
    r = running()
    assert r.action('jump')
    advance(r, 12)
    assert r.action('jump')
    assert r.vy == r.physics.jump2
    assert not r.action('jump')
    advance(r, 360)
    assert r.grounded
    assert r.y == pytest.approx(0)
    assert r.jumps == 0
    assert r.action('jump')


def test_rope_flip_round_trip_changes_side_and_keeps_support():
    r = running()
    assert r.action('flip')
    advance(r, 30)
    assert r.grounded and r.underside
    assert r.y == pytest.approx(-r.physics.height * r.physics.scale)
    assert r.action('flip')
    advance(r, 30)
    assert r.grounded and not r.underside
    assert r.y == pytest.approx(0)


def test_solid_ground_dodge_does_not_flip_through_the_floor():
    r = running(flat(kind=1))
    assert r.action('flip')
    assert r.roll_left > 0
    advance(r, 60)
    assert r.grounded and not r.underside and r.flip_target is None
    assert r.y == 0


def test_pause_and_restart_do_not_advance_or_leak_movement_debt():
    r = running()
    advance(r, 10)
    old = r.snapshot()
    r.paused = True
    advance(r, 60)
    assert r.snapshot() == old
    r.reset()
    assert r.time == 0 and r.paused and not r.actions
    assert r.accumulator == 0


def test_collision_stops_a_normal_run_but_invincible_mode_keeps_running():
    a = running(flat(enemies=[Entity(4, 0.3, 101, 'EnemyBlade')]))
    b = running(flat(enemies=[Entity(4, 0.3, 101, 'EnemyBlade')]))
    b.invincible = True
    advance(a, 60)
    advance(b, 60)
    assert a.dead and a.hits == 1
    assert not b.dead and b.hits >= 1
    assert b.x > a.x


def test_coin_is_collected_once_and_reset_restores_it():
    item = Entity(2, 0.4, 50, 'Coin', item=True)
    r = running(flat(items=[item]))
    advance(r, 60)
    assert r.coins == 1 and item.collected
    advance(r, 60)
    assert r.coins == 1
    r.reset()
    assert r.coins == 0 and not item.collected


def test_link_blocks_are_not_floors_and_local_entities_keep_their_origin(tmp_path):
    p = tmp_path / 'stage_test_7.json'
    p.write_text(json.dumps({'_stageID': 7, '_levelBlockInfos': [[
        {'_pointStart': {'x': 100, 'y': 20}, '_pointEnd': {'x': 120, 'y': 20},
         '_ninjaSpeed': 9, 'enemyInfos': [{'_enemyType': 101,
         '_localPosition': {'x': 4, 'y': 2}, '_localScale': {'x': 2, 'y': 3},
         '_enemyInfoCustom': {'$type': 'EnemyBladeDataStruct'}}]},
        {'_groundType': 3, '_pointStart': {'x': 120, 'y': 20}, '_pointEnd': {'x': 120, 'y': 10}}]]}))
    stage = Stage.load(p)
    assert len(stage.surfaces) == 1
    assert stage.surfaces[0].kind == 0  # omitted client enum means rope/line
    assert (stage.enemies[0].x, stage.enemies[0].y) == (4, 2)
    assert (stage.enemies[0].scale_x, stage.enemies[0].scale_y) == (2, 3)
    assert stage.length == 20


def test_falling_into_a_gap_fails_instead_of_spawning_a_fake_floor():
    stage = Stage('test', 1, [Surface(0, 0, 2, 0, 1, 9), Surface(100, 0, 120, 0, 1, 9)], [], [], 120, 'test')
    r = running(stage)
    advance(r, 180)
    assert r.dead and r.death_reason == '掉落地形'


def test_speed_comes_from_the_current_block_and_can_be_overridden():
    r = running(flat())
    assert r.speed == 9
    r.speed_override = 15
    advance(r, 60)
    assert r.x == pytest.approx(1.2 + 15)


def test_catalog_filters_nonplayable_empty_resource_segments(tmp_path):
    folder = tmp_path / 'assets/assets/gameresources/binarydatas/leveldata/endless'
    folder.mkdir(parents=True)
    (folder / 'stage_endless_1.json').write_text(json.dumps({'_stageID': 1, '_levelBlockInfos': [[
        {'_pointStart': {'x': 0}, '_pointEnd': {'x': 10}}]]}))
    (folder / 'stage_endless_2.json').write_text(json.dumps({'_stageID': 2, '_levelBlockInfos': []}))
    catalog = Catalog(tmp_path)
    assert catalog.source_count == 2
    assert catalog.ids('endless') == [1]
    assert catalog.unplayable == [('endless', 2)]
