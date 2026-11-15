"""Live bridge exercised with saved screenshots and simulated receipts, never ADB."""
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

from utils.intelligence_live import IntelligenceSession,observation,card_name

ROOT=Path(__file__).resolve().parents[1]
P='情报模拟战'


def seen(gold=5,hand=None,empty=None,refreshes=1):
    hand={0:'神乐·琳'} if hand is None else hand
    return dict(gold=gold,hand=hand,visible_slots=set(hand),empty=set(range(9)) if empty is None else set(empty),refreshes=refreshes,health=100)


def test_catalog_variants_and_ambiguous_suffix():
    assert card_name('龙焰·小黑')=='龙焰·小黑'
    assert card_name('炎魂·小黑')=='炎魂·小黑'
    assert card_name('凤林火山战旗')=='风林火山战旗'
    assert card_name('小黑') is None
    assert card_name('琳') is None


def test_purchase_cost_animation_does_not_invalidate_receipt():
    for balance,cost in [(3,2),(1,3)]:
        parsed=observation([(f'金币：{balance}',[1112,160,99,28]),
                            (f'-{cost}',[1211,160,45,23])],[])
        assert parsed['gold']==balance
        assert observation([(f'金币：{balance} -{cost}',[1112,160,144,28])],[])['gold']==balance
    assert observation([('-2',[1211,160,45,23])],[])['gold'] is None
    assert observation([('3',[1150,160,30,28])],[])['gold']==3
    state=IntelligenceSession();state.reset()
    state.pending={'round':1,'gold':5,'actions':[{'card':'剑心·卫鲤','shop_slot':0,'cell':1}]}
    receipt=observation([('金币：3',[1112,160,99,28]),('-2',[1211,160,45,23])],[])
    assert state.confirm(receipt,1)
    assert state.valid and state.board[1]['name']=='剑心·卫鲤'


def test_payment_and_placement_are_confirmed_before_board_changes(tmp_path):
    state=IntelligenceSession(tmp_path/'state.json');state.reset()
    def plan(raw,hand,refreshes,**kw):
        assert raw['gold']==5 and raw['shop_slots']==1
        assert kw['policy']['prioritize_finish'] is True
        return {'actions':[{'card':hand[0],'shop_slot':0,'cell':1}],'next_action':'prepare'}
    result=state.prepare(seen(),1,1,planner=plan)
    assert result['mode']=='rollout' and state.board==[None]*9
    assert state.confirm(seen(gold=4,hand={},empty=set(range(9))-{1}),1)
    assert state.board[1]=={'name':'神乐·琳','entered_round':1}
    assert IntelligenceSession(tmp_path/'state.json').board==state.board


def test_failed_clicks_are_not_optimistically_counted():
    state=IntelligenceSession();state.reset()
    state.pending={'round':1,'gold':5,'actions':[{'card':'神乐·琳','shop_slot':0,'cell':1}]}
    assert state.confirm(seen(),1)  # no gold spent, card still in shop
    assert state.board==[None]*9
    state.pending={'round':1,'gold':5,'actions':[{'card':'神乐·琳','shop_slot':0,'cell':1}]}
    assert not state.confirm(seen(gold=3,hand={},empty=set(range(9))-{1}),1)
    assert not state.valid and state.board==[None]*9


def test_round_advance_and_cold_resume_do_not_invent_existing_cards():
    state=IntelligenceSession()
    result=state.prepare(seen(gold=10,empty=[8]),3,0)
    assert result['mode']=='fallback'
    state.pending={'round':3,'gold':10,'actions':[{'card':'神乐·琳','shop_slot':0,'cell':8}]}
    assert not state.confirm(seen(gold=12,empty=[]),4)
    assert state.board==[None]*9 and not state.valid


def test_second_scan_never_repeats_refresh_even_if_first_click_failed():
    state=IntelligenceSession();state.reset()
    def plan(raw,hand,refreshes,**kw):
        assert refreshes==0
        return {'actions':[],'next_action':'prepare'}
    result=state.prepare(seen(refreshes=1),1,0,planner=plan)
    assert result['next_action']=='prepare'


def test_unknown_currency_skips_purchase():
    state=IntelligenceSession();state.reset()
    assert state.prepare(seen(gold=None),1,1)['mode']=='skip_unknown_gold'
    assert state.pending is None


def test_third_and_fourth_cells_remain_distinct_in_native_click_queue():
    from utils.intelligence_live import click_plans,cell_index
    from utils.intelligence_cards import apply_hand_plan
    actions=[{'card':'神乐·琳','shop_slot':0,'cell':2},
             {'card':'龙吟·洛青','shop_slot':1,'cell':3}]
    patches={}
    context=SimpleNamespace(override_pipeline=lambda patch:patches.update(patch) or True,
                            override_next=lambda *_:True)
    assert apply_hand_plan(context,P+'第一轮选牌',click_plans(actions),P+'准备就绪')
    # Operation numbers are queue order; board targets use row-major 0..8.
    assert patches[P+'放置卡牌1']['action']['param']['target']==[485,222]
    assert patches[P+'放置卡牌2']['action']['param']['target']==[142,412]
    assert cell_index([450,190,70,64])==2
    assert cell_index([107,380,70,64])==3


def test_native_saved_images_invoke_production_action(tmp_path):
    process=subprocess.run([sys.executable,__file__,'native'],cwd=ROOT,capture_output=True,text=True,timeout=90,env=dict(os.environ,MR3A_TEST_WORK=str(tmp_path)))
    assert process.returncode==0,process.stdout[-4000:]+process.stderr[-4000:]
    report=json.loads(process.stdout.strip().splitlines()[-1])
    assert report['first']['gold']==5 and report['first']['health']==100
    assert report['first']['refreshes']==1 and len(report['first']['hand'])==5
    assert report['fourth']['gold']==20 and report['fourth']['health']==100
    assert '神炎·小椒' in report['fourth']['hand'].values()
    assert report['planner_calls']>=2 and report['clicks']>2
    assert set(report['rounds'])=={1,4}
    assert report['direct_controller_calls']==0
    assert report['unpaid_board']==[None]*9
    assert report['receipt_confirmed']
    assert report['receipt_board'][1]=={'name':'星闪·小椒','entered_round':2}
    assert report['four_tigers']['health']==92 and report['four_tigers']['gold']==13
    assert report['four_tigers']['refreshes']==0
    assert report['four_tiger_damage']==14
    assert report['ready_wait'] and not report['before_ready_wait']


def _native():
    import tempfile
    import numpy as np
    from PIL import Image
    from maa.controller import CustomController
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.pipeline import JAnd
    from maa.define import LoggingLevelEnum
    from utils.intelligence_cards import iter_ocr_boxes,empty_cells
    from maa.library import Library
    Library.version()  # Freeze framework mode before importing the Agent registration decorators.
    from maa.agent.agent_server import AgentServer
    # Host these exact action classes in MaaFramework, not an RPC AgentServer.
    for decorator in ['custom_action','custom_recognition','tasker_sink','resource_sink','controller_sink','context_sink']:
        setattr(AgentServer,decorator,staticmethod(lambda *a,**kw:lambda cls:cls))
    from custom.action import intelligence_simulation as action
    pipeline=json.loads((ROOT/'assets/resource/pipeline/情报模拟战.json').read_text())
    frame=np.array(Image.open(ROOT/'tests/fixtures/intelligence_simulation/round.png').convert('RGB'))[:,:,::-1].copy()
    class Frames(CustomController):
        def connect(self):return True
        def request_uuid(self):return 'offline-intelligence-live-bridge'
        def get_features(self):return 0
        def screencap(self):return frame
        def click(self,x,y):self.clicks.append([x,y]);return True
        def swipe(self,*a):raise AssertionError('no drag')
        def start_app(self,*a):return False
        def stop_app(self,*a):return False
        def touch_down(self,*a):return True
        def touch_move(self,*a):return True
        def touch_up(self,*a):return True
        def click_key(self,*a):return False
        def input_text(self,*a):return False
        def key_down(self,*a):return False
        def key_up(self,*a):return False
    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory() as temp:
        Tasker.set_log_dir(temp)
        resource=Resource();assert resource.post_bundle(str(ROOT/'assets/resource')).wait().succeeded
        state=IntelligenceSession();state.reset();assert state.warm()
        action.session=lambda:state
        count=[];original=state.prepare
        def prepare(*a,**kw):count.append(a[1]);return original(*a,**kw)
        state.prepare=prepare
        assert resource.register_custom_action('PlanIntelligenceHand',action.PlanIntelligenceHand())
        assert resource.register_custom_action('ConfirmIntelligenceHand',action.ConfirmIntelligenceHand())
        from custom.action.general import NodeOverride
        assert resource.register_custom_action('NodeOverride',NodeOverride())
        pattern=pipeline[P+'第1回合']['action']['param']['custom_action_param'][P+'当前回合']
        assert resource.override_pipeline({P+'当前回合':pattern,P+'准备就绪':{'next':['OfflineStop']},'OfflineStop':{'action':'StopTask'}})
        controller=Frames();controller.clicks=[];assert controller.post_connection().wait().succeeded
        tasker=Tasker();assert tasker.bind(resource,controller)
        from maa.controller import Controller
        direct=[]
        def forbidden(*a,**kw):direct.append(1);raise AssertionError('Python controller input/capture forbidden')
        for method in ['post_click','post_swipe','post_screencap']:setattr(Controller,method,forbidden)
        def read(image):
            result=tasker.post_recognition('And',JAnd(**pipeline[P+'第一轮选牌']['recognition']['param']),image).wait().get().nodes[0].recognition
            assert result.hit
            data=observation(iter_ocr_boxes(result),empty_cells(result));data['visible_slots']=sorted(data['visible_slots']);data['empty']=sorted(data['empty'])
            return data
        first=read(frame)
        assert resource.override_pipeline({P+'当前回合':{'recognition':{'param':{'expected':['第.*回合']}}}})
        fourth_image=np.array(Image.open(ROOT/'tests/fixtures/intelligence_simulation/xiaojiao.png').convert('RGB'))[:,:,::-1].copy()
        fourth=read(fourth_image)
        def saved(name):
            return np.array(Image.open(ROOT/'tests/fixtures/intelligence_simulation'/name).convert('RGB'))[:,:,::-1].copy()
        before=read(saved('purchase_before.png'));after=read(saved('purchase_after.png'))
        four_tigers=read(saved('four_tigers.png'))
        receipt=IntelligenceSession();receipt.reset();receipt.board[0]={'name':'鬼狩·苍牙','entered_round':1}
        assert before['gold']==8 and before['health']==99
        receipt.pending={'round':2,'gold':8,'actions':[{'card':'星闪·小椒','cell':1,'shop_slot':1}]}
        receipt_confirmed=receipt.confirm(after,2)
        from intelligence_strategy.model import simulate
        four_tiger_damage=simulate({'round':4,'gold':13,'board':['神乐·琳','鬼狩·苍牙','超威·阿力','雷兽·阿力']+[None]*5,'pool_override':{}},profile='refresh_v1')['best_round_damage'][3]
        def already_ready(image):
            detail=tasker.post_recognition('And',JAnd(**pipeline[P+'已准备等待']['recognition']['param']),image).wait().get().nodes[0].recognition
            return bool(detail.hit)
        ready_wait=already_ready(saved('purchase_after.png'));before_ready_wait=already_ready(saved('purchase_before.png'))
        assert resource.override_pipeline({P+'当前回合':pattern})
        assert tasker.post_task(P+'第一轮选牌').wait().succeeded
        state.reset();frame=fourth_image
        assert tasker.post_task(P+'第4回合').wait().succeeded
        report=dict(ready_wait=ready_wait,before_ready_wait=before_ready_wait,four_tiger_damage=four_tiger_damage,first=first,fourth=fourth,four_tigers=four_tigers,receipt_confirmed=receipt_confirmed,receipt_board=receipt.board,rounds=count,planner_calls=len(count),clicks=len(controller.clicks),direct_controller_calls=len(direct),unpaid_board=state.board)
        del tasker,controller,resource
    print(json.dumps(report,ensure_ascii=False))


if __name__=='__main__':_native()


def test_task_precedes_3v3_and_round_contract_is_explicit():
    preset=json.loads((ROOT/'assets/resource/tasks/preset/日常任务.json').read_text())
    names=[v['name'] for v in preset['preset'][0]['task']]
    assert names.index(P)+1==names.index('3v3（仅支持困难图）')
    pipeline=json.loads((ROOT/'assets/resource/pipeline/情报模拟战.json').read_text())
    assert P+'准备匹配策略' in pipeline[P+'匹配前检查']['next']
    assert pipeline[P+'准备匹配策略']['action']['param']['custom_action']=='WarmIntelligenceStrategy'
    for turn in range(1,6):
        overrides=pipeline[P+f'第{turn}回合']['action']['param']['custom_action_param']
        assert overrides[P+'第一轮选牌']['action']['param']['custom_action_param']['round']==turn
        assert overrides[P+'第二轮选牌']['action']['param']['custom_action_param']['refreshes']==0
