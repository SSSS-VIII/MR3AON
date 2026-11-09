-- Paused ground truth for annotation/verification. Never an actor input.
local E,U=MR3A,CS.UnityEngine
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
 local n=CS.NinjaController.Instance.NinjaScript
 local out={frame=U.Time.frameCount,tick=CS.GameManager.Instance.GameInfo._totalFrameCount,
  time=CS.GameManager.Instance.GameInfo._totalTime,engineTime=U.Time.time,width=640,height=360,
  physics=E.state().physics,health=n.CurrentHp,role={point=point(n.transform.position),colliders={}},objects={}}
 local cols=n.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
 for i=0,cols.Length-1 do local c=cols[i]
  if c.enabled and c.name=='Role' then out.role.colliders[#out.role.colliders+1]={name=c.name,box=box(c.bounds)}end
 end
 local objects=U.Object.FindObjectsOfType(typeof(CS.EnemyBase))
 for i=0,objects.Length-1 do local o=objects[i]
  if o.gameObject.activeInHierarchy and o.isActive then
   local row={id=o:GetInstanceID(),type=o:GetType().Name,name=o.name,point=point(o.transform.position),colliders={}}
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
   for j=0,renderers.Length-1 do local r=renderers[j]
    local spriteVisible=r:GetType().Name~='SpriteRenderer' or r.color.a>.1
    if r.enabled and r.gameObject.activeInHierarchy and spriteVisible and r:GetType().Name~='ParticleSystemRenderer'
     and (not hasModel or selected[r:GetInstanceID()]) then
     row.renderers[#row.renderers+1]={name=r.name,type=r:GetType().Name,box=box(r.bounds)}
    end
   end
   local cs=o.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
   for j=0,cs.Length-1 do local c=cs[j]
    if c.enabled then local b=box(c.bounds)
     if b[3]>b[1] and b[4]>b[2] then row.colliders[#row.colliders+1]={name=c.name,box=b,
      type=c:GetType().Name,trigger=c.isTrigger,layer=c.gameObject.layer,tag=c.tag}end
    end
   end
   out.objects[#out.objects+1]=row
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
return true
