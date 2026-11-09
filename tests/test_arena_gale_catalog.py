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
        {'levelID': 1, 'nextLevelID': 2, 'levelDataList': [1]}]]}]))
    source = dict(_levelDataType={'value__': mode}, _groundType={'value__': 3}, _difficultyLevel=28,
                  _stageRandomGroup=[{'_stageRandomList': [{'_stageID': 90, '_weight': 1}]},
                                     {'_stageRandomList': [{'_stageID': 11, '_weight': 3}, {'_stageID': 12, '_weight': 1}]}])
    (tmp_path / 'level_endless_gale_11.bytes.json').write_text(json.dumps([source]))
    (tmp_path / 'level_endless_gale_1.bytes.json').write_text(json.dumps([source]))
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


def test_infinite_section_keeps_its_own_original_board_pool(tmp_path):
    config = files(tmp_path)
    source_path = tmp_path / 'level_endless_gale_11.bytes.json'
    source = json.loads(source_path.read_text())
    source[0]['_loopRandomStage'] = {'_stageRandomList': [{'_stageID': 12, '_weight': 5}]}
    source_path.write_text(json.dumps(source))
    catalog = build_catalog(config, tmp_path)
    assert [v['id'] for v in catalog['maps']['11']['slots'][0]['pool']] == [11, 12]
    assert [(v['id'], v['weight']) for v in catalog['maps']['11']['loop']] == [(12, 5)]


def test_scroll_route_start_is_grouped_under_actual_level(tmp_path):
    config = files(tmp_path)
    rows = json.loads(config.read_text())
    rows[0]['key_path'] = [3]
    rows[0]['values'][0] = [{'levelID': 1, 'nextLevelID': 1, 'levelDataList': [11]}]
    config.write_text(json.dumps(rows))
    result = build_catalog(config, tmp_path)
    assert result['levels'] == [dict(id=3, maps=[dict(id=11, chapter=3, level=1)])]
    assert result['maps']['11']['absoluteLevel'] == 3


def test_start_detection_uses_action_type_and_preserves_continuation_boards(tmp_path):
    from arena_gale_catalog import has_game_start
    make = lambda items: {'_levelBlockInfos': [[{'itemInfos': items}]]}
    assert not has_game_start(make([]))
    assert has_game_start(make([{'_itemType': 3}]))
    assert has_game_start(make([{'_itemType': 100, '_itemInfoCustom': {
        '_levelActionDataList': [{'_actionType': 23, '_actionName': '关闭水面'}]}}]))
    assert not has_game_start(make([{'_itemType': 100, '_itemInfoCustom': {
        '_levelActionDataList': [{'_actionType': 29, '_actionName': 'GameStart'}]}}]))
    catalog = build_catalog(files(tmp_path), tmp_path)
    assert catalog['maps']['1']['slots'][0]['pool'][1]['startsGame'] is False


def duplicate_files(tmp_path):
    config = files(tmp_path)
    config.write_text(json.dumps([{'key_path': [1], 'values': [[
        {'levelID': 1, 'nextLevelID': 1, 'levelDataList': [4, 1]}]]}]))
    portal = dict(_levelDataType=6, _levelBlockInfos=[[{'itemInfos': [
        {'_itemType': 81}, {'_itemType': 100, '_itemInfoCustom': {'_levelActionDataList': [
            {'_actionType': 15, '_finalParamList': [{'_effectName': 'Portal'}]},
            {'_actionType': 5, '_finalParamList': [{'_changeType': 14}]}]}}]}]])
    (tmp_path / 'stage_endless_gale_80.json').write_text(json.dumps(portal))
    path = tmp_path / 'level_endless_gale_4.bytes.json'
    source = json.loads((tmp_path / 'level_endless_gale_1.bytes.json').read_text())
    source[0]['_levelID'] = 4
    source[0]['_stageRandomGroup'].insert(1, {'_stageRandomList': [{'_stageID': 80, '_weight': 1}]})
    path.write_text(json.dumps(source))
    return config, path


def test_menu_merges_portal_entry_but_keeps_original_groups_and_ids(tmp_path):
    config, _ = duplicate_files(tmp_path)
    catalog = build_catalog(config, tmp_path)
    assert [v['id'] for v in catalog['levels'][0]['maps']] == [1]
    assert catalog['routes'][0]['levels'][0]['maps'] == [4, 1]
    assert len(catalog['maps']['4']['slots']) == 2  # Original entry remains playable via API.
    assert catalog['maps']['4']['slots'][1]['group'] == 3
    assert catalog['maps']['4']['menuMap'] == 1
    assert catalog['maps']['4']['menuBoardOffset'] == 1
    assert 'menuMap' not in catalog['maps']['1']


def test_entry_route_with_smaller_pool_uses_original_complete_representative(tmp_path):
    config, path = duplicate_files(tmp_path)
    source = json.loads(path.read_text())
    source[0]['_stageRandomGroup'][-1]['_stageRandomList'].pop()
    path.write_text(json.dumps(source))
    catalog = build_catalog(config, tmp_path)
    assert [v['id'] for v in catalog['levels'][0]['maps']] == [1]
    assert [v['id'] for v in catalog['maps']['1']['slots'][0]['pool']] == [11, 12]
    assert [v['id'] for v in catalog['maps']['4']['slots'][1]['pool']] == [11]


@pytest.mark.parametrize('difference', ['weight', 'speed', 'difficulty', 'loop', 'change_stage'])
def test_gameplay_differences_are_not_merged(tmp_path, difference):
    config, path = duplicate_files(tmp_path)
    source = json.loads(path.read_text())
    group = source[0]['_stageRandomGroup'][-1]
    if difference == 'weight':
        group['_stageRandomList'][0]['_weight'] += 1
    elif difference == 'speed':
        group['_stageSpeed'] = 30
    elif difference == 'difficulty':
        source[0]['_difficultyLevel'] += 1
    elif difference == 'loop':
        source[0]['_loopRandomStage'] = {'_stageRandomList': [{'_stageID': 12, '_weight': 1}]}
    else:
        source[0]['changeToStageList'] = [12]
    path.write_text(json.dumps(source))
    assert [v['id'] for v in build_catalog(config, tmp_path)['levels'][0]['maps']] == [1, 4]


def test_portal_action_inside_gameplay_is_not_discarded_as_entry(tmp_path):
    config, path = duplicate_files(tmp_path)
    source = json.loads(path.read_text())
    groups = source[0]['_stageRandomGroup']
    groups.append(groups.pop(1))
    path.write_text(json.dumps(source))
    assert [v['id'] for v in build_catalog(config, tmp_path)['levels'][0]['maps']] == [1, 4]


def test_ordinary_maps_with_different_ground_are_not_entry_duplicates(tmp_path):
    config, path = duplicate_files(tmp_path)
    source = json.loads(path.read_text())
    source[0]['_stageRandomGroup'].pop(1)
    source[0]['_groundType']['value__'] = 8
    path.write_text(json.dumps(source))
    assert [v['id'] for v in build_catalog(config, tmp_path)['levels'][0]['maps']] == [1, 4]


def test_portal_prefix_with_enemy_is_not_hidden(tmp_path):
    config, _ = duplicate_files(tmp_path)
    path = tmp_path / 'stage_endless_gale_80.json'
    source = json.loads(path.read_text())
    source['_levelBlockInfos'][0][0]['enemyInfos'] = [{'_enemyType': 1}]
    path.write_text(json.dumps(source))
    assert [v['id'] for v in build_catalog(config, tmp_path)['levels'][0]['maps']] == [1, 4]
