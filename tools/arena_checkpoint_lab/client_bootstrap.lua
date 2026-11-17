-- Queue the unchanged offline bootstrap through the original DoString method.
local IO=CS.System.IO
local folder='/sdcard/Android/data/com.pandadastudio.ninjamustdie3/files/arena-control'
local gm=CS.GameManager.Instance
local manifest=CS.BaseFramework.Resource.ResourceManager.Instance.Manifest
IO.File.WriteAllText(folder..'/boot-state.txt',tostring(gm and gm:GetCurFSMStateID())..' manifest='..tostring(manifest~=nil))
local state=gm and tostring(gm:GetCurFSMStateID())
-- A guest with no network interface stays at the original permission state's
-- network prompt. Both early states already have the prepatch manifest.
if not MR3A_BOOT_QUEUED and gm and (state=='Logo: 2' or state=='CheckPermission: 1') and manifest then
    MR3A_BOOT_QUEUED=true
    local ok,result=pcall(function()
        return assert(load(IO.File.ReadAllText('/checkpoint-payload/bootstrap.lua'),'@mr3a-bootstrap'))()
    end)
    IO.File.WriteAllText(folder..'/boot-launch.txt',ok and tostring(result) or ('ERROR '..tostring(result)))
end
