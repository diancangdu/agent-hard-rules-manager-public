# Changelog

## v1.0.0 — 2026-09-25

首个公开版本。机器相关路径已全部移除，规则文件在运行时解析自己的位置。

### 规则本

- `rules/rules.json` 共 **14 条**硬规则，其中 **7 条**带 `hook` 块参与机械拦截：
  `RULE_001` 敏感信息 / `RULE_003` 危险命令 / `RULE_004` 改配置先备份 / `RULE_005` 禁止 C 盘安装
  / `RULE_014` 不弹控制台黑窗 / `RULE_016` 部署先确认环境与回滚 / `RULE_019` Projectless 防漂移。
- 其余 7 条是**语义判断或流程纪律**，无法在单次工具调用层面机械判定，留在 notebook 层由 agent 主动查询后遵守。
- `layer` 字段区分两层：`notebook`（自觉遵守）与 `hook`（机器强制）。两层是**并集**，不是替代。

### 三个消费者，一份规则

同一份 `rules.json` 被三处读取，**不重复维护**：

| 消费者 | 用途 |
|---|---|
| `tools/hard_rules_mcp_server.py` | MCP server，让 agent 主动查规则 |
| `hooks/scripts/pretooluse_guard.py` | 通用 Python 硬闸（Claude Code / Codex 系） |
| `plugin/rule-gate/` | **DSH 原生硬闸插件**（本版新增） |

### 新增：DSH 原生硬闸插件 `plugin/rule-gate/`

通用 hook 桥接在 DSH 上**挂载了但从不触发** —— 判据：一个同时注册在 `SessionStart` 与 `PreToolUse`
的探针脚本，其日志文件**一次都没被创建**，而同一次重启里原生插件的 `gate-ready` 按时落盘。
因此把拦截移进了原生插件。

- 规则文件位置：`HARD_RULES_FILE` 环境变量，或仓库内相对位置（`plugin/rule-gate/` 的上两级）
- 日志：默认写系统临时目录，可用 `HARD_RULES_GATE_LOG` / `HARD_RULES_GATE_DEBUG_LOG` 覆盖
- **失效安全**：规则文件缺失 / JSON 坏 / 正则非法 → 一律放行并记录，绝不因自身故障阻断会话

### 修掉的两个静默失效

- **`check_situation` 对元查询必然返空**：问「我有哪些死规则」返回 `matched_rules: []`，
  与「本任务不受任何规则约束」在返回体上无法区分。现在命中元查询返回**全量**，并附
  `mode` / `total_rules_in_notebook` / `note` —— **空结果自此自描述**。
- **`RULE_004` 承诺的豁免没实现**：`reason` 写着「新建的配置文件不在此限」，但判定里没有
  「目标已存在」这个条件 ⇒ 全新配置文件也被拦。新增 `path_must_exist`，并遵守顺序硬约束
  （必须在 `path_exists` 之前判定，否则新建文件会因找不到 `.bak` 被拦 —— 而新建恰恰无覆盖风险）。

### 判定字段的语义（写规则时用）

`tools` / `fields` / `any_of` / `all_of` / `path_any_of` / `path_not_any_of` /
`path_must_exist` / `path_exists` / `action` / `reason`。

⚠️ **`all_of` 不是独立的 OR 分支**：它只在 `any_of` 命中后才校验。曾经把它当独立条件，
导致 `all_of: [^(?!...Hidden).*$]` 这种排除条件自己就成立，**把每条命令都判成命中**。

### 测试

- `test_rules.py` / `test_fuzzy.py`（场景匹配；后者必须在技能根目录运行）
- 全量回归 **30 个正/反例**：正例必拦、反例必放
- 修掉的三处脚手架缺陷：`subprocess.run` 未传 `cwd`（8 个用例全假报）、
  GBK 控制台把「有失败项」渲染成「脚本崩了」、一个过期期望（`RULE_017` 的触发词含「目录」）

### 已知边界

- `RULE_017` 的触发词「目录」过宽，几乎任何提到目录的文本都会命中它 —— 这是**规则数据**问题，不是代码问题
- `hooks/scripts/pretooluse_guard.py` 不识别 `path_*` 系字段，因此对 `RULE_004/014/016/019`
  的判定与原生插件**不一致**；改规则后以原生插件的回归测试为准
