#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""DSH（DeepSeek Harness）适配器。

产出 DSH profile patch 用的 **YAML 片段**，不自行写入任何文件。

DSH 的 profile patch 文件 `cordis.patch.yml` 是**顶层 YAML 数组**，因此新增内容
用 `- insert:` 包一个行列表。字段名与取值来自已验证的真实 schema，勿改。

注意：DSH 的 profile 由主 agent 统一部署，本适配器的 install() 默认**只生成片段并
打印**，只有在显式传入 write_profile=True 时才真正追加到 profile 文件。
"""

import os

try:  # 作为包导入（import adapters.dsh）
    from . import _common as common
except ImportError:  # 直接以脚本方式运行（python adapters/dsh.py）
    import _common as common

MCP_ID = "agent-hard-rules-mcp"
HOOKS_ID = "agent-hard-rules-hooks"

# 顶层是数组，所以每行都必须以 "- " 开头；缩进 4 空格对齐 insert 下的列表项。
TEMPLATE = (
    "- insert:\n"
    "    - id: %(mcp_id)s\n"
    "      name: '@deepseek-ai/dsh-mcp-client'\n"
    "      config:\n"
    "        transport: 'stdio'\n"
    "        serverName: '%(server)s'\n"
    "        command: '%(python)s'\n"
    "        args: ['%(root)s/%(server_rel)s']\n"
    "        env: {HARD_RULES_FILE: '%(root)s/%(rules_rel)s'}\n"
    "        cwd: '%(root)s'\n"
    "        toolCallTimeoutMs: 30000\n"
    "        failOnStartupError: false\n"
    "    - id: %(hooks_id)s\n"
    "      name: '@deepseek-ai/dsh-hooks-claude-code'\n"
    "      config:\n"
    "        configPath: '%(root)s/%(hooks_rel)s'\n"
    "        pluginRoot: '%(root)s'\n"
    "        projectDir: '%(root)s'\n"
    "        defaultTimeoutMs: 30000\n"
)


def build(python_exe, project_root):
    """生成待合并进 cordis.patch.yml 的 YAML 片段（字符串）。"""
    root = common.fwd(project_root)
    return TEMPLATE % {
        "mcp_id": MCP_ID,
        "hooks_id": HOOKS_ID,
        "server": common.SERVER_NAME,
        "python": common.fwd(python_exe),
        "root": root,
        "server_rel": common.MCP_SERVER_REL,
        "rules_rel": common.RULES_REL,
        "hooks_rel": common.HOOKS_REL,
    }


def target(project_root, home):
    """DSH 的 profile patch 文件绝对路径。"""
    return common.join_fwd(home, ".dsh", "profiles", "desktop", "cordis.patch.yml")


def install(python_exe, project_root, home, dry_run=False, write_profile=False):
    """幂等地把片段追加进 DSH profile。

    默认 write_profile=False —— 只报告状态并打印完整片段，不落盘（profile 由主 agent
    统一部署）。显式写需同时满足 write_profile=True 且 dry_run=False。
    """
    fragment = build(python_exe, project_root)
    path = target(project_root, home)
    existing = common.read_text(path)

    if existing is None:
        state = "目标文件不存在"
        installed = False
    elif MCP_ID in existing:
        state = "已安装（检测到 %s）" % MCP_ID
        installed = True
    else:
        state = "目标文件存在但未安装"
        installed = False

    lines = ["[dsh] profile: %s" % path, "  状态: %s" % state]

    if installed:
        lines.append("  动作: 未变更（幂等，不重复插入）")
    elif not write_profile:
        lines.append(
            "  动作: 跳过写入（默认不写 DSH profile；"
            "如需本安装器直接写入请加 --allow-profile-write）"
        )
        lines.append("  部署: 请把下面的片段交给主 agent，由其合并进 cordis.patch.yml")
    elif dry_run:
        lines.append("  动作: [dry-run] 将在文件末尾追加片段，写入前备份原文件")
    else:
        bak = common.backup(path)
        current = existing or ""
        if current and not current.endswith("\n"):
            current += "\n"
        common.write_atomic(path, current + fragment)
        lines.append("  动作: 已追加片段%s" % ("（备份 -> %s）" % bak if bak else "（新建文件）"))

    lines.append("  片段:")
    lines.append(common.indent_block(fragment))
    return "\n".join(lines)


if __name__ == "__main__":  # 便于人工自检
    print(build("python", os.getcwd()))
