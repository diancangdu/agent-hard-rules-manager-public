#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""HardRules 多 agent 安装器 —— 统一入口。

用法：
    python installers/install.py --agent dsh|codex|claude-code|generic
                                 [--home <dir>] [--python <exe>]
                                 [--project-root <dir>]
                                 [--dry-run | --apply]
                                 [--allow-profile-write] [--absolute-python]

默认 --dry-run：只打印将要做的事与完整配置片段，不落盘。
--apply 才真正写入，且写入前一律 .bak_<timestamp> 备份、合并而非覆盖、可重复运行。

边界说明：DSH 的 profile（cordis.patch.yml）由主 agent 统一部署，因此即使 --apply，
也需要额外显式加 --allow-profile-write 才会由本安装器写入。
"""

import argparse
import json
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT_DEFAULT = os.path.dirname(HERE)
sys.path.insert(0, PROJECT_ROOT_DEFAULT)

from adapters import ADAPTERS  # noqa: E402
from adapters import _common as common  # noqa: E402

# 依次尝试的 Python 解释器（sys.executable / PATH 之外的本机常见安装位）
PYTHON_CANDIDATES = (
    "D:\\Python\\python3.14.7\\python.exe",
    "F:\\Anaconda3\\python.exe",
)

REQUIRED_FILES = (
    common.MCP_SERVER_REL,
    common.RULES_REL,
    common.HOOKS_REL,
    common.GUARD_REL,
)


def fwd(path):
    return os.path.abspath(path).replace("\\", "/")


# --------------------------------------------------------------------------- #
# Python 解释器探测
# --------------------------------------------------------------------------- #

def detect_python(explicit=None):
    """探测可用的 Python 解释器绝对路径。"""
    if explicit:
        if not os.path.isfile(explicit):
            raise SystemExit("错误：--python 指定的解释器不存在：%s" % explicit)
        return fwd(explicit)

    candidates = [sys.executable, shutil.which("python"), shutil.which("python.exe")]
    candidates.extend(PYTHON_CANDIDATES)
    for cand in candidates:
        if cand and os.path.isfile(cand):
            return fwd(cand)
    raise SystemExit("错误：未探测到 Python 解释器，请用 --python <exe> 显式指定。")


# --------------------------------------------------------------------------- #
# hooks.json 维护（支持把 python 替换为绝对解释器路径）
# --------------------------------------------------------------------------- #

def _guard_command(python_token):
    """拼出 hooks.json 里调用守卫脚本的 command。

    ${CLAUDE_PLUGIN_ROOT} 由 DSH 的 hooks-claude-code 桥接在解析配置时替换。
    """
    return '%s "${CLAUDE_PLUGIN_ROOT}/%s"' % (python_token, common.GUARD_REL)


def _hooks_payload(python_token):
    return {
        "hooks": {
            "PreToolUse": [
                {
                    "matcher": common.HOOK_MATCHER,
                    "hooks": [
                        {
                            "type": "command",
                            "command": _guard_command(python_token),
                            "timeout": 30,
                        }
                    ],
                }
            ]
        }
    }


def ensure_hooks_json(project_root, python_exe, dry_run, absolute_python):
    """确保 hooks/hooks.json 存在；--absolute-python 时把解释器换成绝对路径。"""
    path = fwd(os.path.join(project_root, common.HOOKS_REL))
    token = '"%s"' % fwd(python_exe) if absolute_python else "python"
    wanted = json.dumps(_hooks_payload(token), ensure_ascii=False) + "\n"

    lines = ["[hooks.json] %s" % path]

    if not os.path.exists(path):
        if dry_run:
            lines.append("   状态: 不存在；[dry-run] 将按下面的内容创建")
        else:
            common.write_atomic(path, wanted)
            lines.append("   状态: 已创建")
    else:
        current = common.read_text(path) or ""
        if absolute_python:
            existing = common.load_json(path)
            existing_hooks = existing.get("hooks", {}).get("PreToolUse", [])
            commands = [
                h.get("command", "")
                for entry in existing_hooks
                for h in entry.get("hooks", [])
            ]
            if any(c.startswith('"%s"' % fwd(python_exe)) for c in commands):
                lines.append("   状态: 已指向绝对解释器 %s，未变更（幂等）" % fwd(python_exe))
            elif dry_run:
                lines.append("   状态: [dry-run] 将把 command 的 python 换成 %s" % fwd(python_exe))
            else:
                bak = common.backup(path)
                common.write_atomic(path, wanted)
                lines.append(
                    "   状态: 已替换解释器为 %s（备份 -> %s）" % (fwd(python_exe), bak)
                )
        else:
            lines.append("   状态: 已存在，保持原样（未加 --absolute-python，不做替换）")

    lines.append("   内容: %s" % wanted.strip())
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
# 环境自检
# --------------------------------------------------------------------------- #

def check_project(project_root):
    """检查项目必备文件是否齐全，返回报告行列表与缺失项数量。"""
    lines = ["[自检] 项目根: %s" % fwd(project_root)]
    missing = 0
    for rel in REQUIRED_FILES:
        path = os.path.join(project_root, rel)
        if os.path.isfile(path):
            lines.append("   OK      %s" % rel)
        else:
            missing += 1
            lines.append("   缺失 !! %s" % rel)
    return lines, missing


# --------------------------------------------------------------------------- #
# 主流程
# --------------------------------------------------------------------------- #

def build_parser():
    parser = argparse.ArgumentParser(
        prog="install.py",
        description="为 HardRules 生成/安装各 agent 的 MCP 与 hooks 配置（默认 dry-run）。",
    )
    parser.add_argument(
        "--agent", required=True, choices=sorted(ADAPTERS), help="目标 agent"
    )
    parser.add_argument(
        "--home",
        default=None,
        help="agent 配置根目录（默认用户主目录；codex 用 <home>/.codex/config.toml）",
    )
    parser.add_argument("--python", default=None, help="Python 解释器绝对路径（默认自动探测）")
    parser.add_argument(
        "--project-root",
        default=PROJECT_ROOT_DEFAULT,
        help="HardRules 项目根（默认 installers/ 的上级目录）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印，不落盘（默认行为）")
    parser.add_argument("--apply", action="store_true", help="真正写入配置")
    parser.add_argument(
        "--allow-profile-write",
        action="store_true",
        help="仅 dsh：允许直接写入 cordis.patch.yml（默认不写，交由主 agent 部署）",
    )
    parser.add_argument(
        "--absolute-python",
        action="store_true",
        help="把 hooks/hooks.json 里的 python 替换为探测到的绝对解释器路径",
    )
    return parser


def main(argv=None):
    args = build_parser().parse_args(argv)

    if args.apply and args.dry_run:
        raise SystemExit("错误：--apply 与 --dry-run 不能同时使用。")
    apply_changes = bool(args.apply)
    dry_run = not apply_changes

    project_root = os.path.abspath(args.project_root)
    home = os.path.abspath(args.home) if args.home else os.path.expanduser("~")
    python_exe = detect_python(args.python)
    adapter = ADAPTERS[args.agent]

    print("=" * 72)
    print("HardRules 安装器  agent=%s  模式=%s" % (args.agent, "APPLY" if apply_changes else "DRY-RUN"))
    print("=" * 72)
    print("[参数] project_root : %s" % fwd(project_root))
    print("[参数] home         : %s" % fwd(home))
    print("[参数] python       : %s" % python_exe)
    print("[参数] 目标配置     : %s" % adapter.target(project_root, home))
    print("")

    check_lines, missing = check_project(project_root)
    for line in check_lines:
        print(line)
    if missing:
        print("[自检] 警告：有 %d 个必备文件缺失，配置生成可能指向不存在的文件。" % missing)
    print("")

    print(ensure_hooks_json(project_root, python_exe, dry_run, args.absolute_python))
    print("")

    if args.agent == "dsh":
        report = adapter.install(
            python_exe,
            project_root,
            home,
            dry_run=dry_run,
            write_profile=args.allow_profile_write,
        )
    else:
        report = adapter.install(python_exe, project_root, home, dry_run=dry_run)
    print(report)
    print("")

    if dry_run:
        print("提示：当前为 dry-run，未写入任何文件。确认无误后加 --apply 执行。")
    else:
        print("完成：已按上述动作处理（如需回滚，使用同目录下的 .bak_<timestamp> 备份）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
