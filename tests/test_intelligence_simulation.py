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
        assert gate['recognition']['param']['all_of'][-1]==P+f'第{i}回合额度'
        override=gate['action']['param']['custom_action_param']
        assert set(override)=={P+'当前回合',P+'其它回合'}
    assert P+'刷新手牌' in PIPELINE[P+'第一轮选牌']['next']
    assert P+'准备就绪' not in PIPELINE[P+'第一轮选牌']['next']
    assert P+'准备就绪' in PIPELINE[P+'第二轮选牌']['next']
    assert P+'刷新手牌' not in PIPELINE[P+'第二轮选牌']['next']
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


def test_native_round_ocr_card_selection_drag_and_budget_reset():
    result=subprocess.run([sys.executable,__file__,'native'],cwd=ROOT,capture_output=True,text=True,timeout=60)
    assert result.returncode==0,result.stdout[-3000:]+result.stderr[-3000:]
    report=json.loads(result.stdout.strip().splitlines()[-1])
    assert report['daily_claimed'] is True
    assert report['daily_missing_first'] is False and report['daily_missing_second'] is False
    assert report['slots']==[True,False,False,False,True]
    assert report['repeat'] is False and report['reset'] is True
    assert report['round_drags']==4,report
    assert report['refresh_clicks']==1 and report['ready_clicks']==1
    assert report['swipes']==1
    x1,y1,x2,y2=report['drag']
    assert x1>625 and y1>150 and 45<=x2<=565 and 135<=y2<=685


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
    from maa.custom_recognition import CustomRecognition
    from maa.custom_action import CustomAction
    budgets={}
    class Budget(CustomRecognition):
        def analyze(self,context,argv):
            name=argv.node_name
            if budgets.get(name,0):return None
            budgets[name]=1
            return self.AnalyzeResult(box=[0,0,1,1],detail={})

    frame=np.array(Image.open(ROOT/'tests/fixtures/intelligence_simulation/round.png'))[:,:,::-1].copy()
    class Frames(CustomController):
        def connect(self):return True
        def request_uuid(self):return 'offline-image-only'
        def get_features(self):return 0
        def start_app(self,*a):return False
        def stop_app(self,*a):return False
        def screencap(self):return frame
        def click(self,x,y):
            self.clicks.append((x,y))
            if y>610:self.prepared=True
            return True
        def swipe(self,*a):self.drags.append(a);return True
        def touch_down(self,*a):return True
        def touch_move(self,*a):return True
        def touch_up(self,*a):return True
        def click_key(self,*a):return False
        def input_text(self,*a):return False
        def key_down(self,*a):return False
        def key_up(self,*a):return False
    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory(prefix='mr3a-intelligence-offline-') as logs:
        Tasker.set_log_dir(logs)
        r=Resource();assert r.post_bundle(str(ROOT/'assets/resource')).wait().succeeded
        assert r.register_custom_recognition('Count',Budget())
        pattern=PIPELINE[P+'第1回合']['action']['param']['custom_action_param'][P+'当前回合']
        assert r.override_pipeline({P+'当前回合':pattern})
        c=Frames();c.drags=[];c.clicks=[];c.prepared=False;assert c.post_connection().wait().succeeded
        t=Tasker();assert t.bind(r,c)
        def hit(i):
            rule=PIPELINE[P+f'第一轮选牌{i}']['recognition']['param']
            return t.post_recognition('And',JAnd(**rule),frame).wait().get().nodes[0].recognition.hit
        budgets.clear()
        slots=[hit(i) for i in range(1,6)]
        repeated=hit(1)
        budget_name=PIPELINE[P+'重置手牌1']['action']['param']['custom_action_param']['node_name']
        assert budget_name in budgets
        budgets.pop(budget_name)
        reset=hit(1)
        budgets.clear()
        r.override_pipeline({P+'第一轮选牌1':{'next':['离线验证停止']},'离线验证停止':{'action':'StopTask'}})
        assert t.post_task(P+'第一轮选牌1').wait().succeeded
        report={'slots':slots,'repeat':repeated,'reset':reset,'swipes':len(c.drags),'drag':list(c.drags[0][:4])}
        class Reset(CustomAction):
            def run(self,context,argv):
                key=json.loads(argv.custom_action_param)['node_name']
                budgets.pop(key,None)
                return True
        class Override(CustomAction):
            def run(self,context,argv):return context.override_pipeline(json.loads(argv.custom_action_param))
        class Never(CustomRecognition):
            def analyze(self,context,argv):return None
        class Prepared(CustomRecognition):
            def analyze(self,context,argv):
                return self.AnalyzeResult(box=[0,0,1,1],detail={}) if c.prepared else None
        r.register_custom_action('ResetCount',Reset())
        r.register_custom_action('NodeOverride',Override())
        r.register_custom_recognition('LoopDeadlineExpired',Never())
        r.register_custom_recognition('OfflinePrepared',Prepared())
        r.override_pipeline({P+'第一轮选牌1':{'next':PIPELINE[P+'第一轮选牌1']['next']},
                             P+'结算确定':{'recognition':{'type':'Custom','param':{
                                 'custom_recognition':'OfflinePrepared'}},'action':'StopTask','next':[]}})
        budgets.clear();c.drags.clear();c.clicks.clear()
        assert t.post_task(P+'等待对局').wait().succeeded
        report.update(round_points=c.drags,round_drags=len(c.drags),refresh_clicks=sum(y<610 for _,y in c.clicks),
                      ready_clicks=sum(y>610 for _,y in c.clicks))
        daily=np.array(Image.open(ROOT/'tests/fixtures/intelligence_simulation/daily_claimed.png').convert('RGB'))[:,:,::-1].copy()
        rule=PIPELINE[P+'每日全部已领取']['recognition']['param']
        def daily_hit(image):
            return t.post_recognition('And',JAnd(**rule),image).wait().get().nodes[0].recognition.hit
        report['daily_claimed']=daily_hit(daily)
        for label,roi in [('first',[900,176,170,66]),('second',[900,277,170,66])]:
            missing=daily.copy();x,y,w,h=roi;missing[y:y+h,x:x+w]=0
            report['daily_missing_'+label]=daily_hit(missing)
        del t,c,r
    print(json.dumps(report))


if __name__=='__main__':_native()
