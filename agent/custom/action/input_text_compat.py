"""通过 ADBKeyboard 兼容输入 Android 原生 adb input 不支持的 Unicode 文本。"""

from __future__ import annotations

import base64
import json
import shutil
import subprocess
import time
from typing import Any

from maa.agent.agent_server import AgentServer
from maa.context import Context
from maa.custom_action import CustomAction

from utils import logger


_ADB_KEYBOARD_IME = "com.android.adbkeyboard/.AdbIME"
_DEFAULT_IME = "com.android.inputmethod.latin/.LatinIME"
_INPUT_FIELD = (662, 358)
_MAX_INPUT_LENGTH = 128


def _adb_target() -> tuple[str, str]:
    adb = shutil.which("adb") or "/usr/bin/adb"
    result = subprocess.run(
        [adb, "devices"],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=10,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(f"无法执行 adb devices: {result.stderr.strip()}")

    devices = []
    for line in result.stdout.splitlines()[1:]:
        fields = line.split()
        if len(fields) >= 2 and fields[1] == "device":
            devices.append(fields[0])
    if len(devices) != 1:
        raise RuntimeError(f"需要恰好一个 ADB 设备，当前发现: {devices!r}")
    return adb, devices[0]


def _shell(adb: str, serial: str, *args: str) -> str:
    result = subprocess.run(
        [adb, "-s", serial, "shell", *args],
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=20,
        check=False,
    )
    output = (result.stdout + result.stderr).strip()
    if result.returncode != 0:
        raise RuntimeError(f"ADB shell failed: {' '.join(args)}; output={output!r}")
    return output


def _input_text(argv: CustomAction.RunArg) -> str:
    raw = argv.custom_action_param

    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError:
            pass

    if isinstance(raw, dict):
        value = raw.get("input_text", "")
    else:
        value = raw

    if not isinstance(value, str):
        raise TypeError("input_text 必须为字符串")
    return value


def _clear_focused_input(adb: str, serial: str) -> None:
    """清空当前已获得焦点的 Android 编辑框。"""
    keycodes = ["123", *(["67"] * _MAX_INPUT_LENGTH)]
    _shell(adb, serial, "input", "keyevent", *keycodes)


@AgentServer.custom_action("InputTextCompat")
class InputTextCompat(CustomAction):
    """兼容 Unicode 的文本输入动作。

    ASCII 文本继续使用 MaaFramework 原生 InputText；包含非 ASCII 字符时，
    临时切换到 ADBKeyboard，通过 ADB_INPUT_B64 广播提交 UTF-8 文本，随后
    恢复执行动作前的输入法。使用前需在 Waydroid/Android 中安装并启用
    ADBKeyboard（包名 com.android.adbkeyboard）。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        try:
            text = _input_text(argv)
            if not text:
                logger.error("InputTextCompat: input_text 为空")
                return CustomAction.RunResult(success=False)

            adb, serial = _adb_target()
            # 输入框可能保留上次兑换码或调试时留下的引号；输入前始终覆盖旧内容。
            _clear_focused_input(adb, serial)

            if text.isascii():
                _shell(adb, serial, "input", "text", text.replace(" ", "%s"))
                return CustomAction.RunResult(success=True)

            ime_list = _shell(adb, serial, "ime", "list", "-s")
            if _ADB_KEYBOARD_IME not in ime_list.splitlines():
                logger.error(
                    "InputTextCompat: 未安装 ADBKeyboard，"
                    "请安装 com.android.adbkeyboard 后重试"
                )
                return CustomAction.RunResult(success=False)

            previous_ime = _shell(
                adb, serial, "settings", "get", "secure", "default_input_method"
            ).splitlines()
            previous_ime = previous_ime[0].strip() if previous_ime else _DEFAULT_IME
            if "/" not in previous_ime:
                previous_ime = _DEFAULT_IME

            input_succeeded = False
            restore_succeeded = True
            try:
                if previous_ime != _ADB_KEYBOARD_IME:
                    _shell(adb, serial, "ime", "enable", _ADB_KEYBOARD_IME)
                    _shell(adb, serial, "ime", "set", _ADB_KEYBOARD_IME)
                    time.sleep(0.1)

                encoded = base64.b64encode(text.encode("utf-8")).decode("ascii")
                output = _shell(
                    adb,
                    serial,
                    "am",
                    "broadcast",
                    "-a",
                    "ADB_INPUT_B64",
                    "--es",
                    "msg",
                    encoded,
                )
                input_succeeded = "Broadcast completed" in output
                if not input_succeeded:
                    logger.error(
                        "InputTextCompat: ADBKeyboard 广播未完成，"
                        f"output={output!r}"
                    )
            finally:
                if previous_ime != _ADB_KEYBOARD_IME:
                    try:
                        _shell(adb, serial, "ime", "set", previous_ime)
                        time.sleep(0.1)
                    except Exception as exc:
                        restore_succeeded = False
                        logger.error(f"InputTextCompat: 恢复输入法失败: {exc}")

            # Waydroid 的 Unity 输入框会进入 Android 全屏编辑器；发送 Enter
            # 相当于点击编辑器右上角的 OK，否则后续 Maa OCR 仍只能看到键盘。
            if input_succeeded and restore_succeeded:
                _shell(adb, serial, "input", "keyevent", "66")

            return CustomAction.RunResult(
                success=input_succeeded and restore_succeeded
            )
        except Exception as exc:
            logger.exception(f"InputTextCompat 失败: {exc}")
            return CustomAction.RunResult(success=False)


@AgentServer.custom_action("ClearInputTextCompat")
class ClearInputTextCompat(CustomAction):
    """点击兑换码输入框并清空已有内容，保留编辑器焦点供后续输入。"""

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        try:
            adb, serial = _adb_target()
            _shell(adb, serial, "input", "tap", str(_INPUT_FIELD[0]), str(_INPUT_FIELD[1]))
            time.sleep(0.25)
            _clear_focused_input(adb, serial)
            return CustomAction.RunResult(success=True)
        except Exception as exc:
            logger.exception(f"ClearInputTextCompat 失败: {exc}")
            return CustomAction.RunResult(success=False)
