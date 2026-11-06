import json
from pathlib import Path

import pytest

from runtime.task_options import build_task_config, load_task_interface

ROOT = Path(__file__).resolve().parents[1]


def test_real_options_are_transient_and_preserve_other_saved_values():
    interface = load_task_interface(ROOT / 'assets/interface.json')
    config = {'task': [
        {'name': '每周逆袭悬赏', 'option': [{'name': '选择要打的逆袭boss', 'value': '仅逆袭A'}]},
        {'name': '备战副本', 'option': [{'name': '免费接力', 'value': 'No'}]},
    ]}
    before = json.dumps(config)
    tasks = build_task_config(interface, config, ['每周逆袭悬赏', '备战副本'], {
        '每周逆袭悬赏': {'选择要打的逆袭boss': '仅逆袭S'}, '备战副本': {'免费接力': True},
    })
    assert next(o for o in tasks[0]['option'] if o['name'] == '选择要打的逆袭boss')['value'] == '仅逆袭S'
    assert tasks[1]['option'] == [{'name': '免费接力', 'value': 'Yes'}]
    assert json.dumps(config) == before


@pytest.mark.parametrize('patch', [
    {'不存在': {}}, {'备战副本': {'不存在': True}}, {'备战副本': {'免费接力': '错别字'}},
    {'备战副本': {'免费接力': []}}, {'备战副本': []}, [],
])
def test_bad_task_options_fail_before_device_operations(patch):
    with pytest.raises(ValueError):
        build_task_config(load_task_interface(ROOT / 'assets/interface.json'), {}, ['备战副本'], patch)


def test_nested_checkbox_and_inputs_keep_only_active_branches():
    interface = {'task': [{'name': 'T', 'option': ['parent', 'items', 'fields']}], 'option': {
        'parent': {'cases': [{'name': 'A', 'option': ['child']}, {'name': 'B'}], 'default_case': 'A'},
        'child': {'type': 'switch', 'cases': [{'name': 'Yes'}, {'name': 'No'}], 'default_case': 'No'},
        'items': {'type': 'checkbox', 'cases': [{'name': 'a'}, {'name': 'b'}], 'default_case': ['a']},
        'fields': {'type': 'input', 'inputs': [{'name': 'one', 'default': '1', 'pipeline_type': 'int'}, {'name': 'two', 'default': 'old'}]},
    }}
    config = {'task': [{'name': 'T', 'option': [{'name': 'fields', 'inputs': {'two': 'saved'}}]}]}
    task = build_task_config(interface, config, ['T'], {'T': {'parent': 'B', 'items': ['b'], 'fields': {'one': 2}}})[0]
    assert task['option'] == [{'name': 'parent', 'value': 'B'}, {'name': 'items', 'values': ['b']}, {'name': 'fields', 'inputs': {'one': '2', 'two': 'saved'}}]
    with pytest.raises(ValueError, match='未启用'):
        build_task_config(interface, config, ['T'], {'T': {'parent': 'B', 'child': True}})


@pytest.fixture(params=[
    ('每日悬赏', '小号配置', '游戏ID', '实例名称'),
    ('通知', '投递配置', '旧标题', '目标'),
])
def retired_input(request):
    task, option, retired, active = request.param
    interface = {
        'task': [{'name': task, 'option': [option]}],
        'option': {option: {'type': 'input', 'inputs': [
            {'name': active, 'pipeline_type': 'string', 'default': ''},
        ]}},
    }
    saved = {'task': [{'name': task, 'option': [
        {'name': option, 'inputs': {retired: '123456', active: 'small'}},
    ]}]}
    return interface, saved, task, option, retired, active


@pytest.mark.parametrize('override,expected', [(None, 'small'), ('new-small', 'new-small')])
def test_retired_saved_input_is_ignored_before_applying_current_override(retired_input, override, expected):
    interface, saved, task, option, retired, active = retired_input
    before = json.dumps(saved)
    patch = {} if override is None else {task: {option: {active: override}}}
    result = build_task_config(interface, saved, [task], patch)
    assert result == [{'name': task, 'option': [{'name': option, 'inputs': {active: expected}}]}]
    # 不改写磁盘配置的来源对象，也不在构建本次选项时重新带回旧字段。
    assert json.dumps(saved) == before
    assert retired not in result[0]['option'][0]['inputs']


@pytest.mark.parametrize('explicit_field', ['retired', 'unknown'])
def test_explicit_retired_or_unknown_input_remains_an_error(retired_input, explicit_field):
    interface, saved, task, option, retired, active = retired_input
    field = retired if explicit_field == 'retired' else '拼写错误字段'
    with pytest.raises(ValueError, match='已定义输入字段'):
        build_task_config(interface, saved, [task], {task: {option: {field: '123456', active: 'new-small'}}})


@pytest.mark.parametrize('inputs,expected', [
    (None, 'small'), ({'实例名称': 'another-small'}, 'another-small'), ({'游戏ID': '123456'}, None),
])
def test_real_bounty_interface_accepts_old_saved_id_but_not_new_id_argument(inputs, expected):
    interface = load_task_interface(ROOT / 'assets/interface.json')
    saved = {'task': [{'name': '每日悬赏', 'option': [
        {'name': '拉小号模式', 'value': 'Yes'},
        {'name': '小号配置', 'inputs': {'游戏ID': '123456', '实例名称': 'small'}},
    ]}]}
    before = json.dumps(saved)
    patch = {} if inputs is None else {'每日悬赏': {'小号配置': inputs}}
    if expected is None:
        with pytest.raises(ValueError, match='已定义输入字段'):
            build_task_config(interface, saved, ['每日悬赏'], patch)
    else:
        result = build_task_config(interface, saved, ['每日悬赏'], patch)[0]
        option = next(item for item in result['option'] if item['name'] == '小号配置')
        assert option['inputs'] == {'实例名称': expected}
    assert json.dumps(saved) == before


@pytest.mark.parametrize('arguments', [
    ['--task-options', 'null'], ['--task-options', '[]'], ['--task-options', '{}'],
    ['--once'], ['--once', '--task', '备战副本', '--prepare'],
])
def test_launcher_rejects_invalid_invocation_before_opening_an_instance(monkeypatch, arguments):
    from runtime import launcher
    from unittest.mock import Mock
    registry = Mock(side_effect=AssertionError('invalid arguments must not prepare devices'))
    monkeypatch.setattr(launcher, 'InstanceRegistry', registry)
    monkeypatch.setattr('sys.argv', ['run', *arguments])
    with pytest.raises(SystemExit) as exc:
        launcher.main()
    assert exc.value.code == 2
    registry.assert_not_called()
