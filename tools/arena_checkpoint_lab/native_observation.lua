-- Search-only, read-only privileged state. Never loaded by the visual actor.
local E,U=MR3A,CS.UnityEngine
local flags=CS.System.Reflection.BindingFlags.__CastFrom(52)
local attackField=typeof(CS.EnemyAttackModule):GetField('_belongToEnemy',flags)
local fieldCache={}
local function field(obj,name)
    local tp=obj:GetType();local key=tp.FullName..'/'..name
    if fieldCache[key]==nil then
        local parent=tp
        while parent do
            local f=parent:GetField(name,flags)
            if f then fieldCache[key]=f;break end
            parent=parent.BaseType
        end
        if fieldCache[key]==nil then fieldCache[key]=false end
    end
    return fieldCache[key]and fieldCache[key]:GetValue(obj)or nil
end
local function vector(v)return {x=v.x,y=v.y,z=v.z}end
local function shape(c)
    local b=c.bounds
    local center,extents=b.center,b.extents
    -- Disabled warnings still have a declared original shape. Bounds is empty
    -- while disabled, so use the original box's transform, not a made-up box.
    if not c.enabled and c:GetType().Name=='BoxCollider'then
        local lo,hi=U.Vector3(1e9,1e9,1e9),U.Vector3(-1e9,-1e9,-1e9)
        for _,x in ipairs({-1,1})do for _,y in ipairs({-1,1})do for _,z in ipairs({-1,1})do
            local p=c.transform:TransformPoint(c.center+U.Vector3(x*c.size.x/2,y*c.size.y/2,z*c.size.z/2))
            lo=U.Vector3.Min(lo,p);hi=U.Vector3.Max(hi,p)
        end end end
        center=(lo+hi)/2;extents=(hi-lo)/2
    end
    return {id=c:GetInstanceID(),center=vector(center),extents=vector(extents),enabled=c.enabled,type=c:GetType().Name}
end
function E.native_search_observation()
    assert(not E.busy and U.Time.timeScale==0,'Read native search state at its original boundary')
    local n=CS.NinjaController.Instance.NinjaScript
    local out={state=E.state(),hazards={},role={},privileged=true}
    local cols=n.gameObject:GetComponentsInChildren(typeof(U.Collider),true)
    for i=0,cols.Length-1 do local c=cols[i]
        if c.enabled and c.name=='Role'and c.gameObject.activeInHierarchy then out.role[#out.role+1]=shape(c)end
    end
    local jumps=field(n,'_jumpTimes')
    if type(jumps)=='number'then out.jumps_used=jumps end
    local previous=field(n,'_lastNinjaPhysicsState')
    if previous then out.last_physics=tostring(previous)end
    previous=field(n,'__ninjaPrePhysicsState')
    if previous then out.previous_physics=tostring(previous)end
    local support=n._GroundCollider
    if support then
        out.support={start=vector(support.PointStart),finish=vector(support.PointEnd),
            is_line=support.IsLine,is_ground=support.IsGround,slope_speed_ratio=n.SlopeSpeedRatio}
        local supports=U.Object.FindObjectsOfType(typeof(CS.LevelBlockCollider))
        for i=0,supports.Length-1 do local next=supports[i]
            if next~=support and next.enabled and next.isActive then
                local a,b=next.PointStart,next.PointEnd;local last=support.PointEnd
                if a.x<=last.x+.3 and b.x>last.x+.3 and b.x>a.x then
                    local y=a.y+(b.y-a.y)*(last.x-a.x)/(b.x-a.x)
                    if math.abs(y-last.y)<.4 then out.support.continues=true;break end
                end
            end
        end
    end
    local colliders=U.Object.FindObjectsOfType(typeof(U.Collider))
    for i=0,colliders.Length-1 do local c=colliders[i]
        if c.gameObject.activeInHierarchy then
            local module=c.gameObject:GetComponent(typeof(CS.EnemyAttackModule))
            local owner=module and attackField and attackField:GetValue(module)
            if c.tag=='Enemy'or owner then
                local s=shape(c)
                if math.abs(s.center.x-n.transform.position.x)<32 and
                        math.abs(s.center.z-n.transform.position.z)<=s.extents.z+.5 then
                    local enemy=owner or c:GetComponentInParent(typeof(CS.EnemyBase))
                    if enemy then
                        s.owner=enemy:GetInstanceID();s.enemy_type=enemy:GetType().Name
                        local state=field(enemy,'_enemyState')or field(enemy,'_currState')
                        if state then s.phase=tostring(state)end
                    end
                    s.damage_callback=owner~=nil
                    out.hazards[#out.hazards+1]=s
                end
            end
        end
    end
    return out
end
return true
