"""Build invocation-only PI task options for the native configurator."""

from copy import deepcopy
import json
from pathlib import Path
import re


def parse_task_options(text: str) -> dict:
    value = json.loads(text)
    if not isinstance(value, dict):
        raise ValueError("任务选项 JSON 必须为对象")
    return value


def load_task_interface(path: Path) -> dict:
    interface = json.loads(path.read_text())
    for imported in interface.get("import", []):
        fragment = json.loads((path.parent / imported).read_text())
        interface.setdefault("task", []).extend(fragment.get("task", []))
        for name, option in fragment.get("option", {}).items():
            interface.setdefault("option", {}).setdefault(name, option)
    return interface


def _option_value(name, definition, value):
    kind = definition.get("type", "select")
    result = {"name": name}
    if kind == "input":
        fields = {field["name"]: field for field in definition.get("inputs", [])}
        if not isinstance(value, dict) or value.keys() - fields.keys():
            raise ValueError(f"选项 {name} 需要包含已定义输入字段的对象")
        inputs = {}
        for key, field in fields.items():
            raw = value.get(key, field.get("default", ""))
            expected = field.get("pipeline_type", "string")
            if expected == "int" and (isinstance(raw, bool) or not re.fullmatch(r"-?\d+", str(raw))):
                raise ValueError(f"选项 {name}/{key} 需要整数")
            if expected == "bool":
                raw = str(raw).lower()
                if raw not in {"true", "false"}:
                    raise ValueError(f"选项 {name}/{key} 需要布尔值")
            if isinstance(raw, (dict, list)) or raw is None:
                raise ValueError(f"选项 {name}/{key} 需要标量")
            text = str(raw)
            if field.get("verify") and not re.fullmatch(field["verify"], text):
                raise ValueError(f"选项 {name}/{key} 未通过格式校验")
            inputs[key] = text
        result["inputs"] = inputs
        return result
    cases = {case["name"] for case in definition.get("cases", [])}
    if kind == "switch" and isinstance(value, bool):
        value = "Yes" if value else "No"
    if kind == "checkbox":
        if not isinstance(value, list) or any(not isinstance(item, str) or item not in cases for item in value):
            raise ValueError(f"选项 {name} 需要有效选项名数组")
        result["values"] = list(dict.fromkeys(value))
    else:
        if not isinstance(value, str) or value not in cases:
            raise ValueError(f"选项 {name} 的值无效，可选值为 {sorted(cases)}")
        result["value"] = value
    return result


def build_task_config(interface: dict, config: dict, names: list[str], overrides: dict) -> list[dict]:
    if not isinstance(overrides, dict) or overrides.keys() - set(names):
        raise ValueError("--task-options 必须为对象，且只能指定本次 --task 中的任务")
    available = {task["name"]: task for task in interface.get("task", [])}
    definitions = interface.get("option", {})
    configured = {task["name"]: task for task in reversed(config.get("task", []))}
    result = []
    for name in names:
        if name not in available:
            raise ValueError(f"未知任务 {name}")
        patch = overrides.get(name, {})
        if not isinstance(patch, dict):
            raise ValueError(f"任务 {name} 的选项需要对象")
        saved = {item["name"]: item for item in configured.get(name, {}).get("option", [])}
        options = []
        visited = set()

        def collect(option_name):
            if option_name in visited:
                return
            visited.add(option_name)
            definition = definitions[option_name]
            kind = definition.get("type", "select")
            fallback = {} if kind == "input" else definition.get("default_case", [] if kind == "checkbox" else "")
            previous = saved.get(option_name, {})
            field = "inputs" if kind == "input" else ("values" if kind == "checkbox" else "value")
            value = previous.get(field, fallback)
            if kind == "input" and isinstance(value, dict):
                # 保存配置可能来自旧接口。与原生 Configurator 一样只读取
                # 当前输入定义；本次显式传入的未知字段仍交给校验拒绝。
                active_fields = {item["name"] for item in definition.get("inputs", [])}
                value = {key: item for key, item in value.items() if key in active_fields}
            if option_name in patch:
                provided = patch[option_name]
                if kind == "input" and isinstance(provided, dict):
                    value = {**(value if isinstance(value, dict) else {}), **provided}
                else:
                    value = provided
                for scope, selected in (("controller", config.get("controller", {}).get("name")), ("resource", config.get("resource"))):
                    if definition.get(scope) and selected not in definition[scope]:
                        raise ValueError(f"选项 {option_name} 不适用于当前 {scope}")
            # Historical tasks can omit optional selections. Preserve that behavior.
            if option_name not in patch and not value and kind not in {"input", "checkbox"}:
                return
            option = _option_value(option_name, definition, value)
            options.append(option)
            chosen = option.get("values", [option.get("value")])
            for case in definition.get("cases", []):
                if case["name"] in chosen:
                    for child in case.get("option", []):
                        collect(child)

        for root in available[name].get("option", []):
            collect(root)
        if patch.keys() - visited:
            raise ValueError(f"任务 {name} 存在未知或未启用的选项 {sorted(patch.keys() - visited)}")
        result.append({"name": name, "option": deepcopy(options)})
    return result
