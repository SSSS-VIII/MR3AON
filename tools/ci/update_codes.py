#!/usr/bin/env python3
"""Fetch the latest weekly code from BWiki SMW API, update local remote file and send to Kingsoft Docs."""

import json
import os
import sys
import time
import urllib.error
import urllib.parse
import urllib.request

import requests

SMW_URL = "https://wiki.biligame.com/nmd3/api.php?" + urllib.parse.urlencode({
    "action": "ask",
    "query": "[[Category:兑换码]][[Category:每周]]|?兑换码|?时间|sort=时间|order=desc|limit=1",
    "format": "json",
})
META_PATH = "assets/remote/game-meta.json"


def _send_to_kdocs(key: str, value: str) -> bool:
    """Returns True if env vars not set (skip) or if send succeeds."""
    file_id = os.environ.get("KDOCS_FILE_ID")
    if not file_id:
        print("KDocs: env not configured, skip")
        return True

    script_id = os.environ["KDOCS_UPDATE_SCRIPT_ID"]
    token = os.environ["KDOCS_TOKEN"]
    sheet = os.environ.get("KDOCS_SHEET_NAME", "GameMeta")

    url = (
        f"https://www.kdocs.cn/api/v3/ide/file/"
        f"{file_id}/script/{script_id}/sync_task"
    )
    headers = {
        "Content-Type": "application/json",
        "AirScript-Token": token,
    }
    payload = {
        "Context": {
            "argv": {
                "sheetName": sheet,
                "key": key,
                "value": value,
            }
        }
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
    if resp.status_code != 200:
        print(f"ERROR: KDocs API HTTP {resp.status_code}: {resp.text}", file=sys.stderr)
        return False

    result = resp.json()
    print(f"KDocs response: {json.dumps(result, ensure_ascii=False)}")
    return True


def main():
    # Phase 1: HTTP
    t0 = time.perf_counter()
    try:
        req = urllib.request.Request(
            SMW_URL,
            headers={"User-Agent": "MR3A/1.0 (weekly code updater; +https://github.com/originalsage/MR3A)"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read()
            ms = round((time.perf_counter() - t0) * 1000)
            print(f"HTTP {resp.status} ({ms}ms, {len(body)} bytes)")
            data = json.loads(body)
    except Exception as e:
        print(f"ERROR: BWiki fetch failed: {e}", file=sys.stderr)
        return 1

    # Phase 2: Parse SMW response
    try:
        results = data.get("query", {}).get("results", {})
        if not results:
            print("ERROR: SMW returned empty results", file=sys.stderr)
            return 1
        first = list(results.values())[0]
        codes = first.get("printouts", {}).get("兑换码")
        if not codes or not isinstance(codes, list) or len(codes) == 0:
            print("ERROR: 兑换码 field is empty or not a list", file=sys.stderr)
            return 1
        code = codes[0]
        if not isinstance(code, str):
            print(f"ERROR: 兑换码 is not a string: {type(code).__name__}", file=sys.stderr)
            return 1
        print(f"Code: {code}")
    except Exception as e:
        print(f"ERROR: Parse failed: {e}", file=sys.stderr)
        return 1

    # Phase 3: Update local remote file
    try:
        with open(META_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except FileNotFoundError:
        meta = {}
    except json.JSONDecodeError as e:
        print(f"ERROR: game-meta.json corrupt: {e}", file=sys.stderr)
        return 1

    old = meta.get("每周兑换码")
    if old != code:
        meta["每周兑换码"] = code
        with open(META_PATH, "w", encoding="utf-8") as f:
            json.dump(meta, f, ensure_ascii=False, indent=2)
            f.write("\n")
        print(f"Updated remote file: {old!r} -> {code!r}")
    else:
        print(f"Remote file unchanged (current: {code})")

    # Phase 4: Send to Kingsoft Docs (optional, skipped if env not configured)
    if not _send_to_kdocs("每周兑换码", code):
        print("ERROR: Send to Kingsoft Docs failed", file=sys.stderr)
        return 1

    print(f"Done: 每周兑换码 = {code}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
