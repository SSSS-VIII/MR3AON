from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'tools'))
from arena_fixed_sequence import BoardSequence,map_sequences


def sequence():
    return BoardSequence([dict(level=5,map=42,slots=[
        dict(slot=1,fixed=[101],random=False),
        dict(slot=2,fixed=[],random=True),
        dict(slot=3,fixed=[103],random=True),
        dict(slot=4,fixed=[104],random=False),
        dict(slot=5,fixed=[105],random=False)]),
        dict(level=5,map=43,slots=[dict(slot=1,fixed=[201],random=False)]),
        dict(level=6,map=51,slots=[dict(slot=1,fixed=[301],random=False)])])


def test_random_gaps_preserve_order_and_never_skip_an_unseen_fixed_only_slot():
    s=sequence();s.begin(5,1)
    s.accept((5,42,1,101),10,100)
    assert not s.permits((5,42,4,104))
    s.accept((5,42,1,101),90,100)
    assert s.permits((5,42,3,103))and s.permits((5,42,4,104))
    assert not s.permits((5,42,5,105))
    assert not s.permits((5,42,2,999))  # Random boards are never identified.
    s.accept((5,42,4,104),3,100)
    assert [r['slot']for r in s.history if r['status']=='unobserved_random_possible']==[2,3]
    assert not s.permits((5,42,1,101))and not s.permits((5,43,1,201))


def test_own_start_on_random_slot_can_rejoin_only_a_forward_fixed_hypothesis():
    s=sequence();s.begin(5,2)
    assert not s.permits((5,42,1,101))
    assert s.permits((5,42,3,103))
    assert not s.permits((5,42,5,105))
    s.accept((5,42,3,103),5,100)
    assert s.history[0]['status']=='unobserved_random_possible'


def test_background_only_narrows_map_and_cannot_advance_slot_or_create_progress():
    s=sequence();s.begin(5,1)
    for _ in range(3):s.background({(5,42):.95,(5,43):.94})
    assert s.place is None
    for _ in range(3):s.background({(5,42):.95,(5,43):.5})
    assert s.place==(5,42)and s.slot==1 and s.confirmed is None
    assert not s.permits((5,43,1,201))
    for _ in range(4):s.background({(6,51):1.})
    assert s.level==5
    assert 'progress'not in s.state()


def test_only_last_slot_near_exit_can_accept_the_next_level_background():
    s=sequence();s.begin(5,5)
    s.accept((5,42,5,105),10,100)
    for _ in range(3):s.background({(6,51):1.})
    assert s.level==5
    s.accept((5,42,5,105),90,100)
    for _ in range(3):s.background({(6,51):1.})
    assert s.level==6 and s.slot==1 and s.confirmed is None
    assert s.permits((6,51,1,301))


def test_export_retains_random_slots_and_loop_without_adding_random_board_ids():
    variant=lambda i,kind:dict(id=i,classification=dict(layout=kind))
    catalog=dict(levels=[dict(id=5,maps=[dict(id=42)])],maps={'42':dict(slots=[
        dict(pool=[variant(1,'fixed')]),dict(pool=[variant(2,'random')])],
        loop=[variant(3,'fixed'),variant(4,'random')])})
    rows=map_sequences(catalog)
    assert rows[0]['slots']==[dict(slot=1,fixed=[1],random=False,loop=False),
        dict(slot=2,fixed=[],random=True,loop=False),dict(slot=3,fixed=[3],random=True,loop=True)]
