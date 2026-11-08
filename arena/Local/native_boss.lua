-- Training health uses original bonus/phase/health setters and death handling.
local E=MR3A
function E.training_boss_health(boss)
    local gm=CS.GameManager.Instance
    if gm._isOnlyGame and gm.GameInfo.OfflineGame and gm.GameInfo:GetRealCombatType()==6 and boss.CurrentHp>0 then
        boss:InitBonus(CS.CfgBonusType.__CastFrom(3),1,0,0)
        boss:InitStageHp()
        boss:SetHealth(1)
    end
end
if not E.nativeBossHook then
    local f=typeof(CS.EnemyBossBase):GetField('__Hotfix0_BossBattleOfficialStart',CS.System.Reflection.BindingFlags.__CastFrom(60))
    assert(f and f:GetValue(nil)==nil,'Existing boss-start hook must be preserved')
    require('common/util').hotfix_ex(CS.EnemyBossBase,'BossBattleOfficialStart',function(self,showBlood,officialStart)
        self:BossBattleOfficialStart(showBlood,officialStart)
        E.training_boss_health(self)
    end)
    E.nativeBossHook=true
end
return E
