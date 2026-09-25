#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""通用 MCP 适配器。

产出最标准的 `{"mcpServers": {...}}` JSON —— 多数支持 MCP 的客户端
（Cursor / Windsurf / Cline / Continue 等）都能直接读这一段。

与 claude_code 的区别：不带 `type` 等客户端私有字段，只保留 MCP 约定字段
command / args / env / cwd，保证各家都能解析。
"""

import os

try:
    from . import _common as common
except ImportError:
    import _common as common


def build(python_exe, project_root):
    """生成标准 MCP JSON 结构（dict）。"""
    root = common.fwd(project_root)
    return {
        "mcpServers": {
            common.SERVER_NAME: {
                "command": common.fwd(python_exe),
                "args": [root + "/" + common.MCP_SERVER_REL],
                "env": {
                    "HARD_RULES_FILE": root + "/" + common.RULES_REL,
                    "PYTHONPATH": root,
                },
                "cwd": root,
            }
        }
    }


def target(project_root, home):
    """落盘位置：<home>/.hard-rules/mcp.json（不与非通用客户端的配置互相踩）。"""
    return common.join_fwd(home, ".hard-rules", "mcp.json")


def install(python_exe, project_root, home, dry_run=False):
    """幂等地把标准 MCP 段合并进目标 JSON（保留用户已有键）。"""
    path = target(project_root, home)
    snippet = build(python_exe, project_root)
    current = common.load_json(path) if os.path.exists(path) else {}
    merged = common.deep_merge(current, snippet)

    lines = ["[generic] 目标文件: %s" % path]
    if merged == current:
        lines.append("  状态: 已是最新，未变更（幂等）")
    elif dry_run:
        lines.append("  状态: [dry-run] 将合并 mcpServers 段，写入前备份原文件")
    else:
        bak = common.backup(path)
        common.write_atomic(path, common.dump_json(merged))
        lines.append("  状态: 已合并%s" % ("（备份 -> %s）" % bak if bak else "（新建文件）"))

    lines.append("  用法: 把下面的 mcpServers 段拷进你的客户端配置文件")
    lines.append("  片段:")
    lines.append(common.indent_block(common.dump_json(snippet)))
    return "\n".join(lines)


if __name__ == "__main__":
    import json

    print(json.dumps(build("python", os.getcwd()), ensure_ascii=False, indent=2))
