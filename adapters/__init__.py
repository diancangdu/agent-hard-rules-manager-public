# -*- coding: utf-8 -*-
"""多 agent 适配层。

每个适配器模块都提供统一的三件套：

    build(python_exe, project_root) -> str | dict   # 生成配置片段（不落盘）
    target(project_root, home)      -> str          # 目标配置文件绝对路径
    install(python_exe, project_root, home, dry_run=False) -> str  # 幂等写入 + 报告

统一入口见 installers/install.py。
"""

from . import claude_code, codex, dsh, generic_mcp

ADAPTERS = {
    "dsh": dsh,
    "codex": codex,
    "claude-code": claude_code,
    "generic": generic_mcp,
}

__all__ = ["ADAPTERS", "dsh", "codex", "claude_code", "generic_mcp"]
