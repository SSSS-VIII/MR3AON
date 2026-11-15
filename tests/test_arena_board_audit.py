import copy
import json
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
from arena_board_audit import actor_evidence, actor_source_names, build_audit, digest, mechanism, scan_actor_reports


def stage(identity, *, enemies=(102,), items=(), random=False):
    return dict(_levelDataType=6, _stageID=identity, _levelBlockInfos=[[dict(
        _ninjaSpeed=19, _pointStart={'x': 0, 'y': 0}, _pointEnd={'x': 32, 'y': 0},
        enemyInfos=[dict(_enemyType=i, _enemyInfoCustom={'_randomRangeY': 2 if random else 0}) for i in enemies],
        itemInfos=[dict(_itemType=i, _itemInfoCustom={}) for i in items])]])


def fixture_catalog(tmp_path):
    # Two portal aliases are present in raw maps but absent from canonical levels.
    pools = {41: [[5101, 51011], [5102], [5103], [5102]], 51: [[6001, 60011], [6002]]}
    sources = {i: stage(i) for p in pools.values() for slot in p for i in slot}
    sources[5103] = stage(5103, enemies=(), items=(2, 101, 53))
    sources[6002] = stage(6002, enemies=(), items=(32,))
    sources[51011] = stage(51011, random=True)
    maps, levels = {}, []
    for identity, level in [(41, 5), (51, 6)]:
        slots = [dict(position=i+1, group=i+1, pool=[dict(id=v, weight=1, startsGame=True) for v in pool])
                 for i, pool in enumerate(pools[identity])]
        maps[str(identity)] = dict(id=identity, absoluteLevel=level, difficulty=44 if level == 5 else 50,
                                    ground=0, opening=[], slots=slots)
        levels.append(dict(id=level, maps=[dict(id=identity, chapter=1, level=level)]))
        raw = dict(_levelDataType={'value__': 6}, _stageRandomGroup=[
            {'_stageRandomList': [{'_stageID': v, '_weight': 1} for v in pool]} for pool in pools[identity]])
        (tmp_path/f'level_endless_gale_{identity}.bytes.json').write_text(json.dumps([raw]))
    maps['44'] = dict(copy.deepcopy(maps['41']), id=44, menuMap=41, menuBoardOffset=1)
    maps['54'] = dict(copy.deepcopy(maps['51']), id=54, menuMap=51, menuBoardOffset=1)
    for identity, data in sources.items():
        (tmp_path/f'stage_endless_gale_{identity}.json').write_text(json.dumps(data))
    return dict(mode=6, maps=maps, levels=levels)


def saved_episode(*, start=1, goal=2, board=5101):
    setup = dict(level=5, map=41, start=start, goal_stage_index=goal, seed=42, observe=False,
                 initial=dict(map=41, stageIndex=start-1, stageID=board, stageCount=4, god=False),
                 sources={'tools/arena_motion.py': 'abc'}, detector={'sha256': 'old-weights'})
    report = dict(status='passed', final=dict(map=41, stageIndex=goal, damage=0, god=False),
                  actions=[], boards_requested=goal-start+1, had_damage=False, evaluation_error=None,
                  board_entries=[dict(stageIndex=start-1, stageID=board, damage=0),
                                 dict(stageIndex=1, stageID=5102, damage=0),
                                 dict(stageIndex=2, stageID=5103, damage=0)])
    return setup, report


def test_canonical_maps_and_all_shared_slot_contexts_are_preserved(tmp_path):
    catalog = fixture_catalog(tmp_path)
    result = build_audit(catalog, tmp_path, levels=[5, 6])
    assert set(result['maps']) == {'41', '51'}
    assert result['counts']['removed_entry_aliases'] == 2
    shared = result['boards']['5102']['contexts']
    assert [c['slot'] for c in shared] == [2, 4]
    assert [c['native_select']['pins'] for c in shared] == [{'2': 5102}, {'4': 5102}]
    assert shared[0]['native_select'] == dict(chapter=1, level=5, map=41, start=2, pins={'2': 5102})
    assert shared[0]['entry_safety'] == 'not_proven'
    assert result['boards']['51011']['classification']['layout'] == 'random'
    assert result['boards']['5101']['classification']['layout'] == 'fixed'


def test_batches_cover_unique_variants_and_never_cross_special_mechanism(tmp_path):
    result = build_audit(fixture_catalog(tmp_path), tmp_path, levels=[5, 6])
    batches = result['ordinary_first_pass_batches']
    assert [b['level'] for b in batches] == [5, 5, 6, 6]
    assert batches[0]['pins'] == {'1': 5101, '2': 5102}
    assert batches[1]['pins'] == {'1': 51011, '2': 5102}
    assert batches[1]['bridge_or_padding_repeats'] == [5102]
    assert {s for b in batches for s in b['unique_new_stages']} == {5101, 51011, 5102, 6001, 60011}
    assert all(5103 not in b['pins'].values() and 6002 not in b['pins'].values() for b in batches)
    assert result['boards']['6002']['automatic_mechanism_acceptance'] == 'not_established_by_this_audit'


def test_explicit_mechanisms_do_not_classify_enemy_coin_board_as_reward():
    assert mechanism(stage(1, enemies=(), items=(2, 101)))['kind'] == 'reward_coin_layout'
    assert mechanism(stage(1, items=(2, 101)))['kind'] == 'ordinary'
    assert mechanism(stage(1, enemies=(), items=(53,)))['kind'] == 'ordinary'
    assert mechanism(stage(1, enemies=(), items=(32, 2, 101)))['kind'] == 'boss'
    assert mechanism(stage(1, enemies=(), items=(43, 44)))['kind'] == 'special_task'


def test_refuse_non_gale_unmerged_alias_invalid_pool_and_level7(tmp_path):
    catalog = fixture_catalog(tmp_path)
    with pytest.raises(ValueError, match='mode6'):
        build_audit(dict(catalog, mode=3), tmp_path)
    with pytest.raises(ValueError, match='1–6'):
        build_audit(catalog, tmp_path, levels=[7])
    corrupt = copy.deepcopy(catalog)
    corrupt['levels'][0]['maps'][0]['id'] = 44
    with pytest.raises(ValueError, match='canonical'):
        build_audit(corrupt, tmp_path)
    corrupt = copy.deepcopy(catalog)
    corrupt['maps']['41']['slots'][0]['pool'][0]['id'] = 999
    with pytest.raises(ValueError, match='original map group'):
        build_audit(corrupt, tmp_path)


def test_completed_episode_excludes_following_reward_entry_and_matches_manifest(tmp_path):
    catalog = fixture_catalog(tmp_path)
    setup, report = saved_episode()
    evidence, reason = actor_evidence(setup, report, catalog, current_hashes={'tools/arena_motion.py': 'abc'}, required_sources={'tools/arena_motion.py'})
    assert reason is None
    assert [b['stage'] for b in evidence['observed_boards']] == [5101, 5102]
    assert all(b['completed'] and b['whole_episode_no_hit'] for b in evidence['observed_boards'])
    assert evidence['source_match_current']
    assert evidence['detector']['sha256'] == 'old-weights'  # source match does not assert model equality


@pytest.mark.parametrize('change', ['damage', 'had_damage', 'god', 'missing_god', 'evaluation_error'])
def test_zero_final_health_loss_alone_is_not_no_hit(tmp_path, change):
    catalog = fixture_catalog(tmp_path)
    setup, report = saved_episode()
    if change == 'damage': report['final']['damage'] = 400
    elif change == 'had_damage': report['had_damage'] = True
    elif change == 'god': report['final']['god'] = True
    elif change == 'missing_god': del setup['initial']['god']
    else: report['evaluation_error'] = 'timeout'
    evidence, _ = actor_evidence(setup, report, catalog)
    assert not evidence['whole_episode_no_hit']
    assert not any(b['whole_episode_no_hit'] for b in evidence['observed_boards'])


def test_collection_observation_and_legacy_entry_do_not_become_complete_actor_board(tmp_path):
    catalog = fixture_catalog(tmp_path)
    setup, report = saved_episode()
    assert actor_evidence({'initial': {}}, {'frames': 500}, catalog)[1] == 'not_actor_report'
    assert actor_evidence(dict(setup, observe=True), report, catalog)[1] == 'observe_only'
    del setup['goal_stage_index']; del report['boards_requested']
    evidence, _ = actor_evidence(setup, report, catalog)
    assert [b['completed'] for b in evidence['observed_boards']] == [True, True, False]
    assert evidence['observed_boards'][-1]['stage'] == 5103
    assert not evidence['observed_boards'][-1]['whole_episode_no_hit']


def test_passed_status_with_unreached_native_goal_does_not_complete_last_board(tmp_path):
    catalog = fixture_catalog(tmp_path)
    setup, report = saved_episode()
    report['final']['stageIndex'] = 1
    report['board_entries'] = report['board_entries'][:2]
    evidence, _ = actor_evidence(setup, report, catalog)
    assert not evidence['goal_reached']
    assert [b['completed'] for b in evidence['observed_boards']] == [True, False]


def test_map_transition_completes_requested_previous_board_not_boss(tmp_path):
    catalog = fixture_catalog(tmp_path)
    setup, report = saved_episode(start=4, goal=4, board=5102)
    report['board_entries'] = [dict(stageIndex=3, stageID=5102)]
    report['final'].update(map=99, stageIndex=0)
    evidence, _ = actor_evidence(setup, report, catalog)
    assert evidence['goal_reached']
    assert evidence['observed_boards'] == [dict(stage=5102, map=41, slot=4, completed=True,
                                               whole_episode_no_hit=True, at_entry_damage=None)]


def test_alias_actor_evidence_maps_raw_slots_to_canonical_context(tmp_path):
    catalog = fixture_catalog(tmp_path)
    setup, report = saved_episode(start=2, goal=3)
    setup['map'] = 44; setup['initial']['map'] = 44
    report['final']['map'] = 44
    report['board_entries'] = [dict(stageIndex=1, stageID=5101), dict(stageIndex=2, stageID=5102),
                               dict(stageIndex=3, stageID=5103)]
    evidence, _ = actor_evidence(setup, report, catalog)
    assert evidence['map'] == 41 and evidence['raw_map'] == 44
    assert evidence['start'] == 1 and evidence['raw_start'] == 2
    assert [b['slot'] for b in evidence['observed_boards']] == [1, 2]


def test_source_evidence_separates_missing_or_mismatched_manifests(tmp_path):
    catalog = fixture_catalog(tmp_path)
    setup, report = saved_episode()
    for manifest in ({}, {'tools/arena_motion.py': 'changed'}):
        evidence, _ = actor_evidence(setup, report, catalog, current_hashes=manifest)
        assert not evidence['source_match_current']
        assert evidence['source_mismatches_current'] == ['tools/arena_motion.py']
    setup['sources'] = {}
    evidence, _ = actor_evidence(setup, report, catalog)
    assert not evidence['source_match_current']


def test_scan_reads_reports_once_and_build_separates_historical_current(tmp_path):
    catalog = fixture_catalog(tmp_path)
    setup, report = saved_episode()
    (tmp_path/'tools').mkdir(); source = tmp_path/'tools/arena_motion.py'; source.write_text('unchanged')
    setup['sources'] = {'tools/arena_motion.py': digest(source)}
    run = tmp_path/'reports/live'; run.mkdir(parents=True)
    (run/'setup.json').write_text(json.dumps(setup)); (run/'report.json').write_text(json.dumps(report))
    evidence = scan_actor_reports([tmp_path/'reports', run], catalog, source_root=tmp_path, required_sources={'tools/arena_motion.py'})
    assert len(evidence['records']) == 1
    result = build_audit(catalog, tmp_path, evidence=evidence, levels=[5, 6])
    assert result['current_source_actor_record_ids'] == [0]
    assert result['boards']['5101']['current_source_completed']
    assert result['boards']['5101']['contexts'][0]['entry_safety'] == 'historical_actor_started'
    source.write_text('new version')
    result = build_audit(catalog, tmp_path,
                        evidence=scan_actor_reports([run], catalog, source_root=tmp_path, required_sources={'tools/arena_motion.py'}), levels=[5, 6])
    assert result['boards']['5101']['historical_completed']
    assert not result['boards']['5101']['current_source_completed']
    assert not result['current_source_actor_record_ids']


def test_partial_old_manifest_cannot_be_called_current_source_evidence(tmp_path):
    catalog=fixture_catalog(tmp_path);setup,report=saved_episode()
    evidence,_=actor_evidence(setup,report,catalog,
        current_hashes={'tools/arena_motion.py':'abc','tools/new_actor.py':'def'},
        required_sources={'tools/arena_motion.py','tools/new_actor.py'})
    assert evidence['recorded_sources_match_current']
    assert not evidence['source_match_current']
    assert evidence['source_manifest_missing']==['tools/new_actor.py']


def test_reading_runner_manifest_does_not_execute_runtime_imports(tmp_path):
    path=tmp_path/'runner.py'
    path.write_text("raise RuntimeError('must not execute')\ndef run(args):\n    sources=('tools/a.py','tools/b.py')\n")
    assert actor_source_names(path)=={'tools/a.py','tools/b.py'}
