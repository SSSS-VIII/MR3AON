-- Add a VM barrier around the existing advance function. Do not replace it.
local E,U=MR3A,CS.UnityEngine
assert(E and E.advance and not E.busy and U.Time.timeScale==0,'Pause the original battle first')
assert(not E.checkpointGate,'A game gate is already installed')
local JNI=U.AndroidJNI
local function args(pointer)
    local out=CS.System.Array.CreateInstance(typeof(U.jvalue),pointer and 1 or 0)
    if pointer then local value=U.jvalue();value.l=pointer;out[0]=value end
    return out
end
local system=JNI.FindClass('java/lang/System')
local getProperties=JNI.GetStaticMethodID(system,'getProperties','()Ljava/util/Properties;')
local properties=JNI.CallStaticObjectMethod(system,getProperties,args())
local propertyType=JNI.GetObjectClass(properties)
local get=JNI.GetMethodID(propertyType,'get','(Ljava/lang/Object;)Ljava/lang/Object;')
local key=JNI.NewStringUTF('mr3a.checkpoint.gate')
local localGate=JNI.CallObjectMethod(properties,get,args(key))
assert(localGate~=CS.System.IntPtr.Zero,'Native game gate is not registered')
local gate=JNI.NewGlobalRef(localGate)
local gateType=JNI.GetObjectClass(localGate)
local method=JNI.GetMethodID(gateType,'exchange','(Ljava/lang/String;)Ljava/lang/String;')
for _,reference in ipairs({gateType,localGate,key,propertyType,properties,system})do JNI.DeleteLocalRef(reference)end
local C={armed=false,last=nil,originalAdvance=E.advance}
E.checkpointGate=C
local folder=U.Application.persistentDataPath..'/arena-control'
-- Use the existing file bridge's array/number rules for native observations.
local function encode(value,seen,depth)
    local kind=type(value)
    if kind=='nil' then return 'null' end
    if kind=='boolean' then return value and 'true' or 'false' end
    if kind=='number' then
        if value~=value or value==math.huge or value==-math.huge then return json.stringify(tostring(value)) end
        return string.format('%.17g',value)
    end
    if kind~='table' then return json.stringify(tostring(value)) end
    assert(depth<64 and not seen[value],'Cyclic or overly deep result')
    seen[value]=true
    local count,maxIndex,isArray=0,0,true
    for k in pairs(value)do
        count=count+1
        if type(k)~='number' or k<1 or k%1~=0 then isArray=false else maxIndex=math.max(maxIndex,k) end
    end
    isArray=isArray and count>0 and maxIndex==count
    local parts={}
    if isArray then
        for i=1,count do parts[i]=encode(value[i],seen,depth+1)end
    else
        for k,v in pairs(value)do parts[#parts+1]=json.stringify(tostring(k))..':'..encode(v,seen,depth+1)end
    end
    seen[value]=nil
    return (isArray and '[' or '{')..table.concat(parts,',')..(isArray and ']' or '}')
end
local function exchange(value)
    local ok,payload=pcall(encode,value,{},0)
    if not ok or #payload>=262144 then
        payload=encode({schema=1,state=value.state,stateError=value.stateError,last={ok=false,
            error=ok and 'Native observation exceeds mailbox capacity' or tostring(payload)}},{},0)
    end
    local text=JNI.NewStringUTF(payload)
    local result=JNI.CallStringMethod(gate,method,args(text))
    JNI.DeleteLocalRef(text)
    return json.parse(result)
end
local runner=U.GameObject.Find('MR3A_LocalControl'):GetComponent(typeof(U.EventSystems.EventTrigger))
runner:StartCoroutine(require('common/util').cs_generator(function()
    while not CS.System.IO.File.Exists(folder..'/gate-arm')do coroutine.step()end
    C.armed=true
    while true do
        while E.busy do coroutine.step()end
        assert(E.advance==C.originalAdvance and U.Time.timeScale==0,'Original step boundary changed')
        local readable,state=pcall(E.state)
        local out={schema=1,state=readable and state or nil,
            stateError=not readable and tostring(state) or nil,last=C.last,
            loading=CS.LevelManager.Instance.LevelDataLoading,
            levelFinished=CS.LevelManager.Instance.isFinishLoad}
        C.last=nil
        local request=exchange(out)
        local ok,result=pcall(function()
            assert(type(request)=='table','Expected a game command')
            if request.op=='step' then
                E.advance(request.ticks,request.action)
                while E.busy do coroutine.step()end
                return E.result()
            elseif request.op=='probe' then
                return E.rewindProbe.capture()
            elseif request.op=='exec' then
                assert(type(request.code)=='string' and #request.code<3800,'Invalid local code')
                return assert(load(request.code,'@checkpoint-command'))()
            elseif request.op=='state' then return E.state()
            else error('Unsupported game gate operation')end
        end)
        C.last={ok=ok}
        if ok then C.last.result=result else C.last.error=tostring(result)end
    end
end))
return {installed=true,armed=false}
