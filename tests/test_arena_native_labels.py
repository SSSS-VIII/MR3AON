"""Native JSON and pooled-identity regressions from paired arena collection."""
import sys
from pathlib import Path
import pytest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_native_json import normalize_arrays


def test_direct_native_arrays_and_rpc_arrays_decode_identically():
    direct={'objects':{'1':{'colliders':{'1':{'box':{'1':10,'2':20,'3':30,'4':40}}}}}}
    rpc={'objects':[{'colliders':[{'box':[10,20,30,40]}]}]}
    assert normalize_arrays(direct)==normalize_arrays(rpc)==rpc
    assert isinstance(direct['objects'],dict)  # Raw evidence remains unchanged.


@pytest.mark.parametrize('value',[{}, {'2':'x'}, {'1':'a','3':'b'}, {'1':'a','name':'x'}, {'0':'a'}])
def test_numeric_maps_are_not_mistaken_for_dense_arrays(value):
    assert normalize_arrays(value)==value


def test_pooled_id_is_not_a_continuous_future_target():
    pytest.importorskip('cv2')
    from arena_vision_dataset import continuous_identity
    from arena_vision import Box
    obj={'name':'EnemySpider(Clone)','type':'EnemySpider'}
    def sample(t,x):
        truth={}if x is None else{42:(obj,Box(x,200,24,24))}
        return ({'t':t},{},truth,{})
    continuous=[sample(0,500),sample(.08,455),sample(.16,410)]
    assert continuous_identity(continuous,0,2,42)
    assert not continuous_identity([sample(0,200),sample(.08,None),sample(.16,650)],0,2,42)
    assert not continuous_identity([sample(0,200),sample(.08,650)],0,1,42)
