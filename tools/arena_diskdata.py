#!/usr/bin/env python3
"""Decode the observed client diskdata format without running Lua or native code.

A supplied 64-byte local key unwraps records independently. Lua tables keep
numeric keys, array entries and mixed maps; unknown native userdata is rejected.
"""

from pathlib import Path
import struct, json, argparse, hashlib
from arena_fidelity_assets import write_exact


class LuaTable:
    def __init__(self, arr, pairs):
        self.array = arr
        self.pairs = pairs

    def field(self, key):
        for k, v in self.pairs:
            if k == key:
                return v
        return None

    def json(self):
        return {"$lua_array": self.array, "$lua_pairs": self.pairs}


class Reader:
    def __init__(self, b):
        self.b = b
        self.p = 0
        self.nodes = 0

    def take(self, n):
        if n < 0 or self.p + n > len(self.b):
            raise ValueError(("bounds", self.p, n))
        out = self.b[self.p : self.p + n]
        self.p += n
        return out

    def number(self, cookie):
        if cookie == 0:
            return 0
        fmt = {1: "B", 2: "H", 4: "i", 6: "q"}.get(cookie)
        if not fmt:
            raise ValueError(("integer cookie", cookie, self.p))
        return struct.unpack("<" + fmt, self.take(struct.calcsize(fmt)))[0]

    def value(self, depth=0):
        self.nodes += 1
        if depth > 128 or self.nodes > 5000000:
            raise ValueError("limit")
        v = self.take(1)[0]
        typ = v & 7
        cookie = v >> 3
        if typ == 0:
            return None
        if typ == 1:
            return bool(cookie)
        if typ == 2:
            return (
                struct.unpack("<d", self.take(8))[0]
                if cookie == 8
                else self.number(cookie)
            )
        if typ == 3:
            raise ValueError("userdata cannot be recovered as configuration")
        if typ == 4:
            return self.take(cookie).decode("utf8")
        if typ == 5:
            if cookie not in [2, 4]:
                raise ValueError("long string cookie")
            n = struct.unpack("<" + ("H" if cookie == 2 else "i"), self.take(cookie))[0]
            return self.take(n).decode("utf8")
        if typ == 7:
            return {"$shared_table": True}
        if typ == 6:
            n = cookie
            if n == 31:
                tag = self.take(1)[0]
                if tag & 7 != 2 or tag >> 3 == 8:
                    raise ValueError("Invalid extended array size")
                n = self.number(tag >> 3)
            if not 0 <= n <= min(5000000, len(self.b) - self.p):
                raise ValueError("table limit")
            arr = [self.value(depth + 1) for _ in range(n)]
            pairs = []
            while True:
                key = self.value(depth + 1)
                if key is None:
                    break
                pairs.append((key, self.value(depth + 1)))
            return LuaTable(arr, pairs)

    def packet(self):
        size = struct.unpack("<I", self.take(4))[0]
        if size != len(self.b):
            raise ValueError(("packet length", size, len(self.b)))
        vals = []
        while self.p < len(self.b):
            vals.append(self.value())
        return vals


def normal(v):
    if isinstance(v, LuaTable):
        if v.array and not v.pairs:
            return [normal(x) for x in v.array]
        if not v.array and all(isinstance(k, str) for k, x in v.pairs):
            return {k: normal(x) for k, x in v.pairs}
        return {
            "$lua_array": [normal(x) for x in v.array],
            "$lua_pairs": [[normal(k), normal(x)] for k, x in v.pairs],
        }
    return v


def xor_record(data, key):
    if len(key) != 64:
        raise ValueError("Expected 64-byte diskdata key")
    return bytes(v ^ key[i % 64] for i, v in enumerate(data))


def directory(data, key):
    if len(data) < 8:
        raise ValueError("Truncated diskdata file")
    size = struct.unpack("<I", data[-4:])[0] ^ 0xA32A1245
    if not 4 <= size <= len(data) - 4:
        raise ValueError("Invalid directory bounds")
    values = Reader(xor_record(data[-4 - size : -4], key)).packet()
    if len(values) != 1 or not isinstance(values[0], LuaTable):
        raise ValueError("Invalid directory root")
    return values[0], len(data) - 4 - size


def leaves(node, depth, path=()):
    if (
        not isinstance(node, LuaTable)
        or not isinstance(depth, int)
        or not 0 <= depth <= 32
    ):
        raise ValueError("Invalid metadata tree")
    if depth == 0:
        if len(node.array) != 2 or any(k != "_d" for k, v in node.pairs):
            raise ValueError("Invalid record reference")
        offset, size = node.array
        if not isinstance(offset, int) or not isinstance(size, int):
            raise ValueError("Non-integer record reference")
        yield path, (offset, size)
    else:
        for i, v in enumerate(node.array, 1):
            if v is not None:
                yield from leaves(v, depth - 1, path + (i,))
        for k, v in node.pairs:
            if k != "_d":
                yield from leaves(v, depth - 1, path + (k,))


def recover(data, key, output, tables=None):
    root, end = directory(data, key)
    report = {
        "status": "configuration_recovery_not_runtime_equivalence",
        "source_sha256": hashlib.sha256(data).hexdigest(),
        "directory_tables": len(root.pairs),
        "tables": [],
        "errors": [],
    }
    selected = set(tables) if tables else None
    available = {k for k, v in root.pairs}
    if selected and selected - available:
        raise ValueError(
            "Missing requested tables: " + str(sorted(selected - available))
        )
    output.mkdir(parents=True, exist_ok=True)
    for name, meta in root.pairs:
        if selected and name not in selected:
            continue
        try:
            if (
                not isinstance(name, str)
                or Path(name).name != name
                or "/" in name
                or "\\" in name
            ):
                raise ValueError("Unsafe table name")
            records = []
            for path, (offset, size) in leaves(meta, meta.field("_d")):
                if not (0 <= offset <= end and 4 <= size <= end - offset):
                    raise ValueError("Record outside data area")
                encrypted = data[offset : offset + size]
                plain = xor_record(encrypted, key)
                values = Reader(plain).packet()
                records.append(
                    {
                        "key_path": path,
                        "offset": offset,
                        "bytes": size,
                        "sha256": hashlib.sha256(plain).hexdigest(),
                        "values": normal(LuaTable(values, [])),
                    }
                )
            payload = (
                json.dumps(records, ensure_ascii=False, indent=2, allow_nan=False)
                + "\n"
            ).encode()
            stats = write_exact(output / (name + ".json"), payload)
            report["tables"].append({"name": name, "records": len(records), **stats})
        except Exception as exc:
            report["errors"].append({"name": name, "error": str(exc)})
    (output / "recovery.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n"
    )
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    p.add_argument("--key-file", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--table", action="append")
    a = p.parse_args()
    r = recover(a.input.read_bytes(), a.key_file.read_bytes(), a.output, a.table)
    print(
        json.dumps(
            {
                "tables": len(r["tables"]),
                "records": sum(t["records"] for t in r["tables"]),
                "errors": len(r["errors"]),
            }
        )
    )
    if r["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
