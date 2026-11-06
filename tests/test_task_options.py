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
