"""情报模拟战离线开发验证：不连接ADB、不创建或操作命名实例。"""
import json
from datetime import datetime
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parents[1]
P = '情报模拟战'
PIPELINE = json.loads((ROOT/'assets/resource/pipeline/情报模拟战.json').read_text())


@pytest.mark.parametrize(('hour','minute','opened','due'), [
    (0,0,False,(13,10)), (9,59,False,(13,10)), (10,0,True,None),
    (13,59,True,None), (14,0,False,(13,18)), (17,59,False,(13,18)),
    (18,0,True,None), (21,59,True,None), (22,0,False,(14,10)),
    (23,59,False,(14,10)),
])
def test_activity_windows_and_next_opening(monkeypatch,hour,minute,opened,due):
    import pytz
    from custom.reco.time_check import TimeAfter, TimeBefore
    from custom.action.deferred_tasks import next_daily_time
    now=pytz.timezone('Asia/Shanghai').localize(datetime(2026,11,13,hour,minute))
    monkeypatch.setattr('custom.reco.time_check.now_in_timezone',lambda _:now)
    results={}
    for name in ['十点后','十四点前','十八点后','二十二点前']:
        spec=PIPELINE[P+name]['recognition']['param']
        cls=TimeAfter if spec['custom_recognition']=='TimeAfter' else TimeBefore
        arg=SimpleNamespace(custom_recognition_param=json.dumps(spec['custom_recognition_param']))
        results[name]=cls().analyze(None,arg) is not None
    assert ((results['十点后'] and results['十四点前']) or
            (results['十八点后'] and results['二十二点前'])) is opened
    if not opened:
        times=PIPELINE[P+'未开放']['action']['param']['custom_action_param']['daily_times']
        result=next_daily_time(times,now=now)
        assert (result.day,result.hour)==due


def test_two_hands_round_identity_and_fail_closed_completion():
    for i in range(1,6):
        gate=PIPELINE[P+f'第{i}回合']
        assert gate['max_hit']==1
        assert len(gate['recognition']['param']['all_of'])==2
        override=gate['action']['param']['custom_action_param']
        assert set(override)=={P+'当前回合'}
    for phase, after in [('第一轮选牌','刷新手牌'),('第二轮选牌','准备就绪')]:
        assert PIPELINE[P+phase]['action']['param']['custom_action_param']=={'after':P+after}
        assert PIPELINE[P+phase]['post_delay']==0
    assert P+'结算确定' in PIPELINE[P+'导航']['next']
    for node in PIPELINE.values():
        param=node.get('action',{}).get('param',{})
        if param.get('custom_action')=='ResetCount':
            assert param['custom_action_param']['node_name'] in PIPELINE
    final=PIPELINE[P+'每日全部已领取']['recognition']['param']['all_of']
    assert final==[P+'每日任务标题',P+'每日任务1已领取',P+'每日任务2已领取']
    assert PIPELINE[P+'每日全部已领取']['next']==[P+'未知每日状态拒绝完成',P+'确认每日全领取']
    assert PIPELINE[P+'未知每日状态拒绝完成']['next']==['Default_on_error']
    persist=PIPELINE[P+'主页登记完成']['action']['param']['custom_action_param']
    assert persist=={'entry':P+'entry','enabled':False,'valid_until':'next_daily_reset'}
    assert PIPELINE[P+'主页登记完成']['recognition']['param']['all_of']==[P+'游戏主页']
    presets=json.loads((ROOT/'assets/resource/tasks/preset/限时活动.json').read_text())
    assert next(t for t in presets['preset'][0]['task'] if t['name']==P)['enabled'] is False


def test_native_batch_click_placement_refresh_settlement_and_daily():
    result=subprocess.run([sys.executable,__file__,'native'],cwd=ROOT,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout[-3000:]+result.stderr[-3000:]
    report=json.loads(result.stdout.strip().splitlines()[-1])
    assert report['daily_claimed'] is True
    assert report['daily_missing_first'] is False and report['daily_missing_second'] is False
    assert report['roles']==['小黑','焚天','小椒']
    assert '小椒' in report['xiaojiao_roles']
    assert report['swipes']==0
    assert report['clicks']==14  # 两轮各三张、每张两次点击，另有刷新和准备
    assert report['refresh_clicks']==1 and report['ready_clicks']==1
    assert report['settlement'] is True and report['round_is_not_settlement'] is False


def test_refresh_flip_is_not_treated_as_an_empty_hand():
    from utils.intelligence_cards import hand_is_visible
    assert not hand_is_visible([('卡牌商店',[647,157,92,30]),('已刷新',[1083,522,67,26])])
    assert hand_is_visible([('云狐',[880,365,95,25])])


def test_round_reset_and_flip_retry_do_not_advance_phase():
    from custom.action.intelligence_simulation import PlanIntelligenceHand,ResetIntelligenceRounds
    calls=[]
    context=SimpleNamespace(clear_hit_count=lambda name:calls.append(name),
                            override_next=lambda name,nodes:calls.append((name,nodes)) or True)
    assert ResetIntelligenceRounds().run(context,None)
    assert calls==[P+f'第{i}回合' for i in range(1,6)]
    detail=SimpleNamespace(hit=True,filtered_results=[],all_results=[])
    args=SimpleNamespace(node_name=P+'第二轮选牌',reco_detail=detail,
                         custom_action_param=json.dumps({'after':P+'准备就绪'}))
    assert PlanIntelligenceHand().run(context,args)
    assert calls[-1]==(P+'第二轮选牌',[P+'第二轮选牌'])


@pytest.mark.parametrize('name',['风林火山战旗','凤林火山战旗','修罗覆面','其他覆面','赤芒','焚天','黑龙'])
def test_additional_flag_and_mask_candidates(name):
    from utils.intelligence_cards import plan_cards
    result=plan_cards([(name,[680,365,120,25]),('云狐',[880,365,95,25]),
                       ('修罗覆面',[680,310,120,25])],[[105,186,75,75]])
    assert len(result)==1 and result[0][2]==name


def test_card_plan_deduplicates_and_ignores_description_and_full_board():
    from utils.intelligence_cards import plan_cards
    items=[('神炎·小椒',[1050,365,95,25]),('神炎·小椒',[1050,365,95,25]),
           ('上场阿力',[680,300,100,20]),('云狐',[880,365,95,25])]
    cells=[[100,180,75,75],[101,181,75,75],[270,180,75,75]]
    result=plan_cards(items,cells)
    assert len(result)==1 and result[0][0]==(1110,280) and result[0][2]=='小椒'
    assert plan_cards(items,[])==[]


@pytest.mark.parametrize(('statuses','complete'), [
    ([],False), (['已领取'],True), (['已领取','已领取'],True),
    (['已领取','未完成'],False), (['已领取','领取奖励'],False),
    (['已领取','未知状态'],False),
])
def test_daily_completion_requires_nonempty_known_claimed_states(statuses,complete):
    import re
    yes=PIPELINE[P+'每日状态已领取']['recognition']['param']['expected'][0]
    other=PIPELINE[P+'每日状态存在其它文字']['recognition']['param']['expected'][0]
    assert (any(re.search(yes,t) for t in statuses) and not any(re.search(other,t) for t in statuses)) is complete


def test_task_is_selectable_without_touching_account_configuration():
    from runtime.task_options import build_task_config,load_task_interface
    interface=load_task_interface(ROOT/'assets/interface.json')
    config={'task':[]}
    result=build_task_config(interface,config,[P],{})
    assert result[0]['name']==P
    assert config=={'task':[]}


def _native():
    import tempfile
    import numpy as np
    from PIL import Image
    from maa.controller import CustomController
    from maa.define import LoggingLevelEnum
    from maa.pipeline import JAnd
    from maa.resource import Resource
    from maa.tasker import Tasker
    from maa.custom_action import CustomAction
    from utils.intelligence_cards import plan_cards,iter_ocr_boxes,empty_cells,apply_hand_plan

    def load(name):
        return np.array(Image.open(ROOT/'tests/fixtures/intelligence_simulation'/name).convert('RGB'))[:,:,::-1].copy()
    frame=load('round.png')
    class Frames(CustomController):
        def connect(self):return True
        def request_uuid(self):return 'offline-image-only'
        def get_features(self):return 0
        def start_app(self,*a):return False
        def stop_app(self,*a):return False
        def screencap(self):return frame
        def click(self,x,y):self.clicks.append((x,y));return True
        def swipe(self,*a):self.drags.append(a);return True
        def touch_down(self,*a):return True
        def touch_move(self,*a):return True
        def touch_up(self,*a):return True
        def click_key(self,*a):return False
        def input_text(self,*a):return False
        def key_down(self,*a):return False
        def key_up(self,*a):return False
    class Planner(CustomAction):
        def run(self,context,argv):
            plans=plan_cards(iter_ocr_boxes(argv.reco_detail),empty_cells(argv.reco_detail))
            return apply_hand_plan(context,argv.node_name,plans,json.loads(argv.custom_action_param)['after'])
    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory(prefix='mr3a-intelligence-offline-') as logs:
        Tasker.set_log_dir(logs)
        r=Resource();assert r.post_bundle(str(ROOT/'assets/resource')).wait().succeeded
        assert r.register_custom_action('PlanIntelligenceHand',Planner())
        pattern=PIPELINE[P+'第1回合']['action']['param']['custom_action_param'][P+'当前回合']
        assert r.override_pipeline({P+'当前回合':pattern,P+'准备就绪':{'next':['离线验证停止']},
                                    '离线验证停止':{'action':'StopTask'}})
        c=Frames();c.drags=[];c.clicks=[];assert c.post_connection().wait().succeeded
        t=Tasker();assert t.bind(r,c)
        def recognize(name,image):
            rule=PIPELINE[P+name]['recognition']['param']
            return t.post_recognition('And',JAnd(**rule),image).wait().get().nodes[0].recognition
        scan=recognize('第一轮选牌',frame)
        plans=plan_cards(iter_ocr_boxes(scan),empty_cells(scan))
        report={'roles':[v[2] for v in plans]}
        scan2=recognize('第一轮选牌',load('xiaojiao.png'))
        report['xiaojiao_roles']=[v[2] for v in plan_cards(iter_ocr_boxes(scan2),empty_cells(scan2))]
        assert t.post_task(P+'第一轮选牌').wait().succeeded
        report.update(swipes=len(c.drags),clicks=len(c.clicks),
                      refresh_clicks=sum(x>1010 and 495<y<575 for x,y in c.clicks),
                      ready_clicks=sum(y>625 for x,y in c.clicks))
        daily=load('daily_claimed.png')
        report['daily_claimed']=recognize('每日全部已领取',daily).hit
        for label,roi in [('first',[900,176,170,66]),('second',[900,277,170,66])]:
            missing=daily.copy();x,y,w,h=roi;missing[y:y+h,x:x+w]=0
            report['daily_missing_'+label]=recognize('每日全部已领取',missing).hit
        report['settlement']=recognize('结算确定',load('settlement.png')).hit
        report['round_is_not_settlement']=recognize('结算确定',frame).hit
        del t,c,r
    print(json.dumps(report))


if __name__=='__main__':_native()
