#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Codex 适配器。

产出 Codex `config.toml` 的 **TOML 片段**。Codex 的 MCP 配置是表格形式
（`[mcp_servers.<name>]` + `[mcp_servers.<name>.env]`），用单引号字面量串
承载 Windows 路径，避免反斜杠转义问题。
"""

import os

try:
    from . import _common as common
except ImportError:
    import _common as common

SERVER_KEY = "agent-hard-rules"

TEMPLATE = (
    "[mcp_servers.%(key)s]\n"
    "command = '%(python)s'\n"
    "args = ['%(root)s/%(server_rel)s']\n"
    "startup_timeout_sec = 30\n"
    "enabled = true\n"
    "\n"
    "[mcp_servers.%(key)s.env]\n"
    "HARD_RULES_FILE = '%(root)s/%(rules_rel)s'\n"
    "PYTHONPATH = '%(root)s'\n"
)

SECTION_HEADER = "[mcp_servers.%s]" % SERVER_KEY


def build(python_exe, project_root):
    """生成待追加进 config.toml 的 TOML 片段（字符串）。"""
    return TEMPLATE % {
        "key": SERVER_KEY,
        "python": common.fwd(python_exe),
        "root": common.fwd(project_root),
        "server_rel": common.MCP_SERVER_REL,
        "rules_rel": common.RULES_REL,
    }


def target(project_root, home):
    """Codex 的配置文件路径。

    home 默认为用户主目录，即 <home>/.codex/config.toml。若你把 CODEX_HOME 指到了
    别处，请把 --home 指到该目录的**父目录**。
    """
    return common.join_fwd(home, ".codex", "config.toml")


def install(python_exe, project_root, home, dry_run=False):
    """幂等地把 TOML 片段追加进 config.toml。

    已存在同名小节时**不覆盖**：完全相同则报“已是最新”，不同则提示用户手工核对，
    避免踩掉用户自己调整过的配置。
    """
    fragment = build(python_exe, project_root)
    path = target(project_root, home)
    existing = common.read_text(path)

    lines = ["[codex] config: %s" % path]

    if existing is None:
        lines.append("  状态: 目标文件不存在")
        if dry_run:
            action = "[dry-run] 将新建 config.toml 并写入片段"
        else:
            common.write_atomic(path, fragment)
            action = "已新建并写入片段"
    elif SECTION_HEADER not in existing:
        lines.append("  状态: 已存在 config.toml，但未安装本 MCP")
        if dry_run:
            action = "[dry-run] 将在文件末尾追加片段，写入前备份原文件"
        else:
            bak = common.backup(path)
            current = existing if existing.endswith("\n") else existing + "\n"
            common.write_atomic(path, current + "\n" + fragment)
            action = "已追加片段（备份 -> %s）" % bak
    elif fragment.strip() in existing:
        lines.append("  状态: 已安装且内容一致")
        action = "未变更（幂等，不重复插入）"
    else:
        lines.append("  状态: 已存在 %s 段，但内容与本次生成不同" % SECTION_HEADER)
        action = "未变更（拒绝覆盖已有小节；如需更新请手工替换该段后重跑）"

    lines.append("  动作: %s" % action)
    lines.append("  片段:")
    lines.append(common.indent_block(fragment))
    return "\n".join(lines)


if __name__ == "__main__":
    print(build("python", os.getcwd()))
