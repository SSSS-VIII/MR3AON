-- Opt-in ground truth for evaluation/annotation. Never read by the visual policy.
local E=MR3A
local U=CS.UnityEngine
local flags=CS.System.Reflection.BindingFlags.__CastFrom(52)
local function get(o,k) return o:GetType():GetField(k,flags):GetValue(o) end
local lastHurtField=typeof(CS.Ninja):GetField('_lastHurtNinjaEnemy',flags)
local lastHurtIndexField=typeof(CS.Ninja):GetField('lastHurtEnemyIndex',flags)
local enemyInfoField=typeof(CS.EnemyBase):GetField('_enemyInfo',flags)
local file=U.Application.persistentDataPath..'/arena-control/vision-eval.json'
local watch=CS.System.Diagnostics.Stopwatch
local function monotonic() return watch.GetTimestamp()/watch.Frequency end

local function last_hurt_reference(n)
    local enemy=lastHurtField:GetValue(n)
    local out={index=lastHurtIndexField:GetValue(n),present=enemy~=nil,
        scope='Original retained reference; environmental damage can leave an older enemy here'}
    if enemy and enemy.gameObject then
        local info=enemyInfoField:GetValue(enemy)
        out.id=enemy:GetInstanceID();out.name=enemy.name;out.type=enemy:GetType().Name
        out.enemy_type=info and CS.System.Convert.ToInt32(info._enemyType)or nil
        out.active=enemy.gameObject.activeInHierarchy
        out.x=enemy.transform.position.x;out.y=enemy.transform.position.y
    end
    return out
end

-- Capture only on an actual health drop. This is an evaluation witness, never
-- an actor observation; reading one role and one retained enemy avoids a scene
-- scan during live input. The original hurt response may already have run.
function E.vision_hit_geometry(n)
    local cam=U.Camera.main
    local function vector(p)return {x=p.x,y=p.y,z=p.z}end
    local function point(p)
        local q=cam:WorldToViewportPoint(p)
        return {x=q.x*640,y=(1-q.y)*360,z=q.z}
    end
    local function colliders(o,role)
        local result={}
        if not o or not o.gameObject then return result end
        local all=o.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
        for i=0,all.Length-1 do local c=all[i]
            if c.enabled and c.gameObject.activeInHierarchy and
                    ((role and c.name=='Role')or(not role and c.tag=='Enemy')) then
                local bounds=c.bounds
                local row={id=c:GetInstanceID(),name=c.name,type=c:GetType().Name,
                    world_center=vector(bounds.center),world_extents=vector(bounds.extents),
                    plane_quad={},lossy_scale=vector(c.transform.lossyScale)}
                if row.type=='BoxCollider' then
                    row.size=vector(c.size);row.center=vector(c.center)
                    for _,s in ipairs({{-1,-1},{1,-1},{1,1},{-1,1}})do
                        row.plane_quad[#row.plane_quad+1]=point(c.transform:TransformPoint(
                            c.center+U.Vector3(s[1]*c.size.x/2,s[2]*c.size.y/2,0)))
                    end
                else
                    for _,s in ipairs({{-1,-1},{1,-1},{1,1},{-1,1}})do
                        row.plane_quad[#row.plane_quad+1]=point(U.Vector3(
                            bounds.center.x+s[1]*bounds.extents.x,
                            bounds.center.y+s[2]*bounds.extents.y,bounds.center.z))
                    end
                end
                result[#result+1]=row
            end
        end
        return result
    end
    local enemy=lastHurtField:GetValue(n)
    local state
    if enemy then
        local tp=enemy:GetType()
        while tp do
            local f=tp:GetField('_enemyState',flags)
            if f then state=tostring(f:GetValue(enemy));break end
            tp=tp.BaseType
        end
    end
    return {role=colliders(n,true),enemy=colliders(enemy,false),enemy_state=state,
        role_root=vector(n.transform.position),camera=vector(cam.transform.position),
        scope='Post-health-drop original geometry; hurt response may already have changed the role'}
end

function E.vision_interactions()
    local function task(t)
        if not t then return nil end
        return {goal_type=tostring(get(t,'_goalType')),target=get(t,'_targetTypeEnumValue'),
            goal=get(t,'_goalValue'),current=get(t,'_currGoalValue'),description=get(t,'_description')}
    end
    local n=CS.NinjaController.Instance.NinjaScript
    -- Raw original flags; StuckByBlock is also true during ordinary running,
    -- so it is not evidence of a collision without the position/terrain trace.
    local out={stuck_by_block_flag=n.StuckByBlock,dragged_underground=n.BeDragToUnderground}
    local ground=n._GroundCollider
    if ground then
        local a,b=ground.PointStart,ground.PointEnd
        local offset=n.SlopeOffset
        out.support={id=ground:GetInstanceID(),is_line=ground.IsLine,is_ground=ground.IsGround,
            start={x=a.x,y=a.y},finish={x=b.x,y=b.y},slope_state=tostring(n.SlopeState),
            slope_speed_ratio=n.SlopeSpeedRatio,slope_offset={x=offset.x,y=offset.y,z=offset.z}}
    end
    local enemy=CS.EnemyManager.Instance.KillNinjaEnemy
    if enemy and enemy.gameObject then
        out.kill_enemy={id=enemy:GetInstanceID(),name=enemy.name,type=enemy:GetType().Name,
            active=enemy.gameObject.activeInHierarchy,x=enemy.transform.position.x,y=enemy.transform.position.y,
            killed_ninja=typeof(CS.EnemyBase):GetField('_killedNinja',flags):GetValue(enemy)}
    end
    local manager=E.visionTaskManager
    if manager then
        local special=manager.CurrSpecialTask
        if special then E.visionLastSpecialTask=special end
        out.special=task(special);out.timely=task(manager.CurrTimelyTask)
        -- Retain only a read-only reference: an immediately hidden completed
        -- task can otherwise be sampled at 79/80, then disappear before 80.
        if not special then out.last_special=task(E.visionLastSpecialTask) end
    end
    return out
end

function E.vision_evaluation()
    local n=CS.NinjaController.Instance.NinjaScript
    local level=CS.LevelManager.Instance.GameLevelInfo
    local ground=n._GroundCollider
    local index=ground and ground.BelongToStageIndex or -1
    local stages=get(level,'_stageList')
    local id=index>=0 and index<stages.Count and get(stages[index],'_stageBaseInfo')._stageID or 0
    local result={tick=CS.GameManager.Instance.GameInfo._totalFrameCount,frame=U.Time.frameCount,
        time=U.Time.realtimeSinceStartup,health=n.CurrentHp,maxHealth=n.MaxHp,
        physics=tostring(get(n,'__ninjaPhysicsState')),stageIndex=index,stageID=id,stageCount=stages.Count,
        x=n.transform.position.x,y=n.transform.position.y,god=n:IsGodMode(),
        scale=U.Time.timeScale,map=get(level,'_levelBaseInfo')._levelID,
        damage=E.visionEvalDamage or 0,minHealth=E.visionEvalMinHealth or n.CurrentHp,
        keys=E.visionEvalKeys or {},lastKeyTime=E.visionEvalLastKeyTime,
        keyReceipts=E.visionEvalReceipts or {},monotonic=monotonic(),
        last_health_drop=E.visionEvalLastHealthDrop}
    local ok,value=pcall(E.vision_interactions)
    if ok then result.interactions=value else result.interactions_error=tostring(value) end
    return result
end

function E.sample_vision_health()
    local hp=CS.NinjaController.Instance.NinjaScript.CurrentHp
    local before=E.visionEvalPreviousHealth or hp
    E.visionEvalDamage=(E.visionEvalDamage or 0)+math.max(0,before-hp)
    E.visionEvalMinHealth=math.min(E.visionEvalMinHealth or hp,hp)
    E.visionEvalPreviousHealth=hp
    if hp<before then
        local n=CS.NinjaController.Instance.NinjaScript
        local event={monotonic=monotonic(),frame=U.Time.frameCount,before=before,after=hp,
            physics=tostring(get(n,'__ninjaPhysicsState'))}
        local ok,value=pcall(last_hurt_reference,n)
        if ok then event.last_hurt_reference=value else event.reference_error=tostring(value)end
        local geometry_ok,geometry=pcall(E.vision_hit_geometry,n)
        if geometry_ok then event.geometry=geometry else event.geometry_error=tostring(geometry)end
        E.visionEvalLastHealthDrop=event
    end
    for _,pair in ipairs({{'jump',U.KeyCode.K},{'down',U.KeyCode.S}}) do
        if U.Input.GetKeyDown(pair[2]) then
            E.visionEvalKeys[pair[1]]=(E.visionEvalKeys[pair[1]] or 0)+1
            E.visionEvalLastKeyTime=U.Time.realtimeSinceStartup
            E.visionEvalReceipts[pair[1]]={count=E.visionEvalKeys[pair[1]],time=monotonic()}
        end
    end
end

function E.start_vision_evaluation()
    E.visionEvalEnabled=true
    E.visionTaskManager=U.Object.FindObjectOfType(typeof(CS.GameTaskManager))
    E.visionLastSpecialTask=nil
    local hp=CS.NinjaController.Instance.NinjaScript.CurrentHp
    E.visionEvalPreviousHealth=hp;E.visionEvalMinHealth=hp;E.visionEvalDamage=0
    E.visionEvalLastHealthDrop=nil
    E.visionEvalKeys={jump=0,down=0}
    E.visionEvalReceipts={}
    if E.visionEvalRunner then
        E.visionEvalRunner:StopAllCoroutines()
        U.Object.Destroy(E.visionEvalRunner.gameObject)
        E.visionEvalRunner=nil
    end
    local host=U.GameObject('MR3A_VisionEvaluation')
    U.Object.DontDestroyOnLoad(host)
    local runner=host:AddComponent(typeof(U.EventSystems.EventTrigger))
    E.visionEvalRunner=runner
    runner:StartCoroutine(require('common/util').cs_generator(function()
        local last=-1
        while true do
            if E.visionEvalEnabled then pcall(E.sample_vision_health) end
            if E.visionEvalEnabled and U.Time.realtimeSinceStartup-last>=.1 then
                last=U.Time.realtimeSinceStartup
                local ok,result=pcall(E.vision_evaluation)
                if ok then CS.System.IO.File.WriteAllText(file,json.stringify(result))
                else E.visionEvalError=tostring(result) end
            end
            coroutine.step()
        end
    end))
    return true
end
return E
