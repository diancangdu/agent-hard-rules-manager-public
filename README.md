# Hard Rules Manager

An **agent-agnostic hard-rules notebook** — plus, where the host agent supports
it, a machine-enforced gate in front of tool calls.

**Version: `v1.0.0`** — first public release. See [CHANGELOG.md](CHANGELOG.md).
Install: [INSTALL.md](INSTALL.md).

> **This is the public edition.** All machine-specific paths have been removed and
> replaced with neutral examples; rule files resolve their locations at runtime now.
> It also ships `plugin/rule-gate/` — a **native DSH plugin** that enforces the
> notebook's `hook` rules at the tool-call boundary. That plugin exists because the
> generic hook-bridge route silently failed to register on DSH; see
> [plugin/rule-gate/README.md](plugin/rule-gate/README.md) for the measurements.
>
> The private edition keeps the machine-local specifics.

This project used to be `codex-hard-rules-manager`. It is now generic: the
rules live in one JSON file, the same MCP server serves every MCP-capable
agent, and the gate is plain Python behind a file-based hook config.

A **hard rule** is a rule that, once triggered, must be followed
unconditionally. No "it's probably fine this time".

> 中文文档（主文档，内容更完整）：[README.zh.md](README.zh.md)

---

## 1. What is in here

```
HardRules/
├── rules/rules.json                  # 22 rules, UTF-8 JSON (the single source of truth)
├── utils/rule_parser.py              # load / save / query / add / update / delete / match
├── query_rules.py                    # CLI: --check --keyword --all --category --rule-id --json
├── add_rule.py                       # CLI: add a rule (also interactive when run bare)
├── tools/hard_rules_mcp_server.py    # MCP server (standard stdio transport)
├── tools/migrate_layers.py           # one-shot migration that added `layer`
├── hooks/hooks.json                  # Claude Code format: PreToolUse + matcher
├── hooks/scripts/pretooluse_guard.py # the gate itself (selftest 11/11 passing)
├── adapters/                         # config generators: dsh / codex / claude_code / generic_mcp
├── installers/install.py             # unified installer (dry-run by default)
└── docs/
    ├── 分层判断表.md                  # which rules belong in which layer, and why
    └── agent-compat.md               # per-agent support matrix
```

Current rule inventory: **22 rules**, 19 of which are notebook-only and 3 of
which also carry a hook (`RULE_001`, `RULE_003`, `RULE_005`). Categories in use:
安全 / 行为 / 技术 / 协作 / 三模型协同.

---

## 2. Why two layers

This is the most important idea in the project. A rule can live in one of two
layers, and a rule may live in both:

| Layer | Where the enforcement comes from | How it fails |
| --- | --- | --- |
| `notebook` | The agent queries the archive and obeys it on its own | **Silently.** Nobody notices a skipped rule. |
| `hook` | Code intercepts the tool call *before* it runs (`exit 2`) | **Loudly.** The model sees the blocked reason. |

Every rule has a `layer` array:

- `["notebook"]` — the rule is in the notebook only. It depends on the agent
  actively querying the archive.
- `["notebook", "hook"]` — the rule is *also* a machine-enforced gate. A tool
  call that matches its regexes is blocked before execution.

Do the two layers cover the same ground? No. They have different failure modes,
and that is the point: the notebook catches everything (as long as the agent
looks), the gate catches a narrow, unambiguous subset (whether or not the agent
looks).

**How a rule is assigned:** ask what happens when the rule is missed.

- Missing it causes **harm** (irreversible loss, a leaked credential, a
  polluted system drive) → candidate for `hook`.
- Missing it is merely **suboptimal** (uglier code, a missed convention) →
  `notebook` only.

Only 3 of 22 rules cross that line. The full per-rule reasoning is in
[docs/分层判断表.md](docs/分层判断表.md).

### The gate is data, not code

A hook rule carries a `hook` block *inside* `rules.json`:

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

`pretooluse_guard.py` reads this structure at runtime. Editing the rule changes
what is blocked; the script does not need to be touched.

| Field | Meaning |
| --- | --- |
| `tools` | Tool names this gate applies to (the PreToolUse matcher subject) |
| `fields` | Sub-keys of `tool_input` to scan |
| `any_of` | Block if **any** regex matches |
| `all_of` | Block only if **all** regexes match |
| `action` | `deny` (the only action the gate implements) |
| `reason` | The text handed back to the model when blocked |

---

## 3. The hook protocol

Verified against `dsh-hook-protocol/src/codec.ts`:

- `exit 2` → the tool call is **blocked**, and **stderr is the reason the model
  sees**.
- `exit 0` → allow. **Any other exit code is a non-blocking error, i.e. allow.**
- Structured stdout is **only** parsed on a clean exit.
- ⚠️ A top-level `{"decision": "deny"}` is **silently ignored** — only
  `approve` / `block` are valid there. `deny` belongs in
  `hookSpecificOutput.permissionDecision`. This project uses `exit 2 + stderr`
  precisely to sidestep that trap.
- The guard is **fail-open**: if the rules file is missing or unparseable it
  prints a warning and allows the call. It never deadlocks an agent.

The guard also ships a self-check:

```bash
python hooks/scripts/pretooluse_guard.py --selftest   # -> selftest: 11/11 passed
```

---

## 4. Install

Unified entry point (dry-run by default — nothing is written unless you pass
`--apply`):

```bash
python installers/install.py --agent dsh|codex|claude-code|generic \
                             [--home <dir>] [--python <exe>] \
                             [--dry-run | --apply]
```

| Agent | What gets written | Target |
| --- | --- | --- |
| `dsh` | MCP client + hooks bridge config as a YAML fragment | `<home>/.dsh/profiles/desktop/cordis.patch.yml` |
| `codex` | `[mcp_servers.agent-hard-rules]` (+ `.env`) TOML | `<home>/.codex/config.toml` |
| `claude-code` | `.mcp.json` + merged PreToolUse hooks | `<project_root>/.mcp.json`, `<project_root>/.claude/settings.json` |
| `generic` | the most standard `{"mcpServers": {...}}` | `<home>/.hard-rules/mcp.json` |

Behaviour guarantees: dry-run is the default; writes are **merged, not
overwritten**; an existing file is copied to `<name>.bak_<YYYYMMDD_HHMMSS>`
first; re-running is idempotent.

**DSH is special:** its profile is deployed by the main agent, so even with
`--apply` the installer only *prints* the fragment. Writing
`cordis.patch.yml` yourself requires the extra explicit flag
`--allow-profile-write` (and it backs the file up first).

```bash
# 1) preview
python installers/install.py --agent dsh --home D:/dsh-data
# 2) hand the printed fragment to the main agent, or, if you really want the
#    installer to write it:
python installers/install.py --agent dsh --home D:/dsh-data \
    --apply --allow-profile-write
```

See [installers/README.md](installers/README.md) for per-agent detail and
rollback instructions.

---

## 5. Query rules

```bash
python query_rules.py --all                    # every rule
python query_rules.py --check "把 API key 写进 config.py"   # situation match (the core use)
python query_rules.py --keyword "密码,删除,重构"            # keyword search (OR)
python query_rules.py --category 安全
python query_rules.py --rule-id RULE_001
python query_rules.py --json --keyword 密钥     # machine-readable
```

Matching is deliberately recall-oriented ("better to over-match than to miss a
hard rule"). See "Known boundaries" below for the cost of that choice.

Via MCP, the same archive is exposed as:

- resource `rules://notebook` — the full archive as JSON
- tools `list_all_rules` / `get_rule` / `list_categories` / `query_rules` /
  `check_situation` / `add_rule` / `delete_rule`

---

## 6. Add a rule

```bash
python add_rule.py --title "禁止提交密钥" --category 安全 \
  --trigger "密钥,API key,硬编码" \
  --actions "使用环境变量管理密钥" \
  --forbidden "把密钥硬编码进源码" \
  --severity high --by user

python add_rule.py          # bare invocation -> interactive mode
```

A rule looks like this:

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

`layer` and `hook` are **not** settable through `add_rule.py` or through the
MCP `add_rule` tool. A rule added that way has no `layer` field, which means the
gate ignores it — i.e. it is notebook-only. Promoting a rule to `hook` is a
deliberate, manual edit of `rules.json` (see
[docs/分层判断表.md](docs/分层判断表.md)).

---

## 7. Agent support

| Capability | Codex | DSH | Claude Code | Generic MCP client |
| --- | --- | --- | --- | --- |
| MCP server | yes | yes | yes | yes |
| PreToolUse hooks | partial (MCP only for now) | partial (via bridge plugin) | yes (native) | no |
| Instruction file | `AGENTS.md` | `AGENTS.md` | `CLAUDE.md` | n/a |
| Skill auto-scan | yes | yes (ranked roots) | yes | n/a |

Details, exact file paths and what is unverified: see
[docs/agent-compat.md](docs/agent-compat.md).

The practical upshot: **MCP works everywhere; the hard gate does not.** On an
agent without hooks you get the notebook layer — which fails silently. Do not
assume a rule is enforced just because it is in `rules.json`.

---

## 8. Known boundaries

Stated plainly, because over-claiming here is exactly the failure this project
is meant to prevent.

1. **The notebook layer fails silently.** If an agent never queries the
   archive, an unenforced rule produces no warning, no log line, nothing. The
   only thing standing between you and a missed rule is the agent's habit of
   querying first (see `SKILL.md`).
2. **The gate only denies; it cannot allow.** `pretooluse_guard.py` skips any
   hook whose `action` is not `deny`. There is no "pre-approve this pattern"
   capability, so it cannot be used to reduce confirmation prompts.
3. **The 60% bigram threshold is loose and will over-report.** `_text_contains`
   falls back to character-bigram overlap ≥ 0.6, which tolerates Chinese
   insertions and English inflection but also matches text you did not mean to
   match. Treat `--check` hits as "read this rule", not as "this rule is
   violated".
4. **Keywords shorter than 2 characters never fuzzy-match** (exact substring
   only), by design, to avoid mass false positives.
5. **The gate only sees tool-call arguments.** It cannot evaluate state that
   lives across turns, in the filesystem, or in what the user said. Rules of
   that shape stay in the notebook.
6. **Rules added via CLI/MCP are notebook-only** (no `layer` written), so the
   gate will not enforce them until you edit `rules.json` by hand.
7. **`RULE_005` (and the rest of the hook rules) match on text patterns, not on
   intent.** A sufficiently creative spelling of the same dangerous command
   slips through. The gate is a backstop, not a sandbox.

---

## 9. Maintenance

- Rules live in `rules/rules.json` (UTF-8, must stay valid JSON). Editing it by
  hand is supported.
- Delete the file and the next run recreates an empty archive.
- Keep it in git — the rule history is the audit trail.
- Existing `.bak_*` files in `rules/` and `tools/` are historical migrations,
  not part of the runtime.
