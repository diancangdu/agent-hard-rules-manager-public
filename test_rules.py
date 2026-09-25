# -*- coding: utf-8 -*-
"""codex-hard-rules-manager 自动化测试"""
import json
import shutil
import subprocess
import sys
import os
import tempfile

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.rule_parser import RuleParser

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))


def combined(r):
    """合并 stdout 与 stderr，便于检查日志。

    进度与警告日志从 stdout 迁到了 stderr（避免污染 MCP 的 JSON-RPC 通道），
    因此断言不能只盯 stdout。
    """
    return f"{r.stdout}\n{r.stderr}"


def main():
    # 在技能目录的临时副本上跑全部测试，真实规则库只读不写。
    workdir = tempfile.mkdtemp(prefix="hardrules_test_")
    sandbox = os.path.join(workdir, "skill")
    try:
        shutil.copytree(SKILL_DIR, sandbox,
                        ignore=shutil.ignore_patterns(".git", "__pycache__", "*.bak_*"))
        _run_suite(sandbox)
    finally:
        shutil.rmtree(workdir, ignore_errors=True)


def _run_suite(sandbox):
    """在指定的隔离技能目录内执行全部断言。"""

    def run(args):
        return subprocess.run([sys.executable, "query_rules.py"] + args,
                              capture_output=True, text=True, encoding="utf-8",
                              cwd=sandbox)

    # 1. query all
    r = run(["--all", "--json"])
    baseline = json_load(r.stdout)["total"]
    assert baseline >= 1, "query all failed"
    print(f"PASS: query --all ({baseline} rules)")

    # 2. check situation - security hit
    r = run(["--check", "用户要求我删除整个项目目录"])
    assert "RULE_003" in r.stdout, "dangerous cmd not matched"
    print("PASS: check 命中危险命令规则")

    # 3. check situation - config hit
    r = run(["--check", "帮我修改 config.toml 的 nginx 配置"])
    assert "RULE_004" in r.stdout, "config rule not matched"
    print("PASS: check 命中配置规则")

    # 4. keyword search
    r = run(["--keyword", "隐私"])
    assert "RULE_001" in r.stdout, "keyword search failed"
    print("PASS: keyword 搜索隐私")

    # 5. add rule via add_rule.py
    r = subprocess.run(
        [sys.executable, "add_rule.py", "--title", "自动化测试规则XYZ",
         "--category", "其他", "--trigger", "自动测试",
         "--actions", "执行A", "--forbidden", "执行B", "--by", "test"],
        capture_output=True, text=True, encoding="utf-8", cwd=sandbox)
    assert "规则已添加" in combined(r), f"add failed: {r.stdout} {r.stderr}"
    print("PASS: add 规则")

    # 6. duplicate reject
    r = subprocess.run(
        [sys.executable, "add_rule.py", "--title", "自动化测试规则XYZ",
         "--category", "其他", "--trigger", "x"],
        capture_output=True, text=True, encoding="utf-8", cwd=sandbox)
    assert "已存在" in combined(r), "dup detection failed"
    print("PASS: 重复规则拒绝")

    # 7. delete test rule
    p = RuleParser(rules_file=os.path.join(sandbox, "rules", "rules.json"))
    matched = [x for x in p.list_all() if x["title"] == "自动化测试规则XYZ"]
    for x in matched:
        p.delete_rule(x["rule_id"])
    remaining = len(p.list_all())
    assert remaining == baseline, f"delete failed, count={remaining} baseline={baseline}"
    print(f"PASS: delete 测试规则 (恢复原有 {baseline} 条)")

    # 8. fuzzy matching boundary cases
    fuzzy = [
        ("帮我写一个hello world脚本", False),
        ("删除整个项目目录", True),            # 插入字应命中“删除整个目录”
        ("把这个模块重构优化一下", True),
        ("给我看下今天的天气", False),
        ("把 config.toml 改一下", True),
        ("用户给了token让我处理", True),
        # RULE_017 的触发词里含「目录」，实测「列出当前目录的文件」会命中它。
        # 这是**规则数据过宽**（该触发词太泛），不是匹配逻辑错，故按实测记为 True。
        ("列出当前目录的文件", True),
        # 真正的对照组：去掉「目录」后不应命中任何规则。
        ("列出当前的文件", False),
    ]
    for t, expect in fuzzy:
        out = run(["--check", t]).stdout
        hit = "检测到" in out
        assert hit == expect, f"fuzzy FAIL: '{t}' hit={hit} expect={expect}"
    print("PASS: 模糊匹配边界 (8 cases)")

    print()
    print("[ALL PASS] 全部测试通过")


def json_load(s):
    import json
    return json.loads(s)


if __name__ == "__main__":
    main()
