#!/usr/bin/env python3
"""Fetch combat full names from BWiki and sync the single fragment roster source.

Writes assets/resource/data/fragment-roster.json, then regenerates the
勾玉购买忍者碎片 checkbox cases in 日常任务.json from that same list.
"""

from __future__ import annotations

import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
ROSTER_PATH = ROOT / "assets" / "resource" / "data" / "fragment-roster.json"
TASKS_PATH = ROOT / "assets" / "resource" / "tasks" / "日常任务.json"
OPTION_KEY = "勾玉购买忍者碎片"
CONFIG_NODE = "勾玉购买忍者碎片配置"
CATEGORIES = ("作战忍者", "作战角色")
USER_AGENT = "MR3A/1.0 (fragment roster updater; +https://github.com/originalsage/MR3A)"
API = "https://wiki.biligame.com/nmd3/api.php"
RETRIES = 3


def _request_json(params: dict) -> dict:
    url = API + "?" + urllib.parse.urlencode(params)
    last_error: Exception | None = None
    for attempt in range(1, RETRIES + 1):
        t0 = time.perf_counter()
        try:
            req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=20) as resp:
                body = resp.read()
                ms = round((time.perf_counter() - t0) * 1000)
                print(f"HTTP {resp.status} ({ms}ms, {len(body)} bytes) attempt={attempt}")
                return json.loads(body)
        except Exception as e:
            last_error = e
            print(f"WARN: fetch failed attempt={attempt}: {e}", file=sys.stderr)
            if attempt < RETRIES:
                time.sleep(attempt * 2)
    raise RuntimeError(f"BWiki fetch failed after {RETRIES} attempts: {last_error}")


def fetch_category_titles(category: str) -> list[str]:
    titles: list[str] = []
    cont: str | None = None
    while True:
        params = {
            "action": "query",
            "list": "categorymembers",
            "cmtitle": f"Category:{category}",
            "cmlimit": "500",
            "cmnamespace": "0",
            "format": "json",
        }
        if cont:
            params["cmcontinue"] = cont
        data = _request_json(params)
        members = data.get("query", {}).get("categorymembers", [])
        titles.extend(m["title"] for m in members if "title" in m)
        cont = data.get("continue", {}).get("cmcontinue")
        if not cont:
            break
    return titles


def fetch_roster() -> list[str]:
    seen: set[str] = set()
    names: list[str] = []
    for category in CATEGORIES:
        for title in fetch_category_titles(category):
            if "·" not in title or title in seen:
                continue
            seen.add(title)
            names.append(title)
    if not names:
        raise RuntimeError("BWiki returned empty combat roster")
    return names


def merge_order(old: list[str], fetched: list[str]) -> list[str]:
    """Keep prior order for surviving names; append newcomers in fetch order."""
    fetched_set = set(fetched)
    kept = [name for name in old if name in fetched_set]
    kept_set = set(kept)
    added = [name for name in fetched if name not in kept_set]
    return kept + added


def load_roster_file(path: Path) -> list[str]:
    if not path.is_file():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(data, list):
        return [str(x) for x in data]
    names = data.get("names")
    if not isinstance(names, list):
        raise ValueError(f"{path}: missing names list")
    return [str(x) for x in names]


def write_roster_file(path: Path, names: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"names": names}
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def fragment_checkbox_cases(names: list[str]) -> list[dict]:
    return [
        {
            "name": name,
            "pipeline_override": {
                CONFIG_NODE: {
                    "attach": {
                        name: True,
                    }
                }
            },
        }
        for name in names
    ]


def sync_tasks_cases(tasks_path: Path, names: list[str]) -> bool:
    tasks = json.loads(tasks_path.read_text(encoding="utf-8"))
    option = tasks.get("option", {}).get(OPTION_KEY)
    if not isinstance(option, dict):
        raise KeyError(f"missing option {OPTION_KEY!r} in {tasks_path}")
    new_cases = fragment_checkbox_cases(names)
    if option.get("cases") == new_cases:
        return False
    option["cases"] = new_cases
    tasks_path.write_text(
        json.dumps(tasks, ensure_ascii=False, indent=4) + "\n",
        encoding="utf-8",
    )
    return True


def main() -> int:
    try:
        fetched = fetch_roster()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    old = load_roster_file(ROSTER_PATH)
    names = merge_order(old, fetched)
    print(f"Roster: {len(names)} names ({len(names) - len(old):+d} vs file)")

    roster_changed = names != old
    if roster_changed:
        write_roster_file(ROSTER_PATH, names)
        print(f"Updated {ROSTER_PATH.relative_to(ROOT)}")
    else:
        print("Roster file unchanged")

    try:
        tasks_changed = sync_tasks_cases(TASKS_PATH, names)
    except Exception as e:
        print(f"ERROR: sync tasks failed: {e}", file=sys.stderr)
        return 1

    if tasks_changed:
        print(f"Updated {TASKS_PATH.relative_to(ROOT)}")
    else:
        print("Tasks checkbox cases unchanged")

    if not roster_changed and not tasks_changed:
        print("No change")
    return 0


if __name__ == "__main__":
    sys.exit(main())
