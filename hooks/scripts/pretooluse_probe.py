#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Diagnostic probe for the DSH hard-rules hook bridge.

Why this exists: on 2026-09-25 the PreToolUse hard gate was mounted in the DSH
profile but never fired — tool calls that provably match RULE_003 / RULE_005
went through untouched. The gate script itself was fine (selftest 11/11, exit 2
on matching payloads), so the break is in the bridge wiring, not the guard.

Register this on SessionStart AND PreToolUse. It writes one JSONL line per
invocation to $HARD_RULES_PROBE_LOG and always exits 0 (never blocks, never
adds context). A SessionStart line proves the bridge is mounted *and* runnable
before the first turn; absence of any line after a restart proves the bridge
itself is not registered.

Fail-silent by design: a broken probe must never affect the session.
"""
import json
import os
import sys
import tempfile
import time

DEFAULT_LOG = os.path.join(tempfile.gettempdir(), 'hook_probe.jsonl')

KEYS_OF_INTEREST = (
    'command', 'file_path', 'content', 'new_string', 'old_string',
    'pattern', 'path', 'filePath', 'description',
)


def log_path():
    return os.environ.get('HARD_RULES_PROBE_LOG') or DEFAULT_LOG


def main():
    try:
        raw = sys.stdin.read()
    except Exception:                                        # noqa: BLE001
        return 0
    try:
        payload = json.loads(raw) if raw.strip() else {}
    except Exception:                                        # noqa: BLE001
        payload = {'_unparsed_head': raw[:400]}
    if not isinstance(payload, dict):
        payload = {'_raw': str(payload)[:400]}

    tool_input = payload.get('tool_input')
    if not isinstance(tool_input, dict):
        tool_input = {}
    excerpt = {}
    for key in KEYS_OF_INTEREST:
        value = tool_input.get(key)
        if isinstance(value, str):
            excerpt[key] = value[:160]

    record = {
        'ts': time.strftime('%Y-%m-%dT%H:%M:%S'),
        'pid': os.getpid(),
        'ppid': os.getppid(),
        'event': payload.get('hook_event_name'),
        'session_source': payload.get('source'),
        'tool_name': payload.get('tool_name'),
        'tool_use_id': payload.get('tool_use_id'),
        'cwd': payload.get('cwd'),
        'session_id': payload.get('session_id'),
        'input_keys': sorted(tool_input.keys()),
        'input_excerpt': excerpt,
        'payload_keys': sorted(payload.keys()),
    }

    try:
        with open(log_path(), 'a', encoding='utf-8') as handle:
            handle.write(json.dumps(record, ensure_ascii=False) + '\n')
    except Exception:                                        # noqa: BLE001
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main())
