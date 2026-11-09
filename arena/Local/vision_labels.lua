-- Paused ground truth for annotation/verification. Never an actor input.
local E,U=MR3A,CS.UnityEngine
function E.vision_labels()
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
  time=CS.GameManager.Instance.GameInfo._totalTime,width=640,height=360,
  physics=E.state().physics,health=n.CurrentHp,role={point=point(n.transform.position),colliders={}},objects={}}
 local cols=n.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
 for i=0,cols.Length-1 do local c=cols[i]
  if c.enabled and c.name=='Role' then out.role.colliders[#out.role.colliders+1]={name=c.name,box=box(c.bounds)}end
 end
 local objects=U.Object.FindObjectsOfType(typeof(CS.EnemyBase))
 for i=0,objects.Length-1 do local o=objects[i]
  if o.gameObject.activeInHierarchy and o.isActive then
   local row={id=o:GetInstanceID(),type=o:GetType().Name,name=o.name,point=point(o.transform.position),colliders={}}
   local cs=o.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
   for j=0,cs.Length-1 do local c=cs[j]
    if c.enabled then local b=box(c.bounds)
     if b[3]>b[1] and b[4]>b[2] then row.colliders[#row.colliders+1]={name=c.name,box=b}end
    end
   end
   out.objects[#out.objects+1]=row
  end
 end
 return out
end
return true
