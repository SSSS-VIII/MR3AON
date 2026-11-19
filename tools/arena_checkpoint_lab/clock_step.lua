-- Validation-only clock driver. Original advance, physics and UI stay intact.
local E,U=MR3A,CS.UnityEngine
local function board()
    local flags=CS.System.Reflection.BindingFlags.__CastFrom(52)
    local level=CS.LevelManager.Instance.GameLevelInfo
    local ground=CS.NinjaController.Instance.NinjaScript._GroundCollider
    local index=ground and ground.BelongToStageIndex or -1
    local stages=level:GetType():GetField('_stageList',flags):GetValue(level)
    local stage=index>=0 and index<stages.Count and stages[index]or nil
    if index>=stages.Count then stage=level:GetType():GetField('_currLoopStage',flags):GetValue(level)end
    return {map=level:GetType():GetField('_levelBaseInfo',flags):GetValue(level)._levelID,
        stage_index=index,stage_count=stages.Count,loop=index>=stages.Count,
        instance=stage and stage:GetHashCode()or nil,stage_start=stage and stage.StageStartX or -1}
end
function E.advance_render(frames,action)
    assert(not E.busy and U.Time.timeScale==0,'Pause before a clock interval')
    assert(type(frames)=='number' and frames%1==0 and frames>=1 and frames<=120,'Invalid render interval')
    assert(action=='none' or action=='jump' or action=='down','Unknown original input')
    local first_board=board()
    local job={done=false,unit='unity_render_frame',requested_frames=frames,
        action=action,before=E.state(),samples={}}
    E.busy=true
    local runner=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger))
    runner:StartCoroutine(require('common/util').cs_generator(function()
        local ui=CS.UIContorller.Instance.GameOperate
        local released=action=='none'
        local function release()
            if released then return end
            if action=='jump' then ui:OnRightReleased(U.Vector3.zero,U.Vector3.zero)
            else ui:OnLeftReleased(U.Vector3.zero,U.Vector3.zero)end
            released=true
        end
        local ok,err=pcall(function()
            U.Time.captureFramerate=60;U.Time.timeScale=1
            job.input_time=U.Time.time
            if action=='jump' then ui:OnRightDown()end
            if action=='down' then ui:OnLeftDown()end
            local first=U.Time.frameCount
            local deadline=U.Time.realtimeSinceStartup+30
            repeat
                assert(U.Time.realtimeSinceStartup<deadline,'Render clock stopped')
                coroutine.step()
                local state=E.state()
                job.samples[#job.samples+1]=state
                if state.health<job.before.health then job.terminated=true end
                if state.episodeFrame>job.before.episodeFrame then release()end
                local now=board()
                if now.map~=first_board.map or now.stage_index>first_board.stage_index or
                    (first_board.loop and now.instance~=first_board.instance and now.stage_start>first_board.stage_start)then
                    job.exited=true;break
                end
                if state.health<=0 then break end
            until U.Time.frameCount-first>=frames and released
        end)
        local release_ok,release_err=pcall(release)
        U.Time.timeScale=0;E.busy=false;job.done=true;job.after=E.state()
        local board_ok,value=pcall(board)
        if board_ok then job.board=value else job.board_error=tostring(value)end
        job.render_frames=job.after.frame-job.before.frame
        if not ok then job.error=tostring(err)
        elseif not release_ok then job.error=tostring(release_err)end
    end))
    return job
end
return true
