"""Classical rotation/translation estimates for observed native OBBs."""
import math
import numpy as np


def rectangle(quad):
    q=np.asarray(quad,float)
    edges=np.roll(q,-1,axis=0)-q
    lengths=np.linalg.norm(edges,axis=1)
    index=int(np.argmax(lengths[:2]))
    edge=edges[index];width=float(lengths[index]);height=float(lengths[1-index])
    return q.mean(0),width,height,math.atan2(edge[1],edge[0])


def bounds(quad):
    q=np.asarray(quad,float);lo=q.min(0);hi=q.max(0)
    return (*map(float,lo),*map(float,hi-lo))


def transform(quad,angle,center):
    q=np.asarray(quad,float);old=q.mean(0);c,s=math.cos(angle),math.sin(angle)
    rotation=np.array([[c,-s],[s,c]])
    return tuple(tuple(map(float,p))for p in((q-old)@rotation.T+np.asarray(center)))


def update_rotation(track,detection,stamp):
    track.quad=tuple(tuple(map(float,p))for p in detection.quad)if detection.quad is not None else None
    if detection.quad is None or detection.collider_shape!='BoxCollider':
        track.angular_velocity=0.;track.angular_history.clear();return
    _,w,h,angle=rectangle(detection.quad)
    if min(w,h)<1:
        track.angular_velocity=0.;track.angular_history.clear();return
    period=math.pi/2 if max(w,h)/min(w,h)<1.15 else math.pi
    if track.angular_history:
        previous=track.angular_history[-1][1]
        angle=previous+(angle-previous+period/2)%period-period/2
    track.angular_history.append((stamp,angle))
    if len(track.angular_history)<3:return
    data=np.asarray(track.angular_history,float);t=data[:,0]-stamp
    if t[0]>-.04:return
    weights=np.exp(t/.18)
    design=np.column_stack((np.ones(len(t)),t))
    fit,_,_,_=np.linalg.lstsq(design*weights[:,None],data[:,1]*weights,rcond=None)
    residual=float(np.sqrt(np.mean((design@fit-data[:,1])**2)))
    track.angular_velocity=float(fit[1])if residual<.08 else 0.


def touching_capsule(player,quad,margin=0):
    """Distance from a capsule spine to an observed oriented rectangle."""
    center,w,h,angle=rectangle(quad);px,py=player.center
    radius=min(player.w,player.h)/2
    sx=max(0,(player.w-player.h)/2);sy=max(0,(player.h-player.w)/2)
    c,s=math.cos(angle),math.sin(angle)
    def local(x,y):
        x-=center[0];y-=center[1]
        return x*c+y*s,-x*s+y*c
    ax,ay=local(px-sx,py-sy);bx,by=local(px+sx,py+sy)
    vx,vy=bx-ax,by-ay;lo,hi=0.,1.
    for p,v,extent in((ax,vx,w/2),(ay,vy,h/2)):
        if abs(v)<1e-12:
            if abs(p)>extent:lo,hi=1.,0.;break
        else:
            a,b=(-extent-p)/v,(extent-p)/v
            lo=max(lo,min(a,b));hi=min(hi,max(a,b))
    if lo<=hi:return True
    def endpoint(x,y):return max(0,abs(x)-w/2)**2+max(0,abs(y)-h/2)**2
    distance=min(endpoint(ax,ay),endpoint(bx,by));denominator=max(1e-12,vx*vx+vy*vy)
    for x in(-w/2,w/2):
        for y in(-h/2,h/2):
            t=max(0,min(1,((x-ax)*vx+(y-ay)*vy)/denominator))
            distance=min(distance,(ax+t*vx-x)**2+(ay+t*vy-y)**2)
    return distance<(radius+margin)**2


def swept_capsules(before,after,old,new,margin_x=0,margin_y=0,sagitta=0):
    """Batch capsule/OBB sweeps with conservative XY/angular uncertainty.

    Test the convex hull of old/new relative vertices against capsule support
    functions. All possible hull edge normals are included without per-pair
    Python convex-hull calls. Sagitta covers rotation between sample times.
    """
    a=np.asarray(old)[None,:,:,:]-before[:,None,None,:2]
    b=np.asarray(new)[None,:,:,:]-after[:,None,None,:2]
    radius=np.maximum(np.minimum(before[:,2],before[:,3]),np.minimum(after[:,2],after[:,3]))/2
    core_x=np.maximum(0,np.maximum((before[:,2]-before[:,3])/2,(after[:,2]-after[:,3])/2))
    core_y=np.maximum(0,np.maximum((before[:,3]-before[:,2])/2,(after[:,3]-after[:,2])/2))
    sagitta=np.broadcast_to(np.asarray(sagitta),a.shape[:2])
    lower=np.minimum(a.min(axis=2),b.min(axis=2));upper=np.maximum(a.max(axis=2),b.max(axis=2))
    extent=np.stack((radius+core_x+margin_x,radius+core_y+margin_y),axis=1)[:,None,:]+sagitta[:,:,None]
    possible=np.all((lower<=extent)&(upper>=-extent),axis=2)
    rows,cols=np.nonzero(possible);result=np.zeros(a.shape[:2],bool)
    if not len(rows):return result
    # Reject separated AABBs before constructing expensive candidate axes.
    # Each remaining row is one actual player/obstacle pair, not their product.
    a=a[rows,cols];b=b[rows,cols];points=np.concatenate((a,b),axis=1)
    radius=radius[rows];core_x=core_x[rows];core_y=core_y[rows];sagitta=sagitta[rows,cols,None]
    old_edges=np.roll(a,-1,axis=1)-a;new_edges=np.roll(b,-1,axis=1)-b
    bridges=(b[:,:,None,:]-a[:,None,:,:]).reshape(len(a),16,2)
    edges=np.concatenate((old_edges,new_edges,bridges),axis=1)
    normals=np.stack((-edges[...,1],edges[...,0]),axis=-1)
    spine=np.stack((core_x,core_y),axis=1)[:,None,:]
    directions=np.concatenate((points-spine,points+spine),axis=1)
    fixed=np.broadcast_to(np.eye(2),(len(a),2,2))
    axes=np.concatenate((normals,directions,fixed),axis=1)
    norm=np.linalg.norm(axes,axis=-1,keepdims=True);valid=norm[...,0]>1e-10
    axes=axes/np.maximum(norm,1e-10)
    projection=np.einsum('mad,mpd->map',axes,points)
    support=(radius[:,None]+abs(axes[...,0])*core_x[:,None]
             +abs(axes[...,1])*core_y[:,None]
             +abs(axes[...,0])*(margin_x+sagitta)
             +abs(axes[...,1])*(margin_y+sagitta))
    separated=(projection.min(-1)>support)|(projection.max(-1)<-support)
    result[rows,cols]=~np.any(separated&valid,axis=-1)
    return result


def is_box(track):
    shape=getattr(track,'collider_shape',None)
    return shape in('BoxCollider','CapsuleCollider')if shape else track.kind=='trap'
