-- Isolated native prefab previews. No game ticks, factory spawn or gameplay AI.
local E,U=MR3A,CS.UnityEngine
function E.preview_asset(name,filename)
 assert(U.Time.timeScale==0 and not E.busy,'Pause the original client before previewing')
 assert(type(name)=='string' and not string.find(name,'[/\\]'),'Use an original resource name')
 assert(type(filename)=='string' and string.match(filename,'^[%w_-]+%.png$'),'Invalid preview filename')
 local parent,cameraObject,texture,image,handler
 local previous=U.RenderTexture.active
 local result
 local ok,err=pcall(function()
  local full=CS.BaseFramework.Resource.ResourceUtils.GetPrefabFullPath(name)
  assert(full and full~='','Resource name absent from original manifest')
  local method=xlua.get_generic_method(CS.BaseFramework.Resource.ResourceManager,'LoadAsset')(U.GameObject)
  handler=method(CS.BaseFramework.Resource.ResourceManager.Instance,full)
  assert(handler and handler.IsDone,'Original resource did not synchronously load')
  local prefab=handler.Result
  assert(prefab,'Original prefab is empty')
  parent=U.GameObject('MR3A_AssetPreview');parent:SetActive(false)
  local clone=U.Object.Instantiate(prefab,parent.transform,false)
  local behaviours=clone:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
  for i=0,behaviours.Length-1 do behaviours[i].enabled=false end
  local colliders=clone:GetComponentsInChildren(typeof(U.Collider),true)
  local originalEnabled={}
  -- Disable preview contacts without changing the original prefab or live actors.
  for i=0,colliders.Length-1 do originalEnabled[i]=colliders[i].enabled;colliders[i].enabled=false end
  local transforms=clone:GetComponentsInChildren(typeof(U.Transform),true)
  for i=0,transforms.Length-1 do transforms[i].gameObject.layer=30 end
  parent.transform.position=U.Vector3(10000,10000,0)
  parent:SetActive(true)
  local poses={}
  for i=0,behaviours.Length-1 do local b=behaviours[i]
   if b:GetType().Name=='SkeletonAnimation' then
    local initialized,error=pcall(function()b:Initialize(true);b:Update(0);b:LateUpdate()end)
    poses[#poses+1]={type=b:GetType().FullName,initialized=initialized,error=not initialized and tostring(error) or nil}
   end
  end
  local renderers=clone:GetComponentsInChildren(typeof(U.Renderer),true)
  local modelRenderers={};local selectedModel=false
  local enemy=clone:GetComponent(typeof(CS.EnemyBase))
  if enemy then
   local field=typeof(CS.EnemyBase):GetField('_allRenderObj',CS.System.Reflection.BindingFlags.__CastFrom(52))
   if field then local objects=field:GetValue(enemy)
    if objects then
     local count=objects:GetType().IsArray and objects.Length or objects.Count
     for i=0,count-1 do if objects[i] then
      local rs=objects[i]:GetComponentsInChildren(typeof(U.Renderer),true)
      for j=0,rs.Length-1 do modelRenderers[rs[j]:GetInstanceID()]=true;selectedModel=true end
     end end
    end
   end
  end
  local bounds=nil;local count=0
  for i=0,renderers.Length-1 do local r=renderers[i]
   if r.enabled and r.gameObject.activeInHierarchy and r:GetType().Name~='ParticleSystemRenderer'
    and (not selectedModel or modelRenderers[r:GetInstanceID()]) then
    local b=r.bounds
    if b.size.x>0.001 and b.size.y>0.001 then
     if not bounds then bounds=b else bounds:Encapsulate(b)end
     count=count+1
    end
   end
  end
  local particleSample=false
  if not bounds then
   local particles=clone:GetComponentsInChildren(typeof(U.ParticleSystem),true)
   for i=0,particles.Length-1 do local p=particles[i]
    p.useAutoRandomSeed=false;p.randomSeed=1;p:Simulate(.25,true,true,false)
   end
   for i=0,renderers.Length-1 do local r=renderers[i]
    if r.enabled and r.gameObject.activeInHierarchy and r:GetType().Name=='ParticleSystemRenderer'
     and r.bounds.size.x>.001 and r.bounds.size.y>.001 then
     if not bounds then bounds=r.bounds else bounds:Encapsulate(r.bounds)end
     count=count+1;particleSample=true
    end
   end
  end
  assert(bounds and count>0,'No nonempty native renderer in default pose')
  for i=0,colliders.Length-1 do colliders[i].enabled=true end
  U.Physics.SyncTransforms()
  local focus=nil
  for i=0,colliders.Length-1 do local c=colliders[i]
   if originalEnabled[i] and c.tag=='Enemy' and c.bounds.size.x>.001 and c.bounds.size.y>.001 then
    if not focus then focus=c.bounds else focus:Encapsulate(c.bounds)end
   end
  end
  -- Hanging threads can dwarf a spider's body. A separate body portrait uses
  -- original Enemy-tagged geometry for framing; it is not a damage-state label.
  local framing=selectedModel and bounds or (focus or bounds)
  local center=framing.center
  cameraObject=U.GameObject('MR3A_AssetPreviewCamera')
  local camera=cameraObject:AddComponent(typeof(U.Camera))
  camera.enabled=false;camera.cullingMask=1073741824
  camera.clearFlags=U.CameraClearFlags.SolidColor
  camera.backgroundColor=U.Color(.3,.3,.3,1)
  camera.orthographic=true;camera.aspect=1
  camera.orthographicSize=math.max(framing.extents.x,framing.extents.y)*((focus and not selectedModel)and 2 or 1.2)
  camera.nearClipPlane=.01;camera.farClipPlane=100
  camera.transform.position=U.Vector3(center.x,center.y,center.z-20)
  local function projected(b)
   local lo,hi=b.min,b.max
   local x1,y1,x2,y2=100000,100000,-100000,-100000
   for _,x in ipairs({lo.x,hi.x})do for _,y in ipairs({lo.y,hi.y})do for _,z in ipairs({lo.z,hi.z})do
    local p=camera:WorldToViewportPoint(U.Vector3(x,y,z))
    x1=math.min(x1,p.x*256);y1=math.min(y1,(1-p.y)*256)
    x2=math.max(x2,p.x*256);y2=math.max(y2,(1-p.y)*256)
   end end end
   return {x1,y1,x2,y2}
  end
  local colliderReferences={}
  -- Far-away preview layer, still paused: measure default bounds without a
  -- physics step, then disable all preview contacts before camera rendering.
  for i=0,colliders.Length-1 do local c=colliders[i]
   colliderReferences[#colliderReferences+1]={name=c.name,type=c:GetType().Name,
    configured_enabled=originalEnabled[i],trigger=c.isTrigger,box=projected(c.bounds),
    scope='default_pose_not_damage_activation'}
   c.enabled=false
  end
  texture=U.RenderTexture(256,256,24)
  texture:Create();camera.targetTexture=texture;camera:Render()
  U.RenderTexture.active=texture
  image=U.Texture2D(256,256,U.TextureFormat.RGBA32,false)
  image:ReadPixels(U.Rect(0,0,256,256),0,0);image:Apply()
  local png=U.ImageConversion.EncodeToPNG(image)
  local file=U.Application.persistentDataPath..'/arena-control/'..filename
  CS.System.IO.File.WriteAllBytes(file,png)
  result={resource=name,path=full,file=file,renderers=count,poses=poses,colliders=colliderReferences,
   particle_sample_seconds=particleSample and .25 or 0,
   appearance_box=projected(bounds),
   bounds={width=bounds.size.x,height=bounds.size.y},camera_focus=selectedModel and 'original_allRenderObj' or (focus and 'enemy_collider_portrait' or 'render_bounds'),
   status='default_pose_only',
   gameplay_initialized=false,runtime_collision_verified=false}
 end)
 U.RenderTexture.active=previous
 if cameraObject then U.Object.DestroyImmediate(cameraObject)end
 if image then U.Object.DestroyImmediate(image)end
 if texture then texture:Release();U.Object.DestroyImmediate(texture)end
 if parent then U.Object.DestroyImmediate(parent)end
 if handler then handler:Release()end
 if not ok then return {resource=name,error=tostring(err),status='failed'}end
 return result
end
return true
