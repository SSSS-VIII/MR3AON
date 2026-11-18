-- Diagnostic only: execute a frozen route through original UI handlers.
-- No visual policy, rollback, physics replacement or field restoration.
local E,U=MR3A,CS.UnityEngine
local flags=CS.System.Reflection.BindingFlags.__CastFrom(52)
local function board()
    local level=CS.LevelManager.Instance.GameLevelInfo
    local ninja=CS.NinjaController.Instance.NinjaScript
    local ground=ninja._GroundCollider
    return {map=level:GetType():GetField('_levelBaseInfo',flags):GetValue(level)._levelID,
        stage_index=ground and ground.BelongToStageIndex or -1}
end
local function sample()
    local s=E.state()
    return {frame=s.episodeFrame,time=s.time,episode_time=s.episodeTime,
        position=s.position,physics=s.physics,health=s.health,fixed_delta=s.fixedDeltaTime,
        render_frame=s.frame,board=board()}
end
function E.run_fixed_oracle(spec)
    assert(not E.busy and U.Time.timeScale==0,'Start from the paused original entry')
    assert(spec.mode=='continuous_ticks','Unsupported original-client audit mode')
    assert(spec.capture_fps==0 or spec.capture_fps==60,'Use real time or the existing step capture clock')
    local initial=sample()
    local R={done=false,mode=spec.mode,capture_fps=spec.capture_fps,
        initial=initial,actions={},samples={},min_health=initial.health,cancel=false}
    E.fixedOracleAudit=R
    E.busy=true
    local runner=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger))
    runner:StartCoroutine(require('common/util').cs_generator(function()
        local ui=CS.UIContorller.Instance.GameOperate
        local released
        local function release()
            if not released then return end
            if released.action=='jump' then ui:OnRightReleased(U.Vector3.zero,U.Vector3.zero)
            else ui:OnLeftReleased(U.Vector3.zero,U.Vector3.zero)end
            released.after_release=sample()
            released=nil
        end
        local ok,err=pcall(function()
            U.Time.captureFramerate=spec.capture_fps
            U.Time.timeScale=1
            local next_event,last_sample=1,-10
            local deadline=U.Time.realtimeSinceStartup+120
            while true do
                assert(not R.cancel,'Oracle audit cancelled')
                assert(U.Time.realtimeSinceStartup<deadline,'Oracle audit did not finish')
                local current=sample()
                local tick=current.frame-initial.frame
                local hurt=current.health<R.min_health
                R.min_health=math.min(R.min_health,current.health)
                if released and current.frame>released.before.frame then release()end
                if tick>0 and (current.board.map~=initial.board.map or
                        current.board.stage_index>initial.board.stage_index) then
                    R.exit=true;break
                end
                if current.health<=0 or tick>=spec.duration_ticks+50 then break end
                if tick-last_sample>=5 or hurt then
                    R.samples[#R.samples+1]=current;last_sample=tick
                end
                local event=spec.events[next_event]
                if event and tick>=event.relative_tick then
                    assert(not released,'The next input arrived before the previous release')
                    local record={index=next_event-1,target_tick=event.source_tick or event.relative_tick,
                        scheduled_tick=event.relative_tick,
                        actual_tick=tick,action=event.action,before=current}
                    R.actions[#R.actions+1]=record
                    if event.action=='jump' then ui:OnRightDown()else ui:OnLeftDown()end
                    record.immediate=sample()
                    released=record;next_event=next_event+1
                end
                coroutine.step()
            end
        end)
        local release_ok,release_error=pcall(release)
        U.Time.timeScale=0;U.Time.captureFramerate=0;E.busy=false
        local final_ok,final=pcall(sample)
        if final_ok then R.final=final else R.final_error=tostring(final)end
        local eval_ok,evaluation=pcall(E.vision_evaluation)
        if eval_ok then R.evaluation=evaluation else R.evaluation_error=tostring(evaluation)end
        R.done=true
        if not ok then R.error=tostring(err)
        elseif not release_ok then R.error=tostring(release_error)
        elseif not final_ok or not eval_ok then R.error=R.final_error or R.evaluation_error end
    end))
    return {started=true}
end
return true
