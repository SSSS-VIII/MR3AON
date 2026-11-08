-- MR3A local sandbox bridge. Run on the client's own coroutine/main thread.
-- No gameplay changes occur unless a local command file with a new id arrives.
require 'uLua/Coroutine'
local host = CS.UnityEngine.GameObject('MR3A_LocalControl')
CS.UnityEngine.Object.DontDestroyOnLoad(host)
local runner = host:AddComponent(typeof(CS.UnityEngine.EventSystems.EventTrigger))
runner:StartCoroutine(require('common/util').cs_generator(function()
    while type(CheckLoadLuaComplete) ~= 'function' or not CheckLoadLuaComplete() do coroutine.step() end
    local IO = CS.System.IO
    local folder = CS.UnityEngine.Application.persistentDataPath .. '/arena-control'
    IO.Directory.CreateDirectory(folder)
    if IO.File.Exists(folder .. '/offline.json') then
        -- Keep the normal local resource initialization, but do not open the
        -- account SDK login view in this dedicated offline environment.
        Lua_UILogin.Show = function() MR3A_LOCAL_LOGIN_READY = true end
    end
    local commandPath = folder .. '/command.json'
    local resultPath = folder .. '/result.json'
    local lastId = nil
    if IO.File.Exists(commandPath) then
        local ok, previous=pcall(function() return json.parse(IO.File.ReadAllText(commandPath)) end)
        if ok and type(previous)=='table' then lastId=previous.id end
    end
    IO.File.WriteAllText(folder .. '/ready.json', '{"bridge":"mr3a_local","ready":true}')
    print('MR3A_LOCAL_BRIDGE_READY')
    while true do
        if IO.File.Exists(commandPath) then
            local ok, request = pcall(function() return json.parse(IO.File.ReadAllText(commandPath)) end)
            if ok and type(request) == 'table' and request.id ~= nil and request.id ~= lastId then
                lastId = request.id
                local success, result = pcall(function()
                    assert(type(request.code) == 'string' and #request.code < 1048576, 'Invalid local command')
                    local fn, err = load(request.code, '@mr3a-local-command')
                    assert(fn, err)
                    return fn()
                end)
                local response = { id=request.id, ok=success }
                if success then response.result=result else response.error=tostring(result) end
                local function encode(value, seen, depth)
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
                    for k in pairs(value) do
                        count=count+1
                        if type(k)~='number' or k<1 or k%1~=0 then isArray=false else maxIndex=math.max(maxIndex,k) end
                    end
                    isArray=isArray and count>0 and maxIndex==count
                    local parts={}
                    if isArray then
                        for i=1,count do parts[i]=encode(value[i],seen,depth+1) end
                    else
                        for k,v in pairs(value) do parts[#parts+1]=json.stringify(tostring(k))..':'..encode(v,seen,depth+1) end
                    end
                    seen[value]=nil
                    return (isArray and '[' or '{')..table.concat(parts,',')..(isArray and ']' or '}')
                end
                local serialized, payload = pcall(function() return encode(response,{},0) end)
                if not serialized then payload=json.stringify({id=request.id,ok=false,error='Result is not JSON serializable'}) end
                IO.File.WriteAllText(resultPath, payload)
                print('MR3A_LOCAL_COMMAND_DONE', request.id, success)
            end
        end
        coroutine.step()
    end
end))
