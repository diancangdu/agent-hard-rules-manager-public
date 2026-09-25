# Hard Rules Manager（死规则管理器）

一个**与 agent 无关的“死规则记录本”**——如果宿主 agent 支持 hooks，还会在工具调用前多装一道**机器强制的闸门**。

本项目原名 `codex-hard-rules-manager`，现改造为通用版本：规则存在同一个 JSON 文件里，同一套 MCP server 服务所有支持 MCP 的 agent，闸门是纯 Python 脚本 + 文件式 hook 配置。

**死规则** = 一旦触发就必须无条件执行的规则，没有“这次应该没事”。

> English docs: [README.md](README.md)

---

## 1. 项目构成

```
HardRules/
├── rules/rules.json                  # 22 条规则（UTF-8 JSON，唯一事实来源）
├── utils/rule_parser.py              # 加载 / 保存 / 查询 / 新增 / 更新 / 删除 / 匹配
├── query_rules.py                    # CLI：--check --keyword --all --category --rule-id --json
├── add_rule.py                       # CLI：新增规则（不带参数进交互模式）
├── tools/hard_rules_mcp_server.py    # MCP server（标准 stdio 协议）
├── tools/migrate_layers.py           # 一次性迁移脚本（为每条规则补 layer / hook 块）
├── hooks/hooks.json                  # Claude Code 格式：PreToolUse + matcher
├── hooks/scripts/pretooluse_guard.py # 硬闸拦截器本体（自检 11/11 通过）
├── adapters/                         # 各 agent 配置生成：dsh / codex / claude_code / generic_mcp
├── installers/install.py             # 统一安装器（默认 dry-run）
└── docs/
    ├── 分层判断表.md                  # 哪条规则该进哪一层，以及为什么
    └── agent-compat.md               # 各 agent 支持矩阵
```

当前规则清单：**22 条**，其中 **19 条只进 notebook，3 条同时上 hook**（`RULE_001` / `RULE_003` / `RULE_005`）。已用到的分类：安全 / 行为 / 技术 / 协作 / 三模型协同。

---

## 2. 为什么分两层

这是整个项目最重要的一条认知。一条规则可以只活在下面两层中的一层，也可以同时活在两层：

| 层 | 强制力来源 | 失效时的表现 |
| --- | --- | --- |
| `notebook`（规则本） | agent 主动查询规则库 + 自觉遵守 | **静默**——漏了没有任何提示，没人会知道 |
| `hook`（硬闸） | 代码在工具调用**之前**拦截（`exit 2`） | **显式**——模型会看到被 blocked 的理由 |

每条规则都有一个 `layer` 数组：

- `["notebook"]`：只进规则本，靠 agent 主动查询。
- `["notebook", "hook"]`：**同时**有机器强制的闸门。命中其正则的工具调用会在执行前被拦下。

两层覆盖的是同一件事吗？不是。它们的**失效方式不同**，这正是分层的意义：规则本能兜住一切（前提是 agent 去看），硬闸只兜住一小撮**可被机器精确识别**的情况（无论 agent 看没看）。

**怎么判一条规则该进哪层：**问「漏掉它的后果是什么」。

- 漏了会**出事**（不可逆的数据丢失、凭据泄露、系统盘被污染）→ 候选 `hook`。
- 漏了只是**不够好**（代码不漂亮、没遵守某个约定）→ 只进 `notebook`。

22 条里只有 3 条跨过了这条线。逐条的判断理由见 [docs/分层判断表.md](docs/分层判断表.md)。

### 闸门是数据，不是代码

上 hook 的规则，判定逻辑写在 `rules.json` 里的 `hook` 块中：

```json
{
  "rule_id": "RULE_001",
  "title": "敏感信息保护",
  "layer": ["notebook", "hook"],
  "hook": {
    "tools": ["write", "edit", "str_replace_editor"],
    "fields": ["content", "new_string", "new_str", "file_text"],
    "any_of": ["(?i)\\b(api[_-]?key|apikey|secret[_-]?key)\\b\\s*[:=]\\s*[\"'][A-Za-z0-9_\\-./+=]{16,}[\"']"],
    "action": "deny",
    "reason": "命中死规则 RULE_001（敏感信息保护）：疑似把密钥 / 凭据硬编码进文件。"
  }
}
```

`pretooluse_guard.py` 运行时读取这个结构。**改规则不用改脚本**。

| 字段 | 含义 |
| --- | --- |
| `tools` | 本条闸门生效的工具名（即 PreToolUse matcher 的匹配对象） |
| `fields` | 要扫描的 `tool_input` 子键 |
| `any_of` | 任一正则命中即拦截 |
| `all_of` | 全部正则命中才拦截 |
| `action` | `deny`（当前闸门只实现了这一种） |
| `reason` | 被拦截时回给模型的理由文本 |

---

## 3. hook 协议

已对 `dsh-hook-protocol/src/codec.ts` 核实：

- `exit 2` → 工具调用被**阻止**，**stderr 就是模型看到的理由**。
- `exit 0` → 放行；**其他任何退出码都是“非阻塞错误”，即放行**。
- 结构化 stdout **只在 exit 0 时**才被解析。
- ⚠️ **顶层 `{"decision":"deny"}` 会被静默忽略**（那里只认 `approve` / `block`）；`deny` 只能写在 `hookSpecificOutput.permissionDecision`。本项目用 `exit 2 + stderr` 正是为了避开这个坑。
- 拦截器是 **fail-open**：规则文件读不到 / 解析失败 → 只打警告并放行，绝不让 agent 卡死。

拦截器自带自检：

```bash
python hooks/scripts/pretooluse_guard.py --selftest   # -> selftest: 11/11 passed
```

---

## 4. 安装

统一入口（**默认 dry-run，不落盘**，确认无误再加 `--apply`）：

```bash
python installers/install.py --agent dsh|codex|claude-code|generic \
                             [--home <dir>] [--python <exe>] \
                             [--dry-run | --apply]
```

| agent | 写入什么 | 落点 |
| --- | --- | --- |
| `dsh` | MCP client + hooks 桥接配置（YAML 片段） | `<home>/.dsh/profiles/desktop/cordis.patch.yml` |
| `codex` | `[mcp_servers.agent-hard-rules]`（含 `.env`）TOML | `<home>/.codex/config.toml` |
| `claude-code` | `.mcp.json` + 合并 PreToolUse hooks | `<project_root>/.mcp.json`、`<project_root>/.claude/settings.json` |
| `generic` | 最标准的 `{"mcpServers": {...}}` | `<home>/.hard-rules/mcp.json` |

行为承诺：默认 dry-run；**合并而非覆盖**；覆盖已有文件前一律先留 `<文件名>.bak_<YYYYMMDD_HHMMSS>`；可重复运行（幂等）。

**DSH 特殊**：其 profile 由主 agent 统一部署，所以即使加了 `--apply`，本安装器也只**打印片段**。要让安装器自己写 `cordis.patch.yml`，必须再加显式开关 `--allow-profile-write`（且写前备份）。

```bash
# 1) 先看要做什么
python installers/install.py --agent dsh --home D:/dsh-data
# 2) 把打印出来的片段交给主 agent 合并；确需安装器自己写时：
python installers/install.py --agent dsh --home D:/dsh-data \
    --apply --allow-profile-write
```

各 agent 的细节与回滚方法见 [installers/README.md](installers/README.md)。

---

## 5. 查询规则

```bash
python query_rules.py --all                              # 全部规则
python query_rules.py --check "把 API key 写进 config.py"  # 场景匹配（核心用法）
python query_rules.py --keyword "密码,删除,重构"           # 关键词搜索（命中任一）
python query_rules.py --category 安全
python query_rules.py --rule-id RULE_001
python query_rules.py --json --keyword 密钥               # 便于程序解析
```

匹配策略是**宁多勿漏**（漏掉死规则的代价更高）。这么做的副作用见第 8 节。

通过 MCP 暴露的等价能力：

- 资源 `rules://notebook` —— 完整规则库 JSON
- 工具 `list_all_rules` / `get_rule` / `list_categories` / `query_rules` /
  `check_situation` / `add_rule` / `delete_rule`

---

## 6. 新增规则

```bash
python add_rule.py --title "禁止提交密钥" --category 安全 \
  --trigger "密钥,API key,硬编码" \
  --actions "使用环境变量管理密钥" \
  --forbidden "把密钥硬编码进源码" \
  --severity high --by user

python add_rule.py          # 不带参数 -> 交互模式
```

一条规则的完整形态：

```json
{
  "rule_id": "RULE_023",
  "title": "规则标题",
  "category": "安全",
  "severity": "high",
  "trigger_keywords": ["触发词1", "触发词2"],
  "must_execute_actions": ["必须执行的动作1"],
  "forbidden_actions": ["禁止的操作1"],
  "description": "详细说明",
  "created_by": "user",
  "created_at": "2026-09-25T08:30:03+08:00",
  "layer": ["notebook"]
}
```

`layer` 和 `hook` **不能**通过 `add_rule.py` 或 MCP 的 `add_rule` 工具写入。这样加出来的规则没有 `layer` 字段，闸门会忽略它——即事实上只进 notebook。要把一条规则提升为 hook，需要**有意地手工编辑** `rules.json`（判断方法见 [docs/分层判断表.md](docs/分层判断表.md)）。

---

## 7. 各 agent 支持情况

| 能力 | Codex | DSH | Claude Code | 通用 MCP 客户端 |
| --- | --- | --- | --- | --- |
| MCP server | 支持 | 支持 | 支持 | 支持 |
| PreToolUse hooks | 部分（本项目暂时只装 MCP） | 部分（靠桥接插件） | 支持（原生） | 不支持 |
| 指令文件 | `AGENTS.md` | `AGENTS.md` | `CLAUDE.md` | 无统一约定 |
| skill 自动扫描 | 支持 | 支持（按 rank 扫多个根） | 支持 | 无 |

具体落点、文件名与「未验证」项见 [docs/agent-compat.md](docs/agent-compat.md)。

实际结论：**MCP 到处能用，硬闸不能。** 在不支持 hooks 的 agent 上，你只拿到了 notebook 层——而它是**静默失效**的。不要因为一条规则写在 `rules.json` 里，就默认它一定被强制执行。

---

## 8. 已知边界

如实列出，因为在这个项目里夸大能力恰恰是它要防的那种失败。

1. **notebook 层会静默失效。** 如果 agent 从不查询规则库，一条没被执行的规则不会产生任何警告、日志或提示。你和漏掉规则之间唯一的保障是 agent「动手前先查询」的习惯（见 `SKILL.md`）。
2. **硬闸只做 deny，不做 allow。** `pretooluse_guard.py` 会跳过任何 `action` 不是 `deny` 的 hook。它没有「预先批准某类模式」的能力，因此不能用来减少确认提示。
3. **60% bigram 阈值偏松，会误报。** `_text_contains` 在精确子串之外还会用字符二元组重叠度 ≥ 0.6 兜底，能容忍中文插字与英文变形，但也会匹配到你并不想匹配的文本。请把 `--check` 的命中理解为「去读一下这条规则」，而不是「这条规则已被违反」。
4. **长度小于 2 的触发词不做模糊匹配**（只走精确子串），这是为避免大面积误伤而刻意保留的限制。
5. **硬闸只看工具调用入参。** 它无法判断跨轮次的状态、文件系统现状、或用户说过什么。这类形态的规则只能留在 notebook。
6. **通过 CLI / MCP 新增的规则只进 notebook**（不写 `layer`），在手工编辑 `rules.json` 之前，闸门不会强制它。
7. **hook 规则匹配的是文本模式，不是意图。** 危险命令换一种足够刁钻的写法就能绕过。硬闸是兜底，不是沙箱。

---

## 9. 维护

- 规则在 `rules/rules.json`（UTF-8，必须保持 JSON 合法），支持直接手工编辑。
- 删除该文件后首次运行会自动重建空库。
- 建议把 `rules/rules.json` 纳入 git——规则历史就是审计轨迹。
- `rules/` 与 `tools/` 下的 `.bak_*` 文件是历史迁移残留，不参与运行时。
