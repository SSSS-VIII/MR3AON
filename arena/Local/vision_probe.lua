-- Opt-in original-input motion/collider calibration. No gameplay replacement.
local E,U=MR3A,CS.UnityEngine
function E.probe_action(action,ticks,hold)
 assert(action=='jump' or action=='down','Unknown action')
 assert(type(ticks)=='number'and ticks%1==0 and ticks>=1 and ticks<=600,'Invalid duration')
 assert(type(hold)=='number'and hold%1==0 and hold>=1 and hold<=ticks,'Invalid hold')
 assert(not E.busy and U.Time.timeScale==0)
 E.busy=true;E.visionProbe={done=false,action=action,samples={}}
 local runner=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger))
 runner:StartCoroutine(require('common/util').cs_generator(function()
  local ui=CS.UIContorller.Instance.GameOperate
  local released=false
  local initialHealth=CS.NinjaController.Instance.NinjaScript.CurrentHp
  local ok,err=pcall(function()
   local n=CS.NinjaController.Instance.NinjaScript
   local game=CS.GameManager.Instance.GameInfo
   local start=game._totalFrameCount;local engineStart=U.Time.time
   local deadline=U.Time.realtimeSinceStartup+ticks*.1+10
   local function sample()
    local state=E.state()
    for _,v in ipairs(state.colliders)do if v.name=='Role' and v.enabled then
     E.visionProbe.samples[#E.visionProbe.samples+1]={tick=game._totalFrameCount-start,t=U.Time.time-engineStart,physics=state.physics,x=n.transform.position.x,y=n.transform.position.y,cx=v.center.x,cy=v.center.y,w=v.extents.x*2,h=v.extents.y*2}
    end end
   end
   sample();U.Time.captureFramerate=60;U.Time.timeScale=1
   if action=='jump' then ui:OnRightDown() else ui:OnLeftDown() end
   while game._totalFrameCount-start<ticks do
    assert(U.Time.realtimeSinceStartup<deadline,'Motion calibration timed out')
    assert(n.CurrentHp==initialHealth,'Damage during calibration invalidates the motion sample')
    coroutine.step()
    sample()
    if not released and game._totalFrameCount-start>=hold then
     if action=='jump' then ui:OnRightReleased(U.Vector3.zero,U.Vector3.zero) else ui:OnLeftReleased(U.Vector3.zero,U.Vector3.zero) end
     released=true
    end
   end
  end)
  if not released then pcall(function()
   if action=='jump' then ui:OnRightReleased(U.Vector3.zero,U.Vector3.zero) else ui:OnLeftReleased(U.Vector3.zero,U.Vector3.zero) end
  end) end
  U.Time.timeScale=0;U.Time.captureFramerate=0;E.busy=false;E.visionProbe.done=true
  if not ok then E.visionProbe.error=tostring(err) end
 end))
 return true
end
return true
