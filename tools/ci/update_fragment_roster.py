#!/usr/bin/env python3
"""神秘商店勾玉碎片名单：唯一源 + 派生勾选 cases。

为什么需要这个脚本
  名单以前要在 Agent 常量和 GUI checkbox cases 里各抄一份。
  现在只维护一份源；本脚本负责从 BWiki 刷新，或在手改源之后回写派生文件。

唯一源（手动维护改这里）
  assets/resource/data/fragment-roster.json  →  "names"

派生（不要手改，由本脚本生成）
  assets/resource/tasks/日常任务.json
    → option「勾玉购买忍者碎片」.cases
  Agent 运行时直接读上面的 JSON（mystery_shop_fragments.py）

何时怎么用
  1) BWiki 作战分类已有新角色：
       python3 tools/ci/update_fragment_roster.py
     或 GitHub Actions →「Sync fragment roster」→ Run workflow
  2) 游戏已上新角色但 BWiki 还没收录（脚本拉不到）：
       只编辑 fragment-roster.json 的 names，追加全名（流派·名字）
       再执行：
       python3 tools/ci/update_fragment_roster.py --sync-tasks-only
       提交源文件和被改动的 日常任务.json
"""

from __future__ import annotations

import argparse
import json
import sys
import time
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


def apply_roster(names: list[str], *, write_roster: bool) -> int:
    old = load_roster_file(ROSTER_PATH)
    print(f"Roster: {len(names)} names ({len(names) - len(old):+d} vs file)")
    print(f"Source of truth: {ROSTER_PATH.relative_to(ROOT)}")

    roster_changed = False
    if write_roster:
        if names != old:
            write_roster_file(ROSTER_PATH, names)
            roster_changed = True
            print(f"Updated {ROSTER_PATH.relative_to(ROOT)}")
        else:
            print("Roster file unchanged")
    else:
        print("Using existing roster file (no BWiki fetch)")

    try:
        tasks_changed = sync_tasks_cases(TASKS_PATH, names)
    except Exception as e:
        print(f"ERROR: sync tasks failed: {e}", file=sys.stderr)
        return 1

    if tasks_changed:
        print(f"Updated {TASKS_PATH.relative_to(ROOT)} checkbox cases")
    else:
        print("Tasks checkbox cases unchanged")

    if not roster_changed and not tasks_changed:
        print("No change")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=(
            "神秘商店勾玉碎片名单同步。"
            "唯一源: assets/resource/data/fragment-roster.json"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "BWiki 未更新时：编辑源文件 names 后执行\n"
            "  python3 tools/ci/update_fragment_roster.py --sync-tasks-only"
        ),
    )
    parser.add_argument(
        "--sync-tasks-only",
        action="store_true",
        help="不拉 BWiki，只按源文件回写 日常任务.json 勾选 cases",
    )
    args = parser.parse_args(argv)

    if args.sync_tasks_only:
        try:
            names = load_roster_file(ROSTER_PATH)
        except Exception as e:
            print(f"ERROR: {e}", file=sys.stderr)
            return 1
        if not names:
            print(f"ERROR: empty roster in {ROSTER_PATH}", file=sys.stderr)
            return 1
        return apply_roster(names, write_roster=False)

    try:
        fetched = fetch_roster()
    except Exception as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 1

    old = load_roster_file(ROSTER_PATH)
    names = merge_order(old, fetched)
    return apply_roster(names, write_roster=True)


if __name__ == "__main__":
    sys.exit(main())
