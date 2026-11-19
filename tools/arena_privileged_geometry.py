"""World-space original convex box / vertical capsule separation."""
import math
import numpy as np


def capsule_quad(body, quads, active):
    """Retain the real rotated corners, rather than their enclosing AABB.

    The role is the native vertical capsule (center, radius, spine half length).
    Between observations, relative vertex movement bounds a conservative sweep;
    rotation and translation both enter that bound.
    """
    quad=np.asarray(quads)-body[:,None,:2]
    a=quad;b=np.roll(quad,-1,axis=1);edge=b-a
    lengths=np.maximum(1e-16,np.sum(edge*edge,axis=2))
    half=body[:,3,None]
    # Quad vertices to the role's vertical spine.
    distances=np.hypot(a[:,:,0],np.maximum(0.,np.abs(a[:,:,1])-half))
    distance=distances.min(axis=1)
    # Both spine endpoints to each quad edge.
    for sign in (-1,1):
        p=np.zeros((len(body),1,2));p[:,:,1]=sign*half
        fraction=np.clip(np.sum((p-a)*edge,axis=2)/lengths,0.,1.)
        closest=a+fraction[:,:,None]*edge
        distance=np.minimum(distance,np.linalg.norm(closest-p,axis=2).min(axis=1))
    # Either an edge crosses the spine, or the spine is inside the polygon.
    crossing=np.divide(-a[:,:,0],edge[:,:,0],out=np.full_like(lengths,2.),
                       where=np.abs(edge[:,:,0])>1e-12)
    y=a[:,:,1]+np.clip(crossing,0.,1.)*edge[:,:,1]
    intersects=((crossing>=0)&(crossing<=1)&(np.abs(y)<=half)).any(axis=1)
    crosses=edge[:,:,0]*(-a[:,:,1])-edge[:,:,1]*(-a[:,:,0])
    inside=(crosses>=-1e-10).all(axis=1)|(crosses<=1e-10).all(axis=1)
    distance=np.where(inside|intersects,0.,distance)-body[:,2]
    # Bound contact between adjacent samples. Subtract full relative motion,
    # not just an instantaneous corner distance; no moving thin blade tunnels.
    movement=np.linalg.norm(quad[1:]-quad[:-1],axis=2).max(axis=1)
    movement+=np.abs(body[1:,3]-body[:-1,3])+np.abs(body[1:,2]-body[:-1,2])
    enabled=active[1:]|active[:-1]
    sweep=np.minimum(distance[:-1],distance[1:])-movement
    distance[1:]=np.minimum(distance[1:],np.where(enabled,sweep,math.inf))
    return np.where(active|np.r_[False,enabled],distance,math.inf)
