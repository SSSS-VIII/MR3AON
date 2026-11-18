"""Capture transport contracts without an Android device or GPU."""
from pathlib import Path
from types import SimpleNamespace
import sys
import pytest
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_render_capture import RenderCapture,validate_header


def header():
    return dict(sequence=2,frame=100,size=640*360*4,requested=1.,eof=1.01,read_end=1.012,ready=1.016)


def test_valid_header_preserves_source_readback_clock():
    value=header();assert validate_header(value,2)is value
    assert value['eof']<value['ready']


@pytest.mark.parametrize('key,value',[('sequence',1),('sequence',True),('frame',-1),('frame',False),
    ('size',640*360*3),('requested',0),('requested',float('nan')),('eof',float('inf')),
    ('read_end',1.005),('ready',1.011),('ready',True)])
def test_invalid_source_packets_are_not_accepted(key,value):
    packet=header();packet[key]=value
    with pytest.raises(ValueError):validate_header(packet,2)


def test_only_isolated_arena_and_reviewed_geometry_can_open():
    with pytest.raises(ValueError):RenderCapture(SimpleNamespace(spec=SimpleNamespace(name='main')))
    with pytest.raises(ValueError):RenderCapture(SimpleNamespace(spec=SimpleNamespace(name='arena')),width=1280)


def test_native_paired_collection_cannot_silently_use_another_image_backend():
    instance=RenderCapture(SimpleNamespace(spec=SimpleNamespace(name='arena')))
    with pytest.raises(RuntimeError,match='paired'):instance.paired_step(2)


def test_resume_and_first_image_share_one_request_and_keep_the_regular_frame_protocol():
    import io,json
    instance=RenderCapture(SimpleNamespace(spec=SimpleNamespace(name='arena')))
    with pytest.raises(RuntimeError,match='initialized'):instance.resume_capture()
    instance._render_ready=True;instance._sequence=0;sent=[]
    instance._render_socket=SimpleNamespace(sendall=sent.append)
    data=b''
    for sequence in (1,2):
        packet=dict(header(),sequence=sequence)
        data+=json.dumps(packet).encode()+b'\n'+bytes(packet['size'])
    instance._render_file=io.BytesIO(data)
    first=instance.resume_capture();second=instance.capture()
    assert sent==[b'\2',b'\1']
    assert (first.width,first.height)==(640,360) and first.sequence+1==second.sequence
    assert first.device_captured_ns==1010000000
