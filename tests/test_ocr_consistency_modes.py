import pytest

from custom.reco.ocr_consistency import texts_match


def test_full_text_default_and_strict_remain_compatible():
    assert texts_match("收集礼包", "收集礼帶")
    assert not texts_match("收集礼包", "收集大礼包")
    assert not texts_match("收集礼包", "收集礼帶", strict=True)


def test_explicit_prefix_requires_enough_characters_and_does_not_use_fuzzy_match():
    assert texts_match("收集礼包", "收集礼帶", prefix_len=3)
    assert not texts_match("收集大礼包", "收集礼帶", prefix_len=3)
    assert not texts_match("收集", "收集", prefix_len=3)
    for invalid in (0, -1, True, "3"):
        with pytest.raises(ValueError):
            texts_match("收集礼包", "收集礼包", prefix_len=invalid)
