"""情报模拟战原生识别结果的选牌规划，不进行截图、识别或设备输入。"""
import re


def box_xywh(box):
    if hasattr(box, 'x'):
        return box.x, box.y, box.w, box.h
    return tuple(box)


def iter_ocr_boxes(detail):
    if not detail or not detail.hit:
        return []
    out = []
    for result in detail.filtered_results or detail.all_results:
        if getattr(result, 'text', None):
            out.append((result.text, result.box))
        for sub in getattr(result, 'sub_results', []) or []:
            out.extend(iter_ocr_boxes(sub))
    return out


P = '情报模拟战'
ROLES = re.compile(r'(小黑|苍牙|仓牙|琳|阿力|小椒)\s*$')
SLOTS = [(735,280),(925,280),(1110,280),(735,500),(925,500)]


def hand_is_visible(items):
    """翻牌动画只有商店标题/按钮；等名称带恢复后才算一手。"""
    for text, box in items:
        x, y, w, h = box_xywh(box)
        cy = y + h / 2
        if len(text.strip()) >= 2 and (350 <= cy <= 405 or 565 <= cy <= 615) and x + w / 2 < 1020:
            return True
    return False


def plan_cards(items, empty_boxes):
    """一次OCR中的同槽文本去重；角色名限定在两行名称带，忽略描述。"""
    slots = {}
    for text, box in items:
        match = ROLES.search(re.sub(r'\s+', '', text))
        if not match:
            continue
        x,y,w,h = box_xywh(box);cx,cy=x+w/2,y+h/2
        row = 0 if 350<=cy<=405 else 1 if 565<=cy<=615 else -1
        col = 0 if 640<=cx<825 else 1 if 825<=cx<1020 else 2 if 1020<=cx<1220 else -1
        if row<0 or col<0 or (row==1 and col==2):
            continue
        slots.setdefault(row*3+col, match[1])
    boxes=[]
    for box in sorted(set(tuple(box_xywh(b)) for b in empty_boxes),key=lambda b:(b[1],b[0])):
        cx,cy=box[0]+box[2]/2,box[1]+box[3]/2
        if not (45<=cx<=565 and 135<=cy<=685):continue
        if any(abs(cx-(b[0]+b[2]/2))<80 and abs(cy-(b[1]+b[3]/2))<80 for b in boxes):continue
        boxes.append(box)
    return [(SLOTS[i], box, slots[i]) for i,box in zip(sorted(slots),boxes)]


def empty_cells(detail):
    if not detail:return []
    if detail.name==P+'空位':
        return [r.box for r in detail.filtered_results if getattr(r,'box',None) is not None]
    out=[]
    for result in detail.filtered_results or detail.all_results:
        for sub in getattr(result,'sub_results',[]) or []:out.extend(empty_cells(sub))
    return out




def apply_hand_plan(context, node_name, plans, after):
    patch={}
    for i,(start,end,role) in enumerate(plans,1):
        pick=P+f'点击卡牌{i}';place=P+f'放置卡牌{i}'
        patch[pick]={'action':{'type':'Click','param':{'target':list(start)}},'next':[place]}
        patch[place]={'action':{'type':'Click','param':{'target':list(end)}},'next':[P+f'点击卡牌{i+1}' if i<len(plans) else after]}
    if patch and not context.override_pipeline(patch):
        return False
    return context.override_next(node_name, [P+'点击卡牌1' if plans else after])
