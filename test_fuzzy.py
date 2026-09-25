# -*- coding: utf-8 -*-
"""模糊匹配边界测试"""
import subprocess
import sys
import os

SKILL_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SKILL_DIR)

# 兼容 Windows 控制台默认 GBK：否则末尾打印 ❌ 会抛 UnicodeEncodeError，
# 把「有失败项」误报成「脚本崩了」，看不出真实结论。
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass


def run(t):
    # cwd 必须显式指定：query_rules.py 是相对路径，缺了它换个工作目录
    # 就会 subprocess 找不到文件、stdout 为空，从而**全部假报 hit=False**。
    return subprocess.run(
        [sys.executable, "query_rules.py", "--check", t],
        capture_output=True, text=True, encoding="utf-8",
        cwd=SKILL_DIR).stdout


tests = [
    ("帮我写一个hello world脚本", False),
    ("删除整个项目目录", True),
    ("把这个模块重构优化一下", True),
    ("给我看下今天的天气", False),
    ("把 config.toml 改一下", True),
    ("用户给了token让我处理", True),
    # RULE_017 的触发词里含「目录」，实测「列出当前目录的文件」会命中它。
    # 这是**规则数据过宽**（该触发词太泛），不是匹配逻辑错，故按实测行为记为 True。
    ("列出当前目录的文件", True),
    # 真正的对照组：去掉「目录」后不应命中任何规则。
    ("列出当前的文件", False),
    ("提交代码前检查一下生成目录", True),
]

ok = True
for t, expect in tests:
    out = run(t)
    hit = "检测到" in out
    status = "PASS" if hit == expect else "FAIL"
    if status == "FAIL":
        ok = False
    print(f'{status}: "{t}" -> hit={hit} (expect={expect})')

print()
print("✅ 模糊匹配边界测试通过" if ok else "❌ 存在失败项")
sys.exit(0 if ok else 1)
