"""小号专用启动恢复：元数据隔离、原生OCR提示取消与旧页面返回。"""
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def test_startup_recovery_is_only_enabled_by_companion_metadata(monkeypatch):
    from custom.action import bounty_companion as bridge
    gate = bridge.BountyCompanionSession()
    monkeypatch.setattr(bridge, 'read_session', lambda: {})
    assert gate.analyze(None, None) is None
    monkeypatch.setattr(bridge, 'read_session', lambda: {'name': 'small'})
    assert gate.analyze(None, None) is not None
    small = json.loads((ROOT/'assets/resource/pipeline/每日悬赏小号.json').read_text())
    startup = json.loads((ROOT/'assets/resource/pipeline/启动游戏.json').read_text())['启动流程']['next']
    for name in ['悬赏小号启动取消悬浮窗提示','悬赏小号启动确认离队','悬赏小号启动返回']:
        assert name in startup
        assert small[name]['recognition']['param']['all_of'][0] == '悬赏小号启动会话'
        assert 0 < small[name]['max_hit'] <= 8
        assert small[name]['action']['type'] == 'Click'
        assert not small[name].get('next')  # 返回原启动分支，不串入通用back/重启。


def test_native_popup_cancel_requires_title_button_and_companion():
    result = subprocess.run([sys.executable, __file__], cwd=ROOT, capture_output=True,
                            text=True, timeout=60)
    assert result.returncode == 0, result.stdout[-3000:]+result.stderr[-3000:]
    report = json.loads(result.stdout.strip().splitlines()[-1])
    assert report['prompt']['hit']
    x,y,w,h=report['prompt']['box']
    assert 450<=x<x+w<=550 and 600<=y<y+h<=665
    for case in ['missing_title','missing_cancel','not_companion','stale_not_companion','home']:
        assert report[case]['hit'] is False
    assert report['stale']['hit'] is True
    x,y,w,h=report['stale']['box']
    assert x+w<160 and y+h<120


def _native():
    import tempfile
    import numpy as np
    from PIL import Image
    from maa.custom_recognition import CustomRecognition
    from maa.define import LoggingLevelEnum
    from maa.library import Library
    from maa.pipeline import JAnd
    from maa.resource import Resource
    from maa.tasker import Tasker
    enabled=True
    class Session(CustomRecognition):
        def analyze(self,context,argv):
            return self.AnalyzeResult(box=[0,0,1,1],detail={}) if enabled else None
    rule=json.loads((ROOT/'assets/resource/pipeline/每日悬赏小号.json').read_text())[
        '悬赏小号启动取消悬浮窗提示']['recognition']['param']
    original=np.zeros((720,1280,3),dtype=np.uint8)
    original[380:680,300:980]=np.asarray(Image.open(ROOT/'tests/fixtures/companion_startup/overlay_prompt_text.png').convert('RGB'))[:,:,::-1]
    Tasker.set_stdout_level(LoggingLevelEnum.Error)
    with tempfile.TemporaryDirectory(prefix='mr3a-companion-startup-') as logs:
        Tasker.set_log_dir(logs);r=Resource()
        assert r.post_bundle(str(ROOT/'assets/resource')).wait().succeeded
        assert r.register_custom_recognition('BountyCompanionSession',Session())
        t=Tasker();assert Library.framework().MaaTaskerBindResource(t._handle,r._handle)
        report={}
        for case in ['prompt','missing_title','missing_cancel','not_companion']:
            im=original.copy();enabled=case!='not_companion'
            if case=='missing_title':im[400:510,350:950]=255
            if case=='missing_cancel':im[590:675,430:590]=255
            rd=t.post_recognition('And',JAnd(**rule),im).wait().get().nodes[0].recognition
            report[case]={'hit':rd.hit,'box':list(rd.box) if rd.box else None}
        small=json.loads((ROOT/'assets/resource/pipeline/每日悬赏小号.json').read_text())
        rule=small['悬赏小号启动返回']['recognition']['param']
        for case in ['stale','stale_not_companion','home']:
            im=np.zeros((720,1280,3),dtype=np.uint8);enabled=case!='stale_not_companion'
            filename='home_no_back.png' if case=='home' else 'weapon_back.png'
            im[:210,:250]=np.asarray(Image.open(ROOT/'tests/fixtures/companion_startup'/filename).convert('RGB'))[:,:,::-1]
            rd=t.post_recognition('And',JAnd(**rule),im).wait().get().nodes[0].recognition
            report[case]={'hit':rd.hit,'box':list(rd.box) if rd.box else None}
        del t,r
    print(json.dumps(report))


if __name__=='__main__':_native()
