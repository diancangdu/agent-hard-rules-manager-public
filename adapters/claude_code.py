#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Claude Code 适配器。

产出两样东西：
  1. `.mcp.json`                 —— {"mcpServers": {...}}，项目级 MCP 配置
  2. `.claude/settings.json` 里的 hooks 段 —— 把 PreToolUse 拦截器合并进去

两个文件都是**项目级**（相对 project_root），因此 target() 不使用 home 参数，
保留它是为了和其它适配器保持统一签名。
"""

import os

try:
    from . import _common as common
except ImportError:
    import _common as common


def build(python_exe, project_root):
    """生成 .mcp.json 的内容（dict）。"""
    root = common.fwd(project_root)
    return {
        "mcpServers": {
            common.SERVER_NAME: {
                "type": "stdio",
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


def build_hooks(python_exe, project_root):
    """生成要合并进 .claude/settings.json 的 hooks 结构（dict）。

    settings.json 拿不到 ${CLAUDE_PLUGIN_ROOT} 替换，所以这里用绝对路径调用守卫脚本。
    守卫脚本内部靠 __file__ 反推项目根，因此绝对路径是安全且自足的。
    """
    guard = common.fwd(os.path.join(common.fwd(project_root), common.GUARD_REL))
    command = '"%s" "%s"' % (common.fwd(python_exe), guard)
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": common.HOOK_MATCHER,
                    "hooks": [
                        {"type": "command", "command": command, "timeout": 30}
                    ],
                }
            ]
        }
    }


def target(project_root, home):
    """项目级 MCP 配置文件绝对路径。"""
    return common.join_fwd(project_root, ".mcp.json")


def settings_target(project_root):
    """项目级 settings.json 绝对路径。"""
    return common.join_fwd(project_root, ".claude", "settings.json")


def merge_hooks(python_exe, project_root, dry_run=False):
    """幂等合并 hooks 到 .claude/settings.json（保留用户原有设置与既有 hooks）。"""
    path = settings_target(project_root)
    current = common.load_json(path) if os.path.exists(path) else {}
    merged = common.deep_merge(current, build_hooks(python_exe, project_root))

    lines = ["   hooks 文件: %s" % path]
    if merged == current:
        lines.append("   hooks 状态: 已是最新，未变更（幂等）")
        return "\n".join(lines)
    if dry_run:
        lines.append("   hooks 状态: [dry-run] 将合并 hooks 段，写入前备份原文件")
        return "\n".join(lines)

    bak = common.backup(path)
    common.write_atomic(path, common.dump_json(merged))
    lines.append("   hooks 状态: 已合并%s" % ("（备份 -> %s）" % bak if bak else "（新建文件）"))
    return "\n".join(lines)


def install(python_exe, project_root, home, dry_run=False):
    """幂等安装 .mcp.json 与 .claude/settings.json 的 hooks 段。"""
    mcp_path = target(project_root, home)
    mcp_new = build(python_exe, project_root)
    mcp_old = common.load_json(mcp_path) if os.path.exists(mcp_path) else {}
    mcp_merged = common.deep_merge(mcp_old, mcp_new)

    lines = ["[claude-code] mcp 文件: %s" % mcp_path]
    if mcp_merged == mcp_old:
        lines.append("   mcp 状态: 已是最新，未变更（幂等）")
    elif dry_run:
        lines.append("   mcp 状态: [dry-run] 将合并 mcpServers 段，写入前备份原文件")
    else:
        bak = common.backup(mcp_path)
        common.write_atomic(mcp_path, common.dump_json(mcp_merged))
        lines.append("   mcp 状态: 已合并%s" % ("（备份 -> %s）" % bak if bak else "（新建文件）"))

    lines.append(merge_hooks(python_exe, project_root, dry_run=dry_run))

    lines.append("   .mcp.json 片段:")
    lines.append(common.indent_block(common.dump_json(mcp_new)))
    return "\n".join(lines)


if __name__ == "__main__":
    import json

    cwd = os.getcwd()
    print(json.dumps(build("python", cwd), ensure_ascii=False, indent=2))
    print(json.dumps(build_hooks("python", cwd), ensure_ascii=False, indent=2))
