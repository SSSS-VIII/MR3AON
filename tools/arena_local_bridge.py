#!/usr/bin/env python3
"""Build a local Lua control bridge from an explicitly supplied client bundle.

Reads local resources only. This does not install, sign or modify an APK.
"""
import argparse
import gzip
import hashlib
import json
from pathlib import Path

from arena_client import unwrap_bundle
from arena_lua import decode_lua


def patch_bundle(raw, bundle_key, lua_key, lua_iv, bridge):
    import UnityPy
    from Crypto.Cipher import AES
    from Crypto.Util.Padding import pad

    if b"MR3A_LOCAL_BRIDGE_READY" not in bridge:
        raise ValueError("Missing local bridge identity")
    UnityPy.set_assetbundle_decrypt_key(bundle_key)
    env = UnityPy.load(unwrap_bundle(raw))
    originals = {}
    target = None
    for obj in env.objects:
        if obj.type.name != "TextAsset":
            continue
        asset = obj.read()
        payload = asset.m_Script
        if isinstance(payload, str):
            payload = payload.encode("utf8", "surrogateescape")
        originals[obj.path_id] = bytes(payload)
        if asset.m_Name in ("LuaMain", "LuaMain.lua"):
            if target is not None:
                raise ValueError("Multiple LuaMain assets")
            target = (obj, asset, bytes(payload))
    if target is None:
        raise ValueError("No LuaMain asset in this bundle")
    obj, asset, payload = target
    plain = decode_lua(payload, lua_key, lua_iv)
    if b"MR3A_LOCAL_BRIDGE_READY" in plain:
        raise ValueError("Bundle already contains a bridge; use its original backup")
    modified = plain + b"\r\n" + bridge
    packed = gzip.compress(modified, mtime=0)
    encrypted = AES.new(lua_key, AES.MODE_CBC, lua_iv).encrypt(pad(packed, 16))
    asset.m_Script = encrypted.decode("utf8", "surrogateescape")
    asset.save()
    rebuilt = next(iter(env.files.values())).save(packer="lz4")
    if raw[:8] == b"UnityFS\0" and raw[78:86] == b"UnityFS\0":
        rebuilt = raw[:78] + rebuilt
    check = UnityPy.load(unwrap_bundle(rebuilt))
    verified = set()
    for item in check.objects:
        if item.type.name != "TextAsset":
            continue
        data = item.read().m_Script
        if isinstance(data, str):
            data = data.encode("utf8", "surrogateescape")
        expected = encrypted if item.path_id == obj.path_id else originals[item.path_id]
        if data != expected:
            raise ValueError(f"TextAsset changed unexpectedly: {item.path_id}")
        verified.add(item.path_id)
    if verified != set(originals):
        raise ValueError("TextAsset inventory changed")
    if decode_lua(encrypted, lua_key, lua_iv) != modified:
        raise ValueError("Lua encryption roundtrip failed")
    return rebuilt, {
        "original_sha256": hashlib.sha256(raw).hexdigest(),
        "patched_sha256": hashlib.sha256(rebuilt).hexdigest(),
        "lua_path_id": obj.path_id,
        "original_lua_sha256": hashlib.sha256(plain).hexdigest(),
        "bridge_sha256": hashlib.sha256(bridge).hexdigest(),
        "unchanged_text_assets": len(originals) - 1,
        "verification": "resource_roundtrip_only",
    }


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--bundle", type=Path, required=True)
    p.add_argument("--bundle-key-file", type=Path, required=True)
    p.add_argument("--lua-key-file", type=Path, required=True)
    p.add_argument("--lua-iv-file", type=Path, required=True)
    p.add_argument("--bridge", type=Path, default=Path(__file__).resolve().parents[1] / "arena/Local/client_bridge.lua")
    p.add_argument("--output", type=Path, required=True)
    a = p.parse_args()
    raw = a.bundle.read_bytes()
    patched, report = patch_bundle(raw, a.bundle_key_file.read_bytes(), a.lua_key_file.read_bytes(), a.lua_iv_file.read_bytes(), a.bridge.read_bytes())
    if a.output.resolve() == a.bundle.resolve():
        raise ValueError("Output must differ from original bundle")
    a.output.parent.mkdir(parents=True, exist_ok=True)
    a.output.write_bytes(patched)
    a.output.with_suffix(".report.json").write_text(json.dumps(report, indent=2) + "\n")
    print(json.dumps(report))


if __name__ == "__main__":
    main()
