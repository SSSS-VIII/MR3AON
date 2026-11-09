-- Pause-and-label after original advance, then wait for host capture/next step.
local E,U=MR3A,CS.UnityEngine
function E.paired_step(ticks,action,identity)
 assert(not E.busy and U.Time.timeScale==0,'Collection requires paused original physics')
 if not E.pairedRunner then
  local go=U.GameObject('MR3A_PairedCollection');U.Object.DontDestroyOnLoad(go)
  E.pairedRunner=go:AddComponent(typeof(U.EventSystems.EventTrigger))
 end
 E.pairedIdentity=identity
 E.advance(ticks,action)
 E.pairedRunner:StartCoroutine(require('common/util').cs_generator(function()
  while E.busy do coroutine.step()end
  -- Let the original camera's LateUpdate finish while physics stays paused.
  coroutine.step()
  if E.pairedIdentity~=identity then return end
  local ok,labels=pcall(E.vision_labels)
  local result={identity=identity,done=true,action=action,error=E.job.error}
  if ok then result.labels=labels else result.error=tostring(labels)end
  CS.System.IO.File.WriteAllText(U.Application.persistentDataPath..'/arena-control/paired-collection.json',json.stringify(result))
 end))
 return true
end
return true
