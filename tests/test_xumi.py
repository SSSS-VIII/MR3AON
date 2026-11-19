"""须弥幻境：任务重排行绑定和真实画面的原生识别回放。"""
import itertools
import json
from pathlib import Path
import subprocess
import sys

import pytest
from utils.xumi_tasks import task_row_overrides

ROOT = Path(__file__).resolve().parents[1]
P = '须弥幻境'
TEXTS = ['完成1次方寸试炼', '完成1次大千试炼', '方寸试炼累计获得50000分', '大千试炼累计获得50000分']
KINDS = dict(zip(TEXTS, ['方寸次数', '大千次数', '方寸积分', '大千积分']))


@pytest.mark.parametrize('order', list(itertools.permutations(TEXTS)))
def test_claimed_tasks_can_move_to_any_row(order):
    items = [(text, [374, 207 + 106*i, 320, 30]) for i, text in enumerate(order)]
    patch = task_row_overrides(items)
    assert patch is not None
    for i, text in enumerate(order):
        for suffix in ['已领取', '进度']:
            roi = patch[P + KINDS[text] + suffix]['recognition']['param']['roi']
            assert roi[1] <= 207 + 106*i and roi[1] + roi[3] >= 237 + 106*i
            assert roi[1] >= 175 + 106*i and roi[1] + roi[3] <= 270 + 106*i


def test_ambiguous_or_incomplete_task_content_cannot_reuse_rows():
    items = [(text, [374, 207 + 106*i, 320, 30]) for i, text in enumerate(TEXTS)]
    assert task_row_overrides(items[:-1]) is None
    assert task_row_overrides(items + [(TEXTS[0], [374, 520, 200, 30])]) is None
    assert task_row_overrides(items + [items[0]]) == task_row_overrides(items)
    assert task_row_overrides([(t.replace('试炼', '試炼'), b) for t, b in items]) == task_row_overrides(items)
    assert task_row_overrides([(text, [374, 207, 320, 30]) for text in TEXTS]) is None
    assert task_row_overrides([(text, [374, 107 + 106*i, 320, 30]) for i, text in enumerate(TEXTS)]) is None


def test_daily_completion_requires_claims_and_restores_only_next_day():
    pipeline = json.loads((ROOT/'assets/resource/pipeline/须弥幻境.json').read_text())
    complete = pipeline[P+'全部任务已领取']
    assert set(complete['recognition']['param']['all_of']) == {P+'任务面板', *(P+kind+'已领取' for kind in KINDS.values())}
    assert pipeline[P+'检查每日任务']['next'].index(P+'领取全部任务奖励') < pipeline[P+'检查每日任务']['next'].index(P+'全部任务已领取')
    assert complete['next'] == [P+'完成回主页']
    state = pipeline[P+'主页登记完成']['action']['param']['custom_action_param']
    assert state == {'entry': P+'entry', 'enabled': False, 'valid_until': 'next_daily_reset'}
    assert pipeline[P+'继续试炼']['next'] == [P+'设置战斗时限']
    assert pipeline[P+'返回活动']['next'] == [P+'导航']
    assert pipeline[P+'等待结算']['next'][-1] == P+'继续等待结算'
    assert pipeline[P+'总超时']['next'] == ['重启游戏']
    assert '须弥幻境导航返回' not in pipeline[P+'导航']['next']  # 加载黑屏不能盲点返回。


def test_native_xumi_scene_replay():
    result = subprocess.run([sys.executable, __file__], cwd=ROOT, capture_output=True, text=True, timeout=60)
    assert result.returncode == 0, result.stdout[-2500:] + result.stderr[-2500:]


def _replay():
    import tempfile
    import numpy as np
    from PIL import Image
    from maa.define import LoggingLevelEnum
    from maa.library import Library
    from maa.pipeline import JAnd, JOr, JOCR
    from maa.resource import Resource
    from maa.tasker import Tasker

    pipeline = json.loads((ROOT/'assets/resource/pipeline/须弥幻境.json').read_text())
    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory(prefix='mr3a-xumi-native-') as logs:
        Tasker.set_log_dir(logs)
        resource = Resource()
        assert resource.post_bundle(str(ROOT/'assets/resource')).wait().succeeded
        tasker = Tasker()
        assert Library.framework().MaaTaskerBindResource(tasker._handle, resource._handle)
        def hit(name, image):
            rule = pipeline[P+name]['recognition']
            cls = {'And': JAnd, 'Or': JOr, 'OCR': JOCR}[rule['type']]
            return tasker.post_recognition(rule['type'], cls(**rule['param']), image).wait().get().nodes[0].recognition
        cases = {
            'assembly': {'进入活动卡片': True, '活动首页': False},
            'lobby': {'进入方寸试炼': True, '进入大千试炼': True, '打开每日任务': True, '任务面板': False},
            'fangcun': {'方寸开始游戏': True, '大千开始游戏': False},
            'daqian': {'大千开始游戏': True, '试炼页返回任务': True, '方寸开始游戏': False},
            'tasks_fangcun_pending': {'任务面板': True, '方寸任务未完成': True, '大千任务未完成': True, '全部任务已领取': False},
            'tasks_reordered_claimable': {'任务面板': True, '领取全部任务奖励': True, '全部任务已领取': False},
            'tasks_only_daqian_pending': {'任务面板': True, '方寸任务未完成': False, '大千任务未完成': True, '全部任务已领取': False},
            'tasks_all_claimed': {'任务面板': True, '全部任务已领取': True, '方寸任务未完成': False, '大千任务未完成': False, '领取全部任务奖励': False},
            'first_settlement': {'继续试炼': True, '返回活动': False},
            'final_settlement': {'返回活动': True, '继续试炼': False},
        }
        for scene, expected in cases.items():
            image = np.asarray(Image.open(ROOT/'tests/fixtures/xumi'/f'{scene}.png').convert('RGB'))[:, :, ::-1].copy()
            if scene.startswith('tasks_'):
                content = hit('任务全部内容', image)
                patch = task_row_overrides([(r.text, r.box) for r in content.filtered_results])
                assert patch is not None, scene
                assert resource.override_pipeline(patch)
            for name, wanted in expected.items():
                actual = hit(name, image).hit
                assert actual is wanted, (scene, name, actual, wanted)
        del tasker, resource


if __name__ == '__main__':
    _replay()
