from datetime import datetime
from pathlib import Path
from typing import Any, Optional, Union

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_recognition import CustomRecognition
from maa.define import RectType
from PIL import Image

from custom.pipeline_params import parse_pipeline_json_param
from custom.loop_deadline.store import LoopDeadlineStore
from utils import logger

# 相对进程 cwd（与 debug/on_error 同级约定）
_EXPIRED_DUMP_DIR = Path("debug") / "loop_deadline_expired"
# 目录内最多保留的超时截图数；超出则按修改时间删最旧的，避免撑爆磁盘。
_EXPIRED_DUMP_MAX_FILES = 50


def _explicit_scope_from_argv(argv_param: str) -> Optional[str]:
    """
    从 custom_recognition_param 解析 scope。
    未设置（空 JSON、无 scope 键、scope 为空字符串）→ None，表示不命中。
    """
    param = parse_pipeline_json_param(argv_param)
    scope_raw = param.get("scope", None)
    if scope_raw is None:
        return None
    scope = str(scope_raw).strip()
    if not scope:
        return None
    return scope


def _safe_filename_scope(scope: str) -> str:
    return "".join(c if (c.isalnum() or c in "-_.") else "_" for c in scope) or "scope"


def _prune_expired_screenshots(keep_newest: Optional[Path] = None) -> None:
    """保留最新 ``_EXPIRED_DUMP_MAX_FILES`` 张 png，其余按 mtime 删掉。"""
    try:
        files = [p for p in _EXPIRED_DUMP_DIR.glob("*.png") if p.is_file()]
    except OSError as e:
        logger.warning(f"LoopDeadlineExpired: 列举超时截图失败: {e}")
        return
    if len(files) <= _EXPIRED_DUMP_MAX_FILES:
        return
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    for old in files[_EXPIRED_DUMP_MAX_FILES:]:
        if keep_newest is not None and old.resolve() == keep_newest.resolve():
            continue
        try:
            old.unlink(missing_ok=True)
            logger.info(f"LoopDeadlineExpired: 已清理旧超时截图 {old}")
        except OSError as e:
            logger.warning(f"LoopDeadlineExpired: 清理旧超时截图失败 {old}: {e}")


def _save_expired_screenshot(image: Any, scope: str) -> Optional[str]:
    """把到期当帧存到 debug/loop_deadline_expired/；失败只打日志。"""
    if image is None:
        logger.warning("LoopDeadlineExpired: 无图像，跳过截图保存")
        return None
    try:
        _EXPIRED_DUMP_DIR.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y.%m.%d-%H.%M.%S.%f")[:-3]
        path = _EXPIRED_DUMP_DIR / f"{ts}_{_safe_filename_scope(scope)}.png"
        arr = image
        # Maa 传入 BGR；PIL 按 RGB 写
        if getattr(arr, "ndim", 0) == 3 and arr.shape[2] == 3:
            arr = arr[:, :, ::-1]
        Image.fromarray(arr).save(path)
        _prune_expired_screenshots(keep_newest=path)
        logger.info(f"LoopDeadlineExpired: 已保存超时截图 {path}")
        return str(path)
    except Exception as e:
        logger.exception(f"LoopDeadlineExpired: 保存超时截图失败: {e}")
        return None


@AgentServer.custom_recognition("LoopDeadlineExpired")
class LoopDeadlineExpired(CustomRecognition):
    """
    超时分支：显式传入非空 scope，且已为该 scope Arm，且当前已超过截止时间 → 命中；否则不命中。
    custom_recognition_param 为空、或未含非空 scope → 视为参数未设置 → 不命中。
    首次命中到期时，将当前识别帧保存到 debug/loop_deadline_expired/（最多保留 50 张）。
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        try:
            scope = _explicit_scope_from_argv(argv.custom_recognition_param)
            if scope is None:
                return None
            task_id = argv.task_detail.task_id
            if not LoopDeadlineStore.is_armed(task_id, scope):
                return None
            if not LoopDeadlineStore.is_expired(task_id, scope):
                return None
            dump_path = None
            if LoopDeadlineStore.claim_expired_dump(task_id, scope):
                dump_path = _save_expired_screenshot(argv.image, scope)
            detail = {"scope": scope, "expired": True}
            if dump_path:
                detail["dump"] = dump_path
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 1, 1],
                detail=detail,
            )
        except Exception as e:
            logger.exception(f"LoopDeadlineExpired 失败: {e}")
            return None


@AgentServer.custom_recognition("LoopDeadlineActive")
class LoopDeadlineActive(CustomRecognition):
    """
    未超时分支：显式传入非空 scope，且已为该 scope Arm，且尚未超时 → 命中；否则不命中。
    custom_recognition_param 为空、或未含非空 scope → 视为参数未设置 → 不命中。
    """

    def analyze(
        self,
        context: Context,
        argv: CustomRecognition.AnalyzeArg,
    ) -> Union[CustomRecognition.AnalyzeResult, Optional[RectType]]:
        try:
            scope = _explicit_scope_from_argv(argv.custom_recognition_param)
            if scope is None:
                return None
            task_id = argv.task_detail.task_id
            if not LoopDeadlineStore.is_armed(task_id, scope):
                return None
            if LoopDeadlineStore.is_expired(task_id, scope):
                return None
            return CustomRecognition.AnalyzeResult(
                box=[0, 0, 1, 1],
                detail={"scope": scope, "active": True},
            )
        except Exception as e:
            logger.exception(f"LoopDeadlineActive 失败: {e}")
            return None
