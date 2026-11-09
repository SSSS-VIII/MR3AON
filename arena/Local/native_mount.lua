-- Reuse the client's rush movement and type-specific, reference-counted pickup.
local E=MR3A
local U=CS.UnityEngine
local RUSH_SPEED=120
local SHOOTER_ITEM=13
E.mountTraining=E.mountTraining or {}
local state=E.mountTraining

function E.set_mount_rush_speed(mount)
    mount._rushSpeed=RUSH_SPEED
    return RUSH_SPEED
end

function E.clear_mount_training()
    local manager=state.manager
    state.manager=nil;state.ninja=nil;state.mount=nil
    if manager then manager:RemoveAttractItemType(SHOOTER_ITEM) end
end

function E.update_mount_training(active,ninja,mount,manager)
    if not active then E.clear_mount_training();return end
    E.set_mount_rush_speed(mount)
    if state.manager~=manager or state.ninja~=ninja then
        E.clear_mount_training()
        manager:AddAttractItemType(SHOOTER_ITEM)
        state.manager=manager;state.ninja=ninja
    end
    state.mount=mount
end

if not E.mountTrainingObserver then
    local host=U.GameObject('MR3A_MountTraining');U.Object.DontDestroyOnLoad(host)
    local runner=host:AddComponent(typeof(U.EventSystems.EventTrigger))
    E.mountTrainingObserver=true
    runner:StartCoroutine(require('common/util').cs_generator(function()
        while true do
            local ok,err=pcall(function()
                local gm=CS.GameManager.Instance
                local controller=CS.NinjaController.Instance
                local ninja=controller and controller.NinjaScript
                local mc=CS.MountController.Instance
                local manager=CS.ItemManager.Instance
                local active=gm._isOnlyGame and gm.GameInfo.OfflineGame and gm.GameInfo:GetRealCombatType()==6
                    and tostring(gm:GetCurFSMStateID())=='Game: 8' and ninja and ninja.CurrentHp>0
                    and ninja.IsMountState and mc and mc.Mount and manager
                E.update_mount_training(active,ninja,mc and mc.Mount,manager)
            end)
            if not ok then E.mountTrainingError=tostring(err) end
            coroutine.step()
        end
    end))
end
return E
