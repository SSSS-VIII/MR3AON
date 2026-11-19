"""每日任务重排后的同行ROI绑定；只处理已识别文字和坐标。"""
import re


def task_row_overrides(items):
    rows = {}
    seen = set()
    for text, box in items:
        text = re.sub(r'\s+', '', text)
        match = re.search(r'(方寸|大千)[试試]炼', text)
        if not match:
            continue
        if '累计' in text or '积分' in text or re.search(r'获得\d+分', text):
            kind = match[1] + '积分'
        elif re.search(r'(完成|挑战)\d+次', text):
            kind = match[1] + '次数'
        else:
            continue
        x, y, width, height = map(int, box)
        key = (kind, x, y, width, height)
        if key in seen:
            continue
        seen.add(key)
        center = y + height // 2
        if kind in rows or not (350 <= x <= 780 and 175 <= center <= 590):
            return None
        rows[kind] = center
    if set(rows) != {'方寸次数', '方寸积分', '大千次数', '大千积分'}:
        return None
    centers = sorted(rows.values())
    if any(b - a < 80 for a, b in zip(centers, centers[1:])):
        return None
    return {'须弥幻境' + kind + suffix: {'recognition': {'param': {
                'roi': [780, center - 45, 285, 90]}}}
            for kind, center in rows.items() for suffix in ('已领取', '进度')}
