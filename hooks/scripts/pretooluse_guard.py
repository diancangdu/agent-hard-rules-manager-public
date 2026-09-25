#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""PreToolUse hard gate for the agent-hard-rules notebook.

⚠️ 已退役（2026-09-25）：DSH 的实际硬闸现在由原生插件承担 ——
`$DSH_HOME/profiles/desktop/rule-gate/index.js`。原因：本脚本依赖的
`@deepseek-ai/dsh-hooks-claude-code` 桥接在 DSH 里从未激活（ESM 目录导入失败 +
内联插件 apply 阶段拿不到 inject 服务）。

保留本文件仅作参考与本地校验用途。**注意它不识别新加的判定字段**
（`path_any_of` / `path_not_any_of` / `path_exists` / `path_must_exist`），因此对
RULE_004/014/016/019 的判定与原生插件不一致；改动 hook 规则后请以原生插件的测试为准：
`node F:\\DSH-DATA\\dsh-hardrules-backup\\test_all_rules.mjs`

⚠️ 已知差异（2026-09-25，勿误以为两边等价）：本脚本只编译 `any_of` / `all_of`，
**完全不做 path 系判定**（见下方 `if not any_of and not all_of: continue`）。
原生插件在 2026-09-25 新增了 `path_must_exist`（RULE_004 用它实现「只管修改、
不管新建」）。**没有**把该逻辑补进本脚本 —— 它是退役代码，补一份等价实现既无收益
又制造第二份会腐烂的真源；需要核对判定请一律跑上面的 mjs 全量回归（30 个正/反例）。

Protocol (verified against dsh-hook-protocol/src/codec.ts):
  * reads a JSON payload on stdin
  * exit 2  -> the tool call is BLOCKED; stderr becomes the model-visible reason
  * exit 0  -> allow (any other exit code is a non-blocking error, i.e. allow)
  * structured stdout is only parsed on a clean exit, so we deliberately use
    `exit 2 + stderr` — the one dialect every bridge agrees on.
      - a top-level {"decision": "deny"} would be silently IGNORED
        (only approve/block are valid there); deny lives in
        hookSpecificOutput.permissionDecision. Exit code avoids the trap.

Payload fields we use (Claude Code dialect, which DSH bridges):
  tool_name            e.g. "bash" | "pwsh" | "write" | "edit" | "str_replace_editor"
  tool_input           tool arguments dict
  hook_event_name      "PreToolUse"
  cwd / session_id     unused, kept for debugging

Everything the gate enforces is DATA in rules/rules.json — a rule participates
only when its `layer` contains "hook" and it carries a `hook` block:

  hook: {tools: [...], fields: [...], any_of: [regex...], all_of: [regex...],
         action: "deny", reason: "..."}

Fail-open by design: a broken/unreadable rule file never blocks the agent, it
only prints a warning to stderr.
"""
import json
import os
import re
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(HERE, '..', '..'))
DEFAULT_RULES = os.path.join(PROJECT_ROOT, 'rules', 'rules.json')

EXIT_BLOCK = 2
EXIT_ALLOW = 0

# tool_input keys that may hold text worth scanning, in priority order
TEXT_KEYS = ('command', 'content', 'new_string', 'new_str', 'file_text',
             'old_string', 'file_path')


def warn(msg):
    sys.stderr.write('agent-hard-rules guard: %s\n' % msg)


def rules_file():
    return os.environ.get('HARD_RULES_FILE') or DEFAULT_RULES


def load_rules():
    """Return compiled hook rules. Never raises."""
    path = rules_file()
    try:
        with open(path, encoding='utf-8') as f:
            doc = json.load(f)
    except FileNotFoundError:
        warn('rules file not found: %s (gate inactive)' % path)
        return []
    except Exception as e:                                   # noqa: BLE001
        warn('cannot parse %s: %s (gate inactive)' % (path, e))
        return []

    out = []
    for r in doc.get('rules') or []:
        if not isinstance(r, dict):
            continue
        h = r.get('hook')
        if not isinstance(h, dict):
            continue
        layers = r.get('layer') or []
        if isinstance(layers, str):
            layers = [layers]
        if 'hook' not in layers:
            continue
        action = (h.get('action') or 'deny').lower()
        if action != 'deny':
            continue

        def compile_all(key):
            res = []
            for p in h.get(key) or []:
                try:
                    res.append(re.compile(p))
                except re.error as e:
                    warn('%s has an invalid %s regex (%s) - skipped'
                         % (r.get('rule_id'), key, e))
            return res

        any_of = compile_all('any_of')
        all_of = compile_all('all_of')
        if not any_of and not all_of:
            continue

        out.append({
            'rule_id': r.get('rule_id') or '?',
            'title': r.get('title') or '',
            'tools': set(h.get('tools') or []),
            'fields': list(h.get('fields') or TEXT_KEYS),
            'any_of': any_of,
            'all_of': all_of,
            'reason': h.get('reason') or (
                'blocked by hard rule %s' % (r.get('rule_id') or '')),
        })
    return out


def gather_text(tool_input, fields):
    parts = []
    for f in fields:
        v = tool_input.get(f)
        if isinstance(v, str):
            parts.append(v)
        elif isinstance(v, (list, dict)):
            try:
                parts.append(json.dumps(v, ensure_ascii=False))
            except Exception:                                # noqa: BLE001
                pass
    return '\n'.join(parts)


def evaluate(payload):
    """Return (blocked: bool, reason: str)."""
    tool = payload.get('tool_name') or payload.get('toolName') or ''
    if not isinstance(tool, str):
        tool = str(tool)
    tool_input = payload.get('tool_input') or payload.get('toolInput') or {}
    if not isinstance(tool_input, dict):
        tool_input = {'_raw': str(tool_input)}

    if not tool:
        return False, ''

    for rule in load_rules():
        if rule['tools'] and tool not in rule['tools']:
            continue
        text = gather_text(tool_input, rule['fields'])
        if not text.strip():
            continue
        hit = ''
        for rx in rule['any_of']:
            m = rx.search(text)
            if m:
                hit = m.group(0)[:160]
                break
        if not hit and rule['all_of']:
            if all(rx.search(text) for rx in rule['all_of']):
                hit = '(all_of)'
        if hit:
            reason = rule['reason']
            return True, ('%s\n[rule %s - %s]\n[matched: %s]\n[tool: %s]'
                          % (reason, rule['rule_id'], rule['title'], hit, tool))
    return False, ''


def gate_log(payload, blocked, reason):
    """Opt-in invocation probe. Writes one JSONL line per call when
    HARD_RULES_GATE_LOG names a file. Failures never affect the decision."""
    path = os.environ.get('HARD_RULES_GATE_LOG')
    if not path:
        return
    try:
        rec = {
            'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'tool_name': payload.get('tool_name'),
            'tool_name_alt': payload.get('toolName'),
            'hook_event_name': payload.get('hook_event_name'),
            'input_keys': sorted(payload.get('tool_input', {}).keys())
            if isinstance(payload.get('tool_input'), dict) else None,
            'cmd_head': str((payload.get('tool_input') or {}).get('command', ''))[:120]
            if isinstance(payload.get('tool_input'), dict) else None,
            'blocked': blocked,
            'reason_head': (reason or '')[:120],
        }
        with open(path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(rec, ensure_ascii=False) + '\n')
    except Exception:                                        # noqa: BLE001
        pass


def run_hook():
    raw = sys.stdin.read()
    if not raw.strip():
        gate_log({}, False, '(empty stdin)')
        return EXIT_ALLOW
    try:
        payload = json.loads(raw)
    except Exception:                                        # noqa: BLE001
        warn('stdin is not valid JSON - allowing (fail-open)')
        gate_log({}, False, '(invalid JSON)')
        return EXIT_ALLOW
    if not isinstance(payload, dict):
        return EXIT_ALLOW

    try:
        blocked, reason = evaluate(payload)
    except Exception as e:                                   # noqa: BLE001
        warn('internal error %s - allowing (fail-open)' % e)
        gate_log(payload, False, '(internal error: %s)' % e)
        return EXIT_ALLOW

    gate_log(payload, blocked, reason)

    if blocked:
        sys.stderr.write(reason + '\n')
        return EXIT_BLOCK
    return EXIT_ALLOW


CASES = [
    # (name, payload, expect_block)
    ('secrets-hardcoded', {'tool_name': 'write', 'tool_input': {
        'file_path': 'F:/x/a.py',
        'content': 'API_KEY = "sk-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxx"',
    }}, True),
    ('secrets-placeholder', {'tool_name': 'write', 'tool_input': {
        'file_path': 'F:/x/a.py',
        'content': 'API_KEY = os.environ["API_KEY"]',
    }}, False),
    ('rm-rf-root', {'tool_name': 'bash', 'tool_input': {'command': 'rm -rf /'}}, True),
    ('rm-rf-home', {'tool_name': 'bash', 'tool_input': {'command': 'sudo rm -rf ~'}}, True),
    ('rm-rf-build-ok', {'tool_name': 'bash', 'tool_input': {
        'command': 'rm -rf ./build'}}, False),
    ('drop-table', {'tool_name': 'bash', 'tool_input': {
        'command': 'mysql -e "DROP TABLE users"'}}, True),
    ('remove-item-force', {'tool_name': 'pwsh', 'tool_input': {
        'command': 'Remove-Item -Path C:\\tmp\\x -Recurse -Force'}}, True),
    ('curl-to-c-drive', {'tool_name': 'bash', 'tool_input': {
        'command': 'curl -L https://x/y.zip -o C:\\Users\\me\\y.zip'}}, True),
    ('curl-to-f-drive-ok', {'tool_name': 'bash', 'tool_input': {
        'command': 'curl -L https://x/y.zip -o F:\\dl\\y.zip'}}, False),
    ('pip-install-ok', {'tool_name': 'bash', 'tool_input': {
        'command': 'pip install requests'}}, False),
    ('unrelated-tool', {'tool_name': 'read', 'tool_input': {
        'file_path': '/etc/passwd'}}, False),
]


def selftest():
    print('rules file : %s' % rules_file())
    loaded = load_rules()
    print('hook rules : %d  (%s)' % (len(loaded),
                                     ', '.join(r['rule_id'] for r in loaded)))
    print('')
    bad = 0
    for name, payload, expect in CASES:
        got_blocked, reason = evaluate(payload)
        ok = (got_blocked == expect)
        if not ok:
            bad += 1
        print('%-22s expect=%-5s got=%-5s %s' % (
            name, 'BLOCK' if expect else 'allow',
            'BLOCK' if got_blocked else 'allow', 'ok' if ok else '<<< FAIL'))
        if got_blocked and not expect:
            print('    reason: %s' % reason.splitlines()[0][:100])
    print('')
    print('selftest: %d/%d passed' % (len(CASES) - bad, len(CASES)))
    return 1 if bad else 0


if __name__ == '__main__':
    if '--selftest' in sys.argv:
        sys.exit(selftest())
    sys.exit(run_hook())
