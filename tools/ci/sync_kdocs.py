#!/usr/bin/env python3
"""Sync game-meta.json to Kingsoft Docs (blackboard -> KDocs).

Reads assets/remote/game-meta.json and sends each key-value pair
to the GameMeta sheet via update_cell AirScript.
"""

import json
import os
import sys

import requests

META_PATH = "assets/remote/game-meta.json"


def _sync_key(file_id: str, script_id: str, token: str, sheet: str,
              key: str, value: str) -> bool:
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
                "value": str(value),
            }
        }
    }

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)
    if resp.status_code != 200:
        print(
            f"  {key}: HTTP {resp.status_code} {resp.text}",
            file=sys.stderr,
        )
        return False
    print(f"  {key}: OK ({resp.json().get('data', {}).get('result', '')})")
    return True


def main():
    file_id = os.environ.get("KDOCS_FILE_ID")
    script_id = os.environ.get("KDOCS_UPDATE_SCRIPT_ID")
    token = os.environ.get("KDOCS_TOKEN")
    sheet = os.environ.get("KDOCS_SHEET_NAME", "GameMeta")

    if not file_id:
        print("KDOCS_FILE_ID not set, skip")
        return 0
    if not script_id:
        print("KDOCS_UPDATE_SCRIPT_ID not set, skip")
        return 0
    if not token:
        print("KDOCS_TOKEN not set, skip")
        return 0

    try:
        with open(META_PATH, "r", encoding="utf-8") as f:
            meta = json.load(f)
    except FileNotFoundError:
        print(f"ERROR: {META_PATH} not found", file=sys.stderr)
        return 1
    except json.JSONDecodeError as e:
        print(f"ERROR: {META_PATH} invalid: {e}", file=sys.stderr)
        return 1

    print(f"Syncing {len(meta)} keys to Kingsoft Docs...")
    failed = 0
    for key, value in meta.items():
        if not _sync_key(file_id, script_id, token, sheet, key, value):
            failed += 1

    if failed:
        print(f"ERROR: {failed} key(s) failed", file=sys.stderr)
        return 1
    print("Sync complete")
    return 0


if __name__ == "__main__":
    sys.exit(main())
