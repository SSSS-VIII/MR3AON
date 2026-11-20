-- Read-only internal controller input. Separate from pixel observations and
-- from the stopped checkpoint search; no gameplay field or callback is changed.
local E,U=MR3A,CS.UnityEngine
local flags=CS.System.Reflection.BindingFlags.__CastFrom(52)
local cache={}
local taskInstanceField
do
    -- Read the already existing singleton backing field. Calling Instance
    -- could create a manager when observing an uninitialized scene.
    local wanted=typeof(CS.GameTaskManager);local tp=wanted
    local staticFlags=CS.System.Reflection.BindingFlags.__CastFrom(56)
    while tp and not taskInstanceField do
        local fs=tp:GetFields(staticFlags)
        for i=0,fs.Length-1 do
            if fs[i].IsStatic and (fs[i].FieldType.FullName==wanted.FullName or
                    fs[i].Name=='uniqueInstance' and fs[i].FieldType:IsAssignableFrom(wanted)) then
                taskInstanceField=fs[i];break
            end
        end
        tp=tp.BaseType
    end
end
local function vector(v)return {x=v.x,y=v.y,z=v.z}end
local function fields(obj)
    local tp=obj:GetType();local key=tp.FullName
    if cache[key]then return cache[key]end
    local list,seen={},{}
    while tp and tp.FullName~='UnityEngine.MonoBehaviour' do
        local fs=tp:GetFields(flags)
        for i=0,fs.Length-1 do local f=fs[i]
            if not f.IsStatic and not seen[f.Name]and not string.find(f.Name,'Hotfix',1,true)then
                list[#list+1]=f;seen[f.Name]=true
            end
        end
        tp=tp.BaseType
    end
    cache[key]=list;return list
end
local function field(obj,name)
    if not obj then return nil end
    for _,f in ipairs(fields(obj))do if f.Name==name then return f:GetValue(obj)end end
end
local function values(obj)
    local out={}
    if not obj then return out end
    for _,f in ipairs(fields(obj))do
        local tp=f.FieldType;local name=tp.FullName
        if tp.IsPrimitive or tp.IsEnum or name=='UnityEngine.Vector3'or name=='UnityEngine.Vector2'
                or name=='PointV3'or name=='PointV2' then
            local v=f:GetValue(obj)
            if v~=nil then
                if tp.IsEnum then out[f.Name]=tostring(v)
                elseif name=='UnityEngine.Vector3'or name=='PointV3' then out[f.Name]=vector(v)
                elseif name=='UnityEngine.Vector2'or name=='PointV2' then out[f.Name]={x=v.x,y=v.y}
                else out[f.Name]=v end
            end
        end
    end
    return out
end
local function valueProjection(obj)
    local data=values(obj);local omitted={}
    if obj then for _,f in ipairs(fields(obj))do
        if data[f.Name]==nil and f:GetValue(obj)~=nil then
            omitted[#omitted+1]={name=f.Name,type=f.FieldType.FullName}
        end
    end end
    return data,{complete=#omitted==0,omitted=omitted}
end
local function existingSingleton(wanted)
    -- Read the backing field only. Instance getters may create a manager.
    local tp=wanted;local staticFlags=CS.System.Reflection.BindingFlags.__CastFrom(56)
    while tp do local fs=tp:GetFields(staticFlags)
        for i=0,fs.Length-1 do local f=fs[i]
            if f.IsStatic and f.Name=='uniqueInstance'and f.FieldType:IsAssignableFrom(wanted)then
                return f:GetValue(nil)
            end
        end
        tp=tp.BaseType
    end
end
local function originalCollectEffects()
    -- Follow the existing dispatcher references; never create a singleton.
    local backing=typeof(CS.GameEventManager):GetField('instance',CS.System.Reflection.BindingFlags.__CastFrom(56))
    local manager=backing and backing:GetValue(nil)
    local out={present=manager~=nil,native_dispatch=true,unknown_hooks={}}
    if not manager then return out end
    local buffs=field(manager,'gameBuffManager');local passives=field(manager,'ninjaPassiveSkillManager')
    out.buff_manager_present=buffs~=nil;out.passive_manager_present=passives~=nil
    if buffs then
        out.buff_count=field(buffs,'buffCount')
        for key,name in pairs({buff_targets='buffTargetList',buff_definitions='buffDataDic',
                waiting_assist_buffs='waitAddAssistSkillBuffList',waiting_collision_buffs='waitSyncPlayerCollisionBuffDatas'})do
            local list=field(buffs,name);out[key]=list and list.Count or -1
        end
        out.buff_lua_present=field(buffs,'buffTable')~=nil
    end
    if passives then
        local list=field(passives,'passiveSkillList');out.passive_count=list and list.Count or -1
        out.passive_lua_present=false
        for _,name in ipairs({'_passiveSkillLuaTable','_passiveSkillConditionTable','_passiveSkillReduceTable'})do
            if field(passives,name)~=nil then out.passive_lua_present=true end
        end
    end
    local staticFlags=CS.System.Reflection.BindingFlags.__CastFrom(56)
    local mt=typeof(CS.GameMessageManager);local backing=mt:GetField('instance',staticFlags)
    local messages=backing and backing:GetValue(nil);out.message_manager_present=messages~=nil
    if messages then
        local mapping=field(messages,'triggerTypeStr');local subscribers=field(messages,'_messageDelegate')
        -- Original CallTriggerMessageDelegate uses this literal prefix when
        -- the int->string cache has no entry. Reading it must not fill it.
        local key='CfgTriggerType_11'
        if mapping and mapping:ContainsKey(11)then key=mapping[11]end
        out.collect_event_name=key;out.collect_listener_count=-1
        if mapping and subscribers and key=='CfgTriggerType_11'then
            out.collect_listener_count=subscribers:ContainsKey(key)and subscribers[key].Count or 0
        end
    end
    for _,entry in ipairs({{typeof(CS.ItemCoin),'PerformPickupActions',0},
            {typeof(CS.ItemBase),'CollectItem',0},{typeof(CS.GameEventManager),'TriggerCondition',0},
            {typeof(CS.GameEventManager),'DispatchGlobalTriggerEvent',0},
            {typeof(CS.GameBuffManager),'TriggerTarBuffCondition',0},
            {typeof(CS.NinjaPassiveSkillManager),'TriggerCondition',0},
            {typeof(CS.NinjaPassiveSkillManager),'TriggerCondition',1},
            {mt,'CallTriggerMessageDelegate',0},{mt,'CallMessageDelegate',0}})do
        local name='__Hotfix'..entry[3]..'_'..entry[2];local hook=entry[1]:GetField(name,staticFlags)
        if not hook or hook:GetValue(nil)~=nil then
            out.native_dispatch=false;out.unknown_hooks[#out.unknown_hooks+1]=entry[1].Name..'.'..name
        end
    end
    return out
end
local function retiredClearScreen(obj,data)
    local staticFlags=CS.System.Reflection.BindingFlags.__CastFrom(56)
    if obj:GetType().FullName~='SkillClearScreen'or data._bIsSkillEnd~=true or data['<isActive>k__BackingField']~=false then return nil end
    local ok,root=pcall(function()return obj.gameObject end)
    if not ok or not root then return {native_object_unavailable=true}end
    local out={active_self=root.activeSelf,active_hierarchy=root.activeInHierarchy,
        native_cleanup=true,unknown_hooks={},callbacks_clear=true,coroutines_absent=false,component_types={},active_colliders=0,coroutines={}}
    local components=obj:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
    for i=0,components.Length-1 do out.component_types[#out.component_types+1]=components[i]and components[i]:GetType().FullName or 'missing_component'end
    local cs=obj:GetComponentsInChildren(typeof(U.Collider),true)
    for i=0,cs.Length-1 do if cs[i].enabled and cs[i].gameObject.activeInHierarchy then out.active_colliders=out.active_colliders+1 end end
    for _,name in ipairs({'conditionActionEvent','normalActionEvent','collisionActionEvent',
            'collisionExitActionEvent','btAnimatorEvent','conditionParamActionEvent','syncComponent'})do
        if field(obj,name)~=nil then out.callbacks_clear=false end
    end
    local graphs=field(obj,'allGraphOwners');if graphs and graphs.Count>0 then out.callbacks_clear=false end
    for _,entry in ipairs({{typeof(CS.Ninja3BaseObject),'get_isActive'},
            {typeof(CS.Ninja3BaseObject),'MyUpdate'},{typeof(CS.Ninja3BaseObject),'OnDisable'},
            {typeof(CS.NinjaSkillManager),'CleanActiveSkill'},{typeof(CS.NinjaSkillManager),'MyFixedUpdate'},
            {typeof(CS.NinjaSkill),'MyFixedUpdate'},{typeof(CS.NinjaSkill),'MyUpdate'},
            {typeof(CS.NinjaSkill),'OnDisable'},{typeof(CS.NinjaSkill),'SkillEnd'},
            {typeof(CS.NinjaSkill),'DestroySelf'},{typeof(CS.NinjaSkill),'Recycle'},
            {typeof(CS.SkillClearScreen),'MyFixedUpdate'},{typeof(CS.SkillClearScreen),'OnDisable'},
            {typeof(CS.SkillClearScreen),'ClearScreenSkillEnd'},{typeof(CS.SkillClearScreen),'SkillEnd'},
            {typeof(CS.GameDamageManager),'AddNinjaSkillDamageInfo'},
            {typeof(CS.GameDamageManager),'NinjaSkillDamageFixedUpdate'}})do
        local hook=entry[1]:GetField('__Hotfix0_'..entry[2],staticFlags)
        if not hook or hook:GetValue(nil)~=nil then out.native_cleanup=false;out.unknown_hooks[#out.unknown_hooks+1]=entry[1].Name..'.'..entry[2]end
    end
    local controllers=U.Object.FindObjectsOfType(typeof(CS.GameController),true)
    if controllers.Length~=1 then return out end
    local logic=field(controllers[0],'gameLogicManager');local executor=field(logic,'gameCoroutineManager')
    local damage=field(logic,'gameDamagerManager');out.damage_queues={};out.damage_queues_empty=damage~=nil
    for _,name in ipairs({'skillDamageList','enemyDamageList','itemDamageList','mountDamageList'})do
        local list=field(damage,name);out.damage_queues[name]=list and list.Count or -1
        if not list or list.Count~=0 then out.damage_queues_empty=false end
    end
    local list=field(executor,'list');if not list or list.Count>4096 then return out end
    out.coroutines_absent=true
    for _,name in ipairs({'_startCoro','_initCoro','_hideCoro','waitSkillEndCoroutine'})do
        local id=field(obj,name);local row={name=name,id=id,present=false};out.coroutines[#out.coroutines+1]=row
        if id==nil then out.coroutines_absent=false
        elseif tostring(id)~='0'then for i=0,list.Count-1 do
            if tostring(field(list[i],'ID'))==tostring(id)then row.present=true;out.coroutines_absent=false end
        end end
    end
    return out
end
local function originalSkills()
    local manager=existingSingleton(typeof(CS.NinjaSkillManager))
    local out={present=manager~=nil,active={},bullets={}}
    if not manager then return out end
    local function entries(list,count)
        local result={};assert(list and count>=0 and count<=list.Count,'Original skill list count mismatch')
        for i=0,count-1 do local obj=list[i];assert(obj,'Nil original active skill')
            local data=values(obj)
            result[#result+1]={index=i,type=obj:GetType().FullName,fields=data,retired_clear_screen=retiredClearScreen(obj,data)}
        end
        return result
    end
    out.active=entries(field(manager,'activeSkillList'),field(manager,'activeSkillCount'))
    out.bullets=entries(field(manager,'activeSkillBulletList'),field(manager,'activeSkillBulletCount'))
    local move=field(manager,'<CurrMoveSkill>k__BackingField')
    if move then out.move_skill=move:GetType().FullName end
    return out
end
local function logicCoroutines()
    -- The client's original Lua_HotfixManager replaces Brambles.ToNextAction
    -- with coroutine.myStart/myWait, not DelayCallFunctionController. Read
    -- the existing executor; no enumerator is advanced or initialized.
    local out={by_id={}};local controllers=U.Object.FindObjectsOfType(typeof(CS.GameController),true)
    out.controllers=controllers.Length
    if controllers.Length~=1 then return out end
    local manager=field(controllers[0],'gameLogicManager')
    local executor=field(manager,'gameCoroutineManager');local list=field(executor,'list')
    out.processing=field(executor,'isNeedProcess');out.truncated=list and list.Count>4096 or false
    if list then for i=0,math.min(list.Count-1,4095)do local co=list[i]
        local data=values(co);local key=tostring(field(co,'ID'));local stack=field(co,'stack')
        out.by_id[key]=out.by_id[key]or{}
        out.by_id[key][#out.by_id[key]+1]={type=co:GetType().FullName,fields=data,stack_count=stack and stack.Count or nil}
    end end
    return out
end
local function rigidElectric(owner)
    -- RotateElectricBall rotates local Z after translating in world X.
    -- Export the actual hierarchy/axes rather than assuming its generated
    -- spheres still follow their deliberately disabled hover clocks.
    local t=owner.transform;local parent=t.parent
    local m=parent and parent.localToWorldMatrix or U.Matrix4x4.identity
    local error=0
    for a=0,2 do for b=0,2 do error=error+math.abs(m['m'..a..b]-(a==b and 1 or 0))end end
    local rotation=t.localEulerAngles
    local out={parent_axes_identity=error<0.00001,local_rotation=vector(rotation),balls={},colliders={}}
    for _,f in ipairs(fields(owner))do
        if f.FieldType.FullName=='EnemySuspendSpecial'then local ball=f:GetValue(owner)
            if ball then out.balls[#out.balls+1]={id=ball:GetInstanceID(),direct_parent=ball.transform.parent==t,
                movement_enabled=field(ball,'_movementEnable'),alive=ball.isActive and ball.gameObject.activeInHierarchy and
                    not field(ball,'_dead')and not field(ball,'_isRecycled')}end
        end
    end
    local electric=field(owner,'_electric')
    out.direct_electric=electric~=nil and electric.parent==t
    if electric then local cs=electric:GetComponents(typeof(U.Collider))
        for i=0,cs.Length-1 do out.colliders[#out.colliders+1]=cs[i]:GetInstanceID()end
    end
    return out
end
local function actionData(obj,depth,budget)
    -- Traverse only authored action data, never its owner/manager graph.
    -- Unknown or truncated data stays explicit for the planning layer.
    budget=budget or {remaining=2048}
    budget.remaining=budget.remaining-1
    if budget.remaining<0 then return {truncated=true}end
    if obj==nil then return nil end
    if type(obj)=='string' and #obj>512 then return {type='System.String',truncated=true,length=#obj}end
    if type(obj)~='userdata'then return obj end
    local tp=obj:GetType();local name=tp.FullName
    if tp.IsEnum then return tostring(obj)end
    if name=='UnityEngine.Vector3'then return vector(obj)end
    if name=='UnityEngine.Vector2'then return {x=obj.x,y=obj.y}end
    if depth<=0 then return {type=name,truncated=true}end
    if typeof(CS.System.Collections.IList):IsAssignableFrom(tp)then
        local count=tp.IsArray and obj.Length or obj.Count;local out={type=name,items={}}
        out.truncated=count>128
        for i=0,math.min(count-1,127)do out.items[#out.items+1]=actionData(obj[i],depth-1,budget)end
        return out
    end
    if string.sub(name,1,19)~='Ninja3.LevelAction.' and name~='ItemEventDataStruct'
            and name~='PointV3' and name~='PointV2' then
        return {type=name,unmapped_reference=true}
    end
    local out={type=name,fields={}}
    for _,f in ipairs(fields(obj))do out.fields[f.Name]=actionData(f:GetValue(obj),depth-1,budget)end
    return out
end
local function callbacks(obj)
    local out={}
    for _,name in ipairs({'Start','Interrupt','End','Dispose','Complete','Event'})do
        local d=field(obj,name)
        if d then local inv=d:GetInvocationList();out[name]={}
            for i=0,math.min(inv.Length-1,15)do local method=inv[i].Method
                out[name][#out[name]+1]={method=method.Name,declaring_type=method.DeclaringType.FullName,
                    target_type=inv[i].Target and inv[i].Target:GetType().FullName or nil}
            end
            if inv.Length>16 then out.truncated=true end
        end
    end
    return out
end
local function spineState(animation)
    -- Read backing fields only. Skeleton/AnimationState property getters may
    -- initialize a disabled component; observing must never do that.
    if not animation then return nil end
    local skeleton,state=field(animation,'skeleton'),field(animation,'state')
    local out={initialized=skeleton~=nil,time_scale=field(animation,'timeScale'),tracks={},bones={}}
    if not skeleton then return out end
    out.fields=values(skeleton)
    out.state_fields=values(state)
    out.state_callbacks=callbacks(state)
    local skin=field(skeleton,'skin');out.skin=skin and field(skin,'name')or nil
    local t=animation.transform
    out.origin=vector(t:TransformPoint(U.Vector3.zero))
    out.axis_x=vector(t:TransformVector(U.Vector3.right))
    out.axis_y=vector(t:TransformVector(U.Vector3.up))
    local asset=field(animation,'skeletonDataAsset');local text=asset and field(asset,'skeletonJSON')
    out.asset_name=text and text.name or nil
    out.asset_fields=values(asset)
    local tracks=state and field(state,'tracks');local items=tracks and field(tracks,'Items')
    local count=tracks and field(tracks,'Count')or 0
    local function entryData(entry,depth)
        if not entry then return nil end
        local r=values(entry);r.callbacks=callbacks(entry);local anim=field(entry,'animation')
        r.animation=anim and field(anim,'name')or nil;r.has_next=field(entry,'next')~=nil
        if depth>0 then r.mixing_from=entryData(field(entry,'mixingFrom'),depth-1)end
        return r
    end
    out.tracks_truncated=count>4
    if items then for i=0,math.min(count-1,3)do
        out.tracks[#out.tracks+1]={index=i,entry=entryData(items[i],3)}
    end end
    local bones=field(skeleton,'bones');items=bones and field(bones,'Items');count=bones and field(bones,'Count')or 0
    out.bones_truncated=count>128
    if items then for i=0,math.min(count-1,127)do local bone=items[i];local data=field(bone,'data')
        out.bones[#out.bones+1]={name=data and field(data,'name'),x=field(bone,'worldX'),y=field(bone,'worldY'),
            a=field(bone,'a'),b=field(bone,'b'),c=field(bone,'c'),d=field(bone,'d')}
    end end
    return out
end
local function shape(c)
    local tp=c:GetType().Name
    local out={id=c:GetInstanceID(),name=c.name,type=tp,enabled=c.enabled,
        active=c.gameObject.activeInHierarchy,parent_active=c.transform.parent and c.transform.parent.gameObject.activeInHierarchy or false,
        tag=c.tag,trigger=c.isTrigger,
        position=vector(c.transform.position),scale=vector(c.transform.lossyScale),
        rotation_z=c.transform.eulerAngles.z}
    local follower=c.gameObject:GetComponent(typeof(CS.Spine.Unity.SkeletonUtilityBone))
    if follower then
        out.spine_follow={bone_name=field(follower,'boneName'),fields=values(follower),full_scale_chain=false,chain={}}
        local t=c.transform
        for depth=1,32 do
            if t.gameObject:GetComponent(typeof(CS.Spine.Unity.SkeletonAnimation))then out.spine_follow.full_scale_chain=true;break end
            local f=t.gameObject:GetComponent(typeof(CS.Spine.Unity.SkeletonUtilityBone))
            if f then
                local v=values(f);out.spine_follow.chain[#out.spine_follow.chain+1]={bone_name=field(f,'boneName'),fields=v}
                if tostring(v.mode)~='Follow: 0' or not v.position or not v.rotation or not v.scale or
                    v.overrideAlpha~=1 or v.incompatibleTransformMode then break end
            else
                local v=t.localPosition;local q=t.localRotation;local scale=t.localScale
                if v.magnitude>0.00001 or math.abs(q.x)+math.abs(q.y)+math.abs(q.z)+math.abs(q.w-1)>0.00001 or
                    (scale-U.Vector3.one).magnitude>0.00001 then break end
            end
            t=t.parent;if not t then break end
        end
    end
    local b=c.bounds;out.center=vector(b.center);out.extents=vector(b.extents)
    if tp=='BoxCollider'then
        out.local_center=vector(c.center);out.size=vector(c.size);out.quad={}
        local lo,hi=U.Vector3(1e9,1e9,1e9),U.Vector3(-1e9,-1e9,-1e9)
        for _,sign in ipairs({{-1,-1},{1,-1},{1,1},{-1,1}})do
            local p=c.transform:TransformPoint(c.center+U.Vector3(sign[1]*c.size.x/2,sign[2]*c.size.y/2,0))
            out.quad[#out.quad+1]=vector(p)
            lo=U.Vector3.Min(lo,p);hi=U.Vector3.Max(hi,p)
        end
        local matrix=c.transform.localToWorldMatrix
        out.depth_tilt=math.abs(matrix.m02)+math.abs(matrix.m12)>0.00001
        if out.depth_tilt then
            out.quad=nil
            for _,x in ipairs({-1,1})do for _,y in ipairs({-1,1})do for _,z in ipairs({-1,1})do
                local p=c.transform:TransformPoint(c.center+U.Vector3(x*c.size.x/2,y*c.size.y/2,z*c.size.z/2))
                lo=U.Vector3.Min(lo,p);hi=U.Vector3.Max(hi,p)
            end end end
        end
        out.center=vector(c.transform:TransformPoint(c.center))
        out.extents=vector((hi-lo)/2)
        if not out.depth_tilt then out.extents.z=math.abs(c.size.z*c.transform.lossyScale.z/2)end
    elseif tp=='SphereCollider'or tp=='CapsuleCollider'then
        out.local_center=vector(c.center);out.center=vector(c.transform:TransformPoint(c.center))
        out.radius=c.radius
        if tp=='CapsuleCollider'then out.height=c.height;out.direction=c.direction end
        if tp=='SphereCollider'then
            local s=c.transform.lossyScale;local r=c.radius*math.max(math.abs(s.x),math.abs(s.y),math.abs(s.z))
            out.extents={x=r,y=r,z=r}
        end
    end
    local attack=c.gameObject:GetComponent(typeof(CS.EnemyAttackModule))
    local callback=c.gameObject:GetComponent(typeof(CS.EnemyBaseCollider))
    local bramble=c.gameObject:GetComponent(typeof(CS.EnemyBrambleCollider))
    if bramble then out.native_movement_callback='bramble_contact';out.movement_owner=bramble:GetInstanceID()end
    local owner=attack and field(attack,'_belongToEnemy')or callback and field(callback,'_enemy')
    out.damage_kind=attack and 'attack_module'or callback and 'enemy_callback'or c.tag=='Enemy'and 'enemy_tag'or nil
    if owner then out.damage_owner=owner:GetInstanceID()end
    return out
end
local function ghostGeometry(obj)
    local root=obj.transform;local body=root:GetComponent(typeof(U.Rigidbody))
    local out={type=obj:GetType().Name,native_geometry=true,unknown_hooks={},callbacks_clear=true,
        animated_tree=obj:GetComponentsInChildren(typeof(U.Animator),true).Length>0 or
            obj:GetComponentsInChildren(typeof(U.Animation),true).Length>0,
        root_axes={x=vector(root:TransformVector(U.Vector3.right)),y=vector(root:TransformVector(U.Vector3.up)),z=vector(root:TransformVector(U.Vector3.forward))},
        root_physics=body and {kinematic=body.isKinematic,gravity=body.useGravity}or nil,
        nodes={},colliders={},component_types={}}
    for _,name in ipairs({'conditionActionEvent','normalActionEvent','collisionActionEvent',
            'collisionExitActionEvent','btAnimatorEvent','conditionParamActionEvent','syncComponent'})do
        if field(obj,name)~=nil then out.callbacks_clear=false end
    end
    local graphs=field(obj,'allGraphOwners');if graphs and graphs.Count>0 then out.callbacks_clear=false end
    local staticFlags=CS.System.Reflection.BindingFlags.__CastFrom(56)
    for _,entry in ipairs({{typeof(CS.EnemyGhostFire),'ResetEnemyInfo'},
            {typeof(CS.EnemyGhostFire),'FixedUpdateMovement'},{typeof(CS.EnemyGhostFire),'AlphaUpdate'},
            {typeof(CS.EnemyGhostFire),'ProcessOnTriggerEnter'},
            {typeof(CS.EnemyCurve),'SetRenderType'},{typeof(CS.EnemyCurve),'ResetEnemyInfo'},
            {typeof(CS.EnemyCurve),'FixedUpdateMovement'},{typeof(CS.EnemyCurve),'StateUpdate'},
            {typeof(CS.EnemyCurve),'UpdateCureMove'},{typeof(CS.EnemyCurve),'PlayFixedAnimation'},
            {typeof(CS.EnemyBase),'SetRenderType'},{typeof(CS.EnemyBase),'ResetEnemyInfo'},
            {typeof(CS.EnemyBase),'FixedUpdateMovement'},
            {typeof(CS.uTools.uTweener),'Sample'},{typeof(CS.uTools.uTweener),'FixedUpdate'},
            {typeof(CS.uTools.uTweener),'Update'},{typeof(CS.uTools.uTweener),'MyFixedUpdate'},
            {typeof(CS.uTools.uTweener),'ResetToBeginning'},{typeof(CS.uTools.uTweenSprite),'ValueUpdate'},
            {typeof(CS.uTools.uTweenValue),'OnUpdate'},{typeof(CS.uTools.uTweenValue),'set_value'},
            {typeof(CS.uTools.uTweenScale),'OnUpdate'},
            {typeof(CS.uTools.uTweenScale),'set_value'}})do
        local hook=entry[1]:GetField('__Hotfix0_'..entry[2],staticFlags)
        if not hook or hook:GetValue(nil)~=nil then out.native_geometry=false;out.unknown_hooks[#out.unknown_hooks+1]=entry[1].Name..'.'..entry[2]end
    end
    local scripts=obj:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
    for i=0,scripts.Length-1 do out.component_types[#out.component_types+1]=scripts[i]and scripts[i]:GetType().FullName or 'missing_component'end
    local known={}
    local function node(t)
        local id=t:GetInstanceID();if known[id]then return known[id]end
        local rb=t:GetComponent(typeof(U.Rigidbody))
        local q=t.localRotation
        local row={position=vector(t.localPosition),scale=vector(t.localScale),rotation={x=q.x,y=q.y,z=q.z,w=q.w},transform_type=t:GetType().Name,scripts={},scales={},tweens={},
            physics=rb and {kinematic=rb.isKinematic,gravity=rb.useGravity}or nil}
        local components=t:GetComponents(typeof(U.MonoBehaviour))
        for i=0,components.Length-1 do local v=components[i];local kind=v and v:GetType().FullName or 'missing_component'
            row.scripts[#row.scripts+1]=kind
            if kind=='uTools.uTweenScale'or kind=='uTools.uTweenSprite'then
                local tween={type=kind,fields=values(v),curve={},callbacks_clear=true};local curve=field(v,'animationCurve')
                if curve then local keys=curve.keys;tween.curve_truncated=keys.Length>128
                    for k=0,math.min(keys.Length-1,127)do local q=keys[k]
                        tween.curve[#tween.curve+1]={time=q.time,value=q.value,in_tangent=q.inTangent,out_tangent=q.outTangent,weighted_mode=tostring(q.weightedMode)}
                    end
                end
                local finished=field(v,'onFinished')
                if finished then
                    local p=field(finished,'m_PersistentCalls');local calls=p and field(p,'m_Calls')
                    local inv=field(finished,'m_Calls');local a=inv and field(inv,'m_RuntimeCalls');local b=inv and field(inv,'m_PersistentCalls')
                    if not calls or calls.Count>0 or not a or a.Count>0 or not b or b.Count>0 then tween.callbacks_clear=false end
                end
                local receiver=field(v,'eventReceiver');local message=field(v,'callWhenFinished')
                if receiver~=nil or message~=nil and tostring(message)~=''then tween.callbacks_clear=false end
                row.tweens[#row.tweens+1]=tween
                if kind=='uTools.uTweenScale'then row.scales[#row.scales+1]=tween end
            end
        end
        out.nodes[#out.nodes+1]=row;known[id]=#out.nodes;return known[id]
    end
    local cs=obj:GetComponentsInChildren(typeof(U.Collider),true)
    for i=0,cs.Length-1 do local c=cs[i];local info=shape(c)
        if info.damage_kind then
            local row={type=c:GetType().Name,enabled=c.enabled,trigger=c.isTrigger,damage_kind=info.damage_kind,
                owner_bound=info.damage_owner==obj:GetInstanceID(),chain={},complete=false}
            if row.type=='SphereCollider'then row.center=vector(c.center);row.radius=c.radius end
            local t=c.transform
            for depth=1,32 do
                if t==root then row.complete=true;break end
                if not t then break end
                row.chain[#row.chain+1]=node(t);t=t.parent
            end
            out.colliders[#out.colliders+1]=row
        end
    end
    return out
end
local function brambleTemplate(owner,render,context)
    -- ReplenishBlock clones this inactive original block. Its seven thorns
    -- are serialized collision geometry; GetGround(2) supplies the decoration.
    -- Read local vertices, including inactive colliders with empty bounds.
    local prefab=field(owner,'_brambleBlockPrefab');local parent=field(owner,'brambleParent')
    if not prefab or not parent or not render then return nil end
    local t=prefab.transform;local p=parent.transform;local list=field(prefab,'thornList')
    local function scripts(node)
        local result={};local cs=node:GetComponents(typeof(U.Component))
        for i=0,cs.Length-1 do result[#result+1]=cs[i]and cs[i]:GetType().FullName or 'missing_component'end
        return result
    end
    local out={id=prefab:GetInstanceID(),active=prefab.gameObject.activeInHierarchy,root_scripts=scripts(t),
        axis_x=vector(owner.transform:TransformVector(U.Vector3.right)),axis_z=vector(owner.transform:TransformVector(U.Vector3.forward)),
        parent={direct_render_parent=p.parent==render.transform,position=vector(p.localPosition),rotation=vector(p.localEulerAngles),scale=vector(p.localScale)},
        thorns={},truncated=list and list.Count>64 or false,native_generation=true,unknown_generation_hooks={}}
    if not context.decoration_pool then
        local pool=field(CS.LevelPoolManager.Instance,'_groundList')
        local proof={count=pool and pool.Count or 0,truncated=pool and pool.Count>512 or false,colliders=0,behaviours=0}
        if pool then for i=0,math.min(pool.Count-1,511)do local node=pool[i]
            proof.colliders=proof.colliders+node:GetComponentsInChildren(typeof(U.Collider),true).Length
            proof.behaviours=proof.behaviours+node:GetComponentsInChildren(typeof(U.MonoBehaviour),true).Length
        end end
        context.decoration_pool=proof
    end
    out.decoration_pool=context.decoration_pool
    local staticFlags=CS.System.Reflection.BindingFlags.__CastFrom(56)
    local length=typeof(CS.EnemyBramblesBlock):GetField('_length',staticFlags)
    out.cell_length=length and length:GetValue(nil)or nil
    for _,entry in ipairs({{typeof(CS.EnemyBrambles),'ReplenishBlock'},
            {typeof(CS.EnemyBrambles),'ShowNextBrambleBlock'},{typeof(CS.EnemyBramblesBlock),'Show'},
            {typeof(CS.EnemyBramblesSingleThorn),'ThornReset'},{typeof(CS.LevelPoolManager),'GetGround'}})do
        local hook=entry[1]:GetField('__Hotfix0_'..entry[2],staticFlags)
        if not hook or hook:GetValue(nil)~=nil then
            out.native_generation=false;out.unknown_generation_hooks[#out.unknown_generation_hooks+1]=entry[1].Name..'.'..entry[2]
        end
    end
    if list then for i=0,math.min(list.Count-1,63)do local thorn=list[i]
        local row={id=thorn:GetInstanceID(),type=thorn:GetType().FullName,direct_parent=thorn.transform.parent==t,
            scripts=scripts(thorn.transform),colliders={}}
        local cs=thorn:GetComponentsInChildren(typeof(U.Collider),true)
        for j=0,cs.Length-1 do local c=cs[j]
            local shape={type=c:GetType().Name,enabled=c.enabled,own_transform=c.transform==thorn.transform,vertices={}}
            if shape.type=='BoxCollider'then
                for _,x in ipairs({-1,1})do for _,y in ipairs({-1,1})do for _,z in ipairs({-1,1})do
                    local point=c.center+U.Vector3(x*c.size.x/2,y*c.size.y/2,z*c.size.z/2)
                    shape.vertices[#shape.vertices+1]=vector(t:InverseTransformPoint(c.transform:TransformPoint(point)))
                end end end
            end
            row.colliders[#row.colliders+1]=shape
        end
        out.thorns[#out.thorns+1]=row
    end end
    return out
end
local function posedShape(c,root,targetScale,targetPosition)
    -- Evaluate an authored local TRS without changing any Transform.
    -- A hidden blade has zero Y scale: its current bounds cannot describe
    -- tomorrow's attack volume, nor can that singular matrix be inverted.
    if c:GetType().Name~='BoxCollider'then return nil end
    local chain={};local t=c.transform
    for depth=1,32 do
        if t==root then break end
        if not t then return nil end
        chain[#chain+1]=t;t=t.parent
    end
    if t~=root then return nil end
    local matrix=root.parent.localToWorldMatrix*U.Matrix4x4.TRS(targetPosition,root.localRotation,targetScale)
    for i=#chain,1,-1 do local v=chain[i]
        matrix=matrix*U.Matrix4x4.TRS(v.localPosition,v.localRotation,v.localScale)
    end
    local out=shape(c);out.quad={};out.authored_pose=true
    local lo,hi=U.Vector3(1e9,1e9,1e9),U.Vector3(-1e9,-1e9,-1e9)
    for _,sign in ipairs({{-1,-1},{1,-1},{1,1},{-1,1}})do
        local p=matrix:MultiplyPoint3x4(c.center+U.Vector3(sign[1]*c.size.x/2,sign[2]*c.size.y/2,0))
        out.quad[#out.quad+1]=vector(p);lo=U.Vector3.Min(lo,p);hi=U.Vector3.Max(hi,p)
    end
    out.depth_tilt=math.abs(matrix.m02)+math.abs(matrix.m12)>0.00001
    if out.depth_tilt then
        out.quad=nil
        for _,x in ipairs({-1,1})do for _,y in ipairs({-1,1})do for _,z in ipairs({-1,1})do
            local p=matrix:MultiplyPoint3x4(c.center+U.Vector3(x*c.size.x/2,y*c.size.y/2,z*c.size.z/2))
            lo=U.Vector3.Min(lo,p);hi=U.Vector3.Max(hi,p)
        end end end
    end
    out.center=vector((hi+lo)/2);out.extents=vector((hi-lo)/2)
    return out
end
local function grownShape(c,tween)
    local target=field(tween,'to')
    if not target then return nil end
    local out=posedShape(c,tween.transform,target,tween.transform.localPosition)
    if out then out.grown_target=true end
    return out
end
local function rotationEnvelope(c,root)
    -- Fruit render nodes rotate independently. Enclose every such rotation
    -- using authored collider geometry and the finite local transform chain.
    local kind=c:GetType().Name;local radius
    if kind=='SphereCollider'then radius=c.radius
    elseif kind=='CapsuleCollider'then radius=math.max(c.radius,c.height/2)
    elseif kind=='BoxCollider'then radius=c.size.magnitude/2
    else return nil end
    radius=radius+c.center.magnitude
    local t=c.transform;local depth=0
    while t and t~=root and depth<16 do
        local s=t.localScale
        radius=radius*math.max(math.abs(s.x),math.abs(s.y),math.abs(s.z))+t.localPosition.magnitude
        t=t.parent;depth=depth+1
    end
    if t~=root then return nil end
    return {root_radius=radius,depth=depth}
end
function E.privileged_state()
    assert(not E.busy and U.Time.timeScale==0,'Read internal state at a paused original boundary')
    local n=CS.NinjaController.Instance.NinjaScript;local p=n.transform.position
    local out={schema=1,privileged=true,state=E.state(),role={},enemies={},supports={},platforms={},mechanism_items={}}
    local tasks=taskInstanceField and taskInstanceField:GetValue(nil)
    local task=tasks and field(tasks,'<CurrSpecialTask>k__BackingField')
    out.special_task={observed=tasks~=nil,active=task~=nil,fields=values(task),
        identity=task and task:GetHashCode()or nil}
    local camera=CS.CameraController.Instance
    out.camera={right=vector(camera:GetScreenRightTopPos()),real_right=vector(camera:GetRealScreenRightTopPos()),
        reflection_right=vector(camera:GetScreenRightTopPos_Reflection(0)),
        position=vector(camera.LastPosition),direction=CS.GameManager.Instance.CurrDirModeNum,fields=values(camera)}
    out.role.fields=values(n);out.role.velocity=vector(n.Velocity);out.role.gravity=n.Gravity
    out.role.collect_effects=originalCollectEffects()
    out.role.ground_reference_y=CS.NinjaController.Instance:GetGroundY()
    local excludedAir=n.FallFromAirGround
    out.role.excluded_air_ground={present=excludedAir~=nil,fields=values(excludedAir)}
    out.role.slope_state=n.SlopeState
    local staticFlags=CS.System.Reflection.BindingFlags.__CastFrom(56)
    local ninjaType=typeof(CS.Ninja)
    local reverseFlag=ninjaType:GetField('isEnterRollToLineDownReviseVelocityFlag',staticFlags)
    local reverseOffset=ninjaType:GetField('InAirOffsetWhenEnterRollToLineDown',staticFlags)
    assert(reverseFlag and reverseOffset,'Original reversal rules missing')
    out.role.rules={reverse_fast_enabled=reverseFlag:GetValue(nil),reverse_fast_offset=reverseOffset:GetValue(nil)}
    local groundLengthen=typeof(CS.GameManager):GetField('_groundLengthen',staticFlags)
    assert(groundLengthen,'Original ground range rule missing')
    out.role.rules.ground_lengthen=groundLengthen:GetValue(nil)
    out.role.rules.slide_seconds=field(CS.NinjaController.Instance,'_slideTime')
    local slideOffset=field(CS.NinjaController.Instance,'_slideOffset')
    if slideOffset then out.role.rules.slide_offset=vector(slideOffset)end
    out.role.data=values(field(n,'_ninjaData'));out.role.collider_parameters=values(field(n,'_ninjiaCollider'))
    out.role.colliders={};out.role.interaction_colliders={};out.role.god=n:IsGodMode();out.role.mounted=n.IsMountState
    out.role.skills=originalSkills()
    local springAttraction=field(CS.NinjaController.Instance,'<SpringGravitation>k__BackingField')
    out.role.spring_attraction=type(springAttraction)=='number'and springAttraction or springAttraction:GetHashCode()
    local cols=n.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
    for i=0,cols.Length-1 do local c=cols[i]
        if c.enabled and c.gameObject.activeInHierarchy and c.name=='Role'then
            out.role.colliders[#out.role.colliders+1]=shape(c)
        elseif c.name=='ColliderForItem'then
            out.role.interaction_colliders[#out.role.interaction_colliders+1]=shape(c)
        end
    end
    local ground=n._GroundCollider
    out.support_id=ground and ground:GetInstanceID()or nil
    local air=n.OnAirGround
    if air and not air._isFree then out.role.air_ground=values(air)end
    local supports=U.Object.FindObjectsOfType(typeof(CS.LevelBlockCollider))
    local liveBlocks={}
    for i=0,supports.Length-1 do local s=supports[i]
        if s.enabled and s.isActive and s.gameObject.activeInHierarchy and s.PointEnd.x>p.x-8 and s.PointStart.x<p.x+80 then
            local key=s.BelongToStageIndex..':'..s.BelongToBlockIndex
            assert(not liveBlocks[key],'Ambiguous original block spawn queue')
            liveBlocks[key]=s
            out.supports[#out.supports+1]={id=s:GetInstanceID(),start=vector(s.PointStart),finish=vector(s.PointEnd),
                is_line=s.IsLine,is_ground=s.IsGround,stage_index=s.BelongToStageIndex,block_index=s.BelongToBlockIndex,
                info=values(field(s,'_levelBlockInfo'))}
        end
    end
    local platforms=U.Object.FindObjectsOfType(typeof(CS.ItemAirGround))
    for i=0,platforms.Length-1 do local o=platforms[i];local info=o.AirGroundInfo
        if o.enabled and o.isActive and o.gameObject.activeInHierarchy and info and not info._isFree and
                info._rightX>p.x-8 and info._leftX<p.x+80 then
            out.platforms[#out.platforms+1]={id=o:GetInstanceID(),info=values(info),fields=values(o),
                is_current=air and CS.System.Object.ReferenceEquals(info,air)or false}
        end
    end
    local enemies=U.Object.FindObjectsOfType(typeof(CS.EnemyBase))
    local brambleOwners={};local needBrambleTimers=false;local brambleTemplateContext={}
    for i=0,enemies.Length-1 do local o=enemies[i];local kind=o:GetType().Name
        if kind=='EnemyBrambles'and math.abs(o.transform.position.x-p.x)<80 then needBrambleTimers=true end
        if (kind=='EnemyBramblesSingleThorn'or kind=='EnemyBrambleCollider')and
                o.gameObject.activeInHierarchy and math.abs(o.transform.position.x-p.x)<80 then
            local owner=o:GetComponentInParent(typeof(CS.EnemyBrambles),true)
            if owner then brambleOwners[owner:GetInstanceID()]=true end
        end
    end
    local brambleCoroutines={by_id={}}
    if needBrambleTimers or next(brambleOwners)then brambleCoroutines=logicCoroutines()end
    for i=0,enemies.Length-1 do local o=enemies[i]
        if o.gameObject.activeInHierarchy and o.isActive and
                (math.abs(o.transform.position.x-p.x)<80 or brambleOwners[o:GetInstanceID()])then
            local info=field(o,'_enemyInfo');local custom=info and field(info,'_enemyInfoCustom')
            local row={id=o:GetInstanceID(),type=o:GetType().Name,name=o.name,position=vector(o.transform.position),
                fields=values(o),info=values(info),custom=values(custom),custom_type=custom and custom:GetType().Name or nil,
                speed=o.CurrentSpeed,attack=o.Attack,scale=vector(o.transform.lossyScale),rotation_z=o.transform.eulerAngles.z,colliders={}}
            if row.type=='EnemyHook'or row.type=='EnemyBambooThorn'then
                local p=o.transform.parent
                row.swing_axes={local_scale=vector(o.transform.localScale),parent=p and p:GetInstanceID()or 0}
                if p then
                    row.swing_axes.position=vector(p.position)
                    row.swing_axes.x=vector(p:TransformVector(U.Vector3.right))
                    row.swing_axes.y=vector(p:TransformVector(U.Vector3.up))
                    row.swing_axes.z=vector(p:TransformVector(U.Vector3.forward))
                end
            end
            row.info_identity=info and info:GetHashCode()or nil
            if row.type=='EnemyGhostFire'then row.ghost_geometry=ghostGeometry(o)end
            if row.type=='EnemyWarrior'then row.spine=spineState(field(o,'_spineWarrior'))end
            if row.type=='EnemyPoleaxeWarrior'then
                local animation=o.gameObject:GetComponentInChildren(typeof(CS.Spine.Unity.SkeletonAnimation),true)
                row.spine=spineState(animation)
            end
            if row.type=='EnemyFruitPinball' or row.type=='EnemyPiranha'then
                local parent=o.transform.parent;local matrix=parent and parent.localToWorldMatrix or U.Matrix4x4.identity
                local error=0
                for a=0,3 do for b=0,3 do error=error+math.abs(matrix['m'..a..b]-(a==b and 1 or 0))end end
                row.local_movement_parent_identity=error<0.00001
            end
            local at=field(o,'privateAtLevelBlock')
            if at then row.native_support={id=at:GetInstanceID(),start=vector(at.PointStart),finish=vector(at.PointEnd),
                is_line=at.IsLine,is_ground=at.IsGround}end
            if row.type=='EnemyRollingBase'then
                local block=field(o,'_currentBlock')
                if block then row.rolling_support={id=block:GetInstanceID(),start=vector(block.PointStart),finish=vector(block.PointEnd),
                    is_line=block.IsLine,is_ground=block.IsGround,info=values(field(block,'_levelBlockInfo'))}end
                -- None overwrites _currentBlock on activation. A pooled
                -- instance can still hold the preceding spawn's block here.
                local cursor=block
                if tostring(field(o,'_enemyState'))=='none: 0'then cursor=at end
                row.rolling_blocks={};local seen={};local previous={};local back=cursor
                if cursor then seen[cursor:GetInstanceID()]=true end
                for depth=1,4 do
                    local candidate=field(back,'<_LastGroundCollider>k__BackingField')
                    -- Pool recycling can leave stale backward references.
                    -- Export only an actual adjacent predecessor, without
                    -- repairing or following a cycle in the game's graph.
                    if not candidate or seen[candidate:GetInstanceID()] or
                            (candidate.PointEnd-back.PointStart).magnitude>0.001 then break end
                    back=candidate;seen[back:GetInstanceID()]=true;previous[#previous+1]=back
                end
                for depth=#previous,1,-1 do local v=previous[depth]
                    row.rolling_blocks[#row.rolling_blocks+1]={id=v:GetInstanceID(),start=vector(v.PointStart),finish=vector(v.PointEnd),
                        is_line=v.IsLine,is_ground=v.IsGround,info=values(field(v,'_levelBlockInfo'))}
                end
                seen={}
                for depth=1,8 do
                    if not cursor or seen[cursor:GetInstanceID()]then break end
                    seen[cursor:GetInstanceID()]=true
                    row.rolling_blocks[#row.rolling_blocks+1]={id=cursor:GetInstanceID(),start=vector(cursor.PointStart),finish=vector(cursor.PointEnd),
                        is_line=cursor.IsLine,is_ground=cursor.IsGround,info=values(field(cursor,'_levelBlockInfo'))}
                    cursor=field(cursor,'<_NextGroundCollider>k__BackingField')
                end
                row.rolling_chain_truncated=cursor~=nil
            end
            if row.type=='EnemyHook' or row.type=='EnemyBambooThorn'then
                local last,previous=field(o,'_lastRotation'),field(o,'_secondLastRotation')
                if last and previous then row.rotation_samples={last=last.eulerAngles.z,previous=previous.eulerAngles.z}end
            end
            row.controllers={}
            for _,f in ipairs(fields(o))do
                if string.find(f.FieldType.Name,'Controller',1,true)then
                    local v=f:GetValue(o)
                    if v then row.controllers[f.Name]={type=v:GetType().Name,fields=values(v)}end
                end
            end
            local cs=o.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
            if row.type=='EnemyBullutFireRobot'or row.type=='EnemyBullutLaser'or row.type=='EnemyAlarmShooter'then
                local m=o.transform.parent and o.transform.parent.localToWorldMatrix or U.Matrix4x4.identity
                local error=0
                for a=0,2 do for b=0,2 do error=error+math.abs(m['m'..a..b]-(a==b and 1 or 0))end end
                row.bullet_geometry={parent_axes_identity=error<0.00001,chains={}}
                for j=0,cs.Length-1 do local c=cs[j];local chain={};local t=c.transform
                    for depth=1,32 do
                        if not t then break end
                        local components=t:GetComponents(typeof(U.Component));local scripts={}
                        for k=0,components.Length-1 do
                            scripts[#scripts+1]=components[k]and components[k]:GetType().FullName or 'missing_component'
                        end
                        local body=t:GetComponent(typeof(U.Rigidbody))
                        chain[#chain+1]={name=t.name,scripts=scripts,rigidbody=body and
                            {kinematic=body.isKinematic,gravity=body.useGravity,velocity=vector(body.velocity)}or nil}
                        if t==o.transform then break end;t=t.parent
                    end
                    row.bullet_geometry.chains[#row.bullet_geometry.chains+1]={id=c:GetInstanceID(),complete=t==o.transform,nodes=chain,
                        includes_native_components=true}
                end
            end
            if row.type=='EnemyAlarmShooter'then
                local bullets=field(o,'_bulletList');row.alarm_shooter={bullets={},truncated=bullets and bullets.Count>64 or false}
                if bullets then for j=0,math.min(bullets.Count-1,63)do
                    row.alarm_shooter.bullets[#row.alarm_shooter.bullets+1]=values(bullets[j])
                end end
            end
            if row.type=='EnemyBullutLaser'then
                row.laser_growth={scales={},positions={}}
                local components=o.gameObject:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
                for j=0,components.Length-1 do local tween=components[j]
                    local kind=tween and tween:GetType().FullName
                    if kind=='uTools.uTweenScale'or kind=='uTools.uTweenPosition'then
                        local scale={id=tween:GetInstanceID(),root=tween.transform:GetInstanceID(),fields=values(tween),
                            curve={},from_colliders={},to_colliders={}}
                        local curve=field(tween,'animationCurve')
                        if curve then local keys=curve.keys;scale.curve_truncated=keys.Length>128
                            for k=0,math.min(keys.Length-1,127)do local v=keys[k]
                                scale.curve[#scale.curve+1]={time=v.time,value=v.value,in_tangent=v.inTangent,
                                    out_tangent=v.outTangent,weighted_mode=tostring(v.weightedMode)}
                            end
                        end
                        local first,last=field(tween,'from'),field(tween,'to')
                        if first and last then for k=0,cs.Length-1 do local c=cs[k]
                            local a,b
                            if kind=='uTools.uTweenScale'then
                                a=posedShape(c,tween.transform,first,tween.transform.localPosition)
                                b=posedShape(c,tween.transform,last,tween.transform.localPosition)
                            else
                                a=posedShape(c,tween.transform,tween.transform.localScale,first)
                                b=posedShape(c,tween.transform,tween.transform.localScale,last)
                            end
                            if a and b and a.damage_owner==row.id then
                                scale.from_colliders[#scale.from_colliders+1]=a;scale.to_colliders[#scale.to_colliders+1]=b
                            end
                        end end
                        local target=kind=='uTools.uTweenScale'and row.laser_growth.scales or row.laser_growth.positions
                        target[#target+1]=scale
                    end
                end
            end
            if row.type=='EnemySuspendSpecial'then
                local fs=o:GetType():GetFields(flags)
                row.suspend_controller={}
                for j=0,fs.Length-1 do local f=fs[j]
                    if f.FieldType.FullName=='EnemyElectricBall'then
                        local owner=f:GetValue(o)
                        if owner then local info=field(owner,'_enemyInfo')
                            row.suspend_controller={id=owner:GetInstanceID(),type=owner:GetType().Name,
                                info_identity=info and info:GetHashCode()or nil,index=field(owner,'m_index'),
                                alive=owner.gameObject.activeInHierarchy and owner.isActive and
                                    not field(owner,'_dead')and not field(owner,'_isRecycled')}
                            if owner:GetType().Name=='EnemyRotateElectricBall'then
                                row.suspend_controller.position=vector(owner.transform.position)
                                row.suspend_controller.scale=vector(owner.transform.lossyScale)
                                row.suspend_controller.rotation_z=owner.transform.eulerAngles.z
                                row.suspend_controller.fields=values(owner)
                                row.suspend_controller.rigid_electric=rigidElectric(owner)
                            end
                        end
                    end
                end
            end
            if row.type=='EnemyRotateElectricBall'then row.rigid_electric=rigidElectric(o)end
            if row.type=='EnemyConnectElectricBall'then
                local balls=field(o,'_balls');local electric=field(o,'_electric')
                row.electric_connection={balls={},colliders={}}
                row.electric_connection.balls_truncated=balls and balls.Count>8 or false
                if balls then for j=0,math.min(balls.Count-1,7)do local ball=balls[j]
                    row.electric_connection.balls[#row.electric_connection.balls+1]={id=ball:GetInstanceID(),
                        type=ball:GetType().Name,position=vector(ball.transform.position),fields=values(ball)}
                end end
                if electric then
                    row.electric_connection.direct_parent=electric.parent==o.transform
                    row.electric_connection.position=vector(electric.position)
                    row.electric_connection.local_scale=vector(electric.localScale)
                    for j=0,cs.Length-1 do local c=cs[j]
                        if c.transform==electric then row.electric_connection.colliders[#row.electric_connection.colliders+1]=c:GetInstanceID()end
                    end
                end
            end
            if row.type=='EnemyRockTiger'then
                local head=field(o,'_currRenderObj');local matrix=o.transform.localToWorldMatrix
                row.rock_tiger={data=values(field(o,'customData')),head_colliders={},
                    planar_root=math.abs(matrix.m02)+math.abs(matrix.m12)+math.abs(matrix.m20)+math.abs(matrix.m21)<0.00001 and
                        matrix.m00*matrix.m11-matrix.m01*matrix.m10>0}
                if head then local t=head.transform;local q=t.localRotation
                    row.rock_tiger.head={position=vector(t.localPosition),scale=vector(t.localScale),
                        direct_parent=t.parent==o.transform,
                        identity_rotation=math.abs(q.x)+math.abs(q.y)+math.abs(q.z)+math.abs(math.abs(q.w)-1)<0.00001}
                    for j=0,cs.Length-1 do local c=cs[j]
                        if c.transform==t then row.rock_tiger.head_colliders[#row.rock_tiger.head_colliders+1]=c:GetInstanceID()end
                    end
                end
            end
            if row.type=='EnemyBrambles'then
                row.brambles={action=values(field(o,'_currActionParam')),actions={},nodes={},blocks={}}
                local id=rawget(getmetatable(o),'lua_changeStateCo')
                local hook=typeof(CS.EnemyBrambles):GetField('__Hotfix0_ToNextAction',CS.System.Reflection.BindingFlags.__CastFrom(60))
                row.brambles.warning={implementation=hook and hook:GetValue(nil)~=nil and 'lua_fixed_coroutine'or 'native_delay',
                    id=id and tostring(id)or nil,controllers=brambleCoroutines.controllers,processing=brambleCoroutines.processing,
                    truncated=brambleCoroutines.truncated,matches=brambleCoroutines.by_id[tostring(id)]or{}}
                row.brambles.axis_y=vector(o.transform:TransformVector(U.Vector3.up))
                if custom then for _,f in ipairs(fields(custom))do
                    if string.find(f.FieldType.FullName,'BramblesActionParam',1,true)then
                        local list=f:GetValue(custom)
                        if list and typeof(CS.System.Collections.IList):IsAssignableFrom(f.FieldType)then
                            local count=f.FieldType.IsArray and list.Length or list.Count
                            row.brambles.actions_truncated=count>64
                            for j=0,math.min(count-1,63)do row.brambles.actions[#row.brambles.actions+1]=values(list[j])end
                        end
                    end
                end end
                local render=field(o,'_currRenderObj')
                if row.fields._currBrambleIndex<row.fields._totalBrambleBlockNum then
                    row.brambles.template=brambleTemplate(o,render,brambleTemplateContext)
                end
                if render then local t=render.transform
                    row.brambles.render={id=t:GetInstanceID(),position=vector(t.localPosition),scale=vector(t.localScale),
                        rotation=vector(t.localEulerAngles),direct_parent=t.parent==o.transform}
                end
                for _,name in ipairs({'_collider','_colliderLft','_colliderRight','_topCollider'})do
                    local node=field(o,name)
                    if node then local t=node.transform;local ids={}
                        for j=0,cs.Length-1 do if cs[j].transform:IsChildOf(t)then ids[#ids+1]=cs[j]:GetInstanceID()end end
                        row.brambles.nodes[#row.brambles.nodes+1]={field=name,id=t:GetInstanceID(),position=vector(t.localPosition),
                            scale=vector(t.localScale),rotation=vector(t.localEulerAngles),colliders=ids,
                            parent=t.parent and t.parent:GetInstanceID()or nil,active=t.gameObject.activeInHierarchy}
                    end
                end
                local blocks=field(o,'activedBlockList')
                if blocks then row.brambles.blocks_truncated=blocks.Count>64
                    for j=0,math.min(blocks.Count-1,63)do local block=blocks[j]
                        row.brambles.blocks[#row.brambles.blocks+1]={fields=values(block),position=vector(block.transform.position),
                            active=block.gameObject.activeInHierarchy}
                    end
                end
            end
            if row.type=='EnemyBramblesSingleThorn'or row.type=='EnemyBrambleCollider'then
                local owner=o:GetComponentInParent(typeof(CS.EnemyBrambles),true)
                if owner then local render=field(owner,'_currRenderObj')
                    row.brambles_owner={id=owner:GetInstanceID(),under_render=render and o.transform:IsChildOf(render.transform)or false,
                        info_identity=field(owner,'_enemyInfo'):GetHashCode()}
                end
            end
            if row.type=='EnemySmallSword'then
                local breath=field(o,'breathTween')
                row.sword={breath_present=breath~=nil,breath_affects_damage=false}
                if breath then for j=0,cs.Length-1 do local c=cs[j]
                    if shape(c).damage_kind and c.transform:IsChildOf(breath.transform)then
                        row.sword.breath_affects_damage=true
                    end
                end end
            end
            for j=0,cs.Length-1 do local c=cs[j];local owner=c:GetComponentInParent(typeof(CS.EnemyBase),true)
                if owner and owner:GetInstanceID()==row.id then
                    local collider=shape(c)
                    collider.component_owner=owner:GetInstanceID()
                    if row.type=='EnemyFruitPinball' or row.type=='EnemyPiranha'then
                        collider.rotation_envelope=rotationEnvelope(c,o.transform)
                    end
                    row.colliders[#row.colliders+1]=collider
                end
            end
            local tween=field(o,'_tweener')
            if tween and o:GetType().Name=='EnemyHideBlade'then
                row.tween=values(tween);row.grown_colliders={}
                for j=0,cs.Length-1 do local c=cs[j];local grown=grownShape(c,tween)
                    if grown and grown.damage_owner==row.id then row.grown_colliders[#row.grown_colliders+1]=grown end
                end
            end
            if row.type=='EnemyBambooWater'then
                local tween=field(o,'_crabTweener')
                if tween then
                    row.position_tween={type=tween:GetType().FullName,fields=values(tween),curve={},from_colliders={},to_colliders={}}
                    local curve=field(tween,'animationCurve')
                    if curve then local keys=curve.keys
                        for k=0,math.min(keys.Length-1,127)do local v=keys[k]
                            row.position_tween.curve[#row.position_tween.curve+1]={time=v.time,value=v.value,
                                in_tangent=v.inTangent,out_tangent=v.outTangent,
                                weighted_mode=tostring(v.weightedMode),in_weight=v.inWeight,out_weight=v.outWeight}
                        end
                        row.position_tween.curve_truncated=keys.Length>128
                    end
                    local from,to=field(tween,'from'),field(tween,'to')
                    if from and to then for j=0,cs.Length-1 do local c=cs[j]
                        local owner=c:GetComponentInParent(typeof(CS.EnemyBase),true)
                        if owner and owner:GetInstanceID()==row.id then
                            local first=posedShape(c,tween.transform,tween.transform.localScale,from)
                            local last=posedShape(c,tween.transform,tween.transform.localScale,to)
                            if first then row.position_tween.from_colliders[#row.position_tween.from_colliders+1]=first end
                            if last then row.position_tween.to_colliders[#row.position_tween.to_colliders+1]=last end
                        end
                    end end
                end
            end
            if row.type=='EnemyArrow'then
                -- Native ResetEnemyInfo resets this object's local position
                -- to zero and scale to one. UpdateCollider only clips that
                -- authored box into the soil; recover it without undoing the
                -- live Transform or using the image/mesh size as collision.
                local colliderObject=field(o,'_colliderObject')
                if colliderObject then
                    row.untrimmed_colliders={}
                    for j=0,cs.Length-1 do local c=cs[j]
                        local full=posedShape(c,colliderObject.transform,U.Vector3.one,U.Vector3.zero)
                        if full and full.damage_owner==row.id then
                            row.untrimmed_colliders[#row.untrimmed_colliders+1]=full
                        end
                    end
                end
            end
            out.enemies[#out.enemies+1]=row
        end
    end
    -- Coin bodies affect score/energy/task counters; every other ItemBase
    -- must remain visible to the mechanism model, including skill balls.
    local scoreItems={ItemCoin=true,ItemCoinYellowFly=true}
    local items=U.Object.FindObjectsOfType(typeof(CS.ItemBase))
    for i=0,items.Length-1 do local o=items[i];local kind=o:GetType().Name
        if not scoreItems[kind] and o.gameObject.activeInHierarchy and o.isActive and
                o.transform.position.x>p.x-2 and o.transform.position.x<p.x+80 then
            local info=field(o,'_itemInfo');local custom=info and field(info,'_itemInfoCustom')
            local item={id=o:GetInstanceID(),type=kind,
                position=vector(o.transform.position),fields=values(o),info=values(info),custom=values(custom)}
            item.info_identity=info and info:GetHashCode()or nil
            item.custom_type=custom and custom:GetType().Name
            item.custom,item.custom_projection=valueProjection(custom)
            if kind=='ItemFixed'then
                item.component_types={};local scripts=o:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
                for j=0,scripts.Length-1 do if scripts[j]then item.component_types[#item.component_types+1]=scripts[j]:GetType().FullName end end
                item.animated_tree=o:GetComponentsInChildren(typeof(U.Animator),true).Length>0 or
                    o:GetComponentsInChildren(typeof(U.Animation),true).Length>0
            end
            if kind=='ItemSkull'then
                local body=o:GetComponent(typeof(U.Rigidbody));local callbacks=true
                for _,name in ipairs({'conditionActionEvent','normalActionEvent','collisionActionEvent',
                        'collisionExitActionEvent','btAnimatorEvent','conditionParamActionEvent','syncComponent'})do
                    if field(o,name)~=nil then callbacks=false end
                end
                local graphs=field(o,'allGraphOwners')
                if graphs and graphs.Count>0 then callbacks=false end
                item.skull_binding={callbacks_clear=callbacks,component_types={},
                    kinematic=body and body.isKinematic or false,gravity=not body or body.useGravity,
                    animated=o:GetComponentsInChildren(typeof(U.Animator),true).Length>0 or
                        o:GetComponentsInChildren(typeof(U.Animation),true).Length>0}
                local scripts=o:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
                for j=0,scripts.Length-1 do item.skull_binding.component_types[#item.skull_binding.component_types+1]=
                    scripts[j]and scripts[j]:GetType().FullName or 'missing_component'end
            end
            if kind=='ItemSpring'then
                local normal,pop=field(o,'_normalSpring'),field(o,'_popSpring');local q=o.transform.localRotation
                item.spring={normal_active=normal and normal.activeSelf or false,pop_active=pop and pop.activeSelf or false,
                    rotation={x=q.x,y=q.y,z=q.z,w=q.w}}
            end
            if kind=='ItemEvent'then item.action_data=actionData(custom,8)end
            item.colliders={}
            local cs=o.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
            for j=0,cs.Length-1 do local c=cs[j];local owner=c:GetComponentInParent(typeof(CS.ItemBase))
                if owner and owner:GetInstanceID()==item.id then item.colliders[#item.colliders+1]=shape(c)end
            end
            out.mechanism_items[#out.mechanism_items+1]=item
        end
    end
    local level=CS.LevelManager.Instance.GameLevelInfo
    local stages=field(level,'_stageList');local index=ground and ground.BelongToStageIndex or -1
    local stage=index>=0 and index<stages.Count and stages[index]or nil
    if index>=stages.Count then stage=field(level,'_currLoopStage')end
    out.board={stage_index=index,block_index=ground and ground.BelongToBlockIndex or -1,
        stage_start=stage and stage.StageStartX or nil,stage_id=stage and field(stage,'_stageBaseInfo')._stageID or nil,
        map_id=field(level,'_levelBaseInfo')._levelID}
    -- Read the actual resolved block list as well as spawned colliders. Unity
    -- instantiates terrain incrementally; missing a not-yet-created collider
    -- must not turn a known continuation into an imaginary pit.
    out.terrain={};out.pending_enemies={};out.pending_items={};out.spawn_templates={items={}}
    local function springSpawnTemplate()
        local all=U.Resources.FindObjectsOfTypeAll(typeof(CS.ItemSpring));local original
        for i=0,all.Length-1 do local o=all[i]
            if o.name=='ItemSpring'and not o.gameObject.activeInHierarchy then
                assert(not original,'Ambiguous original spring prefab');original=o
            end
        end
        if not original then return {missing=true}end
        local root=original.transform;local cs=original.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
        local result={id=original:GetInstanceID(),type=original:GetType().Name,colliders={},root_scripts={},
            animated_root=root.gameObject:GetComponent(typeof(U.Animator))~=nil or root.gameObject:GetComponent(typeof(U.Animation))~=nil}
        local scripts=root.gameObject:GetComponents(typeof(U.MonoBehaviour))
        for i=0,scripts.Length-1 do if scripts[i]then result.root_scripts[#result.root_scripts+1]=scripts[i]:GetType().Name end end
        for i=0,cs.Length-1 do local c=cs[i]
            local row={type=c:GetType().Name,name=c.name,enabled=c.enabled,trigger=c.isTrigger,
                direct_root=c.transform==root,vertices={}}
            if row.type=='BoxCollider'then
                for _,x in ipairs({-1,1})do for _,y in ipairs({-1,1})do for _,z in ipairs({-1,1})do
                    local p=c.transform:TransformPoint(c.center+U.Vector3(x*c.size.x/2,y*c.size.y/2,z*c.size.z/2))
                    row.vertices[#row.vertices+1]=vector(root:InverseTransformPoint(p))
                end end end
            end
            result.colliders[#result.colliders+1]=row
        end
        return result
    end
    local function staticPickupTemplate(name)
        local coin=name=='ItemCoinRed'
        local all=U.Resources.FindObjectsOfTypeAll(typeof(coin and CS.ItemCoin or CS[name]));local original
        for i=0,all.Length-1 do local obj=all[i]
            if obj.name==name and not obj.gameObject.activeInHierarchy then
                assert(not original,'Ambiguous original pickup prefab');original=obj
            end
        end
        if not original then return {missing=true}end
        local root=original.transform;local manager=existingSingleton(typeof(CS.ItemManager))
        local enumType=typeof(CS.GameItemInfo):GetField('_itemType',flags).FieldType
        local enum=CS.System.Enum.Parse(enumType,name)
        local result={id=original:GetInstanceID(),type=original:GetType().Name,source_name=original.name,
            root_scale=vector(root.localScale),root_scripts={},colliders={},component_types={},
            be_attract_level=tostring(field(original,'beAttractLevel')),follow_ground=field(original,'followGround'),
            attract_item_level=field(original,'attractItemLevel'),
            global_attract=manager and manager:IsItemCanAttracted(enum)or false,
            attraction_manager_present=manager~=nil,
            animated_root=root.gameObject:GetComponent(typeof(U.Animator))~=nil or root.gameObject:GetComponent(typeof(U.Animation))~=nil}
        if name=='ItemSkull'then
            local body=root.gameObject:GetComponent(typeof(U.Rigidbody))
            result.kinematic=body and body.isKinematic or false;result.gravity=not body or body.useGravity
            result.native_skull_callbacks=true;result.unknown_skull_hooks={}
            for _,entry in ipairs({{typeof(CS.ItemSkull),'Initialize'},
                    {typeof(CS.ItemSkull),'ResetItemInfo'},{typeof(CS.ItemSkull),'SetRenderType'},
                    {typeof(CS.ItemSkull),'OnLoadFissonObj'},{typeof(CS.ItemSkull),'ProcessOnTriggerEnter'},
                    {typeof(CS.ItemSkull),'ThisProcessOnTriggerEnter'},
                    {typeof(CS.ItemBase),'FixedUpdateMovement'},{typeof(CS.ItemBase),'PlayFixedAnimation'},
                    {typeof(CS.ItemBase),'PlayLateAnimation'},{typeof(CS.ItemBase),'ProcessOnTriggerStay'},
                    {typeof(CS.ItemBase),'ProcessOnTriggerExit'},{typeof(CS.ItemBase),'ShowPickupEffect'},
                    {typeof(CS.ItemBase),'PlayPickUpAudio'},
                    {typeof(CS.FissonableModule),'Init'},{typeof(CS.FissonableModule),'FissurePieces'},
                    {typeof(CS.EnemyFissonablePieces),'Fissure'},{typeof(CS.EnemyFissonablePieces),'LateUpdate'}})do
                local hook=entry[1]:GetField('__Hotfix0_'..entry[2],staticFlags)
                if not hook or hook:GetValue(nil)~=nil then
                    result.native_skull_callbacks=false
                    result.unknown_skull_hooks[#result.unknown_skull_hooks+1]=entry[1].Name..'.'..entry[2]
                end
            end
        end
        local scripts=root.gameObject:GetComponents(typeof(U.MonoBehaviour))
        for i=0,scripts.Length-1 do if scripts[i]then result.root_scripts[#result.root_scripts+1]=scripts[i]:GetType().Name end end
        scripts=root.gameObject:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
        for i=0,scripts.Length-1 do if scripts[i]then result.component_types[#result.component_types+1]=scripts[i]:GetType().FullName end end
        result.animated_tree=root.gameObject:GetComponentsInChildren(typeof(U.Animator),true).Length>0 or
            root.gameObject:GetComponentsInChildren(typeof(U.Animation),true).Length>0
        local cs=root.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
        for i=0,cs.Length-1 do local c=cs[i]
            local row={type=c:GetType().Name,enabled=c.enabled,trigger=c.isTrigger,direct_root=c.transform==root}
            if row.type=='BoxCollider'then row.center=vector(c.center);row.size=vector(c.size)
            elseif row.type=='SphereCollider'then row.center=vector(c.center);row.radius=c.radius end
            result.colliders[#result.colliders+1]=row
        end
        return result
    end
    local staticBladePrefabs
    local function bladeSpawnTemplate(name)
        if not staticBladePrefabs then
            staticBladePrefabs={}
            local originals=U.Resources.FindObjectsOfTypeAll(typeof(CS.EnemyBlade))
            for i=0,originals.Length-1 do local o=originals[i]
                if not o.name:find('(',1,true)and not o.gameObject.activeInHierarchy then
                    assert(not staticBladePrefabs[o.name],'Ambiguous original blade prefab')
                    staticBladePrefabs[o.name]=o
                end
            end
        end
        local o=staticBladePrefabs[name]
        if not o then return {missing=true}end
        local root=o.transform;local out={id=o:GetInstanceID(),type=o:GetType().Name,fields=values(o),colliders={}}
        local cs=o.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
        for i=0,cs.Length-1 do local c=cs[i];local s=shape(c)
            if s.damage_kind then
                local row={type=s.type,name=c.name,damage_kind=s.damage_kind,enabled=c.enabled,
                    static_chain=true,local_active=true,vertices={}}
                local t=c.transform
                while t do
                    if t~=root and not t.gameObject.activeSelf then row.local_active=false end
                    if t.gameObject:GetComponent(typeof(U.Animator))or t.gameObject:GetComponent(typeof(U.Animation))then
                        row.static_chain=false
                    end
                    local scripts=t.gameObject:GetComponents(typeof(U.MonoBehaviour))
                    for j=0,scripts.Length-1 do local script=scripts[j]
                        if script then local kind=script:GetType().Name
                            if kind~='EnemyBlade'and kind~='EnemyBaseCollider'and kind~='EnemyAttackModule'then
                                row.static_chain=false
                            end
                        end
                    end
                    if t==root then break end;t=t.parent
                end
                if not t then row.static_chain=false end
                if s.type=='BoxCollider'then
                    for _,x in ipairs({-1,1})do for _,y in ipairs({-1,1})do for _,z in ipairs({-1,1})do
                        local p=c.transform:TransformPoint(c.center+U.Vector3(x*c.size.x/2,y*c.size.y/2,z*c.size.z/2))
                        row.vertices[#row.vertices+1]=vector(root:InverseTransformPoint(p))
                    end end end
                end
                out.colliders[#out.colliders+1]=row
            end
        end
        return out
    end
    local function ghostSpawnTemplate()
        local all=U.Resources.FindObjectsOfTypeAll(typeof(CS.EnemyGhostFire));local original
        for i=0,all.Length-1 do local o=all[i]
            if o.name=='EnemyGhostFire'and not o.gameObject.activeInHierarchy then
                assert(not original,'Ambiguous original ghost prefab');original=o
            end
        end
        if not original then return {missing=true}end
        local result=ghostGeometry(original);result.source_name='EnemyGhostFire';return result
    end
    local function curveSpawnTemplate(name)
        local all=U.Resources.FindObjectsOfTypeAll(typeof(CS.EnemyCurveBat));local original
        for i=0,all.Length-1 do local o=all[i]
            if o.name==name and not o.gameObject.activeInHierarchy then
                assert(not original,'Ambiguous original curve prefab');original=o
            end
        end
        if not original then return {missing=true}end
        local root=original.transform;local body=original:GetComponent(typeof(U.Rigidbody))
        local result={id=original:GetInstanceID(),type=original:GetType().Name,source_name=name,
            kinematic=not body or body.isKinematic,gravity=body and body.useGravity or false,
            callbacks_clear=true,native_initialization=true,unknown_hooks={},component_types={},colliders={},
            animated_tree=original:GetComponentsInChildren(typeof(U.Animator),true).Length>0 or
                original:GetComponentsInChildren(typeof(U.Animation),true).Length>0}
        for _,name in ipairs({'conditionActionEvent','normalActionEvent','collisionActionEvent',
                'collisionExitActionEvent','btAnimatorEvent','conditionParamActionEvent','syncComponent'})do
            if field(original,name)~=nil then result.callbacks_clear=false end
        end
        local graphs=field(original,'allGraphOwners')
        if graphs and graphs.Count>0 then result.callbacks_clear=false end
        local scripts=original:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
        for i=0,scripts.Length-1 do result.component_types[#result.component_types+1]=
            scripts[i]and scripts[i]:GetType().FullName or 'missing_component'end
        for _,entry in ipairs({{typeof(CS.EnemyCurveBat),'ResetEnemyInfo'},
                {typeof(CS.EnemyCurveBat),'ProcessOnTriggerEnter'},
                {typeof(CS.EnemyCurve),'SetRenderType'},{typeof(CS.EnemyCurve),'PlayFixedAnimation'},
                {typeof(CS.EnemyCurve),'ResetEnemyInfo'},{typeof(CS.EnemyCurve),'FixedUpdateMovement'},
                {typeof(CS.EnemyCurve),'StateUpdate'},{typeof(CS.EnemyCurve),'UpdateCureMove'},
                {typeof(CS.EnemyBase),'SetRenderType'},{typeof(CS.EnemyBase),'ResetEnemyInfo'},
                {typeof(CS.EnemyBase),'FixedUpdateMovement'},{typeof(CS.EnemyBase),'PlayFixedAnimation'},
                {typeof(CS.EnemyBase),'ProcessOnTriggerEnter'}})do
            local hook=entry[1]:GetField('__Hotfix0_'..entry[2],staticFlags)
            if not hook or hook:GetValue(nil)~=nil then
                result.native_initialization=false;result.unknown_hooks[#result.unknown_hooks+1]=entry[1].Name..'.'..entry[2]
            end
        end
        local cs=original:GetComponentsInChildren(typeof(U.Collider),true)
        for i=0,cs.Length-1 do local c=cs[i];local info=shape(c)
            local row={type=c:GetType().Name,enabled=c.enabled,trigger=c.isTrigger,
                damage_kind=info.damage_kind,owner_bound=info.damage_owner==original:GetInstanceID()}
            if row.type=='SphereCollider'then
                row.center=vector(root:InverseTransformPoint(c.transform:TransformPoint(c.center)))
                local stretch=1;local t=c.transform
                while t and t~=root do
                    local v=t.localScale;stretch=stretch*math.max(math.abs(v.x),math.abs(v.y),math.abs(v.z));t=t.parent
                end
                row.radius=c.radius*stretch;row.under_root=t==root
            end
            result.colliders[#result.colliders+1]=row
        end
        return result
    end
    local function suspendSpawnTemplate(name)
        local all=U.Resources.FindObjectsOfTypeAll(typeof(CS.EnemySuspend));local original
        for i=0,all.Length-1 do local o=all[i]
            if o.name==name and not o.gameObject.activeInHierarchy then
                assert(not original,'Ambiguous original suspend prefab');original=o
            end
        end
        if not original then return {missing=true}end
        local root=original.transform;local body=original:GetComponent(typeof(U.Rigidbody))
        local result={id=original:GetInstanceID(),type=original:GetType().Name,source_name=name,
            kinematic=not body or body.isKinematic,gravity=body and body.useGravity or false,
            callbacks_clear=true,native_initialization=true,unknown_hooks={},component_types={},colliders={},
            animated_tree=original:GetComponentsInChildren(typeof(U.Animator),true).Length>0 or
                original:GetComponentsInChildren(typeof(U.Animation),true).Length>0}
        for _,name in ipairs({'conditionActionEvent','normalActionEvent','collisionActionEvent',
                'collisionExitActionEvent','btAnimatorEvent','conditionParamActionEvent','syncComponent'})do
            if field(original,name)~=nil then result.callbacks_clear=false end
        end
        local graphs=field(original,'allGraphOwners')
        if graphs and graphs.Count>0 then result.callbacks_clear=false end
        local scripts=original:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
        for i=0,scripts.Length-1 do result.component_types[#result.component_types+1]=
            scripts[i]and scripts[i]:GetType().FullName or 'missing_component'end
        result.acc=field(original,'_changeSpeedDirTime');result.reverse_run_flip=field(original,'reverseRunFlip')
        for _,entry in ipairs({{typeof(CS.EnemySuspend),'ResetEnemyInfo'},
                {typeof(CS.EnemySuspend),'FixedUpdateMovement'},
                {typeof(CS.EnemyBase),'SetRenderType'},{typeof(CS.EnemyBase),'ResetEnemyInfo'},
                {typeof(CS.EnemyBase),'FixedUpdateMovement'},{typeof(CS.EnemyBase),'ProcessOnTriggerEnter'}})do
            local hook=entry[1]:GetField('__Hotfix0_'..entry[2],staticFlags)
            if not hook or hook:GetValue(nil)~=nil then
                result.native_initialization=false;result.unknown_hooks[#result.unknown_hooks+1]=entry[1].Name..'.'..entry[2]
            end
        end
        local cs=original:GetComponentsInChildren(typeof(U.Collider),true)
        for i=0,cs.Length-1 do local c=cs[i];local info=shape(c)
            local row={type=c:GetType().Name,enabled=c.enabled,trigger=c.isTrigger,
                damage_kind=info.damage_kind,owner_bound=info.damage_owner==original:GetInstanceID()}
            row.direct_root=c.transform==root;row.vertices={}
            if row.type=='BoxCollider'then
                for _,x in ipairs({-1,1})do for _,y in ipairs({-1,1})do for _,z in ipairs({-1,1})do
                    local p=c.transform:TransformPoint(c.center+U.Vector3(x*c.size.x/2,y*c.size.y/2,z*c.size.z/2))
                    row.vertices[#row.vertices+1]=vector(root:InverseTransformPoint(p))
                end end end
            end
            result.colliders[#result.colliders+1]=row
        end
        return result
    end
    local function thornSpawnTemplate()
        local all=U.Resources.FindObjectsOfTypeAll(typeof(CS.EnemyBambooThorn));local original
        for i=0,all.Length-1 do local o=all[i]
            if o.name=='EnemyBambooThorn'and not o.gameObject.activeInHierarchy then
                assert(not original,'Ambiguous original bamboo-thorn prefab');original=o
            end
        end
        if not original then return {missing=true}end
        local root=original.transform;local part=field(original,'_colliderPart')
        local main=field(original,'_mainPart');local bottom=field(original,'_bottomPart')
        if not part or not main or not bottom then return {missing=true}end
        local body=original:GetComponent(typeof(U.Rigidbody))
        local result={id=original:GetInstanceID(),type=original:GetType().Name,source_name='EnemyBambooThorn',
            kinematic=not body or body.isKinematic,gravity=body and body.useGravity or false,callbacks_clear=true,
            gravity_acc=4.5,reverse_run_flip=field(original,'reverseRunFlip'),native_spawn=true,
            part_position=vector(part.localPosition),part_rotation=vector(part.localEulerAngles),part_count=main.childCount,
            chain={},chain_complete=false,native_initialization=true,unknown_hooks={},component_types={},colliders={},
            animated_tree=original:GetComponentsInChildren(typeof(U.Animator),true).Length>0 or
                original:GetComponentsInChildren(typeof(U.Animation),true).Length>0}
        local t=part
        for depth=1,32 do
            if t==root then result.chain_complete=true;break end
            if not t then break end
            result.chain[#result.chain+1]={position=vector(t.localPosition),rotation=vector(t.localEulerAngles),
                scale=vector(t.localScale),part=t==part,main=t==main,bottom=t==bottom}
            t=t.parent
        end
        for _,name in ipairs({'conditionActionEvent','normalActionEvent','collisionActionEvent',
                'collisionExitActionEvent','btAnimatorEvent','conditionParamActionEvent','syncComponent'})do
            if field(original,name)~=nil then result.callbacks_clear=false end
        end
        local graphs=field(original,'allGraphOwners')
        if graphs and graphs.Count>0 then result.callbacks_clear=false end
        local scripts=original:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
        for i=0,scripts.Length-1 do result.component_types[#result.component_types+1]=
            scripts[i]and scripts[i]:GetType().FullName or 'missing_component'end
        for _,entry in ipairs({{typeof(CS.EnemyBambooThorn),'Initialize'},
                {typeof(CS.EnemyBambooThorn),'ResetEnemyInfo'},{typeof(CS.EnemyBambooThorn),'SetHookRadius'},
                {typeof(CS.EnemyBambooThorn),'FixedUpdateMovement'},{typeof(CS.EnemyBambooThorn),'ProcessState'},
                {typeof(CS.EnemyBambooThorn),'MyUpdate'},{typeof(CS.EnemyFissonable),'ResetEnemyInfo'},
                {typeof(CS.EnemyBase),'ResetEnemyInfo'},{typeof(CS.EnemyBase),'FixedUpdateMovement'}})do
            local hook=entry[1]:GetField('__Hotfix0_'..entry[2],staticFlags)
            if not hook or hook:GetValue(nil)~=nil then
                result.native_initialization=false;result.unknown_hooks[#result.unknown_hooks+1]=entry[1].Name..'.'..entry[2]
            end
        end
        for _,name in ipairs({'CheckEnemy','CheckAddEnemyEntity','CreateEnemy'})do
            local hook=typeof(CS.LevelBlockCollider):GetField('__Hotfix0_'..name,staticFlags)
            if not hook or hook:GetValue(nil)~=nil then result.native_spawn=false end
        end
        local cs=original:GetComponentsInChildren(typeof(U.Collider),true)
        for i=0,cs.Length-1 do local c=cs[i];local info=shape(c)
            if info.damage_kind then
                local row={type=c:GetType().Name,enabled=c.enabled,trigger=c.isTrigger,damage_kind=info.damage_kind,
                    owner_bound=info.damage_owner==original:GetInstanceID(),under_part=c.transform:IsChildOf(part),
                    under_visual=c.transform:IsChildOf(main)or c.transform:IsChildOf(bottom),vertices={}}
                if row.type=='BoxCollider'then
                    for _,x in ipairs({-1,1})do for _,y in ipairs({-1,1})do for _,z in ipairs({-1,1})do
                        local p=c.transform:TransformPoint(c.center+U.Vector3(x*c.size.x/2,y*c.size.y/2,z*c.size.z/2))
                        row.vertices[#row.vertices+1]=vector(part:InverseTransformPoint(p))
                    end end end
                end
                result.colliders[#result.colliders+1]=row
            end
        end
        return result
    end
    local function hookSpawnTemplate(name)
        local all=U.Resources.FindObjectsOfTypeAll(typeof(CS.EnemyHook));local original
        for i=0,all.Length-1 do local o=all[i]
            if o.name==name and not o.gameObject.activeInHierarchy then
                assert(not original,'Ambiguous original hook prefab');original=o
            end
        end
        if not original then return {missing=true}end
        local root=original.transform;local head=field(original,'_hatchet');local pole=field(original,'_longHandle')
        if not head or not pole then return {missing=true}end
        head=head.transform;pole=pole.transform
        local body=original:GetComponent(typeof(U.Rigidbody))
        local result={id=original:GetInstanceID(),type=original:GetType().Name,source_name=name,
            kinematic=not body or body.isKinematic,gravity=body and body.useGravity or false,callbacks_clear=true,
            gravity_acc=field(original,'_gravityAcc'),reverse_run_flip=field(original,'reverseRunFlip'),native_spawn=true,
            head_scale=vector(head.localScale),head_rotation=vector(head.localEulerAngles),parent_identity=true,
            native_initialization=true,unknown_hooks={},component_types={},colliders={},
            animated_tree=original:GetComponentsInChildren(typeof(U.Animator),true).Length>0 or
                original:GetComponentsInChildren(typeof(U.Animation),true).Length>0}
        for _,name in ipairs({'conditionActionEvent','normalActionEvent','collisionActionEvent',
                'collisionExitActionEvent','btAnimatorEvent','conditionParamActionEvent','syncComponent'})do
            if field(original,name)~=nil then result.callbacks_clear=false end
        end
        local graphs=field(original,'allGraphOwners')
        if graphs and graphs.Count>0 then result.callbacks_clear=false end
        local parent=head.parent
        while parent and parent~=root do
            local q=parent.localRotation
            if parent.localPosition.magnitude>0.00001 or (parent.localScale-U.Vector3.one).magnitude>0.00001 or
                    math.abs(q.x)+math.abs(q.y)+math.abs(q.z)+math.abs(q.w-1)>0.00001 then result.parent_identity=false end
            parent=parent.parent
        end
        if not parent then result.parent_identity=false end
        local scripts=original:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
        for i=0,scripts.Length-1 do result.component_types[#result.component_types+1]=
            scripts[i]and scripts[i]:GetType().FullName or 'missing_component'end
        for _,entry in ipairs({{typeof(CS.EnemyHook),'ResetEnemyInfo'},
                {typeof(CS.EnemyHook),'SetHookRadius'},{typeof(CS.EnemyHook),'FixedUpdateMovement'},
                {typeof(CS.EnemyHook),'ProcessState'},{typeof(CS.EnemyFissonable),'ResetEnemyInfo'},
                {typeof(CS.EnemyBase),'ResetEnemyInfo'},{typeof(CS.EnemyBase),'FixedUpdateMovement'}})do
            local hook=entry[1]:GetField('__Hotfix0_'..entry[2],staticFlags)
            if not hook or hook:GetValue(nil)~=nil then
                result.native_initialization=false;result.unknown_hooks[#result.unknown_hooks+1]=entry[1].Name..'.'..entry[2]
            end
        end
        for _,name in ipairs({'CheckEnemy','CheckAddEnemyEntity','CreateEnemy'})do
            local hook=typeof(CS.LevelBlockCollider):GetField('__Hotfix0_'..name,staticFlags)
            if not hook or hook:GetValue(nil)~=nil then result.native_spawn=false end
        end
        local cs=original:GetComponentsInChildren(typeof(U.Collider),true)
        for i=0,cs.Length-1 do local c=cs[i];local info=shape(c)
            if info.damage_kind then
                local row={type=c:GetType().Name,enabled=c.enabled,trigger=c.isTrigger,
                    damage_kind=info.damage_kind,owner_bound=info.damage_owner==original:GetInstanceID(),
                    under_head=c.transform:IsChildOf(head),under_pole=c.transform:IsChildOf(pole),vertices={}}
                if row.type=='BoxCollider'then
                    for _,x in ipairs({-1,1})do for _,y in ipairs({-1,1})do for _,z in ipairs({-1,1})do
                        local p=c.transform:TransformPoint(c.center+U.Vector3(x*c.size.x/2,y*c.size.y/2,z*c.size.z/2))
                        row.vertices[#row.vertices+1]=vector(head:InverseTransformPoint(p))
                    end end end
                end
                result.colliders[#result.colliders+1]=row
            end
        end
        return result
    end
    local function swordSpawnTemplate()
        local candidates=U.Resources.FindObjectsOfTypeAll(typeof(CS.EnemySmallSword))
        local original
        for i=0,candidates.Length-1 do local o=candidates[i]
            if o.name=='EnemySmallSword'and not o.gameObject.activeInHierarchy then
                assert(not original,'Ambiguous original sword prefab');original=o
            end
        end
        if not original then return {missing=true}end
        local rotate=field(original,'_rotateObj');local breath=field(original,'breathTween')
        if not rotate then return {missing=true}end
        local root=original.transform;local rt=rotate.transform
        local out={id=original:GetInstanceID(),rotate_position=vector(rt.localPosition),rotate_scale=vector(rt.localScale),
            rotate_direct_parent=rt.parent==root,appear_seconds=field(original,'appearSpendTime'),
            appear_effect_present=field(original,'_appearEffect')~=nil,colliders={}}
        local cs=original.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
        for i=0,cs.Length-1 do local c=cs[i];local s=shape(c)
            if s.damage_kind then
                local row={name=c.name,type=s.type,damage_kind=s.damage_kind,tag=c.tag,
                    under_rotate=c.transform:IsChildOf(rt),enabled=c.enabled,
                    under_breath=breath and c.transform:IsChildOf(breath.transform)or false,vertices={}}
                if s.type=='BoxCollider'then
                    for _,x in ipairs({-1,1})do for _,y in ipairs({-1,1})do for _,z in ipairs({-1,1})do
                        local p=c.transform:TransformPoint(c.center+U.Vector3(x*c.size.x/2,y*c.size.y/2,z*c.size.z/2))
                        row.vertices[#row.vertices+1]=vector(rt:InverseTransformPoint(p))
                    end end end
                end
                out.colliders[#out.colliders+1]=row
            end
        end
        return out
    end
    local syncObjects=field(CS.LevelManager.Instance,'syncObjectDic')
    local function pendingBlock(b,a,stageIndex,blockIndex,uninstantiated)
        local live=liveBlocks[stageIndex..':'..blockIndex]
        local function addItem(info,source)
            local custom=field(info,'_itemInfoCustom')
            local data,projection=valueProjection(custom)
            local item={id='pending-item:'..stageIndex..':'..blockIndex..':'..info:GetHashCode(),
                info_identity=info:GetHashCode(),info=values(info),custom=data,custom_projection=projection,
                custom_type=custom and custom:GetType().Name,
                block_start=vector(live and live.transform.position or a),stage_index=stageIndex,block_index=blockIndex,
                source=source,sync_blocked=syncObjects and syncObjects:ContainsKey(info.baseID)or false}
            if tostring(info._itemType)=='ItemEvent: 100'then item.action_data=actionData(custom,8)end
            if tostring(info._itemType)=='ItemSpring: 15'and not out.spawn_templates.spring then
                out.spawn_templates.spring=springSpawnTemplate()
            end
            local name=tostring(info._itemType):match('^([^:]+):')
            if (name=='ItemMagnet'or name=='ItemElementBall'or name=='ItemFixed'or name=='ItemSkull'or name=='ItemCoinRed')and not out.spawn_templates.items[name]then
                out.spawn_templates.items[name]=staticPickupTemplate(name)
            end
            out.pending_items[#out.pending_items+1]=item
        end
        local function add(info,source)
            local kind=tostring(info._enemyType);local number=tonumber(kind:match(': (%d+)$'))
            if number and number>10000 then return end -- Same native InitEnemyInfo filter.
            local data=values(info);local custom=field(info,'_enemyInfoCustom')
            local customData,projection=valueProjection(custom)
            local blocked=syncObjects and syncObjects:ContainsKey(info.baseID)or false
            out.pending_enemies[#out.pending_enemies+1]={id='pending:'..stageIndex..':'..blockIndex..':'..info:GetHashCode(),
                info_identity=info:GetHashCode(),info=data,custom=customData,custom_projection=projection,
                custom_type=custom and custom:GetType().Name,
                block_start=vector(live and live.transform.position or a),stage_index=stageIndex,block_index=blockIndex,
                source=source,sync_blocked=blocked,vertical_gate=live and field(live,'openGenerateDistanceY')or false}
            if kind=='EnemyGhostFire: 205'then
                out.spawn_templates.curves=out.spawn_templates.curves or{}
                if not out.spawn_templates.curves.EnemyGhostFire then out.spawn_templates.curves.EnemyGhostFire=ghostSpawnTemplate()end
            end
            if kind=='EnemyBambooThorn: 120'then
                out.spawn_templates.hooks=out.spawn_templates.hooks or{}
                if not out.spawn_templates.hooks.EnemyBambooThorn then out.spawn_templates.hooks.EnemyBambooThorn=thornSpawnTemplate()end
            end
            if kind=='EnemyGoldHook: 289'or kind:match('^EnemyHook: ')then
                out.spawn_templates.hooks=out.spawn_templates.hooks or{}
                local name=kind:match('^(.-): ')
                if not out.spawn_templates.hooks[name]then out.spawn_templates.hooks[name]=hookSpawnTemplate(name)end
            end
            if kind=='EnemyCurveBat: 204'or kind=='EnemyCurveCrow: 224'or kind=='EnemyCurveFireFairy: 229'then
                out.spawn_templates.curves=out.spawn_templates.curves or{}
                local name=kind:match('^(.-): ')
                if not out.spawn_templates.curves[name]then out.spawn_templates.curves[name]=curveSpawnTemplate(name)end
            end
            if kind=='EnemySuspendBalloon: 235'then
                out.spawn_templates.suspends=out.spawn_templates.suspends or{}
                local name=kind:match('^(.-): ')
                if not out.spawn_templates.suspends[name]then out.spawn_templates.suspends[name]=suspendSpawnTemplate(name)end
                local q=U.Quaternion.Euler(U.Vector3(info._localEulerAngles.x,info._localEulerAngles.y,info._localEulerAngles.z))
                out.pending_enemies[#out.pending_enemies].pose_rotation={x=q.x,y=q.y,z=q.z,w=q.w}
            end
            if kind=='EnemySmallSword: 250'and not out.spawn_templates.small_sword then
                out.spawn_templates.small_sword=swordSpawnTemplate()
            end
            local bladeNames={['EnemyBlade: 101']=true,['EnemyBlade2: 107']=true,['EnemyBlade3: 108']=true,
                ['EnemyBlade4: 109']=true,['EnemyBlade6: 116']=true,['EnemyBladeGold: 241']=true}
            if bladeNames[kind]then
                local q=U.Quaternion.Euler(U.Vector3(info._localEulerAngles.x,
                    info._localEulerAngles.y,info._localEulerAngles.z))
                out.pending_enemies[#out.pending_enemies].pose_rotation={x=q.x,y=q.y,z=q.z,w=q.w}
                out.spawn_templates.blades=out.spawn_templates.blades or{}
                local name=kind:match('^(.-): ')
                if not out.spawn_templates.blades[name]then out.spawn_templates.blades[name]=bladeSpawnTemplate(name)end
            end
        end
        if live then
            -- The original linked list contains only unconsumed spawns.
            -- PreloadEnemyList and the full authored list include enemies
            -- which were already created/recycled and cannot substitute it.
            local list=field(live,'enemyList');assert(list,'Original enemy queue missing')
            local node=list.First;local count=0
            while node do add(node.Value,'native_enemyList');count=count+1;node=node.Next end
            assert(count==list.Count,'Original spawn queue changed during paused read')
            local items=field(live,'itemList');assert(items,'Original item queue missing')
            node=items.First;count=0
            while node do addItem(node.Value,'native_itemList');count=count+1;node=node.Next end
            assert(count==items.Count,'Original item queue changed during paused read')
        elseif uninstantiated then
            local infos=field(b,'enemyInfos')
            if infos then for i=0,infos.Count-1 do add(infos[i],'resolved_uninstantiated_block')end end
            local items=field(b,'itemInfos')
            if items then for i=0,items.Count-1 do addItem(items[i],'resolved_uninstantiated_block')end end
        end
    end
    if stage and ground then
        local blocks=field(stage,'_finalBlockList');local anchor=ground.BelongToBlockIndex
        if anchor>=0 and anchor<blocks.Count then
            local starts={};starts[anchor]=ground.PointStart
            for i=anchor+1,blocks.Count-1 do local previous=blocks[i-1]
                starts[i]=starts[i-1]+U.Vector3(previous._pointEnd.x-previous._pointStart.x,
                    previous._pointEnd.y-previous._pointStart.y,0)
            end
            for i=anchor-1,0,-1 do local b=blocks[i]
                starts[i]=starts[i+1]-U.Vector3(b._pointEnd.x-b._pointStart.x,b._pointEnd.y-b._pointStart.y,0)
            end
            for i=0,blocks.Count-1 do local b=blocks[i]
                local a=starts[i]
                local z=a+U.Vector3(b._pointEnd.x-b._pointStart.x,b._pointEnd.y-b._pointStart.y,0)
                if z.x>p.x-8 and a.x<p.x+80 then
                    out.terrain[#out.terrain+1]={id='resolved:'..index..':'..i,start=vector(a),finish=vector(z),
                        kind=tostring(b._groundType),hidden=b._hideGround,block_index=i,stage_index=index,
                        death_offset_y=b._isDeadBlockOffsetY,speed=b._ninjaSpeed}
                    pendingBlock(b,a,index,i,i>anchor)
                end
            end
            local tail=blocks[blocks.Count-1]
            local nextStart=starts[blocks.Count-1]+U.Vector3(tail._pointEnd.x-tail._pointStart.x,
                tail._pointEnd.y-tail._pointStart.y,0)
            out.board.finish=vector(nextStart)
            -- Adjacent resolved stages share the original endpoint. Include
            -- their terrain before native object instantiation catches up.
            for nextIndex=index+1,math.min(index+2,stages.Count-1)do
                local nextBlocks=field(stages[nextIndex],'_finalBlockList')
                for i=0,nextBlocks.Count-1 do local b=nextBlocks[i];local a=nextStart
                    local z=a+U.Vector3(b._pointEnd.x-b._pointStart.x,b._pointEnd.y-b._pointStart.y,0)
                    if z.x>p.x-8 and a.x<p.x+80 then
                        out.terrain[#out.terrain+1]={id='resolved:'..nextIndex..':'..i,start=vector(a),finish=vector(z),
                            kind=tostring(b._groundType),hidden=b._hideGround,block_index=i,stage_index=nextIndex,
                            death_offset_y=b._isDeadBlockOffsetY,speed=b._ninjaSpeed}
                        pendingBlock(b,a,nextIndex,i,true)
                    end
                    nextStart=z
                end
            end
        end
    end
    if not out.spawn_templates.spring then
        for _,item in ipairs(out.mechanism_items)do if item.type=='ItemSpring'then
            out.spawn_templates.spring=springSpawnTemplate();break
        end end
    end
    for _,item in ipairs(out.mechanism_items)do
        if (item.type=='ItemMagnet'or item.type=='ItemElementBall'or item.type=='ItemFixed'or item.type=='ItemSkull')and not out.spawn_templates.items[item.type]then
            out.spawn_templates.items[item.type]=staticPickupTemplate(item.type)
        end
    end
    return out
end
return true
