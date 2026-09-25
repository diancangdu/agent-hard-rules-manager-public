# 安装教程

两条路：**自动化脚本**（推荐）或**手动**。

这个项目有三个可独立使用的部件：

| 部件 | 作用 | 载体 |
|---|---|---|
| **规则本** | `rules/rules.json` —— 规则实体 | 一个 JSON 文件 |
| **MCP server** | 让 agent 主动查询规则（`check_situation`） | `tools/hard_rules_mcp_server.py` |
| **硬闸** | 命中规则时**拒绝工具调用** | `hooks/`（Python，通用）或 `plugin/rule-gate/`（DSH 原生） |

只想要「规则清单」→ 只用第一个。想要「机器强制执行」→ 三个都要。

---

## 前置条件

- Python 3.8+（安装器会自己探测；也可用 `--python` 指定）
- 任一宿主：DSH / Codex / Claude Code / 任意支持 MCP 的 agent

---

## 一、自动化安装

统一入口是 `installers/install.py`；`.ps1` 只是转发参数的薄壳。

```bash
# 1) 先干跑，看它会改什么（默认就是 dry-run，不写盘）
python installers/install.py --agent dsh

# 2) 确认无误再写入
python installers/install.py --agent dsh --apply
```

### 参数

| 参数 | 说明 |
|---|---|
| `--agent` | 必填：`dsh` / `codex` / `claude-code` / `generic` |
| `--home <dir>` | 宿主配置根目录（默认用户主目录） |
| `--python <exe>` | 指定解释器；默认自动探测 |
| `--project-root <dir>` | 项目级安装的目标项目根 |
| `--dry-run` | 只打印计划（**默认**） |
| `--apply` | 真正写盘 |
| `--allow-profile-write` | DSH：允许直接写 `cordis.patch.yml`（默认不写） |
| `--absolute-python` | 把 hook 配置里的 `python` 换成绝对路径 |

写入行为：**合并而非覆盖**；写前留 `.bak_<timestamp>`；可重复运行（幂等）。

### 各 agent 的差异

| agent | 落点 | 备注 |
|---|---|---|
| **DSH** | `<home>/.dsh/profiles/<profile>/cordis.patch.yml` | 默认只**打印片段**，让你自己粘贴 |
| **Codex** | `<home>/.codex/config.toml` | 追加两段 `[mcp_servers.*]` TOML |
| **Claude Code** | `<project_root>/.mcp.json` + hooks 文件 | 合并时保留你已有的条目 |
| **generic** | 打印通用的 MCP server 配置 | 自己接到宿主里 |

---

## 二、手动安装

### 1. 规则本

把 `rules/rules.json` 放到你的项目里即可，没有任何依赖。格式见
[README.md](README.md) 的「钩子的判定字段」一节。

### 2. MCP server（让 agent 能主动查）

```json
{
  "mcpServers": {
    "hard_rules": {
      "command": "python",
      "args": ["<repo>/tools/hard_rules_mcp_server.py"],
      "env": { "HARD_RULES_FILE": "<repo>/rules/rules.json" }
    }
  }
}
```

⚠️ `serverName` 建议固定为 `hard_rules`：技能与文档里的工具名（`check_situation`）是按它写的。

MCP server 是**常驻子进程**：改 `.py` 要重启宿主，但改 `rules.json` **立即生效**
（每次调用都重新加载，无缓存）。

### 3. 硬闸 —— 通用路径（Python）

`hooks/hooks.json` 是给宿主用的模板：

```json
{"hooks":{"PreToolUse":[{"matcher":".*","hooks":[
  {"type":"command","command":"python \"<repo>/hooks/scripts/pretooluse_guard.py\"","timeout":30}]}]}}
```

把 `<repo>` 换成实际路径，接到宿主的 hook 配置里。

### 4. 硬闸 —— DSH 路径（原生插件，推荐）

⚠️ **DSH 上不要用上面那条 Python 路径。** 实测该桥接**挂载了但从不触发**：
一个同时注册在 `SessionStart` 与 `PreToolUse` 的探针脚本，其日志文件**一次都没被创建**，
而同一次重启里原生插件的 `gate-ready` 按时落盘。

DSH 用 `plugin/rule-gate/`：

```powershell
Copy-Item -Recurse .\plugin\rule-gate "$env:DSH_HOME\profiles\desktop\rule-gate"
```

然后在 `cordis.patch.yml` 追加：

```yaml
- insert:
    - id: rule-gate
      name: './rule-gate/index.js'
      config: {}
```

细节与判定字段语义见 [`plugin/rule-gate/README.md`](plugin/rule-gate/README.md)。

---

## 三、验证

**不要只看「有没有报错」** —— 这个项目的失败模式以静默为主。用可复现判据：

### 规则本 + MCP

```
check_situation("我要删掉整个目录")     → 应命中 RULE_003
check_situation("现在你的死规则有什么")  → 元查询，应返回全量规则
```

⚠️ **元查询与「本任务不受约束」在返回体上必须能区分**：返回体里应带
`mode`（`situation` / `self_inspection`）与 `total_rules_in_notebook`。
如果只拿到一个空的 `matched_rules` 而没有任何说明，**不能**读成「没有规则要守」。

### 硬闸

| 判据 | 期望 |
|---|---|
| 跑一条必然命中的命令 | **被拒绝**，且理由里带 `[rule RULE_00X - ...]` |
| 同一条命令的「安全版本」 | 放行 |
| 闸门自己的日志 | 启动时一条 `gate-ready`（列出参与拦截的规则）；放过一条规则时一条 `rule-hit` |

关键是**同时要有正例和反例**：只有正例被拦，说明不了闸门没误伤。

### 回归测试

```bash
python test_rules.py     # 规则本自身
python test_fuzzy.py     # 场景匹配（注意：必须在技能根目录跑）
```

---

## 四、卸载

```powershell
# 1. 从宿主配置里删掉 MCP server 条目与 hook 条目
# 2. DSH：删掉 cordis.patch.yml 里的 rule-gate insert 块，然后重启
# 3. 删目录（rules.json 建议先备份 —— 那是你的规则资产）
Copy-Item .\rules\rules.json .\rules\rules.json.backup
Remove-Item -Recurse -Force "<repo>"
```

⚠️ **先删配置再删目录**。顺序反了会导致宿主启动时找不到插件。

---

## 五、常见问题

| 现象 | 原因 | 处理 |
|---|---|---|
| 配好了但什么都没发生 | 最可能是**插件名指向了目录** | `name` 必须是 `./rule-gate/index.js` 这种具体文件 |
| 启动时报 `patch: entry "X" not found` | 那条 id 定向补丁的目标不存在 | 该块配置从未生效；删掉或改对 id |
| 改了规则没生效 | 改的是 `.py` 而非 `rules.json` | 改 `.py` 要重启宿主；改 `rules.json` 立即生效 |
| 空结果被当成「没有规则」 | 元查询返回体缺少自描述字段 | 看 `total_rules_in_notebook`，别只看 `matched_rules` |
| 闸门把所有命令都拦了 | `all_of` 被当成了独立分支 | `all_of` 只在 `any_of` 命中后才校验 |
