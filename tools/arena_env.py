"""Synchronous visual-training adapter for the isolated original arena client.

Observations contain original 1280x720 PNG bytes and optional privileged state.
Actions: 0/none, 1/jump, 2/down. One tick is the client's original 0.02 s step.
No model, reward shaping, account login or online arena control is included.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import subprocess

from arena_bootstrap import wait_job
from arena_local import LocalClient, ROOT
from runtime import InstanceSession


@dataclass(frozen=True)
class Observation:
    image_png: bytes
    state: dict

    def save(self, directory: Path, name: str):
        directory.mkdir(parents=True, exist_ok=True)
        (directory / f"{name}.png").write_bytes(self.image_png)
        (directory / f"{name}.json").write_text(json.dumps(self.state, ensure_ascii=False, indent=2) + "\n")


class ArenaEnv:
    ACTIONS = {0: "none", 1: "jump", 2: "down"}

    def __init__(self, *, auto_start=True, client=None):
        self.client = client or LocalClient(InstanceSession("arena"))
        self.auto_start = auto_start
        self._last_state = None
        self._terminated = False

    def _observe(self, state):
        return Observation(self.client.session.screenshot(), state)

    def reset(self, *, seed=1, chapter=1, level=1, map_id=None, start_board=1, boards=None):
        if type(seed) is not int or not 0 <= seed <= 2147483647:
            raise ValueError("Seed must be an integer in 0..2147483647")
        if type(chapter) is not int or type(level) is not int or chapter < 1 or level < 1:
            raise ValueError("Chapter and level must be positive integers")
        if map_id is not None and (type(map_id) is not int or map_id < 1):
            raise ValueError("Map ID must be a positive integer")
        if type(start_board) is not int or start_board < 1:
            raise ValueError("Starting board must be a positive integer")
        if boards is not None and (not isinstance(boards, dict) or any(
                type(k) is not int or k < 1 or type(v) is not int or v < 1 for k, v in boards.items())):
            raise ValueError("Boards must map integer positions to positive variant IDs")
        if map_id is None and (start_board != 1 or boards):
            raise ValueError("Select a map before selecting boards")
        selection = None
        if map_id is not None:
            selection = dict(level=level, map=map_id, start=start_board,
                             pins={str(k): v for k, v in (boards or {}).items()})
            if chapter != 1:
                selection['chapter'] = chapter
        # A failed reset must not leave the previous episode open for stepping.
        self._last_state = None
        self._terminated = True
        ready = None
        try:
            ready = self.client.execute("return MR3A and MR3A.state()", timeout=1)
        except RuntimeError as exc:
            if "已有控制者" in str(exc) or not self.auto_start:
                raise
        except TimeoutError:
            if not self.auto_start:
                raise
        if not ready:
            if not self.auto_start:
                raise RuntimeError("Start the local arena first with tools/run-arena --paused")
            subprocess.run([str(ROOT / "tools/run-arena"), "--paused", "--no-focus", "--seed", str(seed),
                            "--chapter", str(chapter), "--level", str(level)], cwd=ROOT, check=True)
        else:
            self.client.load_environment()
            self.client.execute("MR3A.menu_suppressed=true;if MR3A.hide_menu then MR3A.hide_menu() end;return true")
            if selection is None:
                self.client.execute(f"MR3A.nativeSelection=nil;return MR3A.reset({seed},{chapter},{level})")
                wait_job(self.client, "MR3A.resetJob")
        if selection is not None:
            self.client.execute("return MR3A.native_select(json.parse(" + json.dumps(json.dumps(selection)) + f"),{seed})")
            wait_job(self.client, "MR3A.travel", timeout=610)
        state = self.client.execute("return MR3A.state()")
        if (state.get("state") != "Game: 8" or state.get("mode") != 6 or state.get("timeScale") != 0
                or state.get("maxHealth") != 5000 or state.get("health", 0) <= 0
                or (selection is None and state.get("health") != 5000)):
            raise RuntimeError("Reset did not produce a paused, healthy Xiaohei battle")
        self._last_state = state
        self._terminated = False
        return self._observe(state), {"seed": seed, "chapter": chapter, "level": level, "selection": selection}

    def step(self, action, *, ticks=1):
        if type(action) is int:
            action = self.ACTIONS.get(action)
        if action not in self.ACTIONS.values():
            raise ValueError("Action must be none/jump/down or 0/1/2")
        if type(ticks) is not int or not 1 <= ticks <= 600:
            raise ValueError("Ticks must be an integer in 1..600")
        if self._last_state is None or self._terminated:
            raise RuntimeError("Reset the environment before stepping")
        self.client.execute(f"return MR3A.advance({ticks},{json.dumps(action)})")
        job = wait_job(self.client, "MR3A.job", timeout=max(15, ticks * 0.2 + 10))
        state = job["after"]
        reward = state["score"] - self._last_state["score"]
        terminated = bool(job.get("terminated") or state.get("health", 1) <= 0)
        info = {"ticks": state["episodeFrame"] - job["before"]["episodeFrame"],
                "render_frames": state["frame"] - job["before"]["frame"],
                "health_delta": state["health"] - self._last_state["health"],
                "samples": job["samples"], "reward_source": "original_client_score_delta"}
        self._last_state = state
        self._terminated = terminated
        return self._observe(state), reward, terminated, False, info

    def layout(self):
        return self.client.execute("return MR3A.layout()")

    def close(self):
        """Pause the environment; preserve its named instance and local data."""
        self.client.execute("return MR3A.pause()")
