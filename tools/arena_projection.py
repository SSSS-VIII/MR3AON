"""Recover gameplay-plane colliders from projected 3-D bounding-cube labels.

Projecting all eight AABB corners inflates boxes with distance from screen
center. It is not the same as a collider's cross-section in the gameplay plane.
"""
import json
from pathlib import Path
from arena_vision import Box

CAMERA=json.loads((Path(__file__).resolve().parents[1]/'arena/vision-camera.json').read_text())
FOCAL=(CAMERA['focal_x']+CAMERA['focal_y'])/2
SCALE=FOCAL/CAMERA['player_plane_depth']


def _axis(center,half,focal):
    # Cross-center bounds have both extrema on the near face of the cube.
    return half/(focal+(half if abs(center)<half else abs(center)))


def _center(center,half,q):
    if abs(center)<half:
        return center*(1-q)
    return center-(1 if center>=0 else-1)*half*q


def sphere_plane(box):
    x,y=box.center;ax=x-CAMERA['center_x'];ay=y-CAMERA['center_y']
    q=(_axis(ax,box.w/2,FOCAL)+_axis(ay,box.h/2,FOCAL))/2
    q=max(0,min(.45,q));radius=FOCAL*q
    cx=CAMERA['center_x']+_center(ax,box.w/2,q)
    cy=CAMERA['center_y']+_center(ay,box.h/2,q)
    return Box(cx-radius,cy-radius,2*radius,2*radius)


def capsule_plane(box):
    """Original Role capsule is vertical; its X/Z half extents are the radius."""
    x,y=box.center;ax=x-CAMERA['center_x'];ay=y-CAMERA['center_y']
    q=max(0,min(.45,_axis(ax,box.w/2,FOCAL)))
    radius=FOCAL*q
    cx=CAMERA['center_x']+_center(ax,box.w/2,q)
    cy=CAMERA['center_y']+_center(ay,box.h/2,q)
    half=box.h/2*(1-q)if abs(ay)<box.h/2 else box.h/2-abs(ay)*q
    half=max(radius,half)
    return Box(cx-radius,cy-half,2*radius,2*half)
