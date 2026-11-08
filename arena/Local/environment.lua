-- Local controls for the client's original GameOnly path.
-- The host runs on a separate Unity object; gameplay keeps its original update.
MR3A = MR3A or {}
local E = MR3A
local U = CS.UnityEngine
local flags = CS.System.Reflection.BindingFlags.__CastFrom(52)

local function vector(v) return {x=v.x,y=v.y,z=v.z} end

function E.state()
    local gm = CS.GameManager.Instance
    local out = {state=tostring(gm:GetCurFSMStateID()),content=tostring(gm.CurrContentState),
        frame=U.Time.frameCount,time=U.Time.time,timeScale=U.Time.timeScale,
        only=gm._isOnlyGame,offline=gm.GameInfo.OfflineGame,
        mode=gm.GameInfo._combatType,chapter=gm.GameInfo._chapterID,level=gm.GameInfo._levelID}
    local c = CS.NinjaController.Instance
    if c and c.NinjaScript then
        local n = c.NinjaScript
        out.position=vector(n.transform.position)
        out.speed=c:GetNinjaSpeed()
        out.physics=tostring(n:GetType():GetField('__ninjaPhysicsState',flags):GetValue(n))
        out.colliders={}
        local cols=n.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
        for i=0,cols.Length-1 do
            local v=cols[i]
            local row={name=v.name,type=v:GetType().Name,enabled=v.enabled,trigger=v.isTrigger,
                center=vector(v.bounds.center),extents=vector(v.bounds.extents)}
            if v:GetType().Name=='CapsuleCollider' then
                row.radius=v.radius;row.height=v.height;row.direction=v.direction
                row.localCenter=vector(v.center)
            end
            out.colliders[#out.colliders+1]=row
        end
    end
    return out
end

function E.pause()
    U.Time.timeScale=0
    return E.state()
end

function E.resume()
    U.Time.timeScale=1
    return E.state()
end

function E.advance(frames, action)
    assert(type(frames)=='number' and frames%1==0 and frames>=1 and frames<=600,'Frames must be 1..600')
    assert(action=='none' or action=='jump' or action=='down','Unknown action')
    assert(not E.busy,'An advance is already active')
    assert(U.Time.timeScale==0,'Pause before advancing')
    assert(tostring(CS.GameManager.Instance:GetCurFSMStateID())=='Game: 8','Battle is not ready')
    E.busy=true
    E.job={done=false,action=action,samples={},before=E.state()}
    local runner=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger))
    runner:StartCoroutine(require('common/util').cs_generator(function()
        local ok,err=pcall(function()
            local ui=CS.UIContorller.Instance.GameOperate
            U.Time.timeScale=1
            if action=='jump' then ui:OnRightDown() end
            if action=='down' then ui:OnLeftDown() end
            for i=1,frames do
                coroutine.step()
                local n=CS.NinjaController.Instance.NinjaScript
                E.job.samples[#E.job.samples+1]={frame=U.Time.frameCount,time=U.Time.time,
                    position=vector(n.transform.position),
                    physics=tostring(n:GetType():GetField('__ninjaPhysicsState',flags):GetValue(n))}
                if i==1 then
                    if action=='jump' then ui:OnRightReleased(U.Vector3.zero,U.Vector3.zero) end
                    if action=='down' then ui:OnLeftReleased(U.Vector3.zero,U.Vector3.zero) end
                end
            end
        end)
        U.Time.timeScale=0
        E.busy=false
        E.job.done=true
        if not ok then E.job.error=tostring(err) end
        E.job.after=E.state()
    end))
    return {started=true,frames=frames,action=action}
end

function E.result() return E.job end

function E.prepare(chapter, level)
    local gm=CS.GameManager.Instance
    assert(not gm.InRealGame,'A battle is already active')
    CurAvatar=CurAvatar or require('UI/Data/Avatar')()
    CurAvatar.serverindex=1
    local g=CS.Ninja3GameInfo.GameInfo()
    g.OfflineGame=true
    g._combatType=3
    g._chapterID=chapter or 1
    g._levelID=level or 1
    gm.GameInfo=g
    gm._isOnlyGame=true
    local r=g._roleInfo
    r._ninjatsuID=1
    r._magicInfo=Lua_GameManager.CreateNinjaMagicInfo({curNinjutsuid=1,roleid=1,curSkinid=1})
    g._ninjaMagicInfo=r._magicInfo
    gm:ChangeFSMState(11)
    return E.state()
end

function E.enter()
    local gm=CS.GameManager.Instance
    assert(gm._isOnlyGame and gm.GameInfo.OfflineGame,'Requires offline GameOnly')
    assert(gm.gameRecordManager,'GameOnly initialization has not completed')
    local g=gm.GameInfo
    gm:PreloadLevelData(g._combatType,g._chapterID,g._levelID)
    gm:EnterGameScene()
    return E.state()
end

return E
