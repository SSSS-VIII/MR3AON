-- Local controls for the client's original GameOnly path.
-- The host runs on a separate Unity object; gameplay keeps its original update.
MR3A = MR3A or {}
local E = MR3A
local U = CS.UnityEngine
local flags = CS.System.Reflection.BindingFlags.__CastFrom(52)
E.seed=E.seed or 1
E.mode=6
E.healthMultiplier=20
if not E.seedHook then
    local util=require('common/util')
    util.hotfix_ex(CS.RandomManager,'Random_Seed',function(seed)
        CS.RandomManager.Random_Seed(E.seed or seed)
    end)
    util.hotfix_ex(CS.RandomManager,'Random_Boss_Seed',function(seed)
        CS.RandomManager.Random_Boss_Seed(E.seed or seed)
    end)
    E.seedHook=true
end

local function vector(v) return {x=v.x,y=v.y,z=v.z} end

function E.state()
    local gm = CS.GameManager.Instance
    local out = {state=tostring(gm:GetCurFSMStateID()),content=tostring(gm.CurrContentState),
        frame=U.Time.frameCount,time=U.Time.time,timeScale=U.Time.timeScale,
        only=gm._isOnlyGame,offline=gm.GameInfo.OfflineGame,
        mode=gm.GameInfo:GetRealCombatType(),combatFamily=gm.GameInfo._combatType,chapter=gm.GameInfo._chapterID,level=gm.GameInfo._levelID,seed=E.seed,
        episodeFrame=gm.GameInfo._totalFrameCount,episodeTime=gm.GameInfo._totalTime,healthMultiplier=E.healthMultiplier}
    out.score=gm.GameInfo._scoreInfo._totalScore
    out.distance=gm.GameInfo._scoreInfo._runDistance
    out.coins=gm.GameInfo._scoreInfo.TotalCoin
    local c = CS.NinjaController.Instance
    if c and c.NinjaScript then
        local n = c.NinjaScript
        out.position=vector(n.transform.position)
        out.speed=c:GetNinjaSpeed()
        out.health=n.CurrentHp
        out.maxHealth=n.MaxHp
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

function E.layout()
    local level=CS.LevelManager.Instance.GameLevelInfo
    local list=level:GetType():GetField('_stageList',flags):GetValue(level)
    local out={seed=E.seed,stages={}}
    for i=0,list.Count-1 do
        local stage=list[i]
        local info=stage:GetType():GetField('_stageBaseInfo',flags):GetValue(stage)
        local blocks=stage:GetType():GetField('_finalBlockList',flags):GetValue(stage)
        local row={stage=info._stageID,blocks={}}
        for j=0,blocks.Count-1 do
            row.blocks[#row.blocks+1]=json.parse(U.JsonUtility.ToJson(blocks[j]))
        end
        out.stages[#out.stages+1]=row
    end
    return out
end

function E.parameters()
    local n=CS.NinjaController.Instance.NinjaScript
    local data=n:GetType():GetField('_ninjaData',flags):GetValue(n)
    return {role=1,skin=1,level=1,fixedDeltaTime=U.Time.fixedDeltaTime,
        canJump3=n.CanJump3,canJump4=n.CanJump4,
        configured=json.parse(U.JsonUtility.ToJson(data)),runtime=E.state()}
end

function E.load_audio()
    E.audio={done=false}
    local previousScale=U.Time.timeScale
    U.Time.timeScale=1
    local runner=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger))
    runner:StartCoroutine(require('common/util').cs_generator(function()
        local ok,err=pcall(function()
            coroutine.yield(CS.FMODUnity.RuntimeManager.LoadAllBanksAfterFullPatch())
        end)
        U.Time.timeScale=previousScale
        E.audio.done=true
        if not ok then E.audio.error=tostring(err) end
    end))
    return {loading=true}
end

function E.pause()
    U.Time.timeScale=0
    return E.state()
end

function E.resume()
    U.Time.captureFramerate=0
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
    E.job={done=false,action=action,unit='native_physics_tick',samples={},before=E.state()}
    local runner=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger))
    runner:StartCoroutine(require('common/util').cs_generator(function()
        local ok,err=pcall(function()
            local ui=CS.UIContorller.Instance.GameOperate
            U.Time.captureFramerate=60
            U.Time.timeScale=1
            if action=='jump' then ui:OnRightDown() end
            if action=='down' then ui:OnLeftDown() end
            local game=CS.GameManager.Instance.GameInfo
            local firstTick=game._totalFrameCount
            local lastTick=firstTick
            local released=false
            local deadline=U.Time.realtimeSinceStartup+frames*0.2+10
            while game._totalFrameCount-firstTick<frames do
                assert(U.Time.realtimeSinceStartup<deadline,'Physics ticks stopped advancing')
                coroutine.step()
                local n=CS.NinjaController.Instance.NinjaScript
                if game._totalFrameCount>lastTick then
                    lastTick=game._totalFrameCount
                    E.job.samples[#E.job.samples+1]={frame=U.Time.frameCount,time=U.Time.time,
                        episodeFrame=game._totalFrameCount,episodeTime=game._totalTime,
                        position=vector(n.transform.position),
                        physics=tostring(n:GetType():GetField('__ninjaPhysicsState',flags):GetValue(n))}
                end
                if n.CurrentHp<=0 then E.job.terminated=true;break end
                if not released and game._totalFrameCount>firstTick then
                    if action=='jump' then ui:OnRightReleased(U.Vector3.zero,U.Vector3.zero) end
                    if action=='down' then ui:OnLeftReleased(U.Vector3.zero,U.Vector3.zero) end
                    released=true
                end
            end
            if not released then
                if action=='jump' then ui:OnRightReleased(U.Vector3.zero,U.Vector3.zero) end
                if action=='down' then ui:OnLeftReleased(U.Vector3.zero,U.Vector3.zero) end
            end
        end)
        U.Time.timeScale=0
        E.busy=false
        E.job.done=true
        if not ok then E.job.error=tostring(err) end
        E.job.after=E.state()
    end))
    return {started=true,ticks=frames,action=action}
end

function E.result() return E.job end

function E.poll_keys()
    local gm=CS.GameManager.Instance
    if E.busy or tostring(gm:GetCurFSMStateID())~='Game: 8' then return end
    local input=U.Input
    local keys=U.KeyCode
    local ui=CS.UIContorller.Instance.GameOperate
    if input.GetKeyDown(keys.P) then
        E.lastKey='P'
        if U.Time.timeScale==0 then E.resume() else E.pause() end
    elseif input.GetKeyDown(keys.R) or input.GetKeyDown(keys.N) then
        local change=input.GetKeyDown(keys.N)
        E.lastKey=change and 'N' or 'R'
        E.reset(change and ((E.seed+1)%2147483648) or E.seed,gm.GameInfo._chapterID,gm.GameInfo._levelID)
    elseif input.GetKeyDown(keys.Period) and U.Time.timeScale==0 then
        E.lastKey='.'
        E.advance(1,'none')
    elseif input.GetKeyDown(keys.Space) or input.GetKeyDown(keys.W) or input.GetKeyDown(keys.UpArrow) then
        E.lastKey='jump'
        if U.Time.timeScale==0 then E.advance(1,'jump') else ui:OnRightDown() end
    elseif input.GetKeyDown(keys.S) or input.GetKeyDown(keys.DownArrow) then
        E.lastKey='down'
        if U.Time.timeScale==0 then E.advance(1,'down') else ui:OnLeftDown() end
    end
    if input.GetKeyUp(keys.Space) or input.GetKeyUp(keys.W) or input.GetKeyUp(keys.UpArrow) then
        ui:OnRightReleased(U.Vector3.zero,U.Vector3.zero)
    end
    if input.GetKeyUp(keys.S) or input.GetKeyUp(keys.DownArrow) then
        ui:OnLeftReleased(U.Vector3.zero,U.Vector3.zero)
    end
end

function E.enable_keyboard()
    if E.keyboardReady then return true end
    local host=U.GameObject('MR3A_InputControl')
    U.Object.DontDestroyOnLoad(host)
    local runner=host:AddComponent(typeof(U.EventSystems.EventTrigger))
    E.keyboardReady=true
    runner:StartCoroutine(require('common/util').cs_generator(function()
        while true do
            local ok,err=pcall(E.poll_keys)
            if not ok then E.keyboardError=tostring(err) end
            coroutine.step()
        end
    end))
    return true
end

function E.new_info(chapter,level)
    assert(NCONFIG.CfgEndlessGaleData[chapter or 1] and NCONFIG.CfgEndlessGaleData[chapter or 1][level or 1],
        'Unknown arena chapter or level')
    local g=CS.Ninja3GameInfo.GameInfo()
    g.OfflineGame=true
    g._combatType=E.mode
    g._chapterID=chapter or 1
    g._levelID=level or 1
    local r=g._roleInfo
    r._ninjatsuID=1
    r._magicInfo=Lua_GameManager.CreateNinjaMagicInfo({curNinjutsuid=1,roleid=1,curSkinid=1})
    g._ninjaMagicInfo=r._magicInfo
    return g
end

function E.prepare(chapter, level)
    local gm=CS.GameManager.Instance
    local state=tostring(gm:GetCurFSMStateID())
    assert(state~='Game: 8' and state~='LoadingGame: 9','A battle is already active')
    CurAvatar=CurAvatar or require('UI/Data/Avatar')()
    CurAvatar.serverindex=1
    gm.GameInfo=E.new_info(chapter,level)
    gm._isOnlyGame=true
    gm:ChangeFSMState(11)
    return E.state()
end

function E.role_defaults()
    local gm=CS.GameManager.Instance
    local g=gm.GameInfo
    if E.roleGameInfo==g then return end
    gm:InitBaseBonusGameOnly()
    local bonuses={}
    Lua_GameManager.GetRoleAddBonus(bonuses,{roleid=1,level=1})
    for _,v in pairs(bonuses) do
        local x=v.bonusvalue
        local multiplier=v.bonustype==NCONFIG.CfgBonusType.HP and E.healthMultiplier or 1
        g._bonusManager:AddRoleProperty(g._playerID,g._roleInfo._roleID,
            CS.CfgBonusType.__CastFrom(v.bonustype),x[1]*multiplier,x[2]*multiplier,x[3])
    end
    local cfg=NCONFIG.CfgGameScoreCoinExp
    for _,k in ipairs({'CritMulti_Base_Score','CritMulti_Base_Damage','ScoreFactor_DistanceToScore','ScoreMax','CoinMax'}) do g[k]=cfg[k] end
    g.CoinBaseReward=cfg.CoinBaseReward_Gale
    for _,k in ipairs({'Distance','Monster','Coin'}) do g['CoinFactor_ScoreTransCoin_'..k]=cfg['CoinFactor_ScoreTransCoin_'..k..'_Gale'] end
    gm._gameOnlyAutoResurgence=false
    E.roleGameInfo=g
end

function E.enter()
    local gm=CS.GameManager.Instance
    assert(gm._isOnlyGame and gm.GameInfo.OfflineGame,'Requires offline GameOnly')
    assert(gm.gameRecordManager,'GameOnly initialization has not completed')
    E.role_defaults()
    if CS.GameException.Instance then CS.GameException.Instance.gameObject:SetActive(false) end
    CS.GameLoading.CloseLoading()
    local g=gm.GameInfo
    gm:PreloadLevelData(E.mode,g._chapterID,g._levelID)
    gm:EnterGameScene()
    E.wait_ready()
    return E.state()
end

function E.wait_ready()
    local gm=CS.GameManager.Instance
    E.resetJob={done=false,seed=E.seed}
    local runner=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger))
    runner:StartCoroutine(require('common/util').cs_generator(function()
        local ok,err=pcall(function()
            local deadline=U.Time.realtimeSinceStartup+60
            while tostring(gm:GetCurFSMStateID())~='Game: 8' or tostring(gm.CurrContentState)~='Running: 1' do
                assert(U.Time.realtimeSinceStartup<deadline,'Reset did not enter the battle')
                coroutine.step()
            end
        end)
        U.Time.timeScale=0
        E.resetJob.done=true
        if not ok then E.resetJob.error=tostring(err) end
        E.resetJob.state=E.state()
    end))
end

function E.reset(seed, chapter, level)
    local gm=CS.GameManager.Instance
    assert(gm._isOnlyGame and gm.GameInfo.OfflineGame,'Requires offline GameOnly')
    assert(type(seed)=='number' and seed%1==0 and seed>=0 and seed<=2147483647,'Invalid seed')
    assert(not E.busy,'An advance is active')
    E.seed=seed
    U.Time.captureFramerate=60
    U.Time.timeScale=1
    gm:PauseGameContent()
    gm:ClearAllObjectsInScene()
    U.Random.InitState(seed)
    gm.GameInfo=E.new_info(chapter,level)
    gm:InitGameData()
    gm:InitTestBonus()
    E.role_defaults()
    gm:PreloadLevelData(E.mode,chapter or 1,level or 1)
    gm:EnterGameScene()
    E.wait_ready()
    return {resetting=true,seed=seed,chapter=chapter or 1,level=level or 1}
end

return E
