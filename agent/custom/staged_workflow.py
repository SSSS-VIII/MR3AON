"""一次性阶段工作流：按实例/账号标识/版本保存进度，不参与每日重置。"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import hashlib
import json
import os
from pathlib import Path
import tempfile
import threading

from utils.runtime_paths import get_runtime_paths


@dataclass(frozen=True)
class Stage:
    workflow: str
    account: str
    revision: str
    number: int
    timing_mode: str = "post_click"
    initial_delay_ms: int = 0
    interval_offset_ms: int = 0

    def __post_init__(self):
        for text in (self.workflow, self.account, self.revision):
            if not isinstance(text, str) or not text.strip() or len(text) > 100:
                raise ValueError("工作流、账号标识和版本必须为非空短字符串")
        if type(self.number) is not int or self.number < 1:
            raise ValueError("阶段编号必须为正整数")
        if self.timing_mode not in ("post_click", "absolute"):
            raise ValueError("未知动作时序模式")
        if type(self.initial_delay_ms) is not int or not 0 <= self.initial_delay_ms <= 10000:
            raise ValueError("首段等待须为0～10000毫秒")
        if type(self.interval_offset_ms) is not int or not -500 <= self.interval_offset_ms <= 500:
            raise ValueError("动作间隔偏移须为-500～500毫秒")


class StageStore:
    def __init__(self, path: Path | None = None):
        self._path = path
        self._lock = threading.RLock()

    @property
    def path(self):
        return self._path or get_runtime_paths().config_dir / "staged_workflows.json"

    def _read(self):
        if not self.path.exists():
            return {"version": 1, "workflows": {}}
        data = json.loads(self.path.read_text(encoding="utf-8"))
        if data.get("version") != 1 or not isinstance(data.get("workflows"), dict):
            raise ValueError("工作流进度文件格式错误，拒绝覆盖")
        return data

    def _write(self, data):
        self.path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".workflow-", dir=self.path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as stream:
                json.dump(data, stream, ensure_ascii=False, indent=2)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)

    def _entry(self, data, stage: Stage):
        identity = [stage.workflow, stage.account, stage.revision]
        key = hashlib.sha256(json.dumps(identity, ensure_ascii=False).encode()).hexdigest()
        for item in data["workflows"].values():
            if item["workflow"] == stage.workflow and item["account"] == stage.account and item["revision"] != stage.revision:
                raise ValueError("该账号已有其它版本的进度，需要人工核对后迁移")
        return data["workflows"].setdefault(key, {
            "workflow": stage.workflow, "account": stage.account,
            "revision": stage.revision, "stages": {},
        })

    def begin(self, stage: Stage, *, retry: bool = False) -> bool:
        with self._lock:
            data = self._read()
            stages = self._entry(data, stage)["stages"]
            previous = stages.get(str(stage.number), {})
            if previous.get("status") == "completed":
                return False
            if previous.get("status") in ("running", "paused") and not retry:
                raise ValueError("该阶段上次未完成；请核对页面与已消费步骤后显式确认重试")
            stages[str(stage.number)] = {
                "status": "running", "updated_at": datetime.now().astimezone().isoformat(),
            }
            self._write(data)
            return True

    def mark(self, stage: Stage, status: str, *, reason: str = ""):
        if status not in ("completed", "paused"):
            raise ValueError("非法阶段状态")
        with self._lock:
            data = self._read()
            stages = self._entry(data, stage)["stages"]
            if stages.get(str(stage.number), {}).get("status") != "running":
                raise ValueError("仅正在执行的阶段可以完成或暂停")
            stages[str(stage.number)] = {
                "status": status, "reason": reason,
                "updated_at": datetime.now().astimezone().isoformat(),
            }
            self._write(data)


stage_store = StageStore()
_active: dict[int, Stage | None] = {}
_active_lock = threading.RLock()


def guard_stage(task_id: int, stage: Stage | None = None):
    with _active_lock:
        _active[task_id] = stage


def stage_is_guarded(task_id: int) -> bool:
    with _active_lock:
        return task_id in _active


def active_stage(task_id: int) -> Stage | None:
    with _active_lock:
        return _active.get(task_id)


def forget_stage(task_id: int):
    with _active_lock:
        _active.pop(task_id, None)
