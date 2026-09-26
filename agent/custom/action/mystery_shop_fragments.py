import json
import re
from pathlib import Path

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context

from utils import logger
from utils.runtime_paths import get_runtime_paths

CONFIG_NODE = "勾玉购买忍者碎片配置"
# 游戏里只有第 8 个商品位会刷勾玉碎片（0-based：商品7）。
FRAGMENT_SLOT = 7
FRAGMENT_NODE = f"神秘商店商品{FRAGMENT_SLOT}是配置碎片"
_ROSTER_FILE = "fragment-roster.json"


def _roster_candidates() -> list[Path]:
    paths = get_runtime_paths()
    return [
        paths.resource_dir / "data" / _ROSTER_FILE,
        paths.project_root / "assets" / "resource" / "data" / _ROSTER_FILE,
    ]


def load_fragment_roster() -> list[str]:
    """Load the single shipped roster used by agent and GUI checkbox sync."""
    last_error: Exception | None = None
    for path in _roster_candidates():
        if not path.is_file():
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as e:
            last_error = e
            continue
        names = data if isinstance(data, list) else data.get("names")
        if not isinstance(names, list) or not names:
            last_error = ValueError(f"{path}: names must be a non-empty list")
            continue
        return [str(name) for name in names]
    raise FileNotFoundError(
        f"fragment roster not found in {[str(p) for p in _roster_candidates()]}"
        + (f"; last error: {last_error}" if last_error else "")
    )


# 商店卡面是「流派·忍者碎片」。空格会先被节点 replace 去掉。
FRAGMENT_ROSTER = load_fragment_roster()


def fragment_pattern(name: str) -> str:
    return re.escape(name) + r".*碎片"


@AgentServer.custom_action("ApplyMysteryShopFragmentConfig")
class ApplyMysteryShopFragmentConfig(CustomAction):
    """
    读取勾玉购买忍者碎片配置的 attach，把勾选的全名写入第 8 商品位的碎片识别。

    attach 的 key 是流派·忍者全名，值为 true 才购买。
    多个勾选靠配置合并进同一个 attach，和藏宝图一样。
    没有勾选时该商品位保持关闭，商店继续只买忍币商品。
    """

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> CustomAction.RunResult:
        del argv
        config_node = context.get_node_data(CONFIG_NODE)
        attach = config_node.get("attach", {}) if config_node else {}
        roster = set(FRAGMENT_ROSTER)
        selected = [name for name in FRAGMENT_ROSTER if attach.get(name)]
        for key, value in attach.items():
            if value and key not in roster:
                logger.warning(f"无法识别的勾玉碎片 {key!r}，已跳过")

        if not selected:
            logger.info("未勾选勾玉忍者碎片")
            return CustomAction.RunResult(success=True)

        expected = [fragment_pattern(name) for name in selected]
        override = {
            FRAGMENT_NODE: {
                "enabled": True,
                "recognition": {"param": {"expected": expected}},
            }
        }
        if not context.override_pipeline(override):
            logger.error("勾玉碎片 override_pipeline 失败")
            return CustomAction.RunResult(success=False)

        logger.info(f"勾玉碎片: {selected}")
        return CustomAction.RunResult(success=True)
