-- Paused ground truth for annotation/verification. Never an actor input.
local E,U=MR3A,CS.UnityEngine
local inspectFlags=CS.System.Reflection.BindingFlags.__CastFrom(52)
local deadField=typeof(CS.EnemyBase):GetField('_dead',inspectFlags)
local enemyInfoField=typeof(CS.EnemyBase):GetField('_enemyInfo',inspectFlags)
local enemyPropertyField=typeof(CS.EnemyBase):GetField('_enemyBaseProperty',inspectFlags)
local callbackOwnerField=typeof(CS.EnemyBaseCollider):GetField('_enemy',inspectFlags)
local supportType=typeof(CS.LevelBlockCollider)
local airGroundType=typeof(CS.ItemAirGround)
local supportDataField=supportType:GetField('_levelBlockInfo',inspectFlags)
local controllerTypes={}
local parameterIds={enemy_infos={},base_properties={}}
local parameterCounts={enemy_infos=0,base_properties=0}
local function register_parameters(kind,value,updates)
 if not value then return nil end
 local id=parameterIds[kind][value]
 if id then return id end
 id=parameterCounts[kind]+1;parameterCounts[kind]=id;parameterIds[kind][value]=id
 local entry={id=id,type=value:GetType().FullName}
 local ok,data=pcall(function()return json.parse(U.JsonUtility.ToJson(value))end)
 if ok then entry.initial_parameters=data else entry.error=tostring(data)end
 updates[kind][#updates[kind]+1]=entry
 return id
end
local function controller_fields(tp)
 local key=tp.FullName
 if controllerTypes[key]then return controllerTypes[key]end
 local fields={}
 for _,name in ipairs({'_currState','_enemyState','_currStateTime','_stayTime','_rushDistance','_currAnim',
  '_aimSpeed','_flySpeed','_lastAttackPos','_lastAimLinePos',
  '_moveSpeed','_currentMoveSpeed','_rushSpeed','_rotateSpeed','_rotationSpeed','_angleSpeed','_shootTime',
  '_shootInterval','_shootTimer','_currTime','_delayTime','_remainTime','_rushDir','_moveDir','_direction'})do
  local parent=tp
  while parent do
   local f=parent:GetField(name,inspectFlags)
   if f then fields[name]=f;break end
   parent=parent.BaseType
  end
 end
 controllerTypes[key]=fields
 return fields
end
function E.vision_labels(include_scene)
 local cam=U.Camera.main
 local function point(p)
  local q=cam:WorldToViewportPoint(p)
  return {x=q.x*640,y=(1-q.y)*360,z=q.z}
 end
 local function box(bounds)
  local lo,hi=bounds.min,bounds.max
  local x1,y1,x2,y2=100000,100000,-100000,-100000
  for _,x in ipairs({lo.x,hi.x})do for _,y in ipairs({lo.y,hi.y})do for _,z in ipairs({lo.z,hi.z})do
   local p=point(U.Vector3(x,y,z))
   x1=math.min(x1,p.x);y1=math.min(y1,p.y);x2=math.max(x2,p.x);y2=math.max(y2,p.y)
  end end end
  return {x1,y1,x2,y2}
 end
 local function vector(p)return {x=p.x,y=p.y,z=p.z}end
 local function matrix(m)return {m.m00,m.m01,m.m02,m.m03,m.m10,m.m11,m.m12,m.m13,
  m.m20,m.m21,m.m22,m.m23,m.m30,m.m31,m.m32,m.m33}end
 local function collider(c,owner)
  local kind=c:GetType().Name
  local rotation=c.transform.rotation
  local row={id=c:GetInstanceID(),owner_id=owner,name=c.name,box=box(c.bounds),type=kind,
   bounds_center=vector(c.bounds.center),bounds_extents=vector(c.bounds.extents),
   trigger=c.isTrigger,layer=c.gameObject.layer,tag=c.tag,local_to_world=matrix(c.transform.localToWorldMatrix),
   lossy_scale=vector(c.transform.lossyScale),world_rotation={x=rotation.x,y=rotation.y,z=rotation.z,w=rotation.w}}
  local callback=c.gameObject:GetComponent(typeof(CS.EnemyBaseCollider))
  if callback and callbackOwnerField then
   local target=callbackOwnerField:GetValue(callback)
   if target then row.callback_owner_id=target:GetInstanceID()end
  end
  if kind=='BoxCollider' then
   row.center=vector(c.center);row.world_center=vector(c.transform:TransformPoint(c.center));row.size=vector(c.size);row.plane_quad={}
   for _,sign in ipairs({{-1,-1},{1,-1},{1,1},{-1,1}})do
    local p=c.center+U.Vector3(sign[1]*c.size.x/2,sign[2]*c.size.y/2,0)
    row.plane_quad[#row.plane_quad+1]=point(c.transform:TransformPoint(p))
   end
  elseif kind=='SphereCollider'or kind=='CapsuleCollider' then
   row.center=vector(c.center);row.world_center=vector(c.transform:TransformPoint(c.center));row.radius=c.radius
   if kind=='CapsuleCollider'then row.height=c.height;row.direction=c.direction end
   local b=c.bounds
   row.plane_quad={point(U.Vector3(b.min.x,b.min.y,b.center.z)),point(U.Vector3(b.max.x,b.min.y,b.center.z)),
    point(U.Vector3(b.max.x,b.max.y,b.center.z)),point(U.Vector3(b.min.x,b.max.y,b.center.z))}
  end
  return row
 end
 local n=CS.NinjaController.Instance.NinjaScript
 local out={label_schema=4,frame=U.Time.frameCount,tick=CS.GameManager.Instance.GameInfo._totalFrameCount,
  time=CS.GameManager.Instance.GameInfo._totalTime,engineTime=U.Time.time,width=640,height=360,
  physics=E.state().physics,health=n.CurrentHp,god=n:IsGodMode(),mounted=n.IsMountState,
  role={point=point(n.transform.position),colliders={}},objects={},supports={},
  parameter_updates={enemy_infos={},base_properties={}},parameter_reference_base=1,
  camera={projection=matrix(cam.projectionMatrix),world_to_camera=matrix(cam.worldToCameraMatrix)}}
 local cols=n.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
 for i=0,cols.Length-1 do local c=cols[i]
  if c.enabled and c.gameObject.activeInHierarchy and c.name=='Role' then
   out.role.colliders[#out.role.colliders+1]=collider(c,n:GetInstanceID())
  end
 end
 local objects=U.Object.FindObjectsOfType(typeof(CS.EnemyBase))
 for i=0,objects.Length-1 do local o=objects[i]
  if o.gameObject.activeInHierarchy and o.isActive then
   local row={id=o:GetInstanceID(),type=o:GetType().Name,name=o.name,point=point(o.transform.position),colliders={}}
   row.dead=deadField:GetValue(o)
   local info=enemyInfoField:GetValue(o)
   if info then row.source_type_id=CS.System.Convert.ToInt32(info._enemyType)end
   row.enemy_info_reference=register_parameters('enemy_infos',info,out.parameter_updates)
   row.family_type_id=row.source_type_id;row.resource_family=o.name
   local property=enemyPropertyField:GetValue(o)
   if property then
    row.base_property_reference=register_parameters('base_properties',property,out.parameter_updates)
    -- Optional diagnostic values: failure must stay explicit and must not
    -- discard the original geometry/labels or alter the native enemy.
    local ok,value=pcall(function()
     return {current_speed=o.CurrentSpeed,
      max_health=o.MaxHp,current_health=o.CurrentHp,damage_ratio=o.DamageRatio,
      damage_type=tostring(o.EnemyDamageType),has_damaged_role=o.DamageRole}
    end)
    if ok then row.runtime_parameters=value else row.runtime_parameters_error=tostring(value)end
   end
   local ancestor=o.transform.parent and o.transform.parent:GetComponentInParent(typeof(CS.EnemyBase))
   if ancestor then row.parent_enemy_id=ancestor:GetInstanceID()end
   while ancestor and (not row.family_type_id or row.family_type_id==0)do
    local parentInfo=enemyInfoField:GetValue(ancestor)
    if parentInfo then
     local id=CS.System.Convert.ToInt32(parentInfo._enemyType)
     if id~=0 then row.family_type_id=id;row.resource_family=ancestor.name end
    end
    ancestor=ancestor.transform.parent and ancestor.transform.parent:GetComponentInParent(typeof(CS.EnemyBase))
   end
   row.controller={}
   if typeof(CS.EnemyStraightBat):IsAssignableFrom(o:GetType())then row.motion_family='straight_bat'end
   for name,f in pairs(controller_fields(o:GetType()))do
     local value=f:GetValue(o)
     if f.FieldType.IsEnum then row.controller[name]=tostring(value)
     elseif f.FieldType.IsPrimitive or f.FieldType.FullName=='System.String'then row.controller[name]=value
     elseif f.FieldType.FullName=='UnityEngine.Vector3'and value then row.controller[name]=vector(value)end
   end
   row.renderers={}
   local renderers=o.gameObject:GetComponentsInChildren(typeof(U.Renderer),true)
   local selected={};local hasModel=false
   local field=typeof(CS.EnemyBase):GetField('_allRenderObj',CS.System.Reflection.BindingFlags.__CastFrom(52))
   if field then local groups=field:GetValue(o)
    if groups then local count=groups:GetType().IsArray and groups.Length or groups.Count
     for k=0,count-1 do if groups[k] then
      local parts=groups[k]:GetComponentsInChildren(typeof(U.Renderer),true)
      for q=0,parts.Length-1 do selected[parts[q]:GetInstanceID()]=true;hasModel=true end
     end end
    end
   end
   local particles={}
   for j=0,renderers.Length-1 do local r=renderers[j]
    local spriteVisible=r:GetType().Name~='SpriteRenderer' or r.color.a>.1
    local owner=r:GetComponentInParent(typeof(CS.EnemyBase))
    if r.enabled and r.gameObject.activeInHierarchy and spriteVisible
     and owner and owner:GetInstanceID()==row.id
     and (not hasModel or selected[r:GetInstanceID()]) then
     local visual={name=r.name,type=r:GetType().Name,box=box(r.bounds)}
     if r:GetType().Name=='ParticleSystemRenderer' then
      local system=r:GetComponent(typeof(U.ParticleSystem))
      if system and system.particleCount>0 then particles[#particles+1]=visual end
     else row.renderers[#row.renderers+1]=visual end
    end
   end
   if #row.renderers==0 and #particles>0 then row.renderers=particles;row.particle_only=true end
   local cs=o.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
   for j=0,cs.Length-1 do local c=cs[j]
    local owner=c:GetComponentInParent(typeof(CS.EnemyBase))
    if c.enabled and c.gameObject.activeInHierarchy and owner and owner:GetInstanceID()==row.id then
     local b=box(c.bounds)
     if b[3]>b[1] and b[4]>b[2] then row.colliders[#row.colliders+1]=collider(c,row.id)end
    end
   end
   out.objects[#out.objects+1]=row
  end
 end
 local ground=n._GroundCollider
 out.stage_index=ground and ground.BelongToStageIndex or -1
 out.support_id=ground and ground:GetInstanceID()or nil
 out.base_support_id=out.support_id
 local airSupport=n.OnAirGround
 out.air_support_source_id=airSupport and not airSupport._isFree and airSupport.sourceId or nil
 if airSupport and not airSupport._isFree then
  out.air_reference={left=airSupport._leftX,right=airSupport._rightX,top=airSupport._topY,bottom=airSupport._bottomY}
 end
 out.block_index=ground and ground.BelongToBlockIndex or -1
 local level=CS.LevelManager.Instance.GameLevelInfo
 local stages=level:GetType():GetField('_stageList',inspectFlags):GetValue(level)
 if out.stage_index>=0 and out.stage_index<stages.Count then
  local stage=stages[out.stage_index]
  out.stage_id=stage:GetType():GetField('_stageBaseInfo',inspectFlags):GetValue(stage)._stageID
 end
 if ground then
  local supports=U.Object.FindObjectsOfType(supportType)
  for i=0,supports.Length-1 do local support=supports[i]
   if support.enabled and support.isActive and support.gameObject.activeInHierarchy then
    local a,b=point(support.PointStart),point(support.PointEnd)
    if a.z>0 and b.z>0 and math.max(a.x,b.x)>-16 and math.min(a.x,b.x)<656
     and math.max(a.y,b.y)>-16 and math.min(a.y,b.y)<376 then
     local data=supportDataField:GetValue(support)
     out.supports[#out.supports+1]={id=support:GetInstanceID(),start=a,finish=b,
      kind=support.IsLine and 'rope' or support.IsGround and 'platform' or 'other',
      stage_index=support.BelongToStageIndex,block_index=support.BelongToBlockIndex,
      hidden=data._hideGround,has_air_ground=support.HasAirGround,
      death_offset_y=data._isDeadBlockOffsetY,ground_type=tostring(data._groundType),switch=tostring(support.groundSwitchType)}
    end
   end
  end
 end
 local platforms=U.Object.FindObjectsOfType(airGroundType)
 for i=0,platforms.Length-1 do local platform=platforms[i];local info=platform.AirGroundInfo
  if platform.enabled and platform.isActive and platform.gameObject.activeInHierarchy and info and not info._isFree then
   local z=platform.transform.position.z
   local a,b=point(U.Vector3(info._leftX,info._topY,z)),point(U.Vector3(info._rightX,info._topY,z))
   if a.z>0 and b.z>0 and math.max(a.x,b.x)>-16 and math.min(a.x,b.x)<656
    and math.max(a.y,b.y)>-16 and math.min(a.y,b.y)<376 then
    local visible=false
    local renderers=platform:GetComponentsInChildren(typeof(U.Renderer),true)
    for j=0,renderers.Length-1 do local r=renderers[j]
     if r.enabled and r.gameObject.activeInHierarchy and(r:GetType().Name~='SpriteRenderer'or r.color.a>.1)then visible=true end
    end
    out.supports[#out.supports+1]={id=platform:GetInstanceID(),source='ItemAirGround',source_id=info.sourceId,
     start=a,finish=b,kind='platform',floating=true,hidden=not visible,
     transparent=info._transparent,avoid_fall=info._isAvoidFall,
     speed={x=info._speedX,y=info._speedY},world_top=info._topY,world_bottom=info._bottomY,
     world_left=info._leftX,world_right=info._rightX}
    -- Ordinary generated platforms can all have sourceId=0; compare the
    -- actual native AirGroundInfo reference instead of treating it as an ID.
    if airSupport and CS.System.Object.ReferenceEquals(info,airSupport)then
     out.air_reference_id=platform:GetInstanceID();out.support_id=out.air_reference_id
    end
   end
  end
 end
 if include_scene then
  out.scene_colliders={}
  local colliders=U.Object.FindObjectsOfType(typeof(U.Collider))
  for i=0,colliders.Length-1 do local c=colliders[i]
   if c.enabled and c.gameObject.activeInHierarchy then local b=box(c.bounds)
    if b[3]>0 and b[1]<640 and b[4]>0 and b[2]<360 and b[3]>b[1] and b[4]>b[2] then
     out.scene_colliders[#out.scene_colliders+1]={name=c.name,type=c:GetType().Name,box=b,
      trigger=c.isTrigger,layer=c.gameObject.layer,tag=c.tag}
    end
   end
  end
  local ground=n._GroundCollider
  if ground then
   local flags=CS.System.Reflection.BindingFlags.__CastFrom(52)
   local fields=ground:GetType():GetFields(flags)
   out.ground={type=ground:GetType().FullName,fields={}}
   for i=0,fields.Length-1 do local f=fields[i]
    local ok,value=pcall(function()return f:GetValue(ground)end)
    local name=f.FieldType.FullName
    if ok and value~=nil then
     if f.FieldType.IsPrimitive then out.ground.fields[f.Name]=value
     elseif f.FieldType.IsEnum then out.ground.fields[f.Name]=tostring(value)
     elseif name=='UnityEngine.Vector2' then out.ground.fields[f.Name]={x=value.x,y=value.y}
     elseif name=='UnityEngine.Vector3' then out.ground.fields[f.Name]={x=value.x,y=value.y,z=value.z}end
    end
   end
  end
 end
 return out
end

function E.vision_resolved_layout()
 local function get(o,key)return o:GetType():GetField(key,inspectFlags):GetValue(o)end
 local level=CS.LevelManager.Instance.GameLevelInfo
 local ground=CS.NinjaController.Instance.NinjaScript._GroundCollider
 assert(ground,'A native support is required to identify the selected stage')
 local index=ground.BelongToStageIndex;local stages=get(level,'_stageList')
 assert(index>=0,'The native support has no stage index')
 local stage=index<stages.Count and stages[index]or get(level,'_currLoopStage')
 assert(stage,'The selected native stage has not been generated')
 local out={stage_id=get(stage,'_stageBaseInfo')._stageID,stage_index=index,
  stage_start=stage.StageStartX,blocks={}}
 local blocks=get(stage,'_finalBlockList')
 local origin=blocks.Count>0 and blocks[0]._pointStart.x or 0
 for i=0,blocks.Count-1 do
  local data=blocks[i];local row={index=i,ground_type=tostring(data._groundType),enemies={},
   start_x=stage.StageStartX+data._pointStart.x-origin,finish_x=stage.StageStartX+data._pointEnd.x-origin}
  if data.enemyInfos then
   for j=0,data.enemyInfos.Count-1 do local info=data.enemyInfos[j]
    local p=info._localPosition
    row.enemies[#row.enemies+1]={source_type_id=CS.System.Convert.ToInt32(info._enemyType),position=p and {x=p.x,y=p.y,z=p.z}or {}}
   end
  end
  out.blocks[#out.blocks+1]=row
 end
 return out
end
return true
