-- Opt-in read-only evidence for rollback research. No restore or update hook.
local E,U=MR3A,CS.UnityEngine
assert(E and E.state,'Load the existing local environment first')
local flags=CS.System.Reflection.BindingFlags.__CastFrom(52)
local staticFlags=CS.System.Reflection.BindingFlags.__CastFrom(56)
local P={schema=1,originalAdvance=E.advance}

local function value(v,t)
 if v==nil then return nil end
 if t.IsEnum then return tostring(v)end
 if t.IsPrimitive or t.FullName=='System.String' then return v end
 if t.FullName=='UnityEngine.Vector2'then return {x=v.x,y=v.y}end
 if t.FullName=='UnityEngine.Vector3'then return {x=v.x,y=v.y,z=v.z}end
 if t.FullName=='UnityEngine.Quaternion'then return {x=v.x,y=v.y,z=v.z,w=v.w}end
 if t.IsArray and t:GetElementType().IsPrimitive then
  local out={};for i=0,v.Length-1 do out[#out+1]=v[i]end;return out
 end
 return nil
end

local function fields(obj)
 local out,omitted={},{}
 local fs=obj:GetType():GetFields(flags)
 for i=0,fs.Length-1 do
  local f=fs[i]
  if not f.IsStatic and not string.find(f.Name,'Hotfix',1,true)then
   local ok,v=pcall(function()return f:GetValue(obj)end)
   if ok then
    local decoded=value(v,f.FieldType)
    if decoded~=nil then out[f.Name]=decoded
    elseif v~=nil then omitted[#omitted+1]={name=f.Name,type=f.FieldType.FullName}end
   else omitted[#omitted+1]={name=f.Name,error=tostring(v)}end
  end
 end
 return {values=out,omitted=omitted}
end

function P.capture()
 assert(not E.busy and U.Time.timeScale==0,'Probe requires paused original physics')
 local gm=CS.GameManager.Instance
 assert(gm._isOnlyGame and gm.GameInfo.OfflineGame,'Requires isolated offline GameOnly')
 local nc=CS.NinjaController.Instance
 assert(nc and nc.NinjaScript,'Original role is not ready')
 local out={schema=P.schema,fullSnapshot=false,state=E.state(),role=fields(nc.NinjaScript),
  gameTime=fields(CS.GameTimeManager.Instance),rng={},objects={},
  coverage='Primitive/enum/vector/primitive-array evidence only; omitted references are explicit. Not a restorable snapshot.',
  originalAdvanceUnchanged=E.advance==P.originalAdvance,
  engine={time=U.Time.time,fixedTime=U.Time.fixedTime,frame=U.Time.frameCount,captureFramerate=U.Time.captureFramerate}}
 local fs=typeof(CS.RandomManager):GetFields(staticFlags)
 for i=0,fs.Length-1 do
  local f=fs[i]
  if not string.find(f.Name,'Hotfix',1,true)then
   local v=f:GetValue(nil)
   if type(v)=='userdata'and v:GetType().FullName=='System.Random'then out.rng[f.Name]=fields(v)
   else
    local decoded=value(v,f.FieldType)
    if decoded~=nil then out.rng[f.Name]=decoded end
   end
  end
 end
 local randomState=U.Random.state
 out.unityRandom=fields(randomState)
 local enemies=U.Object.FindObjectsOfType(typeof(CS.EnemyBase))
 for i=0,enemies.Length-1 do
  local enemy=enemies[i]
  if enemy.gameObject.activeInHierarchy and enemy.isActive then
   local p=enemy.transform.position
   out.objects[#out.objects+1]={type=enemy:GetType().Name,name=enemy.name,
    position={x=p.x,y=p.y,z=p.z},fields=fields(enemy)}
  end
 end
 return out
end

function P.close()
 assert(not E.busy and U.Time.timeScale==0,'Close at a paused boundary')
 assert(E.advance==P.originalAdvance,'Existing step function changed during probe')
 E.rewindProbe=nil
 return true
end

E.rewindProbe=P
return {schema=P.schema,fullSnapshot=false,mutatesGameplay=false}
