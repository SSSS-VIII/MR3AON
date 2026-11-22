"""Keep real duplicate detection while allowing shared error fallbacks."""
import pytest

from tools.ci.check_routes import duplicate_routes


def test_normal_and_error_routes_are_independent():
    node = {'next': ['stop'], 'on_error': ['stop']}
    assert list(duplicate_routes(node)) == []


@pytest.mark.parametrize('field', ['next', 'on_error'])
@pytest.mark.parametrize('second', ['stop', '[JumpBack]stop', {'name': 'stop', 'jump_back': True}])
def test_repeated_candidate_is_rejected_in_each_list(field, second):
    errors = list(duplicate_routes({'node': {field: ['stop', second]}}))
    assert len(errors) == 1
    assert f'.{field}[1]: duplicate route stop' in errors[0]


def test_anchors_have_a_separate_namespace():
    assert list(duplicate_routes({'next': ['stop', '[Anchor]stop']})) == []
    errors = list(duplicate_routes({'next': ['[JumpBack][Anchor]stop', {'name': 'stop', 'anchor': True}]}))
    assert len(errors) == 1


def test_option_overrides_are_checked():
    task = {'option': {'mode': {'cases': [{'pipeline_override': {
        'node': {'on_error': ['stop', 'stop']}
    }}]}}}
    assert len(list(duplicate_routes(task))) == 1
