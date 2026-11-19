-- Read-only internal controller input. Separate from pixel observations and
-- from the stopped checkpoint search; no gameplay field or callback is changed.
local E,U=MR3A,CS.UnityEngine
local flags=CS.System.Reflection.BindingFlags.__CastFrom(52)
local cache={}
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
local function shape(c)
    local tp=c:GetType().Name
    local out={id=c:GetInstanceID(),name=c.name,type=tp,enabled=c.enabled,
        active=c.gameObject.activeInHierarchy,parent_active=c.transform.parent and c.transform.parent.gameObject.activeInHierarchy or false,
        tag=c.tag,trigger=c.isTrigger,
        position=vector(c.transform.position),scale=vector(c.transform.lossyScale),
        rotation_z=c.transform.eulerAngles.z}
    local b=c.bounds;out.center=vector(b.center);out.extents=vector(b.extents)
    if tp=='BoxCollider'then
        out.local_center=vector(c.center);out.size=vector(c.size);out.quad={}
        local lo,hi=U.Vector3(1e9,1e9,1e9),U.Vector3(-1e9,-1e9,-1e9)
        for _,sign in ipairs({{-1,-1},{1,-1},{1,1},{-1,1}})do
            local p=c.transform:TransformPoint(c.center+U.Vector3(sign[1]*c.size.x/2,sign[2]*c.size.y/2,0))
            out.quad[#out.quad+1]=vector(p)
            lo=U.Vector3.Min(lo,p);hi=U.Vector3.Max(hi,p)
        end
        out.center=vector(c.transform:TransformPoint(c.center))
        out.extents=vector((hi-lo)/2)
        out.extents.z=math.abs(c.size.z*c.transform.lossyScale.z/2)
    elseif tp=='SphereCollider'or tp=='CapsuleCollider'then
        out.local_center=vector(c.center);out.center=vector(c.transform:TransformPoint(c.center))
        out.radius=c.radius
        if tp=='CapsuleCollider'then out.height=c.height;out.direction=c.direction end
    end
    local attack=c.gameObject:GetComponent(typeof(CS.EnemyAttackModule))
    local callback=c.gameObject:GetComponent(typeof(CS.EnemyBaseCollider))
    local owner=attack and field(attack,'_belongToEnemy')or callback and field(callback,'_enemy')
    out.damage_kind=attack and 'attack_module'or callback and 'enemy_callback'or c.tag=='Enemy'and 'enemy_tag'or nil
    if owner then out.damage_owner=owner:GetInstanceID()end
    return out
end
function E.privileged_state()
    assert(not E.busy and U.Time.timeScale==0,'Read internal state at a paused original boundary')
    local n=CS.NinjaController.Instance.NinjaScript;local p=n.transform.position
    local out={schema=1,privileged=true,state=E.state(),role={},enemies={},supports={},platforms={}}
    local camera=CS.CameraController.Instance
    out.camera={right=vector(camera:GetScreenRightTopPos()),real_right=vector(camera:GetRealScreenRightTopPos()),
        reflection_right=vector(camera:GetScreenRightTopPos_Reflection(0)),
        position=vector(camera.LastPosition),direction=CS.GameManager.Instance.CurrDirModeNum}
    out.role.fields=values(n);out.role.velocity=vector(n.Velocity);out.role.gravity=n.Gravity
    local staticFlags=CS.System.Reflection.BindingFlags.__CastFrom(56)
    local ninjaType=typeof(CS.Ninja)
    local reverseFlag=ninjaType:GetField('isEnterRollToLineDownReviseVelocityFlag',staticFlags)
    local reverseOffset=ninjaType:GetField('InAirOffsetWhenEnterRollToLineDown',staticFlags)
    assert(reverseFlag and reverseOffset,'Original reversal rules missing')
    out.role.rules={reverse_fast_enabled=reverseFlag:GetValue(nil),reverse_fast_offset=reverseOffset:GetValue(nil)}
    out.role.data=values(field(n,'_ninjaData'));out.role.collider_parameters=values(field(n,'_ninjiaCollider'))
    out.role.colliders={};out.role.god=n:IsGodMode();out.role.mounted=n.IsMountState
    local cols=n.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
    for i=0,cols.Length-1 do local c=cols[i]
        if c.enabled and c.gameObject.activeInHierarchy and c.name=='Role'then
            out.role.colliders[#out.role.colliders+1]=shape(c)
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
    for i=0,enemies.Length-1 do local o=enemies[i]
        if o.gameObject.activeInHierarchy and o.isActive and math.abs(o.transform.position.x-p.x)<80 then
            local info=field(o,'_enemyInfo');local custom=info and field(info,'_enemyInfoCustom')
            local row={id=o:GetInstanceID(),type=o:GetType().Name,name=o.name,position=vector(o.transform.position),
                fields=values(o),info=values(info),custom=values(custom),custom_type=custom and custom:GetType().Name or nil,
                speed=o.CurrentSpeed,scale=vector(o.transform.lossyScale),colliders={}}
            row.info_identity=info and info:GetHashCode()or nil
            row.controllers={}
            for _,f in ipairs(fields(o))do
                if string.find(f.FieldType.Name,'Controller',1,true)then
                    local v=f:GetValue(o)
                    if v then row.controllers[f.Name]={type=v:GetType().Name,fields=values(v)}end
                end
            end
            local cs=o.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
            for j=0,cs.Length-1 do local c=cs[j];local owner=c:GetComponentInParent(typeof(CS.EnemyBase))
                if owner and owner:GetInstanceID()==row.id then row.colliders[#row.colliders+1]=shape(c)end
            end
            out.enemies[#out.enemies+1]=row
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
