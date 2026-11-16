# 镜界百器节点持久化禁用被遗留字段 enable 顶掉

## 现象

`清理镜界百器体力` 已写入 `agent_task_state.json`（`enabled: false` 至次日 05:00），重启/再进队仍反复进入清体力。

## 原因

任务选项里用的是遗留字段 `enable`（如 `{"清理镜界百器体力":{"enable":true}}`）。Agent 持久化只合并 `enabled:false`，提交后变成：

```json
"清理镜界百器体力": {"enable": true, "enabled": false}
```

框架仍按 `enable:true` 命中该节点。

## 改动

- 合并 / 持久化节点覆盖时同时写 `enabled` 与 `enable`。
- 规范化 PiCli `pipeline_override` 时把二者收成一致。
- `DisableNode` / `EnableNode` 同样双写。

## 验证

- `pytest agent/tests/test_persistent_node_enable.py`
- 实机：清体力登记后同日再进镜界百器，主页应跳过 `清理镜界百器体力`。
