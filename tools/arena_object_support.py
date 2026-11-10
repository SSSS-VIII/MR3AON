"""Locate an object's visible native support, independently of the runner's."""
from arena_support import height


def object_support(segments,detection):
    box=detection.box
    candidates=[]
    for segment in segments:
        # PinballBase queries its LevelBlockCollider, not an ItemAirGround.
        if segment['kind']not in ('rope','platform')or segment['confidence']<.5:continue
        y=height(segment,box.center[0])
        if y is not None and y>=box.center[1]+box.h/2-6:
            candidates.append((y,segment))
    if not candidates:return None
    y,segment=min(candidates,key=lambda pair:pair[0])
    floor={k:segment[k]for k in ('a','b','vx','vy')}
    floor.update(left_clipped=segment.get('left_clipped',False),right_clipped=segment.get('right_clipped',False))
    return dict(y=y,segment=floor)
