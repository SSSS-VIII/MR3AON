"""Original resource recovery must not hide missing assets or substitute bytes."""
from pathlib import Path
import sys
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_fidelity_assets import dependency_closure, write_exact, spine_header, audit_unity_export


def manifest(names, edges):
    return {'AssetBundleNames': list(enumerate(names)),
            'AssetBundleInfos': [(i,{'AssetBundleDependencies':edges.get(i,[])}) for i in range(len(names))]}


def test_dependency_closure_includes_shared_transitive_resources_once():
    data=manifest(['body','atlas','shader','fx'],{0:[1,3],1:[2],3:[2]})
    assert dependency_closure(data,['body','atlas'])==['shader','atlas','fx','body']


def test_circular_original_references_are_preserved_not_dropped_or_recursive():
    data=manifest(['body','material','shader'],{0:[1],1:[2],2:[1]})
    assert set(dependency_closure(data,['body']))=={'body','material','shader'}
    assert len(dependency_closure(data,['body']))==3


def test_unknown_root_and_missing_dependency_fail_explicitly():
    with pytest.raises(ValueError,match='absent'):
        dependency_closure(manifest(['body'],{}),['made-up'])
    with pytest.raises(ValueError,match='Missing'):
        dependency_closure(manifest(['body'],{0:[9]}),['body'])


def test_original_payload_is_exact_and_conflicting_cab_cannot_overwrite(tmp_path):
    target=tmp_path/'CAB-test'
    payload=b'\xff\x80\0shader and particle bytes\0\0'
    info=write_exact(target,payload)
    assert target.read_bytes()==payload
    assert info['bytes']==len(payload)
    assert len(info['sha256'])==64
    assert write_exact(target,payload)==info
    with pytest.raises(ValueError,match='Conflicting'):
        write_exact(target,b'placeholder')
    assert target.read_bytes()==payload


def test_spine_version_comes_from_binary_header_not_asset_filename():
    assert spine_header(b'\x94\x1b\x87\xc7\xc2r\xc0%\x074.0.21\0bones')=='4.0.21'
    assert spine_header(b'encrypted or unknown') is None


def test_exporter_substitutions_are_reported_and_clean_export_is_not_validation(tmp_path):
    assets = tmp_path/'Assets'
    assets.mkdir()
    (assets/'Ninja.cs').write_text('//Dummy class.')
    (assets/'Spine.shader').write_text('//DummyShaderTextExporter')
    report = audit_unity_export(tmp_path)
    assert report['placeholder_shaders'] == report['dummy_scripts'] == 1
    assert report['dummy_script_paths'] == ['Assets/Ninja.cs']
    assert report['ready_for_visual_training'] is False
    (assets/'Ninja.cs').write_text('class Ninja {}')
    (assets/'Spine.shader').write_text('Shader "Spine" {}')
    report = audit_unity_export(tmp_path)
    assert report['placeholder_shaders'] == report['dummy_scripts'] == 0
    assert report['ready_for_visual_training'] is False
    with pytest.raises(ValueError, match='Assets directory missing'):
        audit_unity_export(tmp_path/'missing')
