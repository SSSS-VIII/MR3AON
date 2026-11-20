"""Native SkeletonUtilityBone Follow geometry, independent of animation timing.

This reconstructs a directly attached original BoxCollider from a known bone
pose. It does not forecast enemy movement, track transitions or collider enable.
"""
import math
import numpy as np


def follow_quad(spine, bone, collider):
    follow=collider.get('spine_follow',{})
    fields=follow.get('fields',{})
    if (collider['type']!='BoxCollider' or collider.get('depth_tilt') or
            follow.get('bone_name')!=bone['name'] or fields.get('mode')!='Follow: 0' or
            fields.get('position') is not True or fields.get('rotation') is not True or
            fields.get('scale') is not False or fields.get('overrideAlpha')!=1 or
            fields.get('incompatibleTransformMode') is not False):
        raise ValueError('Unvalidated native bone-follow configuration')
    xy=lambda v:np.array([v['x'],v['y']],float)
    basis=np.column_stack((xy(spine['axis_x']),xy(spine['axis_y'])))
    gram=basis.T@basis
    if abs(np.linalg.det(basis))<1e-12 or abs(gram[0,1])>1e-5 or abs(gram[0,0]-gram[1,1])>1e-5:
        raise ValueError('Unvalidated degenerate, sheared or nonuniform skeleton basis')
    # A directly attached collider keeps its authored scale. The bone's matrix
    # scale is deliberately ignored because SkeletonUtilityBone.scale is false.
    theta=math.atan2(bone['c'],bone['a'])
    rotation=np.array([[math.cos(theta),-math.sin(theta)],[math.sin(theta),math.cos(theta)]])
    if any(abs(collider['scale'][axis]-np.linalg.norm(basis[:,i]))>1e-5
           for i,axis in enumerate(('x','y'))):
        raise ValueError('Unvalidated additional bone collider scale')
    local=xy(collider['local_center'])+np.array([[-1,-1],[1,-1],[1,1],[-1,1]])*xy(collider['size'])/2
    return (local@rotation.T+xy(bone))@basis.T+xy(spine['origin'])
