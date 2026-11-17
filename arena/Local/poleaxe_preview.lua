-- Reuses the existing isolated prefab-preview mechanism. No gameplay AI/ticks.
local E,U=MR3A,CS.UnityEngine
function E.poleaxe_preview_end()
 local p=E.poleaxePreview;if not p then return true end
 U.RenderTexture.active=p.previous
 if p.cameraObject then U.Object.DestroyImmediate(p.cameraObject)end
 if p.image then U.Object.DestroyImmediate(p.image)end
 if p.texture then p.texture:Release();U.Object.DestroyImmediate(p.texture)end
 if p.parent then U.Object.DestroyImmediate(p.parent)end
 if p.handler then p.handler:Release()end
 E.poleaxePreview=nil;return true
end
function E.poleaxe_preview_begin(scale)
 assert(type(scale)=="number" and scale>0 and scale<1000,"Invalid projection scale")
 assert(U.Time.timeScale==0 and not E.busy,'Pause before original-asset rendering')
 E.poleaxe_preview_end()
 local p={previous=U.RenderTexture.active};E.poleaxePreview=p
 local ok,err=pcall(function()
  local full=CS.BaseFramework.Resource.ResourceUtils.GetPrefabFullPath('EnemyPoleaxeWarrior')
  local method=xlua.get_generic_method(CS.BaseFramework.Resource.ResourceManager,'LoadAsset')(U.GameObject)
  p.handler=method(CS.BaseFramework.Resource.ResourceManager.Instance,full)
  assert(p.handler and p.handler.IsDone and p.handler.Result,'Original prefab not loaded')
  p.parent=U.GameObject('MR3A_PoleaxePosePreview');p.parent:SetActive(false)
  p.clone=U.Object.Instantiate(p.handler.Result,p.parent.transform,false)
  local behaviours=p.clone:GetComponentsInChildren(typeof(U.MonoBehaviour),true)
  for i=0,behaviours.Length-1 do local b=behaviours[i];b.enabled=false
   if b:GetType().Name=='SkeletonAnimation'then p.spine=b end
  end
  assert(p.spine,'Original SkeletonAnimation missing')
  local colliders=p.clone:GetComponentsInChildren(typeof(U.Collider),true)
  for i=0,colliders.Length-1 do local c=colliders[i];c.enabled=false
   if c.name=='Warrior'and c:GetType().Name=='BoxCollider'then p.body=c end
  end
  assert(p.body,'Original body geometry missing')
  local transforms=p.clone:GetComponentsInChildren(typeof(U.Transform),true)
  for i=0,transforms.Length-1 do transforms[i].gameObject.layer=30 end
  p.parent.transform.position=U.Vector3(10000,10000,0);p.parent:SetActive(true)
  p.spine:Initialize(true);p.spine:Update(0)
  p.skeleton=p.spine.Skeleton;p.data=p.skeleton.Data
  p.cameraObject=U.GameObject('MR3A_PoleaxePoseCamera');p.camera=p.cameraObject:AddComponent(typeof(U.Camera))
  local camera=p.camera;camera.enabled=false;camera.cullingMask=1073741824
  camera.clearFlags=U.CameraClearFlags.SolidColor;camera.backgroundColor=U.Color(0,0,0,0)
  camera.orthographic=true;camera.aspect=1;camera.orthographicSize=256/(2*scale)
  camera.nearClipPlane=.01;camera.farClipPlane=100;camera.allowHDR=false
  local center=p.body.transform:TransformPoint(p.body.center)
  camera.transform.position=U.Vector3(center.x,center.y+45/scale,center.z-20)
  p.texture=U.RenderTexture(256,256,24,U.RenderTextureFormat.ARGB32);p.texture:Create();camera.targetTexture=p.texture
  p.image=U.Texture2D(256,256,U.TextureFormat.RGBA32,false)
 end)
 if not ok then E.poleaxe_preview_end();error(err)end
 local animations={}
 for i=0,p.data.Animations.Count-1 do local a=p.data.Animations.Items[i];animations[#animations+1]={name=a.Name,duration=a.Duration}end
 return {resource='EnemyPoleaxeWarrior',animations=animations,paused=true,window=256,scale=scale,body_center_offset={0,-45}}
end
function E.poleaxe_preview_render(name,t,filename)
 local p=assert(E.poleaxePreview,'Preview not initialized')
 assert(U.Time.timeScale==0 and not E.busy,'Preview must remain paused')
 assert(type(filename)=='string'and string.match(filename,'^[%w_-]+%.png$'),'Invalid filename')
 local clip=assert(p.data:FindAnimation(name),'Original clip absent')
 assert(t>=0 and t<=clip.Duration+.00001,'Phase outside source animation')
 local sk=p.skeleton;sk:SetToSetupPose()
 clip:Apply(sk,0,t,false,nil,1,CS.Spine.MixBlend.Replace,CS.Spine.MixDirection.In)
 sk:UpdateWorldTransform()
 local bone=sk:FindBone('axe');local before={bone.WorldX,bone.WorldY,bone.A,bone.B,bone.C,bone.D}
 p.spine:MyLateUpdate()
 local after={bone.WorldX,bone.WorldY,bone.A,bone.B,bone.C,bone.D}
 p.camera:Render();U.RenderTexture.active=p.texture
 p.image:ReadPixels(U.Rect(0,0,256,256),0,0);p.image:Apply()
 local png=U.ImageConversion.EncodeToPNG(p.image);local path=U.Application.persistentDataPath..'/arena-control/'..filename
 CS.System.IO.File.WriteAllBytes(path,png);U.RenderTexture.active=p.previous
 return {name=name,phase=t,duration=clip.Duration,path=path,bone_before_mesh=before,bone_after_mesh=after,
  texture_format=tostring(p.texture.format),texture_graphics_format=tostring(p.texture.graphicsFormat),camera_clear_alpha=p.camera.backgroundColor.a,corner_alpha=p.image:GetPixel(0,0).a,color_space=tostring(U.QualitySettings.activeColorSpace),scope='isolated_original_animation_render_no_gameplay_AI_or_physics'}
end
function E.poleaxe_preview_background(r,g,b)
 local p=assert(E.poleaxePreview,'Preview not initialized')
 assert(r>=0 and r<=1 and g>=0 and g<=1 and b>=0 and b<=1,'Invalid preview background')
 p.camera.backgroundColor=U.Color(r,g,b,1);return true
end
return true
