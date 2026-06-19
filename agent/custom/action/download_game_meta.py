"""从金山文档 GameData 表格下载 game-meta 到本地 resource/data/"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict

import requests
from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils.logger import logger

# ==== 金山文档配置 ====
_FILE_ID = "crcMio8nY0BC"
_READ_SCRIPT_ID = "V2-w26sb7C0aQrCANrd6qZ2t"
_AIRSCRIPT_TOKEN = "1NKkJQNwt4yNsLNVTTmnVH"
_SHEET_NAME = "GameMeta"
# ======================

_PROJECT_ROOT = Path(__file__).resolve().parents[3]  # agent/custom/acetion → 项目根
_DATA_DIR = _PROJECT_ROOT / "assets" / "resource" / "data"
_FILE_NAME = "game-meta.json"
_LOCAL_PATH = str(_DATA_DIR / _FILE_NAME)

# 首次运行无本地缓存时的兜底数据
_FALLBACK_DATA: Dict[str, str] = {
    "版本名称": "未知版本",
    "累充活动": "未知活动",
    "每周兑换码": "",
}


def _fetch_from_kdocs() -> Dict[str, Any] | None:
    url = (
        f"https://www.kdocs.cn/api/v3/ide/file/"
        f"{_FILE_ID}/script/{_READ_SCRIPT_ID}/sync_task"
    )
    headers = {
        "Content-Type": "application/json",
        "AirScript-Token": _AIRSCRIPT_TOKEN,
    }
    payload = {"Context": {"argv": {"sheetName": _SHEET_NAME}}}

    resp = requests.post(url, headers=headers, data=json.dumps(payload), timeout=10)

    if resp.status_code != 200:
        logger.warning(f"DownloadGameMeta: HTTP {resp.status_code}")
        return None

    try:
        body = resp.json()
    except json.JSONDecodeError:
        logger.warning("DownloadGameMeta: 响应非 JSON")
        return None

    # 金山 sync_task 响应结构: {"code":0, "data":{"result": ...}}
    raw = body
    if isinstance(raw, dict):
        if "data" in raw and isinstance(raw["data"], dict):
            inner = raw["data"].get("result")
            if inner is not None:
                raw = inner

    # 如果结果是 JSON 字符串，再解一层
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            pass

    if isinstance(raw, dict):
        # 过滤掉非字符串值，保留纯键值对
        result = {str(k): v for k, v in raw.items() if v is not None}
        if result:
            return result

    logger.warning("DownloadGameMeta: 解析后非有效 dict")
    return None


def _save_local(data: Dict[str, Any]) -> bool:
    os.makedirs(_DATA_DIR, exist_ok=True)
    tmp_fd, tmp_path = tempfile.mkstemp(
        suffix=".json", prefix="game-meta", dir=_DATA_DIR
    )
    try:
        with os.fdopen(tmp_fd, "w", encoding="utf-8") as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, _LOCAL_PATH)
        return True
    except OSError:
        try:
            os.remove(tmp_path)
        except OSError:
            pass
        return False


def _load_local() -> Dict[str, Any] | None:
    try:
        with open(_LOCAL_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
            if isinstance(data, dict):
                return data
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        pass
    return None


@AgentServer.custom_action("DownloadGameMeta")
class DownloadGameMeta(CustomAction):
    """从金山文档 GameData 表格拉取键值对，存入本地 resource/data/game-meta.json。

    失败时保留已有本地文件。首次运行且无网络时写入兜底数据。
    """

    def run(
        self, context: Context, argv: CustomAction.RunArg
    ) -> CustomAction.RunResult:
        remote = _fetch_from_kdocs()

        if remote is not None:
            if _save_local(remote):
                logger.info(
                    f"DownloadGameMeta: 已更新本地 {_LOCAL_PATH} " f"({len(remote)} 条)"
                )
                return CustomAction.RunResult(success=True)
            logger.error("DownloadGameMeta: 写入本地文件失败")
            # 落盘失败但请求成功，success=True 不阻塞
            return CustomAction.RunResult(success=True)

        # 网络/解析失败，检查本地缓存
        local = _load_local()
        if local is not None:
            logger.warning("DownloadGameMeta: 远端获取失败，沿用本地缓存")
            return CustomAction.RunResult(success=True)

        # 首次运行，无缓存，写入兜底数据
        logger.warning("DownloadGameMeta: 无本地缓存，写入兜底数据")
        _save_local(_FALLBACK_DATA)
        return CustomAction.RunResult(success=True)
