"""Collision geometry counterexamples that distinguish real corners/AABB."""
from pathlib import Path
import sys
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_privileged_geometry import capsule_quad


def rectangle(center,length,width,angle):
    q=np.array([[-length/2,-width/2],[length/2,-width/2],
                [length/2,width/2],[-length/2,width/2]])
    c,s=np.cos(angle),np.sin(angle)
    return q@np.array([[c,s],[-s,c]])+center


def test_slender_diagonal_box_does_not_fill_its_empty_AABB_corners():
    # The AABB contains the capsule; the original diagonal blade is far away.
    q=rectangle(np.array([0.,0.]),8.,.1,np.pi/4)
    body=np.array([[2.,-2.,.18,.3]])
    assert capsule_quad(body,q[None,:,:],np.array([True]))[0]>2.


def test_capsule_spine_intersects_box_without_either_endpoint_inside():
    q=rectangle(np.array([0.,0.]),3.,.1,0.)
    body=np.array([[0.,0.,.18,2.]])
    assert capsule_quad(body,q[None,:,:],np.array([True]))[0]<0


def test_fast_thin_blade_cannot_skip_capsule_between_samples():
    q=np.array([rectangle(np.array([x,0.]),.1,3.,0.) for x in (-1.,1.)])
    body=np.tile([0.,0.,.18,.3],(2,1))
    assert capsule_quad(body,q,np.array([True,True]))[-1]<0


def test_inactive_attack_shape_does_not_become_a_hazard():
    q=np.tile(rectangle(np.zeros(2),3.,3.,0.),(2,1,1))
    body=np.tile([0.,0.,.18,.3],(2,1))
    assert np.isinf(capsule_quad(body,q,np.array([False,False]))).all()
