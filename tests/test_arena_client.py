"""Offline structural parsing and export boundaries, using synthetic data only."""
from pathlib import Path
import struct
import sys
import zipfile

import pytest

TOOLS = Path(__file__).resolve().parents[1] / 'tools'
sys.path.insert(0, str(TOOLS))
from arena_nrbf import NrbfReader
from arena_client import safe_asset_path, summarize_stage, unwrap_bundle, text_asset_bytes, ClientSource, ninja_parameters


def i32(value):
    return struct.pack('<i', value)


def string(value):
    data = value.encode()
    assert len(data) < 128
    return bytes([len(data)]) + data


def header():
    return b'\0' + struct.pack('<iiii', 1, -1, 1, 0)


def test_nrbf_forward_references_null_runs_and_primitive_arrays():
    # Root object array references a later primitive array and a later string.
    data = (header() + b'\x10' + i32(1) + i32(5)
            + b'\x09' + i32(2) + b'\x0d\x02' + b'\x09' + i32(3) + b'\x0a'
            + b'\x0f' + i32(2) + i32(2) + b'\x0b' + struct.pack('<ff', 9.5, 14)
            + b'\x06' + i32(3) + string('Stage_Test') + b'\x0b')
    assert NrbfReader(data).parse().expanded() == [[9.5, 14], None, None, 'Stage_Test', None]


def test_nrbf_typed_class_and_metadata_reuse():
    # Array of two named classes; the second reuses class metadata id 2.
    data = (header() + b'\x10' + i32(1) + i32(2)
            + b'\x04' + i32(2) + string('StageSpeed') + i32(1) + string('speed')
            + b'\x00\x0b' + struct.pack('<f', 9.5)
            + b'\x01' + i32(3) + i32(2) + struct.pack('<f', 14) + b'\x0b')
    assert NrbfReader(data).parse().expanded() == [
        {'$type': 'StageSpeed', 'speed': 9.5}, {'$type': 'StageSpeed', 'speed': 14}]


@pytest.mark.parametrize('payload', [b'bad', header(), header() + b'\xff',
                                    header() + b'\x10' + i32(1) + i32(-1)])
def test_nrbf_rejects_malformed_data(payload):
    with pytest.raises(ValueError):
        NrbfReader(payload).parse()


def test_nrbf_rejects_trailing_bytes_and_invalid_null_runs():
    valid = header() + b'\x06' + i32(1) + string('ok') + b'\x0b'
    with pytest.raises(ValueError, match='Trailing'):
        NrbfReader(valid + b'extra').parse()
    bad = header() + b'\x10' + i32(1) + i32(1) + b'\x0d\x02\x0b'
    with pytest.raises(ValueError, match='null run'):
        NrbfReader(bad).parse()


def test_binary_text_asset_preserves_non_utf8_bytes():
    payload = b'\xff\x80\0\xef\xbf\xbd'
    class FakeObject:
        def get_raw_data(self):
            return i32(1) + b'x\0\0\0' + i32(len(payload)) + payload
    assert text_asset_bytes(FakeObject()) == payload


@pytest.mark.parametrize('path', ['../secret', '/tmp/secret', 'assets/../../secret', 'assets\\secret'])
def test_export_paths_stay_inside_destination(path):
    with pytest.raises(ValueError):
        safe_asset_path(path)


def test_stage_summary_keeps_raw_speeds_and_zero_without_guessing_units():
    stage = {'_stageID': 7, '_levelDataType': 0, '_levelBlockInfos': [[
        {'_ninjaSpeed': 0, 'enemyInfos': [{}]}, {'_ninjaSpeed': 9.5, 'itemInfos': [{}, {}]}]]}
    summary = summarize_stage(stage)
    assert summary['raw_ninja_speeds'] == [0, 9.5]
    assert (summary['blocks'], summary['enemies'], summary['items']) == (2, 1, 2)
    assert 'not verified' in summary['speed_units']


def test_unwrap_checks_declared_size():
    inner = b'UnityFS\0' + struct.pack('>I', 8) + b'5.x.x\0' + b'2022.3.62f2c1\0'
    inner += struct.pack('>Q', len(inner) + 8)
    outer = b'UnityFS\0' + bytes(70)
    assert unwrap_bundle(outer + inner) == inner
    with pytest.raises(ValueError, match='length'):
        unwrap_bundle(outer + inner + b'bad')


def test_source_prefers_dynamic_and_falls_back_to_apk(tmp_path):
    apk = tmp_path / 'client.apk'
    with zipfile.ZipFile(apk, 'w') as archive:
        archive.writestr('assets/AssetBundles/current.ab', b'old')
        archive.writestr('assets/AssetBundles/base-only.ab', b'base')
    dynamic = tmp_path / 'DynamicContent'
    (dynamic / 'AssetBundles').mkdir(parents=True)
    (dynamic / 'AssetBundles/current.ab').write_bytes(b'updated')
    (dynamic / 'PatchVersion').write_bytes(b'\x041248')
    source = ClientSource(apk, dynamic)
    try:
        assert source.read_bundle('current.ab') == (b'updated', 'dynamic')
        assert source.read_bundle('base-only.ab') == (b'base', 'apk')
        assert source.bundles() == ['base-only.ab', 'current.ab']
        assert source.version() == b'\x041248'.hex()
        with pytest.raises(ValueError):
            source.read_bundle('../outside')
    finally:
        source.close()


def test_physics_selection_excludes_clone_enemy_and_external_scripts():
    objects = [
        {'type': 'MonoScript', 'path_id': 10, 'data': {'m_ClassName': 'Ninja'}},
        {'type': 'MonoScript', 'path_id': 20, 'data': {'m_ClassName': 'NinjaCopy'}},
        {'type': 'MonoScript', 'path_id': 30, 'data': {'m_ClassName': 'EnemyNormalNinja'}},
    ]
    for index, script_id, file_id in [(1, 10, 0), (2, 20, 0), (3, 30, 0), (4, 10, 1)]:
        objects.append({'type': 'MonoBehaviour', 'path_id': index, 'data': {
            'm_Script': {'m_FileID': file_id, 'm_PathID': script_id},
            '_ninjaData': {'_jumpForce1': 99}}})
    assert ninja_parameters(objects) == [
        {'component_path_id': 1, 'script': 'Ninja', 'ninja_data': {'_jumpForce1': 99},
         'game_object_path_id': None, 'game_object_name': None, 'game_object_active': None,
         'main_collider_component_path_id': None}]
