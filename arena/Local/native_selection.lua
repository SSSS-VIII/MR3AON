-- Selection inputs and travel use the client's original complete-map mechanisms.
local E=MR3A
local U=CS.UnityEngine
local flags=CS.System.Reflection.BindingFlags.__CastFrom(52)
local function get(o,k) return o:GetType():GetField(k,flags):GetValue(o) end
local file=U.Application.persistentDataPath..'/arena-control/catalog-native.json'
E.catalog=json.parse(CS.System.IO.File.ReadAllText(file))
assert(E.catalog.mode==6,'Gale catalog required')
local catalog=E.catalog

function E.needs_round_start(map,firstID)
    for _,group in ipairs(map.opening) do
        for _,v in ipairs(group.pool) do if v.startsGame~=false then return false end end
    end
    for _,v in ipairs(map.slots[1].pool) do
        if v.id==firstID then return v.startsGame==false end
    end
    return false
end

function E.ensure_battle_start(ninja)
    local gm=CS.GameManager.Instance
    if not gm._isOnlyGame or not gm.GameInfo.OfflineGame or gm.GameInfo:GetRealCombatType()~=6
        or tostring(gm.CurrContentState)~='WaitGameStart: 0' then return end
    if CS.Util.Enum2Int(get(ninja,'__ninjaPhysicsState'))==0 then return end
    local level=CS.LevelManager.Instance.GameLevelInfo
    if not level then return end
    local map=catalog.maps[tostring(get(level,'_levelBaseInfo')._levelID)]
    local stages=get(level,'_stageList')
    if not map or not stages or stages.Count==0 then return end
    local firstID=get(stages[0],'_stageBaseInfo')._stageID
    if E.needs_round_start(map,firstID) then
        -- Continuation boards can have no start trigger at all. Initialize the
        -- new local round through the client's API, without changing the board.
        gm:StartGameContent()
        E.resetJob.nativeStartForContinuation=firstID
    end
end

function E.validate_selection(s)
    assert(type(s)=='table','Selection required')
    local chapter,level=s.chapter,s.level
    if not chapter then
        for _,entry in ipairs(catalog.levels) do
            if entry.id==level then
                for _,map in ipairs(entry.maps) do if map.id==s.map then chapter=map.chapter;level=map.level end end
            end
        end
        -- Hidden entry-route duplicates remain valid raw IDs for existing API
        -- profiles. Resolve their original route without rewriting any slots.
        if not chapter then
            for _,route in ipairs(catalog.routes) do
                local offset=route.id>=3 and route.id-1 or 0
                for _,entry in ipairs(route.levels) do
                    if entry.id+offset==level then
                        for _,id in ipairs(entry.maps) do
                            if id==s.map then chapter=route.id;level=entry.id;break end
                        end
                    end
                    if chapter then break end
                end
                if chapter then break end
            end
        end
    end
    local allowed=false
    for _,route in ipairs(catalog.routes) do
        if route.id==chapter then
            for _,entry in ipairs(route.levels) do
                if entry.id==level then for _,id in ipairs(entry.maps) do if id==s.map then allowed=true end end end
            end
        end
    end
    assert(allowed,'Map is outside this Gale level pool')
    local map=catalog.maps[tostring(s.map)]
    local count=#map.slots+(#map.loop>0 and 1 or 0)
    local start=s.start or 1
    assert(type(start)=='number' and start%1==0 and start>=1 and start<=count,'Unknown board position')
    local pins={}
    for position,id in pairs(s.pins or {}) do
        position=tonumber(position)
        assert(position and position%1==0 and position>=1 and position<=count,'Unknown pinned position')
        local pool=position<=#map.slots and map.slots[position].pool or map.loop
        if id~=0 then
            local found=false
            for _,v in ipairs(pool) do if v.id==id then found=true end end
            assert(found,'Variant is outside this board pool')
            pins[tostring(position)]=id
        end
    end
    return {chapter=chapter,level=level,absoluteLevel=map.absoluteLevel,map=s.map,start=start,pins=pins}
end

-- Re-capture only when environment.lua has supplied a new baseline function.
if E.nativeRoleWrapper~=E.role_defaults then
    local original=E.role_defaults
    E.nativeRoleWrapper=function()
        original()
        CurAvatar.arena.endlessType=6
        local g=CS.GameManager.Instance.GameInfo
        local absolute=g._levelID+(g._chapterID>=3 and g._chapterID-1 or 0)
        CurAvatar.isSkipEndless=absolute>1
        CurAvatar.SkipLevel=absolute
        if absolute>1 then Lua_GameManager.SetEndlessSkipLevelInfo(absolute) end
    end
    E.role_defaults=E.nativeRoleWrapper
end

function E.native_pin_groups(self,kind,groups,loop,changes)
    local s=E.nativeSelection
    if s and CS.GameManager.Instance.GameInfo:GetRealCombatType()==6 then
        local map=catalog.maps[tostring(s.map)]
        -- Entry boards are shared by different maps. Match every original pool
        -- before pinning so a later level's preload cannot inherit this choice.
        local matches=groups.Count==#map.opening+#map.slots
        for _,entries in ipairs({map.opening,map.slots}) do
            for _,slot in ipairs(entries) do
                if matches then
                    local expected={}
                    for _,v in ipairs(slot.pool) do expected[v.id]=true end
                    local pool=groups[slot.group-1]._stageRandomList
                    if pool.Count==0 then matches=false end
                    for i=0,pool.Count-1 do if not expected[pool[i]._stageID] then matches=false end end
                end
            end
        end
        if matches then
            local function pin_pool(pool,id)
                if not id then return end
                for i=pool.Count-1,0,-1 do if pool[i]._stageID~=id then pool:RemoveAt(i) end end
                assert(pool.Count==1,'Selected variant missing in native pool')
            end
            for _,slot in ipairs(map.slots) do pin_pool(groups[slot.group-1]._stageRandomList,s.pins[tostring(slot.position)]) end
            if loop and #map.loop>0 then pin_pool(loop._stageRandomList,s.pins[tostring(#map.slots+1)]) end
        end
    end
    -- Never remove or reorder a board: all original events and traps stay present.
    return self:GetLoadStageStream(kind,groups,loop,changes)
end
if not E.nativePinHooks then
    local function unused(name)
        local f=typeof(CS.LevelManager):GetField('__Hotfix0_'..name,CS.System.Reflection.BindingFlags.__CastFrom(60))
        assert(f and f:GetValue(nil)==nil,'Existing '..name..' hook must be preserved')
    end
    unused('GetLevelDataID');unused('GetLoadStageStream')
    local util=require('common/util')
    util.hotfix_ex(CS.LevelManager,'GetLevelDataID',function(self,level)
        local s=E.nativeSelection
        if s and CS.GameManager.Instance.GameInfo:GetRealCombatType()==6 and level==s.level and get(self,'_currChapterID')==s.chapter then return s.map end
        return self:GetLevelDataID(level)
    end)
    util.hotfix_ex(CS.LevelManager,'GetLoadStageStream',function(self,kind,groups,loop,changes)
        return E.native_pin_groups(self,kind,groups,loop,changes)
    end)
    E.nativePinHooks=true
end
local function buffs(n)
    local list=CS.GameBuffManager.Instance:GetTargetBuffList(n,true)
    local ids={}
    if list then for i=0,list.Count-1 do
        local b=list[i];local id=b.BuffData.buffID
        ids[tostring(id)]={id=id,fromRole=b.SkillSource==CS.CfgSkillSource.Role}
    end end
    return ids
end
function E.remove_carrier_buffs(n,before,after)
    local removed={}
    for key,value in pairs(after) do
        if not before[key] and value.fromRole then
            CS.GameBuffManager.Instance:RemoveBuff(n,value.id)
            removed[#removed+1]=value.id
        end
    end
    return removed
end
local function native_grounded(n)
    local state=tostring(get(n,'__ninjaPhysicsState'))
    return state=='runOnLine: 1' or state=='runOnGround: 5'
end
local function ground_stage(n)
    return n._GroundCollider and n._GroundCollider.BelongToStageIndex or -1
end
if E.nativeResetWrapper~=E.reset then E.nativeBaseReset=E.reset end

function E.native_select(spec,seed)
    assert(not E.busy,'A battle operation is active')
    local s=E.validate_selection(spec)
    seed=seed or E.seed
    assert(type(seed)=='number' and seed%1==0 and seed>=0 and seed<=2147483647,'Invalid seed')
    E.busy=true
    E.travel={done=false,phase='waiting_for_preload',selection=s}
    local runner=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger))
    runner:StartCoroutine(require('common/util').cs_generator(function()
        local held=false
        local ninja
        local ok,err=pcall(function()
            local deadline=U.Time.realtimeSinceStartup+600
            U.Time.captureFramerate=60;U.Time.timeScale=1
            while CS.LevelManager.Instance.LevelDataLoading do
                assert(U.Time.realtimeSinceStartup<deadline,'Previous preload did not finish')
                coroutine.step()
            end
            E.nativeSelection=s
            E.travel.phase='reset'
            E.busy=false
            E.nativeBaseReset(seed,s.chapter,s.level)
            E.busy=true
            while not E.resetJob.done do assert(U.Time.realtimeSinceStartup<deadline,'Reset timed out');coroutine.step() end
            assert(not E.resetJob.error,E.resetJob.error)
            local level=CS.LevelManager.Instance.GameLevelInfo
            assert(get(level,'_levelBaseInfo')._levelID==s.map,'Selected map did not load')
            local stages=get(level,'_stageList')
            local map=catalog.maps[tostring(s.map)]
            assert(stages.Count==#map.slots,'Full original map is required')
            ninja=CS.NinjaController.Instance.NinjaScript
            local beforeBuffs=buffs(ninja)
            if s.start>1 then
                E.travel.phase='rush'
                local mount=CS.MountController.Instance
                -- Boss/loop blocks extend while running. Use the original
                -- generated StageStartX, never a sum of static block widths.
                mount:RushAtGameStart(true,100000)
                E.travel.rushSpeed=E.set_mount_rush_speed(mount.Mount)
                U.Time.captureFramerate=60;U.Time.timeScale=1
                local mounted=false
                local target
                local targetStage
                while true do
                    assert(U.Time.realtimeSinceStartup<deadline,'Dragon rush timed out')
                    assert(CS.LevelManager.Instance.GameLevelInfo==level,'Left the selected map before arrival')
                    E.travel.currentBoard=ground_stage(ninja)+1
                    if not target then
                        local stage=s.start<=stages.Count and stages[s.start-1] or get(level,'_currLoopStage')
                        if stage and stage.StageStartX>0 and get(stage,'_currBlockIndex')>0 then
                            targetStage=stage;target=stage.StageStartX
                            E.travel.target=target
                            mount.CurrStartRushRemainDis=math.max(1,target-ninja.transform.position.x-40)
                        end
                    end
                    if ninja.IsMountState then mounted=true end
                    if mounted and not ninja.IsMountState and native_grounded(ninja) then
                        assert(target,'Rush ended before the target board was generated')
                        break
                    end
                    coroutine.step()
                end
                E.travel.landedAt=ninja.transform.position.x
                E.travel.phase='approach'
                while ninja.transform.position.x<target or not native_grounded(ninja) or ground_stage(ninja)~=s.start-1 do
                    assert(U.Time.realtimeSinceStartup<deadline,'Target board not reached')
                    assert(ninja.CurrentHp>0,'Died approaching selected board')
                    assert(ground_stage(ninja)<s.start,'No grounded entry within the selected board')
                    coroutine.step()
                end
                E.travel.targetStage=get(targetStage,'_stageBaseInfo')._stageID
                E.travel.phase='clearing_landing_effects'
                CS.NinjaController.Instance:SetStopRun(true,true,0);held=true
                local now=buffs(ninja)
                E.travel.removedBuffs=E.remove_carrier_buffs(ninja,beforeBuffs,now)
                -- Let original timed protection expire. No counter writes or
                -- orphaned delayed callbacks remain after arrival.
                while ninja:IsGodMode() do
                    assert(U.Time.realtimeSinceStartup<deadline,'Landing protection did not expire')
                    coroutine.step()
                end
                CS.NinjaController.Instance:SetStopRun(false,false,0);held=false
                E.travel.godAfter=ninja:IsGodMode()
                assert(native_grounded(ninja),'Selected entrance did not remain grounded')
                assert(ground_stage(ninja)==s.start-1,'Left the selected board during landing')
                assert(ninja.CurrentHp>0,'Died at the selected entrance')
                E.travel.groundStageIndex=ground_stage(ninja)
            end
            E.travel.fullMapStages=stages.Count
            if s.start<=stages.Count then
                E.travel.targetStage=get(stages[s.start-1],'_stageBaseInfo')._stageID
            elseif not E.travel.targetStage then
                local loop=get(level,'_currLoopStage')
                if loop then E.travel.targetStage=get(loop,'_stageBaseInfo')._stageID end
            end
            local wanted=s.pins[tostring(s.start)]
            assert(not wanted or E.travel.targetStage==wanted,'Selected variant did not become active')
            E.travel.phase='ready'
        end)
        if held then CS.NinjaController.Instance:SetStopRun(false,false,0) end
        U.Time.timeScale=0;E.busy=false
        E.travel.done=true
        if not ok then E.travel.error=tostring(err);E.travel.phase='error' end
        E.travel.state=E.state()
    end))
    return {started=true}
end
E.select=E.native_select
E.nativeResetWrapper=function(seed,chapter,level)
    local s=E.nativeSelection
    if s and s.chapter==(chapter or 1) and s.level==(level or 1) then return E.native_select(s,seed) end
    E.nativeSelection=nil
    return E.nativeBaseReset(seed,chapter,level)
end
E.reset=E.nativeResetWrapper
return E
