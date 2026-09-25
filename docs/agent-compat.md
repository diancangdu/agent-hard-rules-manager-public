# 各 agent 兼容性

本文档说明 HardRules 在各类 agent 上的支持情况，以及**每项能力具体落到哪个文件**。

一句话结论：**MCP 到处能用，硬闸不能。** 没有 hooks 的 agent 只拿到 notebook 层，而 notebook 层是**静默失效**的。

---

## 一、支持矩阵

行 = 能力，列 = agent。每格给出结论与落点。

| 能力 | Codex | DSH | Claude Code | 通用 MCP 客户端 |
| --- | --- | --- | --- | --- |
| **MCP**（读取/维护规则库） | **支持**<br>`<home>/.codex/config.toml` 里 `[mcp_servers.agent-hard-rules]` + `.env` | **支持**<br>`<home>/.dsh/profiles/desktop/cordis.patch.yml` 里 `- insert:` 两条（`@deepseek-ai/dsh-mcp-client`，`serverName: hard_rules`） | **支持**<br>`<project_root>/.mcp.json` 的 `mcpServers` | **支持**<br>标准 `{"mcpServers": {...}}`，安装器产出 `<home>/.hard-rules/mcp.json` |
| **hooks**（工具调用前硬闸，`exit 2`） | **部分**<br>有 hooks 机制但接入方式不同；本项目当前**只给 Codex 装 MCP**，hooks 留待后续 | **部分**<br>没有原生 hook；靠桥接插件 `@deepseek-ai/dsh-hooks-claude-code` 消费 Claude Code 格式的 `hooks.json`（另有 `dsh-hooks-codex`） | **支持（原生）**<br>`PreToolUse`；`hooks/hooks.json`（项目内）或合并进 `<project_root>/.claude/settings.json` | **不支持**<br>MCP 规范里没有「工具调用前拦截」原语 |
| **指令文件**（agent 自动读取的约定文件） | **支持**<br>`AGENTS.md` | **支持**<br>`AGENTS.md`（从项目根逐层扫到工作目录） | **支持**<br>`CLAUDE.md` | **无统一约定**<br>各客户端自定义，未验证 |
| **skill 自动扫描** | **支持**<br>skills 目录（**具体扫描顺序未验证**） | **支持**<br>按 rank：项目 `.dsh/skills` → 项目 `.agents/skills` → `customSkillDirs` → `$DSH_HOME/skills` → `~/.agents/skills` → bundled | **支持**<br>（**具体根目录未验证**） | **不支持 / 未验证**<br>多数通用 MCP 客户端没有 skill 概念 |

**「部分」的含义**：能力本身存在，但本项目当前没有为它生成配置，或者需要用桥接插件间接实现。**「未验证」的含义**：本文档没有在本机确认该行为，请以对应 agent 的官方文档为准。

---

## 二、每种能力实际给到你什么

把矩阵翻译成使用后果：

| agent | notebook 层 | hook 层 | 结论 |
| --- | --- | --- | --- |
| Claude Code | ✅ | ✅ 原生 | 两层齐全 |
| DSH | ✅ | ✅ 但需桥接插件 | 装好桥接后两层齐全；**profile 由主 agent 统一部署** |
| Codex | ✅ | ❌ 当前未装 | 只有 notebook 层——**静默失效**风险全在这里 |
| 通用 MCP 客户端 | ✅ | ❌（规范不支持） | 同上 |

所以：在 Codex 与通用 MCP 客户端上，`RULE_001` / `RULE_003` / `RULE_005` **不会被机器拦下**，它们的保障完全来自 agent 主动查询规则库。不要因为这三条在 `rules.json` 里带了 `hook` 块，就以为在任何 agent 上都生效了。

---

## 三、MCP 层的兼容性契约

本项目的 MCP server（`tools/hard_rules_mcp_server.py`）刻意只依赖 MCP 约定，因此可跨 agent 复用：

- **传输**：标准 stdio（`server.run(transport="stdio")`）。
- **路径自足**：server 靠 `__file__` 反推项目根定位 `rules/rules.json`；`HARD_RULES_FILE` 环境变量可覆盖规则库路径。因此任何工作目录下启动都能找到规则库。
- **stdout 干净**：所有诊断输出走 stderr（`utils/rule_parser.py` 的日志固定写 stderr），避免污染 JSON-RPC 通道。
- **serverName 统一**：共享常量为 `hard_rules`（需匹配 `[A-Za-z0-9_-]{1,32}`）；Codex 适配器用的 TOML 小节名是 `agent-hard-rules`。
- **暴露的能力**：资源 `rules://notebook`、`file://{+path}`；工具 `list_all_rules` / `get_rule` / `list_categories` / `query_rules` / `check_situation` / `add_rule` / `delete_rule`。

⚠️ MCP 层的 `add_rule` **不支持写入 `layer` / `hook`**。用 MCP 加出来的规则没有 `layer` 字段，闸门会忽略它（即事实上只进 notebook）。要上 hook 需手工编辑 `rules.json`，见 [分层判断表.md](分层判断表.md)。

---

## 四、hooks 层的兼容性契约

`hooks/hooks.json` 用的是 **Claude Code 格式**，DSH 的桥接插件在解析配置时会替换 `${CLAUDE_PLUGIN_ROOT}` 占位符：

```json
{"hooks":{"PreToolUse":[{"matcher":"bash|pwsh|write|edit|str_replace_editor","hooks":[{"type":"command","command":"python \"${CLAUDE_PLUGIN_ROOT}/hooks/scripts/pretooluse_guard.py\"","timeout":30}]}]}}
```

几个关键点：

- **matcher** 由共享常量 `HOOK_MATCHER` 决定，当前为 `bash|pwsh|write|edit|str_replace_editor`。改这个字符串会同时影响所有 agent。
- **`${CLAUDE_PLUGIN_ROOT}` 不是所有宿主都会替换。** Claude Code 的 `settings.json` 拿不到这个变量，所以适配器在写 `.claude/settings.json` 时改用**绝对路径**调用守卫脚本（守卫脚本靠 `__file__` 反推项目根，因此绝对路径是安全且自足的）。DSH 侧则由桥接插件替换占位符。
- **返回协议**（已对 `dsh-hook-protocol/src/codec.ts` 核实）：
  - `exit 2` → 阻止，**stderr 就是模型看到的理由**；
  - `exit 0` → 放行，**其他任何退出码都是非阻塞错误，即放行**；
  - 结构化 stdout 只在 `exit 0` 时被解析；
  - ⚠️ 顶层 `{"decision":"deny"}` 会被**静默忽略**（只认 `approve` / `block`），`deny` 必须写在 `hookSpecificOutput.permissionDecision`。本项目用 `exit 2 + stderr` 正是为了绕开这个坑。
- **fail-open**：规则文件读不到或解析失败时，守卫只打警告并放行，绝不阻塞 agent。
- **payload 字段**：守卫读 `tool_name` / `tool_input`（Claude Code 风格），并额外兼容 `toolName` / `toolInput` 驼峰写法；`cwd` / `session_id` 当前未使用。

守卫自带回归自检：

```bash
python hooks/scripts/pretooluse_guard.py --selftest   # -> selftest: 11/11 passed
```

---

## 五、指令文件与 skill 扫描

- **指令文件**：Codex / DSH 读 `AGENTS.md`，Claude Code 读 `CLAUDE.md`。若想让 agent 自动知道本项目的两条铁律，需要把 `SKILL.md` 的要点（或直接指向本项目）写进对应文件——本项目**不会**自动修改这些文件。
- **DSH 的 skill 扫描顺序**（按 rank，来自任务给定的已验证事实）：
  1. 项目 `.dsh/skills`
  2. 项目 `.agents/skills`
  3. `customSkillDirs`
  4. `$DSH_HOME/skills`
  5. `~/.agents/skills`
  6. bundled
- **Codex / Claude Code 的 skill 扫描顺序**：未在本机验证，请查官方文档。

---

## 六、安装到各 agent

统一入口见 [../installers/README.md](../installers/README.md)。速览：

```bash
python installers/install.py --agent dsh|codex|claude-code|generic [--apply]
```

对 DSH，即使加 `--apply`，profile（`cordis.patch.yml`）也默认**不被写入**——需要额外显式加 `--allow-profile-write`。这是有意的边界：DSH 的 profile 由主 agent 统一部署。

---

## 七、未验证项汇总

诚实列出，避免误用：

1. Codex 的 hooks 接入方式与本项目 `hooks.json` 的适配细节——**未验证**，当前不给 Codex 装 hooks。
2. Codex / Claude Code 的 skill 扫描根与扫描顺序——**未验证**。
3. 通用 MCP 客户端（Cursor / Windsurf / Cline / Continue 等）是否提供任何形式的工具调用前拦截——**未验证**，按「不支持」处理。
4. `dsh-hooks-codex` 与本项目 `hooks.json` 的兼容性——**未验证**。
5. 除 Windows 外的平台（守卫脚本与安装器在路径处理上偏 Windows 用法，如盘符判断）——**未验证**。

---

## 八、相关文档

- [../README.zh.md](../README.zh.md) —— 项目总览、两层机制与已知边界
- [分层判断表.md](分层判断表.md) —— 哪条规则在哪一层，以及新增规则怎么判
- [../SKILL.md](../SKILL.md) —— 两条铁律、强制执行流程、被闸门拦下后的正确做法
