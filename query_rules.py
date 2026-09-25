#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
查询死规则 / Query Hard Rules —— Codex Hard Rules Manager

用法示例：
  python query_rules.py --all                          # 列出全部规则
  python query_rules.py --keyword 密码                 # 按关键词搜索
  python query_rules.py --keyword 安全,隐私            # 多关键词（命中任一）
  python query_rules.py --category 安全                # 按分类筛选
  python query_rules.py --rule-id RULE_001             # 查看单条规则详情
  python query_rules.py --check "当前场景/任务描述"     # 场景匹配（核心用法）
  python query_rules.py --json --keyword 密码          # 输出原始 JSON（供程序解析）
"""

import argparse
import json
import os
import sys

# 兼容 Windows 控制台默认 GBK 编码：强制 UTF-8 输出，避免 emoji/中文报错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.rule_parser import RuleParser  # noqa: E402


def _print_human(rules):
    if not rules:
        print("未匹配到任何规则。")
        return
    print(f"共 {len(rules)} 条规则：")
    print("-" * 60)
    for rule in rules:
        print(RuleParser.format_rule(rule))
        print("-" * 60)


def main():
    ap = argparse.ArgumentParser(
        description="查询死规则库（Codex Hard Rules Manager）。"
    )
    grp = ap.add_mutually_exclusive_group()
    grp.add_argument("--all", action="store_true", help="列出全部规则")
    grp.add_argument("--keyword", metavar="K", help="按关键词搜索（可用逗号分隔多个词）")
    grp.add_argument("--rule-id", metavar="ID", help="查看指定规则详情，如 RULE_001")
    grp.add_argument("--check", metavar="TEXT", help="场景匹配：把当前情况与所有死规则比对")
    ap.add_argument("--category", metavar="C", help="按分类筛选（安全/行为/技术/其他）")
    ap.add_argument("--json", action="store_true", help="以 JSON 格式输出（便于程序解析）")
    args = ap.parse_args()

    parser = RuleParser()

    # 场景匹配（核心用法）
    if args.check:
        matched = parser.check_situation(args.check)
        meta = parser.is_self_inspection(args.check)
        if args.json:
            print(json.dumps({"matched": matched, "total": len(matched),
                              "mode": "self_inspection" if meta else "situation",
                              "total_rules_in_notebook": len(parser.list_all())},
                             ensure_ascii=False, indent=2))
        elif meta:
            # 元查询：问的是规则库自身，返回的是全量，并非「命中某条规则」
            print(f"ℹ 自省查询：返回全量规则库（{len(matched)} 条）。")
            print("=" * 60)
            for rule in matched:
                print(RuleParser.format_rule(rule))
                print("=" * 60)
        elif not matched:
            # 明确区分「没命中」与「库是空的」：否则措辞不匹配会被读成没有规则
            print(f"⚠ 未匹配到任何死规则 —— 注意：这不代表规则库为空，"
                  f"库中共有 {len(parser.list_all())} 条。")
            print("   --check 只做关键词匹配；要看全量请用 --all。")
        else:
            print(f"⛔ 检测到 {len(matched)} 条死规则命中 —— 必须严格按规则执行，"
                  f"不得有侥幸心理！")
            print("=" * 60)
            for rule in matched:
                print(RuleParser.format_rule(rule))
                print("=" * 60)
        return

    # 单条规则
    if args.rule_id:
        rule = parser.get_rule(args.rule_id)
        if args.json:
            print(json.dumps(rule, ensure_ascii=False, indent=2) if rule
                  else json.dumps({"error": f"未找到规则 {args.rule_id}"},
                                  ensure_ascii=False))
        elif rule:
            print(RuleParser.format_rule(rule))
        else:
            print(f"未找到规则：{args.rule_id}")
        return

    # 分类 / 关键词 / 全部
    rules = parser.query_rules(keyword=args.keyword, category=args.category)
    if args.all and not args.keyword and not args.category:
        rules = parser.list_all()

    if args.json:
        print(json.dumps({"rules": rules, "total": len(rules)},
                         ensure_ascii=False, indent=2))
    else:
        _print_human(rules)


if __name__ == "__main__":
    main()
