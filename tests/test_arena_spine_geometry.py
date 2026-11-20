"""Real native weapon boxes must follow their original skeleton bone pose."""
import copy
import json
from pathlib import Path
import sys
import numpy as np
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_spine_geometry import follow_quad

CASES=json.loads((Path(__file__).parent/'fixtures/arena-spine-weapon-geometry.json').read_text())['cases']


@pytest.mark.parametrize('case',CASES)
def test_original_bone_pose_reconstructs_native_weapon_corners(case):
    quad=follow_quad(case['spine'],case['bone'],case['collider'])
    actual=np.array([[v['x'],v['y']]for v in case['collider']['quad']])
    assert np.linalg.norm(quad-actual,axis=1).max()<1e-5


@pytest.mark.parametrize('mutation',('scale','overrideAlpha','depth','bone'))
def test_unvalidated_follow_variants_cannot_silently_use_weapon_geometry(mutation):
    case=copy.deepcopy(CASES[0]);c=case['collider']
    if mutation=='scale':c['spine_follow']['fields']['scale']=True
    elif mutation=='overrideAlpha':c['spine_follow']['fields']['overrideAlpha']=.5
    elif mutation=='depth':c['depth_tilt']=True
    else:c['spine_follow']['bone_name']='another_bone'
    with pytest.raises(ValueError):follow_quad(case['spine'],case['bone'],c)
