# 开发记录规则：家目录工作区也能读到

## 现象

仓库里早已有 `.cursor/rules/development-records.mdc`（`alwaysApply: true`），要求提交前写 `.mr3a-records` 且与代码同一次 commit。但 Cursor 工作区经常是 `/home/linn`，子目录 `MR3A/.cursor/rules/` **不会**作为项目规则注入，Agent 等于没读到，于是又只交代码漏归档。

## 改动

- 家目录：`~/.cursor/rules/mr3a-development-records.mdc`（`alwaysApply: true`），明确改 `MR3A` 时必须写记录。
- 仓库根：`AGENTS.md` 再写一遍同一强制约定（部分 Agent 默认读此文件）。
- 原 `MR3A/.cursor/rules/development-records.mdc` 注明工作区陷阱，并指向上述备份。

## 验证

- 打开工作区 `/home/linn` 时，规则列表应能看到 `mr3a-development-records`。
- 之后凡 MR3A 行为改动的 commit，归档与代码必须同批。
