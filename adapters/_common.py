# -*- coding: utf-8 -*-
"""适配器共享底层工具（纯标准库）。

只做四件事：路径规范化、写前备份、原子写入、JSON 深合并。
面向各 agent 的配置生成逻辑放在各自的适配器模块里，此文件不生成任何配置。
"""

import json
import os
import shutil
import sys
from datetime import datetime

# 兼容 Windows 控制台默认 GBK：避免中文/emoji 输出直接抛异常
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# 各 agent 共享的常量（serverName 需匹配 [A-Za-z0-9_-]{1,32}）
SERVER_NAME = "hard_rules"
MCP_SERVER_REL = "tools/hard_rules_mcp_server.py"
RULES_REL = "rules/rules.json"
HOOKS_REL = "hooks/hooks.json"
GUARD_REL = "hooks/scripts/pretooluse_guard.py"
HOOK_MATCHER = "bash|pwsh|write|edit|str_replace_editor"


def fwd(path):
    """规范化为绝对路径 + 正斜杠。

    正斜杠在 Windows 上同样合法，且能避开 YAML/TOML 单引号串里的转义歧义。
    """
    return os.path.abspath(path).replace("\\", "/")


def join_fwd(*parts):
    """拼接路径片段并规范化。"""
    return fwd(os.path.join(*parts))


def stamp():
    """备份文件名用的时间戳。"""
    return datetime.now().strftime("%Y%m%d_%H%M%S")


def read_text(path):
    """读取文本；文件不存在返回 None。"""
    if not os.path.exists(path):
        return None
    with open(path, "r", encoding="utf-8") as fh:
        return fh.read()


def ensure_dir(path):
    """确保目标文件所在目录存在，返回新建的目录（已存在则 None）。"""
    folder = os.path.dirname(os.path.abspath(path))
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
        return folder
    return None


def backup(path):
    """覆盖已有文件前先留一份 <name>.bak_<timestamp>；返回备份路径或 None。"""
    if not os.path.exists(path):
        return None
    dest = "%s.bak_%s" % (path, stamp())
    shutil.copy2(path, dest)
    return dest


def write_atomic(path, text):
    """同目录临时文件 + os.replace，避免写一半崩溃损坏配置。"""
    ensure_dir(path)
    tmp = "%s.tmp_%s" % (path, stamp())
    with open(tmp, "w", encoding="utf-8", newline="\n") as fh:
        fh.write(text)
    os.replace(tmp, path)


def load_json(path):
    """读取 JSON 对象；文件缺失或为空时返回 {}。"""
    raw = read_text(path)
    if not raw or not raw.strip():
        return {}
    return json.loads(raw)


def dump_json(obj):
    """统一的 JSON 落盘格式：UTF-8、不转义中文、2 空格缩进、结尾换行。"""
    return json.dumps(obj, ensure_ascii=False, indent=2) + "\n"


def deep_merge(base, addition):
    """把 addition 合并进 base 的副本。

    - dict：递归合并
    - list：取并集（保留原有顺序，只追加缺失项）——保证“只追加、不覆盖”
    - 标量：以 addition 为准
    """
    if isinstance(base, dict) and isinstance(addition, dict):
        out = dict(base)
        for key, value in addition.items():
            out[key] = deep_merge(out[key], value) if key in out else value
        return out
    if isinstance(base, list) and isinstance(addition, list):
        out = list(base)
        for item in addition:
            if item not in out:
                out.append(item)
        return out
    return addition


def indent_block(text, prefix="    "):
    """把多行文本整体缩进，便于在报告里贴片段。"""
    return "\n".join(prefix + line for line in text.splitlines())
