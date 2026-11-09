-- Local UGUI pause menu and loading card.
local E=MR3A
local U=CS.UnityEngine
local UI=U.UI
E.menu=E.menu or {enabled=false,page=1,position=1,pins={}}
local M=E.menu
local colors={panel=U.Color(.035,.055,.09,.98),card=U.Color(.075,.105,.15,1),
    button=U.Color(.12,.17,.24,1),selected=U.Color(.13,.39,.47,1),text=U.Color(.9,.94,.98,1),
    muted=U.Color(.6,.7,.8,1),accent=U.Color(.36,.87,.78,1)}

local function rect(name,parent,x,y,w,h)
    local g=U.GameObject(name)
    local r=g:AddComponent(typeof(U.RectTransform))
    if parent then r:SetParent(parent,false) end
    r.anchorMin=U.Vector2(0,1);r.anchorMax=U.Vector2(0,1);r.pivot=U.Vector2(0,1)
    r.anchoredPosition=U.Vector2(x,-y);r.sizeDelta=U.Vector2(w,h)
    return g,r
end
local function background(name,parent,x,y,w,h,color)
    local g,r=rect(name,parent,x,y,w,h)
    local image=g:AddComponent(typeof(UI.Image));image.color=color
    return g,r,image
end
local function text(parent,value,x,y,w,h,size,color)
    local g,r=rect('Label',parent,x,y,w,h)
    local t=g:AddComponent(typeof(UI.Text))
    t.font=M.font;t.text=value;t.fontSize=size or 20;t.color=color or colors.text
    t.alignment=U.TextAnchor.MiddleLeft;t.raycastTarget=false
    t.horizontalOverflow=U.HorizontalWrapMode.Wrap;t.verticalOverflow=U.VerticalWrapMode.Truncate
    return t
end
local function button(parent,label,x,y,w,h,fn,selected)
    local g,r,image=background(label,parent,x,y,w,h,selected and colors.selected or colors.button)
    local b=g:AddComponent(typeof(UI.Button));b.targetGraphic=image
    local nav=b.navigation;nav.mode=UI.Navigation.Mode.None;b.navigation=nav
    local t=text(r,label,10,0,w-20,h,string.find(label,'\n') and 18 or 20);t.alignment=U.TextAnchor.MiddleCenter
    b.onClick:AddListener(function()
        local ok,err=pcall(fn)
        if not ok then E.menuError=tostring(err);M.error='操作未完成，请重试。';E.draw_menu() end
    end)
    return b
end
local function current_level()
    for _,v in ipairs(E.catalog.levels) do if v.id==M.absoluteLevel then return v end end
    return E.catalog.levels[1]
end
local function slots(map)
    local out={}
    for _,v in ipairs(map.slots) do out[#out+1]=v end
    if #map.loop>0 then out[#out+1]={position=#out+1,pool=map.loop,loop=true} end
    return out
end
local function variant_page(slot,pin)
    if pin then for i,v in ipairs(slot.pool) do if v.id==pin then return math.floor(i/6)+1 end end end
    return 1
end
local function change_map(identity)
    M.map=identity;M.position=1;M.page=1;M.variantPage=1;M.pins={}
end
local function change_level(identity)
    M.absoluteLevel=identity;change_map(current_level().maps[1].id)
end

function E.menu_start(position)
    if E.busy then return false end
    M.error=nil
    E.menuError=nil
    local spec={level=M.absoluteLevel,map=M.map,start=position,pins=M.pins}
    E.native_select(spec,M.seed)
    M.pendingStart=E.travel
end

function E.finish_menu_start()
    local job=M.pendingStart
    if job and job~=E.travel then M.pendingStart=nil;return nil end
    if not job or not job.done then return nil end
    M.pendingStart=nil
    if job.error then
        M.error='无法开始，请重新选择后再试。'
        return false
    end
    E.hide_menu()
    E.resume()
    return true
end

function E.draw_menu()
    if not M.enabled or E.menu_suppressed or not E.catalog then return end
    if not M.root or not M.root.gameObject then
        local g=U.GameObject('MR3A_PauseMenu')
        U.Object.DontDestroyOnLoad(g)
        local canvas=g:AddComponent(typeof(U.Canvas));canvas.renderMode=U.RenderMode.ScreenSpaceOverlay;canvas.sortingOrder=32000
        local scaler=g:AddComponent(typeof(UI.CanvasScaler))
        scaler.uiScaleMode=UI.CanvasScaler.ScaleMode.ScaleWithScreenSize;scaler.referenceResolution=U.Vector2(1280,720)
        g:AddComponent(typeof(UI.GraphicRaycaster))
        M.root=canvas
        local fonts=U.Resources.FindObjectsOfTypeAll(typeof(U.Font))
        for i=0,fonts.Length-1 do if fonts[i].name=='556' then M.font=fonts[i];break end end
        if not M.font then M.font=U.Resources.GetBuiltinResource(typeof(U.Font),'LegacyRuntime.ttf') end
    end
    M.root.gameObject:SetActive(true)
    if M.body then U.Object.Destroy(M.body) end
    local body,r=background('Pause',M.root.transform,0,0,1280,720,colors.panel);M.body=body
    local g=CS.GameManager.Instance.GameInfo
    M.absoluteLevel=M.absoluteLevel or (g._levelID+(g._chapterID>=3 and g._chapterID-1 or 0))
    M.seed=M.seed or E.seed
    M.map=M.map or current_level().maps[1].id
    local map=E.catalog.maps[tostring(M.map)]
    local positions=slots(map)
    M.position=math.min(M.position or 1,#positions)
    text(r,'疾风竞技场 · 选关',26,14,620,46,30,colors.accent)
    button(r,'继续游戏  P',1038,24,216,48,function() E.resume() end,true)
    button(r,'重开  R',848,24,174,48,function() E.reset(E.seed,g._chapterID,g._levelID) end)
    text(r,'种子 '..M.seed,730,103,230,36,20,colors.muted)
    button(r,'−',982,103,48,36,function() M.seed=(M.seed+2147483647)%2147483648;E.draw_menu() end)
    button(r,'+',1040,103,48,36,function() M.seed=(M.seed+1)%2147483648;E.draw_menu() end)
    button(r,'全部随机',1100,103,154,36,function() M.pins={};E.draw_menu() end)
    local _,a=background('Levels',r,24,156,160,452,colors.card)
    local _,b=background('Maps',r,200,156,210,452,colors.card)
    local _,c=background('Boards',r,426,156,304,452,colors.card)
    local _,d=background('Variants',r,746,156,510,452,colors.card)
    text(a,'关卡',14,6,140,38,22)
    for i,level in ipairs(E.catalog.levels) do
        local identity=level.id
        button(a,'第 '..identity..' 关',12,52+(i-1)*47,136,39,function() change_level(identity);E.draw_menu() end,M.absoluteLevel==identity)
    end
    text(b,'地图',14,6,180,38,22)
    for i,entry in ipairs(current_level().maps) do
        local id=entry.id
        button(b,'地图 '..i..'  /  '..id,12,52+(i-1)*54,186,44,function() change_map(id);E.draw_menu() end,M.map==id)
    end
    text(c,'板子  ·  '..#positions..' 项',14,6,275,38,22)
    local pages=math.ceil(#positions/6)
    M.page=math.min(M.page or 1,pages)
    for index=(M.page-1)*6+1,math.min(M.page*6,#positions) do
        local position=index
        local pin=M.pins[tostring(position)]
        local label=(positions[position].loop and '无限段' or ('第 '..position..' 块'))..' · '..(pin and tostring(pin) or '随机抽取')
        button(c,label,12,52+(index-(M.page-1)*6-1)*51,280,43,function() M.position=position;M.variantPage=variant_page(positions[position],M.pins[tostring(position)]);E.draw_menu() end,M.position==position)
    end
    if pages>1 then
        button(c,'上一页',12,376,108,40,function() M.page=(M.page+pages-2)%pages+1;E.draw_menu() end)
        text(c,M.page..' / '..pages,130,376,62,40,18)
        button(c,'下一页',194,376,98,40,function() M.page=M.page%pages+1;E.draw_menu() end)
    end
    local slot=positions[M.position]
    text(d,(slot.loop and '无限段版型' or ('第 '..M.position..' 块 · 版型')),16,6,470,38,22)
    local choices={{id=0}}
    for _,candidate in ipairs(slot.pool) do choices[#choices+1]=candidate end
    local variantPages=math.ceil(#choices/6)
    M.variantPage=math.min(M.variantPage or 1,variantPages)
    for index=(M.variantPage-1)*6+1,math.min(M.variantPage*6,#choices) do
        local v=choices[index]
        local id=v.id
        local selected=(M.pins[tostring(M.position)] or 0)==id
        local classification=v.classification
        local kind=classification and classification.label or ''
        if classification and classification.motion=='random' then kind=kind..' · 动作随机' end
        local label=id==0 and '随机抽取' or ('版型 '..id..'\n'..kind)
        local row=index-(M.variantPage-1)*6
        button(d,label,16+((row-1)%2)*240,54+math.floor((row-1)/2)*53,228,48,function()
            M.pins[tostring(M.position)]=id~=0 and id or nil;E.draw_menu()
        end,selected)
    end
    if variantPages>1 then
        button(d,'上一页',16,224,150,36,function() M.variantPage=(M.variantPage+variantPages-2)%variantPages+1;E.draw_menu() end)
        text(d,M.variantPage..' / '..variantPages,184,224,100,36,18)
        button(d,'下一页',314,224,180,36,function() M.variantPage=M.variantPage%variantPages+1;E.draw_menu() end)
    end
    button(d,slot.loop and '从无限段开始' or ('从第 '..M.position..' 块开始'),16,356,478,58,function() E.menu_start(M.position) end,true)
    button(r,'从头开始',746,626,300,58,function() E.menu_start(1) end,true)
    button(r,'换种子重开  N',1062,626,194,58,function() E.reset((E.seed+1)%2147483648,g._chapterID,g._levelID) end)
    text(r,'K 跳跃     S 下翻     P 暂停 / 继续',26,632,692,36,20,colors.muted)
    if M.error then text(r,M.error,26,674,1228,36,17,U.Color(1,.55,.4,1)) end
end

function E.hide_menu()
    if M.root then M.root.gameObject:SetActive(false) end
end
function E.show_menu()
    if M.enabled and not E.menu_suppressed then E.draw_menu() end
end
function E.sync_menu()
    local level=CS.LevelManager.Instance.GameLevelInfo
    local base=level:GetType():GetField('_levelBaseInfo',CS.System.Reflection.BindingFlags.__CastFrom(52)):GetValue(level)
    local identity=base._levelID
    if not E.catalog.maps[tostring(identity)] then identity=E.nativeSelection and E.nativeSelection.map or M.map or E.catalog.levels[1].maps[1].id end
    M.map=identity;M.absoluteLevel=E.catalog.maps[tostring(M.map)].absoluteLevel;M.seed=E.seed
    local selection=E.nativeSelection and E.nativeSelection.map==M.map and E.nativeSelection
    M.position=selection and selection.start or 1
    M.page=math.floor((M.position-1)/6)+1;M.variantPage=1
    M.pins={}
    if selection then for k,v in pairs(selection.pins) do M.pins[k]=v end end
    local selected=slots(E.catalog.maps[tostring(M.map)])[M.position]
    if selected then M.variantPage=variant_page(selected,M.pins[tostring(M.position)]) end
end
function E.enable_menu()
    M.enabled=true
    E.sync_menu()
    if U.Time.timeScale==0 then E.show_menu() end
    return true
end
function E.draw_native_progress()
    if not M.root then E.draw_menu() end
    if M.body then U.Object.Destroy(M.body) end
    local body,r=background('TravelProgress',M.root.transform,0,0,1280,720,U.Color(0,0,0,0));M.body=body
    local _,card=background('Loading',r,390,270,500,164,colors.panel)
    text(card,'加载中…',32,22,436,52,30,colors.accent)
    M.progress=text(card,'',32,88,436,42,22)
    M.root.gameObject:SetActive(true)
end
if not E.menuObserver then
    local host=U.GameObject('MR3A_MenuObserver');U.Object.DontDestroyOnLoad(host)
    local runner=host:AddComponent(typeof(U.EventSystems.EventTrigger))
    E.menuObserver=true
    runner:StartCoroutine(require('common/util').cs_generator(function()
        local lastBusy=false
        local lastJob
        local lastInfo
        while true do
            local ok,err=pcall(function()
                if M.enabled and not E.menu_suppressed then
                    local started=E.finish_menu_start()
                    if started~=nil then
                        if not started then E.draw_menu() end
                        lastBusy=false;lastJob=E.travel;lastInfo=CS.GameManager.Instance.GameInfo
                    elseif E.travel and E.travel.done and E.travel.error then
                        if lastJob~=E.travel or not M.root.gameObject.activeSelf then E.draw_menu() end
                        lastBusy=false;lastJob=E.travel
                    elseif E.busy and E.travel and not E.travel.done then
                        if not lastBusy then E.draw_native_progress() end
                        local s=E.travel.selection
                        M.progress.text='第 '..s.absoluteLevel..' 关 · 第 '..s.start..' 块'
                        lastBusy=true
                    elseif U.Time.timeScale==0 and tostring(CS.GameManager.Instance:GetCurFSMStateID())=='Game: 8' then
                        local info=CS.GameManager.Instance.GameInfo
                        if info~=lastInfo then E.sync_menu();E.draw_menu();lastInfo=info end
                        if lastBusy or (E.travel and E.travel~=lastJob and E.travel.done) then
                            E.sync_menu()
                            if E.travel and E.travel.error then M.error='无法开始，请重新选择后再试。' end
                            E.draw_menu()
                        elseif M.root and not M.root.gameObject.activeSelf then E.sync_menu();E.draw_menu() end
                        lastBusy=false;lastJob=E.travel
                    else
                        E.hide_menu();lastBusy=false
                    end
                else E.hide_menu() end
            end)
            if not ok then E.menuError=tostring(err) end
            coroutine.step()
        end
    end))
end
return E
