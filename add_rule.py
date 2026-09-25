#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
新增死规则 / Add a Hard Rule —— Codex Hard Rules Manager

用法示例（命令行传参）：
  python add_rule.py --title 数据隐私保护 --category 安全 \
      --trigger "个人信息,密码,API key" \
      --actions "在 final 频道回复;使用绝对路径;不存储敏感信息" \
      --forbidden "猜测用户意图;自行跳过安全检查" \
      --severity high --by user

无参数运行时进入交互模式，逐个提问录入规则。
"""

import argparse
import os
import sys

# 兼容 Windows 控制台默认 GBK 编码：强制 UTF-8 输出，避免 emoji/中文报错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from utils.rule_parser import RuleParser, VALID_CATEGORIES, VALID_SEVERITIES  # noqa: E402


def _ask(prompt, default=None, required=False):
    """交互式提问。"""
    suffix = f"（默认: {default}）" if default else ""
    while True:
        val = input(f"{prompt}{suffix}: ").strip()
        if not val and default:
            return default
        if not val and required:
            print("此项不能为空，请重新输入。")
            continue
        return val


def _interactive(parser):
    print("== 新增死规则（交互模式）==")
    print(f"可用分类: {'、'.join(sorted(VALID_CATEGORIES))} | "
          f"严重级别: {'/'.join(VALID_SEVERITIES)}")
    title = _ask("规则标题", required=True)
    category = _ask("分类", default="其他")
    severity = _ask("严重级别 (high/medium/low)", default="high")
    triggers = _ask("触发关键词（逗号/顿号分隔）", default="")
    desc = _ask("详细说明", default="")
    actions = _ask("必须执行的动作（分号/逗号分隔）", default="")
    forbidden = _ask("禁止做的操作（分号/逗号分隔）", default="")
    by = _ask("创建人", default="user")

    rule = {
        "title": title,
        "category": category,
        "severity": severity,
        "trigger_keywords": triggers,
        "description": desc,
        "must_execute_actions": actions,
        "forbidden_actions": forbidden,
        "created_by": by,
    }
    return parser.add_rule(rule)


def main():
    ap = argparse.ArgumentParser(description="新增死规则（Codex Hard Rules Manager）。")
    ap.add_argument("--title", help="规则标题（必填）")
    ap.add_argument("--category", default="其他", help="分类（安全/行为/技术/其他）")
    ap.add_argument("--severity", default="high", help="严重级别（high/medium/low）")
    ap.add_argument("--trigger", help="触发关键词，逗号/顿号分隔")
    ap.add_argument("--description", default="", help="规则的详细说明")
    ap.add_argument("--actions", help="必须执行的动作，分号/逗号分隔")
    ap.add_argument("--forbidden", help="禁止做的操作，分号/逗号分隔")
    ap.add_argument("--by", default="user", help="创建人名称")
    args = ap.parse_args()

    parser = RuleParser()

    # 无参数 -> 交互模式
    if not args.title:
        _interactive(parser)
        return

    if args.category not in VALID_CATEGORIES:
        print(f"警告：分类 '{args.category}' 不在默认范围内，已按原样保存。"
              f"建议使用：{'、'.join(sorted(VALID_CATEGORIES))}")

    rule = {
        "title": args.title,
        "category": args.category,
        "severity": args.severity,
        "trigger_keywords": args.trigger or "",
        "description": args.description,
        "must_execute_actions": args.actions or "",
        "forbidden_actions": args.forbidden or "",
        "created_by": args.by,
    }
    parser.add_rule(rule)


if __name__ == "__main__":
    main()
