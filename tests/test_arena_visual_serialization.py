"""A visible warning must not terminate gameplay while writing diagnostics."""
import json
from pathlib import Path
import sys
import pytest
pytest.importorskip('cv2')
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_vision import Box,serializable


def test_nested_warning_boxes_and_motion_records_are_json_serializable():
    observation=dict(cues=[dict(box=Box(20,30,40,50),confidence=.9)],
                     nested={'trajectory':(Box(1,2,3,4),)})
    restored=json.loads(json.dumps(serializable(observation)))
    assert restored['cues'][0]['box']==dict(x=20,y=30,w=40,h=50)
    assert restored['nested']['trajectory'][0]['h']==4
