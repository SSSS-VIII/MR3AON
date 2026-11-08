"""Synthetic diskdata structures, independent of the client's private key/data."""

import struct
from pathlib import Path
import sys
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))
from arena_diskdata import Reader, LuaTable, normal, xor_record, directory, recover


def packet(content):
    return struct.pack("<I", len(content) + 4) + content


def number(n):
    return b"\x22" + struct.pack("<i", n)


def string(s):
    data = s.encode()
    assert len(data) < 32
    return bytes([len(data) * 8 + 4]) + data


def table(array=(), pairs=()):
    assert len(array) < 31
    return (
        bytes([len(array) * 8 + 6])
        + b"".join(array)
        + b"".join(k + v for k, v in pairs)
        + b"\0"
    )


def test_mixed_lua_keys_and_numeric_widths_are_preserved():
    content = table(
        [number(-3)],
        [(string("a"), b"\x01"), (number(7), b"\x42" + struct.pack("<d", 0.25))],
    )
    value = Reader(packet(content)).packet()[0]
    assert value.array == [-3]
    assert value.pairs == [("a", False), (7, 0.25)]
    assert normal(value) == {
        "$lua_array": [-3],
        "$lua_pairs": [["a", False], [7, 0.25]],
    }
    assert Reader(
        packet(b"\x02\x0a\xff\x12\xff\xff\x32" + struct.pack("<q", -2))
    ).packet() == [0, 255, 65535, -2]


def test_truncation_invalid_types_lengths_and_extended_array_sizes_fail():
    for raw in [
        b"",
        packet(b"\x12\x01"),
        packet(b"\x03"),
        packet(b"\xfd\xff"),
        packet(b"\xfe\x42"),
        packet(b"\xfe\x22" + struct.pack("<i", -1)),
    ]:
        with pytest.raises((ValueError, struct.error)):
            Reader(raw).packet()
    with pytest.raises(ValueError):
        Reader(b"\x08\0\0\0").packet()


def fixture_file():
    key = bytes(range(64))
    row = packet(table(pairs=[(string("Speed"), number(8))]))
    reference = table([number(0), number(len(row))])
    meta = table([reference], [(string("_d"), number(1))])
    index = packet(table(pairs=[(string("CfgFixture"), meta)]))
    return (
        xor_record(row, key)
        + xor_record(index, key)
        + struct.pack("<I", len(index) ^ 0xA32A1245),
        key,
    )


def test_directory_and_rows_are_read_with_separate_xor_phases(tmp_path):
    data, key = fixture_file()
    root, end = directory(data, key)
    assert root.field("CfgFixture").field("_d") == 1
    report = recover(data, key, tmp_path)
    assert len(report["tables"]) == 1 and not report["errors"]
    import json

    row = json.loads((tmp_path / "CfgFixture.json").read_text())[0]
    assert row["key_path"] == [1] and row["values"] == [{"Speed": 8}]
    with pytest.raises(ValueError, match="Missing requested"):
        recover(data, key, tmp_path, ["Absent"])
    for bad in [b"bad", data[:-4] + b"\0" * 4]:
        with pytest.raises(ValueError):
            directory(bad, key)
    with pytest.raises(ValueError, match="64-byte"):
        xor_record(b"abc", b"wrong")
