import json
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from arena_gale_catalog import build_catalog


def files(tmp_path, mode=6):
    config = tmp_path / 'config.json'
    config.write_text(json.dumps([{'key_path': [1], 'values': [[
        {'levelID': 2, 'nextLevelID': 2, 'levelDataList': [11]},
        {'levelID': 1, 'nextLevelID': 2, 'levelDataList': [11]}]]}]))
    source = dict(_levelDataType={'value__': mode}, _groundType={'value__': 3}, _difficultyLevel=28,
                  _stageRandomGroup=[{'_stageRandomList': [{'_stageID': 90, '_weight': 1}]},
                                     {'_stageRandomList': [{'_stageID': 11, '_weight': 3}, {'_stageID': 12, '_weight': 1}]}])
    (tmp_path / 'level_endless_gale_11.bytes.json').write_text(json.dumps([source]))
    for identity in [90, 11, 12]:
        stage = dict(_levelDataType=6, _stageUseFor=1 if identity == 90 else 0,
                     _levelBlockInfos=[[{}]])
        (tmp_path / f'stage_endless_gale_{identity}.json').write_text(json.dumps(stage))
    return config


def test_original_pool_order_weights_and_opening_separation(tmp_path):
    catalog = build_catalog(files(tmp_path), tmp_path)
    assert catalog['mode'] == 6
    assert [v['id'] for v in catalog['routes'][0]['levels']] == [1, 2]
    m = catalog['maps']['11']
    assert m['opening'][0]['pool'][0]['id'] == 90
    assert m['slots'][0]['position'] == 1 and m['slots'][0]['group'] == 2
    assert [(v['id'], v['weight']) for v in m['slots'][0]['pool']] == [(11, 3), (12, 1)]


def test_rejects_normal_mode_and_missing_board(tmp_path):
    config = files(tmp_path, mode=0)
    with pytest.raises(ValueError, match='non-Gale'):
        build_catalog(config, tmp_path)
    files(tmp_path)
    (tmp_path / 'stage_endless_gale_12.json').unlink()
    with pytest.raises(ValueError, match='Missing Gale board 12'):
        build_catalog(config, tmp_path)


def test_short_ledge_after_vertical_drop_is_marked_as_context_risk():
    from arena_gale_catalog import entry_info
    entry = entry_info([
        {'_groundType': 3, '_pointStart': {'x': 100, 'y': 20}, '_pointEnd': {'x': 100, 'y': 12}},
        {'_groundType': 1, '_pointStart': {'x': 100, 'y': 12}, '_pointEnd': {'x': 104, 'y': 12}},
    ])
    assert entry['risk'] and entry['length'] == 4 and entry['heightOffset'] == -8
    assert '短平台' in entry['reason'] and '落差' in entry['reason']


def test_random_layout_is_distinct_from_random_action_and_pool_choice():
    from arena_gale_catalog import classify_board
    fixed = {'_levelBlockInfos': [[{'enemyInfos': [{'_enemyType': 1, '_enemyInfoCustom': {'_randomRangeY': 0}}]}]]}
    assert classify_board(fixed)['layout'] == 'fixed'
    fixed['_levelBlockInfos'][0][0]['enemyInfos'][0]['_enemyInfoCustom']['_randomRotateDir'] = True
    result = classify_board(fixed)
    assert result['layout'] == 'fixed' and result['motion'] == 'random'
    fixed['_levelBlockInfos'][0][0]['enemyInfos'][0]['_enemyInfoCustom']['_randomRangeY'] = 5
    result = classify_board(fixed)
    assert result['layout'] == 'random' and result['layout_evidence'] == ['1._randomRangeY']
