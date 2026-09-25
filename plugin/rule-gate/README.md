# rule-gate — native DSH plugin

Enforces the notebook's `hook` rules **at the tool-call boundary**: a matched rule
makes DSH reject the tool call outright instead of relying on the model to obey.

Loads the same `rules/rules.json` as the Python guard and the MCP server — one rule
file, three consumers. It only enforces rules that carry **both**:

- `layer` containing `"hook"`
- a `hook` block with `hook.action === "deny"`

Everything else stays a notebook rule (the agent is expected to query it and comply).

## Why a native plugin instead of the generic hook bridge

DSH can run Claude-Code-style hook configs through a bridge package. That route was
wired up first and **never fired**. The measurement, not a guess:

| Evidence | Result |
|---|---|
| A probe script registered on `SessionStart` **and** `PreToolUse`, writing one JSONL line per invocation | its log file was **never created** — not a single line |
| The same restart, same log directory, the native plugin's own `gate-ready` line | appeared **on time** |
| Dozens of tool calls afterwards | the probe stayed absent |

⇒ The bridge mounts but does not register its hooks. Since the gate had to work, the
enforcement moved into this plugin.

**Do not blame the bridge's silence on missing services.** A plausible-sounding
explanation is that its `inject = ["shell", "sessionProjections"]` can never be
satisfied — but both services exist on that host, and the injection contract means
"wait for them, then apply". The root cause was never located; the probe log is what
settles the question, and it is worth re-running before trusting any explanation.

Two further constraints that bit during development, both silent failures:

- The plugin `name` in the profile patch **must point to a concrete file**
  (`./rule-gate/index.js`). Pointing it at the directory triggers Node ESM's
  `ERR_UNSUPPORTED_DIR_IMPORT`; the plugin then does not load and **nothing is logged**.
- Do not declare a static `inject` array on an inline plugin; services are not ready at
  `apply` time. Listen on the extension point instead.

## Install

```yaml
# profile cordis.patch.yml
- insert:
    - id: rule-gate
      name: './rule-gate/index.js'
      config: {}
```

Then restart DSH — profile patches are read once per process, there is no hot reload.
Set `enforce: false` in the config to log matches without blocking.

## Configuration (all optional)

| Env var | Default | Purpose |
|---|---|---|
| `HARD_RULES_FILE` | `../../rules/rules.json` relative to this plugin | rule file location |
| `HARD_RULES_GATE_LOG` | `<tmpdir>/hard-rules-gate.jsonl` | decision log (`gate-ready` / `rule-hit`) |
| `HARD_RULES_GATE_DEBUG` | off | when set, log every evaluated call |
| `HARD_RULES_GATE_DEBUG_LOG` | `<tmpdir>/hard-rules-gate-debug.jsonl` | where the debug trace goes |

## How a rule is evaluated

```
tools: [...]        tool whitelist (absent = all tools)
fields: [...]       which arguments the regexes run against
any_of: [...]       precondition: at least one must match
all_of: [...]       ADDITIONAL requirements, checked only after any_of matched
path_any_of: [...]  target path matches any of these
path_not_any_of: [..] path matches any of these -> rule does not apply (exclusion)
path_must_exist     target must already exist, else skip (a new file cannot be overwritten)
path_exists: [...]  at least one of these exists on disk -> precondition satisfied
```

⚠️ **`all_of` is not an independent OR branch.** It is only consulted once `any_of`
has matched. Treating it as a standalone condition is a real bug that was shipped once:
an `all_of: [^(?!...Hidden).*$]` exclusion matched *everything*, so the gate blocked
every command. Keep the order.

⚠️ **`path_must_exist` must be evaluated before `path_exists`.** Otherwise a brand-new
config file is rejected for having no `.bak` — when creating a file is precisely the
case with no overwrite risk.

Rules are written with Python regex syntax and may carry an inline `(?i)` flag, which
JavaScript's `RegExp` does not accept; the plugin extracts it into a flag.
**Other Python-only constructs would need matching support here.**

## Fail-safe

If the rule file is missing, unreadable, bad JSON, or contains an invalid regex, the
plugin **allows the call** and records why. It never guesses and never blocks on its
own failure — a broken gate must not brick the session.
