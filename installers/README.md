# HardRules 多 agent 安装器

把 HardRules 的**规则库（MCP server）**和**PreToolUse 硬拦截（hooks）**装到各个 agent 上。

统一入口是 `installers/install.py`，`.ps1` 只是转发参数的薄壳。

## 一分钟上手

```bash
# 1) 先看要做什么（默认就是 dry-run，不落盘）
python installers/install.py --agent dsh

# 2) 确认无误再落盘
python installers/install.py --agent dsh --apply
```

## 参数

| 参数 | 说明 |
| --- | --- |
| `--agent` | 必填，`dsh` / `codex` / `claude-code` / `generic` |
| `--home <dir>` | agent 配置根目录，默认用户主目录 |
| `--python <exe>` | Python 解释器绝对路径，默认自动探测 |
| `--project-root <dir>` | HardRules 项目根，默认 `installers/` 的上级目录 |
| `--dry-run` | 只打印，不落盘（**默认行为**） |
| `--apply` | 真正写入 |
| `--allow-profile-write` | 仅 dsh：允许直接写 `cordis.patch.yml`（默认不写） |
| `--absolute-python` | 把 `hooks/hooks.json` 里的 `python` 换成绝对解释器路径 |

解释器探测顺序：`sys.executable` → PATH 里的 `python` / `python.exe`。
需要固定用某个解释器时，用 `--python <exe>`（或 PowerShell 的 `-Python <exe>`）显式指定。

写入行为：**合并而非覆盖**、写入前留 `.bak_<timestamp>`、可重复运行（幂等，不重复插入）。

## 各 agent 怎么装

### DSH

DSH 的 profile patch 是**顶层 YAML 数组**，新增内容用 `- insert:` 包一个行列表。
profile 由主 agent 统一部署，所以本安装器**默认只生成片段并打印**：

```bash
python installers/install.py --agent dsh --home D:/dsh-data
```

把打印出来的片段交给主 agent 合并进
`<home>/.dsh/profiles/desktop/cordis.patch.yml`。
确实要让本安装器自己写（会先备份原文件）时，显式加：

```bash
python installers/install.py --agent dsh --home D:/dsh-data --apply --allow-profile-write
```

生成的片段包含两条：`agent-hard-rules-mcp`（`@deepseek-ai/dsh-mcp-client`）
和 `agent-hard-rules-hooks`（`@deepseek-ai/dsh-hooks-claude-code`，读取 `hooks/hooks.json`）。
`serverName` 固定为 `hard_rules`。

PowerShell：

```powershell
.\install_dsh.ps1                                        # dry-run
.\install_dsh.ps1 -Apply                                 # 只装 MCP/hooks 配置，不动 profile
.\install_dsh.ps1 -Home D:\dsh-data -Apply -AllowProfileWrite
```

### Codex

追加 `[mcp_servers.agent-hard-rules]` 与 `[mcp_servers.agent-hard-rules.env]` 两段 TOML：

```bash
python installers/install.py --agent codex --home C:/Users/me --apply
# -> C:/Users/me/.codex/config.toml
```

`--home` 指到配置目录的**父目录**。如果 `CODEX_HOME` 被指到别处，把 `--home`
指到该目录的父目录即可。

已存在同名小节时**不会覆盖**：内容一致报“已是最新”，不一致则提示手工核对，
避免踩掉你自己调整过的配置。

```powershell
.\install_codex.ps1 -Apply
```

### Claude Code

项目级配置，两个文件都落在 `--project-root` 下：

- `<project_root>/.mcp.json` —— `{"mcpServers": {...}}`
- `<project_root>/.claude/settings.json` —— 合并 PreToolUse hooks 段

```bash
python installers/install.py --agent claude-code --project-root D:/MyProject --apply
```

`--project-root` 请指向**你的工作项目**；默认值是 HardRules 自身。
合并时会保留你原有的 `mcpServers`、`permissions` 以及已有的 hooks 条目。

### generic（任意支持 MCP 的客户端）

产出最标准的 `{"mcpServers": {...}}`，只含 `command / args / env / cwd`，
不带任何客户端私有字段：

```bash
python installers/install.py --agent generic --apply
# -> <home>/.hard-rules/mcp.json
```

把打印出来的 `mcpServers` 段拷进你的客户端配置文件即可（Cursor / Windsurf /
Cline / Continue 等）。

## hooks.json

`hooks/hooks.json` 是 Claude Code hooks 格式，用 `${CLAUDE_PLUGIN_ROOT}` 占位项目根
（DSH 的 hooks-claude-code 桥接在解析配置时会替换它）：

```json
{"hooks":{"PreToolUse":[{"matcher":"bash|pwsh|write|edit|str_replace_editor","hooks":[{"type":"command","command":"python \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pretooluse_guard.py\"","timeout":30}]}]}}
```

安装器会自动确保它存在。若你的环境里 PATH 上的 `python` 不可靠，用
`--absolute-python`（可配合 `--apply`）把解释器换成探测到的绝对路径，
`${CLAUDE_PLUGIN_ROOT}` 占位符保持不变。

## 回滚

每次覆盖已有文件前都会在同目录留一份 `<文件名>.bak_<YYYYMMDD_HHMMSS>`，
改坏了直接改回原名即可。
