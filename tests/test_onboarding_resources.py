"""起号接入闭包、队列交接和上游动作序列保持检查。"""
import ast
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RESOURCE = ROOT / 'assets/resource'


def test_all_stages_have_guarded_start_success_and_local_failure_routes():
    common = json.loads((RESOURCE / 'pipeline/起号必读.json').read_text())
    assert common['起号阶段停止']['action']['type'] == 'StopTask'
    assert common['起号流程失败']['action']['param']['custom_action'] == 'PauseWorkflowStage'
    for stage in range(1, 15):
        prefix = f'起号{stage:02}'
        nodes = json.loads((RESOURCE / f'pipeline/{prefix}.json').read_text())
        root = nodes[prefix + 'entry']
        assert root['action']['param']['custom_action'] == 'BeginWorkflowStage'
        assert root['action']['param']['custom_action_param']['stage'] == stage
        assert root['next'] == [prefix + '阶段入口']
        success = prefix + '结束' if stage < 14 else '起号14结束返回主页面'
        assert nodes[success]['recognition']
        assert nodes[success]['next'] == ['起号阶段完成登记']
        for node in nodes.values():
            assert 'on_error' in node  # 不继承日常重启路径
            assert node['on_error'] != ['Default_on_error']


def test_presets_options_and_documentation_images_form_a_complete_import():
    interface = json.loads((ROOT / 'assets/interface.json').read_text())
    tasks = json.loads((RESOURCE / 'tasks/新号起号.json').read_text())
    preset = json.loads((RESOURCE / 'tasks/preset/新号起号.json').read_text())['preset'][0]
    assert [t['name'] for t in tasks['task']] == [t['name'] for t in preset['task']]
    assert len(tasks['task']) == 15
    assert 'resource/tasks/新号起号.json' in interface['import']
    for stage in range(2, 15):
        assert (RESOURCE / f'tasks/images/起号{stage:02}使用场景.jpg').is_file()
    for task in tasks['task'][1:]:
        assert '起号账号标识' in task['option']
        assert tasks['option']['起号手动确认重试']['default_case'] == 'No'


def test_all_actions_use_stage_timing_without_changing_recorded_click_data():
    # 从固定v1.6.2源码核对过的点击个数/总等待，防止接入时误删动作。
    expected = {
        '1_3': (43, 78000), '1_4': (18, 32300), '2_1': (28, 90000),
        '2_2': (45, 108950), '2_3': (8, 23000), '2_4': (27, 105800),
        '2_6': (40, 85200), '2_7': (26, 52100), '2_8': (45, 120900), '2_9': (15, 22600),
    }
    for suffix, (count, total) in expected.items():
        text = (ROOT / f'agent/custom/action/qh_level_{suffix}.py').read_text()
        assert 'bind_stage_clicks(context, argv.task_detail.task_id)' in text
        waits = [ast.literal_eval(node.args[2]) for node in ast.walk(ast.parse(text))
                 if isinstance(node, ast.Call) and isinstance(node.func, ast.Name)
                 and node.func.id == 'click' and len(node.args) == 3]
        assert len(waits) == count
        assert sum(waits) == total
