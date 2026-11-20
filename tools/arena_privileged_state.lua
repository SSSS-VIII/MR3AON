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
        if tp.IsPrimitive or tp.IsEnum or name=='UnityEngine.Vector3'or name=='UnityEngine.Vector2' then
            local v=f:GetValue(obj)
            if v~=nil then
                if tp.IsEnum then out[f.Name]=tostring(v)
                elseif name=='UnityEngine.Vector3' then out[f.Name]=vector(v)
                elseif name=='UnityEngine.Vector2' then out[f.Name]={x=v.x,y=v.y}
                else out[f.Name]=v end
            end
        end
    end
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
    for i=0,supports.Length-1 do local s=supports[i]
        if s.enabled and s.isActive and s.gameObject.activeInHierarchy and s.PointEnd.x>p.x-8 and s.PointStart.x<p.x+80 then
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
    local brambleOwners={};local needBrambleTimers=false
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
            row.info_identity=info and info:GetHashCode()or nil
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
    local physicalItems={ItemSpring=true,ItemHorn=true,ItemSkull=true,ItemShell=true,ItemShieldBall=true,
        ItemBossController=true,ItemSpecialTaskStart=true,ItemSpecialTaskEnd=true,ItemEvent=true}
    local items=U.Object.FindObjectsOfType(typeof(CS.ItemBase))
    for i=0,items.Length-1 do local o=items[i];local kind=o:GetType().Name
        if physicalItems[kind] and o.gameObject.activeInHierarchy and o.isActive and
                o.transform.position.x>p.x-2 and o.transform.position.x<p.x+80 then
            local info=field(o,'_itemInfo');local custom=info and field(info,'_itemInfoCustom')
            local item={id=o:GetInstanceID(),type=kind,
                position=vector(o.transform.position),fields=values(o),info=values(info),custom=values(custom)}
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
    out.terrain={}
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
                    end
                    nextStart=z
                end
            end
        end
    end
    return out
end
return true
