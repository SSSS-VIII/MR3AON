-- Run once through LuaManager.DoString on Unity's own main thread.
-- The resource key is a private local file; do not embed it in a Lua chunk name.
local U=CS.UnityEngine
local IO=CS.System.IO
local folder=U.Application.persistentDataPath..'/arena-control'
local key=IO.File.ReadAllText(folder..'/resource-key')
assert(#key==16,'Invalid local resource key')
U.AssetBundle.SetAssetBundleDecryptKey(key)
CS.GameManager.Instance._isOnlyGame=true
CS.Util.SetInt('DeviceLevel',3)
local p=CS.Patch.Instance
p:StopAllCoroutines()
p:SetIsCallReady2LoginBefore(true)
local resources=CS.BaseFramework.Resource.ResourceUtils
local ok,manifest=resources.GetLocalMasterManifest(nil)
assert(ok and manifest,'Local manifest missing')
local save=CS.SaveData()
resources.ReadLocalAssetBundleMD5(save)
local flags=CS.System.Reflection.BindingFlags.__CastFrom(52)
p:GetType():GetField('m_saveData',flags):SetValue(p,save)
p:GetType():GetField('patchManifest',flags):SetValue(p,manifest)
p:InitManifest()
local host=U.GameObject('MR3A_EarlyBootstrap')
U.Object.DontDestroyOnLoad(host)
local runner=host:AddComponent(typeof(U.EventSystems.EventTrigger))
runner:StartCoroutine(require('common/util').cs_generator(function()
    -- Release the temporary Java transport before continuing module startup.
    coroutine.yield(U.WaitForSeconds(3))
    local success,err=pcall(function()
        p:StartReadLuaFiles(false)
        p:PatchForceReadLuaFile()
    end)
    IO.File.WriteAllText(folder..'/boot-loaded.txt',success and 'ok' or tostring(err))
end))
return 'local manifest and MD5 initialized'
