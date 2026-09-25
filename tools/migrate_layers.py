# -*- coding: utf-8 -*-
"""One-shot migration: add `layer` (+ executable `hook` spec) to every rule.

Design
------
Every rule lives in the notebook (`layer` contains "notebook").
A rule ALSO gets a machine-enforced gate (`layer` contains "hook") only when
missing it would be *harmful*, not merely *suboptimal*:

  RULE_001  secrets hard-coded into files   -> deny
  RULE_003  irreversible destructive cmds   -> deny
  RULE_005  download/install targeting C:   -> deny

The `hook` spec is data, not code, so the gate follows the notebook:
editing rules.json changes what is blocked without touching the hook script.

  hook = {
    tools:  [tool names to match]          # PreToolUse matcher subject
    fields: [payload fields to scan]       # tool_input sub-keys
    any_of: [regex, ...]                   # block if ANY matches
    all_of: [regex, ...]                   # optional; block only if ALL match
    action: "deny"
    reason: "message returned to the model"
  }

Run:  python tools/migrate_layers.py [--dry-run]
"""
import json
import re
import sys
import shutil
import datetime

RULES = r'D:\HardRules\rules\rules.json'


def hook_specs():
    return {
        # ── RULE_001 敏感信息保护 ────────────────────────────────────────────
        # Only patterns that are very unlikely to appear in legitimate prose.
        'RULE_001': {
            'tools': ['write', 'edit', 'str_replace_editor'],
            'fields': ['content', 'new_string', 'new_str', 'file_text'],
            'any_of': [
                # name = "long-value"  /  name: 'long-value'
                r"""(?i)\b(api[_-]?key|apikey|secret[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|refresh[_-]?token|password|passwd)\b\s*[:=]\s*["'][A-Za-z0-9_\-./+=]{16,}["']""",
                # well-known credential prefixes
                r"""\b(sk-[A-Za-z0-9]{20,}|sk-ant-[A-Za-z0-9_\-]{20,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|AKIA[0-9A-Z]{16}|xox[baprs]-[A-Za-z0-9\-]{10,})\b""",
                # PEM private key blocks
                r"""-----BEGIN [A-Z ]*PRIVATE KEY-----""",
            ],
            'action': 'deny',
            'reason': ('命中死规则 RULE_001（敏感信息保护）：疑似把密钥 / 凭据硬编码进文件。'
                       '请改为读取环境变量或 .env（并确认 .env 已在 .gitignore 中），'
                       '源码里只保留占位符名，不要写入真实值。'),
        },

        # ── RULE_003 禁止危险命令 ────────────────────────────────────────────
        # Deliberately narrow: routine `rm -rf ./build` is NOT blocked, only
        # operations whose damage is unrecoverable.
        'RULE_003': {
            'tools': ['bash', 'pwsh'],
            'fields': ['command'],
            'any_of': [
                # wipe a filesystem root / home / drive root
                r"""(?i)\brm\s+(-[A-Za-z]+\s+)*-[A-Za-z]*[rR][A-Za-z]*[fF][A-Za-z]*\s+(-[A-Za-z]+\s+)*(/|/\*|~|\$HOME|\$\{HOME\}|[A-Za-z]:[\\/])\s*($|[;&|])""",
                r"""(?i)\brm\s+(-[A-Za-z]+\s+)*-[A-Za-z]*[fF][A-Za-z]*[rR][A-Za-z]*\s+(-[A-Za-z]+\s+)*(/|~|\$HOME|[A-Za-z]:[\\/])\s*($|[;&|])""",
                # formatting / partitioning
                r"""(?i)\b(mkfs(\.[a-z0-9]+)?|wipefs|diskpart|fdisk|parted)\b""",
                r"""(?i)\bformat\s+[A-Za-z]:(\s|$)""",
                r"""(?i)\bdd\s+[^\n|]*\bof=\s*/dev/(sd|nvme|hd)""",
                # destructive SQL
                r"""(?i)\b(DROP\s+(TABLE|DATABASE|SCHEMA)|TRUNCATE\s+TABLE)\b""",
                # Windows recursive force delete
                r"""(?i)\b(Remove-Item|ri)\b[^\n|]*-Recurse[^\n|]*-Force""",
                r"""(?i)\bRemove-Item\b[^\n|]*-Force[^\n|]*-Recurse""",
                r"""(?i)\bdel\s+/[sfq]\b""",
                r"""(?i)\b(rd|rmdir)\s+/[sq]\b""",
                # fork bomb
                r""":\(\)\s*\{.*\|.*&.*\}\s*;\s*:""",
            ],
            'action': 'deny',
            'reason': ('命中死规则 RULE_003（禁止危险命令）：该命令包含不可逆的删除 / 格式化 / '
                       '破坏性操作（如清空根目录、格式化磁盘、DROP DATABASE、递归强删）。'
                       '请先向用户说明后果并取得明确确认；能用回收站 / 备份等可恢复方式的，'
                       '一律改用可恢复方式。'),
        },

        # ── RULE_005 禁止在 C 盘下载或安装 ──────────────────────────────────
        # Only explicit C: targets. We deliberately do NOT block package managers
        # generally (their default cache location is a preference, not a hazard).
        'RULE_005': {
            'tools': ['bash', 'pwsh'],
            'fields': ['command'],
            'any_of': [
                r"""(?i)\b(curl|wget)\b[^\n|;&]*\s-[oO]\s*["']?C:[\\/]""",
                r"""(?i)\b(Invoke-WebRequest|iwr)\b[^\n|;&]*-OutFile\s+["']?C:[\\/]""",
                r"""(?i)\b(Start-BitsTransfer|bitsadmin)\b[^\n|;&]*(?:-Destination|/transfer)\s+["']?C:[\\/]""",
                r"""(?i)(?:>|>>)\s*["']?C:[\\/](?:Users|Windows|Program\s*Files|ProgramData|Temp)\b""",
                r"""(?i)\b(?:Expand-Archive|tar|unzip|7z\s+x)\b[^\n|;&]*(?:-DestinationPath|-d|-C|-o)\s+["']?C:[\\/]""",
            ],
            'action': 'deny',
            'reason': ('命中死规则 RULE_005（禁止在 C 盘下载或安装）：命令的下载 / 解压 / 安装目标'
                       '落在 C 盘。请改到 F 盘等非系统盘路径后重试（D:\\data 或 '
                       'D:\\ 下的独立目录）。'),
        },
    }


def main():
    dry = '--dry-run' in sys.argv
    with open(RULES, encoding='utf-8') as f:
        doc = json.load(f)

    rules = doc['rules']
    specs = hook_specs()

    changed_nb = 0
    changed_hk = 0
    for r in rules:
        rid = r.get('rule_id')
        if rid in specs:
            r['layer'] = ['notebook', 'hook']
            r['hook'] = specs[rid]
            changed_hk += 1
        else:
            # keep any existing extra keys, only ensure layer is present
            if r.get('layer') != ['notebook']:
                r['layer'] = ['notebook']
            changed_nb += 1

    # validate every hook regex compiles before we write anything
    errs = []
    for r in rules:
        h = r.get('hook')
        if not h:
            continue
        for key in ('any_of', 'all_of'):
            for pat in h.get(key, []):
                try:
                    re.compile(pat)
                except re.error as e:
                    errs.append('%s %s: %r -> %s' % (r['rule_id'], key, pat[:50], e))
    if errs:
        print('REGEX COMPILE FAILED:')
        for e in errs:
            print('  ' + e)
        sys.exit(1)
    print('regex validation: all patterns compile OK')

    doc['last_updated'] = datetime.datetime.now().astimezone().isoformat(timespec='seconds')
    doc.setdefault('_schema', {})
    doc['_schema'].update({
        'layer': 'notebook = agent reads on demand; hook = machine-enforced gate',
        'hook.tools': 'DSH/Claude tool names this gate matches (PreToolUse matcher subject)',
        'hook.fields': 'tool_input sub-keys scanned',
        'hook.any_of': 'block if ANY regex matches',
        'hook.all_of': 'block only if ALL regexes match',
    })

    print('notebook-only rules = %d' % changed_nb)
    print('hook-enforced rules = %d  (%s)' % (
        changed_hk, ', '.join(sorted(specs))))

    if dry:
        print('(dry-run, not written)')
        return

    shutil.copy2(RULES, RULES + '.bak_migrate_layers')
    with open(RULES, 'w', encoding='utf-8') as f:
        json.dump(doc, f, ensure_ascii=False, indent=2)
        f.write('\n')
    print('written: %s (backup: rules.json.bak_migrate_layers)' % RULES)


if __name__ == '__main__':
    main()
