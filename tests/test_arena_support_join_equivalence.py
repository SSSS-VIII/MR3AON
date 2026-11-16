"""Optimize the existing topology test without changing its boundary semantics."""
from pathlib import Path
import sys
import pytest
pytest.importorskip('numpy')
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_support import joined_endpoints,connected_height,height


def original_join(a,b):
    return min(np.linalg.norm(np.asarray(a[p])-b[q])for p,q in [('a','b'),('b','a')])<=6


def original_height(segments,selected_id,x,seconds=0):
    reached={selected_id};pending=[s for s in segments if s['id']==selected_id]
    while pending:
        old=pending.pop()
        for s in segments:
            if s['id']in reached or s['kind']!=old['kind']:continue
            if original_join(old,s):reached.add(s['id']);pending.append(s)
    values=[y for s in segments if s['id']in reached for y in[height(s,x,seconds)]if y is not None]
    return min(values)if values else None


def test_random_and_near_boundary_pairs_match_the_original_norm():
    rng=np.random.default_rng(5129)
    for _ in range(2000):
        a=dict(a=rng.uniform(-800,1200,2).tolist(),b=rng.uniform(-800,1200,2).tolist())
        b=dict(a=rng.uniform(-800,1200,2).tolist(),b=rng.uniform(-800,1200,2).tolist())
        assert joined_endpoints(a,b)==original_join(a,b)
    for angle in np.linspace(0,2*np.pi,30):
        for delta in [-1e-7,-1e-12,0.,1e-12,1e-7]:
            point=np.array([np.cos(angle),np.sin(angle)])*(6+delta)
            a=dict(a=(100,100),b=(0,0));b=dict(a=tuple(point),b=(300,300))
            assert joined_endpoints(a,b)==original_join(a,b)


@pytest.mark.parametrize('bad',[float('nan'),float('inf'),float('-inf')])
def test_nonfinite_order_keeps_legacy_unknown_behavior(bad):
    for first in [True,False]:
        a=dict(a=(0,0),b=(10,0));b=dict(a=(10,0),b=(0,0))
        a['a'if first else'b']=(bad,0)
        assert joined_endpoints(a,b)==original_join(a,b)


def test_connected_slopes_gaps_and_moving_surfaces_keep_exact_queries():
    segments=[dict(id=1,kind='rope',a=(0.,200.),b=(200.,210.),vx=-300.,vy=0.),
              dict(id=2,kind='rope',a=(204.,210.),b=(400.,190.),vx=-300.,vy=0.),
              dict(id=3,kind='rope',a=(408.,190.),b=(600.,200.),vx=-300.,vy=0.),
              dict(id=4,kind='platform',a=(200.,210.),b=(500.,210.),vx=-300.,vy=0.),
              dict(id=5,kind='floating_platform',a=(190.,210.),b=(400.,210.),vx=-180.,vy=20.)]
    for identity in [1,2,3,4,5,99]:
        for seconds in [0.,.04,.4,1.]:
            for x in [-100.,0.,150.,210.,390.,550.,700.]:
                assert connected_height(segments,identity,x,seconds)==original_height(segments,identity,x,seconds)
