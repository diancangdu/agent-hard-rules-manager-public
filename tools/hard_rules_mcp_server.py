#!/usr/bin/env python3
"""Local MCP server for the agent-hard-rules notebook.

Exposes the dead-rules notebook (hard rules) as a real MCP backend so Codex can
call it through the MCP protocol instead of a bare skill folder.  All tools wrap
the existing RuleParser from utils/rule_parser.py and operate on rules/rules.json.
"""
from __future__ import annotations

import contextlib
import json
import os
import sys
from pathlib import Path

for _s in (sys.stdout, sys.stderr):
    try:
        _s.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from mcp.server.mcpserver import MCPServer
from mcp.server.mcpserver.resources import ResourceSecurity
from utils.rule_parser import RuleParser

parser = RuleParser(rules_file=str(ROOT / "rules" / "rules.json"))


def _run(fn, *args, **kwargs):
    """Call a RuleParser method with stdout redirected to stderr.

    RuleParser prints progress messages (e.g. "\u2705 \u89c4\u5219\u5df2\u6dfb\u52a0") to stdout,
    which would corrupt the MCP stdio JSON-RPC channel.  Redirecting those prints
    to stderr keeps the protocol channel clean.
    """
    with contextlib.redirect_stdout(sys.stderr):
        return fn(*args, **kwargs)

server = MCPServer(
    name="agent-hard-rules",
    title="Codex Hard Rules Manager",
    description=(
        "Dead-rules notebook: before acting on any task that may be covered by a "
        "rule, query the rule archive and follow matched rules unconditionally. "
        "No luck-based shortcuts. Users can add rules at any time."
    ),
    version="1.0.0",
    instructions=(
        "Use this server to check hard rules before acting: call check_situation "
        "with the current task/situation. If any rule matches, it MUST be followed "
        "unconditionally (no exceptions, no luck-based shortcuts). Query rules, "
        "list categories, and add new rules as requested."
    ),
)


def _serialize(rule: dict) -> dict:
    return json.loads(json.dumps(rule, ensure_ascii=False))


@server.resource("rules://notebook", name="Hard Rules Notebook",
                 description="Complete JSON of all dead rules (hard rules) in the notebook",
                 mime_type="application/json")
def rules_notebook() -> str:
    """Return the full rules archive as a JSON document."""
    return json.dumps({"rules": [_serialize(r) for r in _run(parser.list_all)]}, ensure_ascii=False, indent=2)


# 允许通过 file:// 读取的根目录（模型误用 read_mcp_resource 读文件时也能正常返回，而非报错）
# 默认包含技能目录、CODEX_HOME 与用户主目录下的 codex 目录，可用环境变量覆盖：
#   HARD_RULES_EXTRA_READ_ROOTS = 用 os.pathsep 分隔的额外允许根目录
def _default_allowed_roots() -> list[Path]:
    roots = [ROOT]
    for env_name in ("CODEX_HOME",):
        value = os.environ.get(env_name)
        if value:
            roots.append(Path(value))
    home = Path.home()
    roots.append(home / "Documents" / "codex")
    extra = os.environ.get("HARD_RULES_EXTRA_READ_ROOTS", "")
    for item in extra.split(os.pathsep):
        item = item.strip()
        if item:
            roots.append(Path(item))
    return roots


ALLOWED_FILE_ROOTS = _default_allowed_roots()


def _normalize_fs_path(raw: str) -> str:
    """file:// URI 提取的 path 形如 /D:/CodexHome/x -> 转 Windows 盘符路径"""
    p = raw
    while p.startswith("/"):
        p = p[1:]
    if len(p) >= 2 and p[1] == ":" and not p.startswith("\\\\"):
        p = p[0] + ":" + p[2:].replace("/", "\\\\")
    return p


def _safe_file_read(raw_path: str) -> str:
    """在允许根目录内安全读取文件；越权/不存在返回说明文本而非抛错。"""
    path = _normalize_fs_path(raw_path)
    try:
        real = Path(path).resolve()
    except Exception:
        return "INVALID PATH: " + raw_path
    roots = [r.resolve() for r in [ROOT] + ALLOWED_FILE_ROOTS]
    if not any(real == r or str(real).startswith(str(r) + "\\") for r in roots):
        return "ACCESS DENIED: outside allowed roots"
    if not real.exists() or not real.is_file():
        return "FILE NOT FOUND: " + path
    try:
        return real.read_text(encoding="utf-8")
    except UnicodeDecodeError:
        return "(binary or non-text file)"
    except Exception as e:
        return "READ ERROR: " + str(e)


@server.resource(
    "file://{+path}",
    name="File Reader",
    description="Read a local file by absolute path (file:// URI).",
    security=ResourceSecurity(reject_absolute_paths=False, exempt_params={"path"}),
)
def file_reader(path: str) -> str:
    return _safe_file_read(path)


@server.tool()
def list_all_rules() -> list[dict]:
    """Return every rule in the dead-rules notebook (all categories)."""
    return [_serialize(r) for r in _run(parser.list_all)]


@server.tool()
def get_rule(rule_id: str) -> dict:
    """Return one rule by its id (e.g. RULE_001)."""
    rule = _run(parser.get_rule, rule_id)
    if rule is None:
        raise ValueError(f"Rule not found: {rule_id}")
    return _serialize(rule)


@server.tool()
def list_categories() -> list[str]:
    """Return the distinct categories present in the rules archive."""
    return _run(parser.list_categories)


@server.tool()
def query_rules(keyword: str = "", category: str = "") -> list[dict]:
    """Search rules by keyword (title/description/actions) and optional category.

    Uses fuzzy matching: exact substring hit, or bigram overlap >= 0.6 (better to
    over-match than to miss a hard rule). Empty keyword returns all rules.
    """
    kw = keyword.strip() if keyword else ""
    cat = category.strip() if category else ""
    return [_serialize(r) for r in _run(parser.query_rules, kw or None, cat or None)]


@server.tool()
def check_situation(text: str) -> dict:
    """Check a task/situation against the dead-rules notebook.

    Returns `matched_rules` plus a `mode` field:
      - "situation": ordinary keyword match; `matched_rules` may be empty.
      - "self_inspection": the text asked about the notebook itself, so the
        WHOLE notebook is returned. Such a meta-query carries no rule keyword
        and would otherwise come back empty, which is indistinguishable from
        "no rule applies".

    An empty `matched_rules` NEVER means the notebook is empty - check
    `total_rules_in_notebook`, and call list_all_rules for the complete list.
    If any rule matches, it MUST be followed unconditionally - no luck-based
    shortcuts.
    """
    matched = _run(parser.check_situation, text)
    total = len(_run(parser.list_all) or [])
    self_inspection = parser.is_self_inspection(text)
    payload = {
        "mode": "self_inspection" if self_inspection else "situation",
        "matched_rules": [_serialize(r) for r in matched],
        "total_rules_in_notebook": total,
    }
    if self_inspection:
        payload["note"] = (
            "Self-inspection query detected (the text asks about the notebook "
            "itself). The COMPLETE notebook is returned so that no rule can be "
            "missed. Read every rule below."
        )
    elif not matched:
        payload["note"] = (
            "No rule matched by keyword. This does NOT mean the notebook is "
            "empty - it currently holds %d rules. check_situation only does "
            "keyword matching, so either rephrase the situation closer to a "
            "rule's trigger_keywords, or call list_all_rules for the full list."
            % total
        )
    return payload


@server.tool()
def add_rule(title: str, category: str = "general", trigger: str = "",
             actions: list[str] | None = None, forbidden: list[str] | None = None,
             severity: str = "medium") -> str:
    """Add a new hard rule to the notebook. Creates it and returns the stored rule.

    The incoming field names mirror the human-facing vocabulary (trigger/actions/
    forbidden). They are normalized to the canonical RuleParser schema
    (trigger_keywords/must_execute_actions/forbidden_actions) before saving, so
    the new rule is actually reachable by check_situation().

    Returns a JSON string so the stdio protocol never has to convert a bare
    Python object across the wire.
    """
    ok = _run(parser.add_rule, {
        "title": title,
        "category": category or "general",
        "trigger_keywords": trigger,
        "must_execute_actions": actions or [],
        "forbidden_actions": forbidden or [],
        "severity": severity or "medium",
    })
    if not ok:
        # add_rule returns False when the title already exists; surface the
        # existing rule instead of returning a misleading success payload.
        for existing in _run(parser.list_all) or []:
            if existing.get("title") == title:
                return json.dumps(
                    {"added": False, "reason": "duplicate_title",
                     "existing_rule": _serialize(existing)},
                    ensure_ascii=False, indent=2)
        return json.dumps({"added": False, "reason": "rejected"}, ensure_ascii=False)

    for existing in _run(parser.list_all) or []:
        if existing.get("title") == title:
            return json.dumps({"added": True, "rule": _serialize(existing)},
                              ensure_ascii=False, indent=2)
    return json.dumps({"added": True}, ensure_ascii=False)


@server.tool()
def delete_rule(rule_id: str) -> str:
    """Delete a rule by id. Returns a JSON string describing the outcome."""
    removed = bool(_run(parser.delete_rule, rule_id))
    return json.dumps({"rule_id": rule_id, "deleted": removed}, ensure_ascii=False)


if __name__ == "__main__":
    server.run(transport="stdio")
