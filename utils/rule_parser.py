# -*- coding: utf-8 -*-
"""
死规则解析器 / Rule Parser —— Codex Hard Rules Manager（死规则记录本）

提供基于 JSON 的死规则存储、查询、新增、更新、删除与“场景匹配”能力。
“死规则”是 Codex 必须无条件执行的强制性规则：触发即执行、禁止侥幸心理。
"""

import json
import os
import re
import sys
import tempfile
from datetime import datetime

# 兼容 Windows 控制台默认 GBK 编码：强制 UTF-8 输出，避免 emoji/中文报错
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

# 项目根目录 = 本文件所在目录的上级（utils/ -> skill 根目录）
SKILL_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_RULES_FILE = os.path.join(SKILL_ROOT, "rules", "rules.json")

VALID_CATEGORIES = {"安全", "行为", "技术", "其他"}
VALID_SEVERITIES = {"high", "medium", "low"}


def _log(message):
    """进度与警告统一写 stderr。

    stdout 可能被 MCP stdio 协议占用；任何 print 到 stdout 的日志都会破坏
    JSON-RPC 通道，所以这里从源头把诊断信息固定到 stderr。
    """
    print(message, file=sys.stderr)


def _to_list(value):
    """把各种形式的输入规范化为字符串列表：
    - 已是列表 -> 逐项拆分
    - 字符串   -> 按 分号/换行 拆分；没有这些分隔符时再按 逗号/顿号 拆分

    条目内部允许保留中文逗号（例如“包含清晰的 SKILL.md、触发条件、标准步骤”），
    否则一条说明会被错误拆成多段。
    """
    if value is None:
        return []
    if isinstance(value, list):
        items = []
        for v in value:
            items.extend(_split_text(str(v)))
        return [i for i in items if i]
    return _split_text(str(value))


def _split_text(text):
    """按层级分隔符拆分文本为条目列表。

    优先使用分号/换行作为条目分隔符；仅当文本中没有这两类分隔符时，
    才退回逗号/顿号分隔，以兼容旧的逗号串写法。对应地，中文顿号在
    文本中按“并列词”处理，不当作条目边界。
    """
    text = text.strip()
    if not text:
        return []
    if re.search(r"[;；\n\r]", text):
        parts = re.split(r"[;；\n\r]+", text)
    elif re.search(r"[,，]", text):
        parts = re.split(r"[,，]+", text)
    else:
        parts = [text]
    return [p.strip() for p in parts if p.strip()]


def _text_contains(text, keyword):
    """判断文本是否“命中”关键词。

    策略（宁多勿漏，因为漏掉死规则后果更严重）：
    1. 精确子串命中 -> True
    2. 否则做字符二元组 (bigram) 重叠度判断：关键词的二元组在文本中出现
       比例达到阈值即视为命中，用于容忍中文插入字（如“删除整个目录”
       命中“删除整个项目目录”）及英文变形（API key / API keys）。
    """
    kw = keyword.strip().lower()
    if not kw:
        return False
    if kw in text:
        return True
    # 太短的关键词（1 个字符）不做模糊匹配，避免误伤
    if len(kw) < 2:
        return False
    trigrams = [kw[i:i + 2] for i in range(len(kw) - 1)]
    if not trigrams:
        return False
    hits = sum(1 for t in trigrams if t in text)
    return hits / len(trigrams) >= 0.6


def _rule_searchable_text(rule):
    """拼接一条规则中可被检索的全部文本（用于关键词/场景匹配）。"""
    parts = [
        str(rule.get("title", "")),
        str(rule.get("description", "")),
        str(rule.get("category", "")),
        " ".join(str(k) for k in rule.get("trigger_keywords", [])),
        " ".join(str(a) for a in rule.get("must_execute_actions", [])),
        " ".join(str(a) for a in rule.get("forbidden_actions", [])),
    ]
    return " ".join(parts).lower()


# ---------------------------------------------------------------------- #
# 自省查询（self-inspection）
# ---------------------------------------------------------------------- #
# 「现在有哪些死规则？」这类元查询描述的是**规则库自身**，因此不含任何一条
# 规则的 trigger_keywords。若照普通关键词匹配走，它必然返回空 —— 而「空」
# 与「本任务不受任何规则约束」在返回体上完全无法区分，属于**静默失效**：
# 调用方会把「我问错了措辞」误读成「没有规则要守」。
#
# 所以这里单独识别，命中即返回**全量**规则（沿用本模块「宁多勿漏」原则：
# 漏掉一条死规则的代价远大于多返回几条）。
#
# 采用**两级主语**，以免把普通任务放大成全量返回：
#   · 强主语：明确指规则库自身，配任意提问/罗列标记即成立
#   · 弱主语：裸的「规则 / rules」太宽（lint 规则、validation rules），
#     只在**强提问标记**下才认
_SI_STRONG_SUBJECT = re.compile(
    r"(死规则|硬规则|规则库|规则本|规则清单|规则列表|rules\.json|hard[\s\-_]?rules?)",
    re.IGNORECASE,
)
_SI_WEAK_SUBJECT = re.compile(r"(规则|\brules?\b)", re.IGNORECASE)
# 提问 / 罗列标记（宽）
_SI_ASK = re.compile(
    r"(哪些|哪个|什么|有啥|有什么|多少|几条|几项|列出|列举|罗列|清单|一览"
    r"|全部|所有|list|show|what|which|how\s+many|enumerate)",
    re.IGNORECASE,
)
# 强提问标记（窄）：去掉「全部 / 所有」——这两个词太容易出现在普通任务里
_SI_STRONG_ASK = re.compile(
    r"(哪些|哪个|什么|有啥|有什么|多少|几条|几项|列出|列举|罗列"
    r"|list|show|what|which|how\s+many|enumerate)",
    re.IGNORECASE,
)


def is_self_inspection_query(text):
    """判断文本是在**询问规则库自身**（元查询），而不是在描述某个任务。

    判据（两级，防止误伤普通任务）：
      1. 强主语 + 任意提问标记  -> 是元查询
      2. 弱主语（裸「规则/rules」）+ **强**提问标记 -> 是元查询

    - 是元查询：「现在你的死规则有什么」「列出全部规则」「what rules do you have」
    - 不是元查询：「新增一条死规则：以后都要备份」（强主语但无提问标记）
    - 不是元查询：「把所有的 lint rules 都关掉」（弱主语，但只有弱提问词「所有」）
    """
    if not text or not text.strip():
        return False
    if _SI_STRONG_SUBJECT.search(text) and _SI_ASK.search(text):
        return True
    return bool(_SI_WEAK_SUBJECT.search(text) and _SI_STRONG_ASK.search(text))


class RuleParser:
    """JSON 规则库操作类：加载 / 保存 / 查询 / 新增 / 更新 / 删除 / 场景匹配。"""

    def __init__(self, rules_file=None):
        self.rules_file = rules_file or DEFAULT_RULES_FILE
        self._ensure_file()

    # ------------------------------------------------------------------ #
    # 基础 I/O
    # ------------------------------------------------------------------ #

    def _ensure_file(self):
        """确保规则文件存在，不存在则创建空规则库。"""
        if not os.path.exists(self.rules_file):
            os.makedirs(os.path.dirname(self.rules_file), exist_ok=True)
            self._atomic_save({"rules": [], "last_updated": self._now()})

    @staticmethod
    def _now():
        return datetime.now().astimezone().isoformat(timespec="seconds")

    def _atomic_save(self, data):
        """原子写入：先写临时文件再替换，避免中途崩溃损坏规则库。"""
        os.makedirs(os.path.dirname(self.rules_file), exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(self.rules_file), suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            os.replace(tmp, self.rules_file)
        except Exception:
            if os.path.exists(tmp):
                os.remove(tmp)
            raise

    def load_rules(self):
        """加载全部规则（含元信息）。"""
        try:
            with open(self.rules_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            raise RuntimeError(f"规则库文件损坏或无法读取：{self.rules_file} ({e})") from e

    # ------------------------------------------------------------------ #
    # 新增规则
    # ------------------------------------------------------------------ #

    def next_rule_id(self, rules):
        """按 RULE_001 / RULE_002 … 递增生成下一个规则编号。"""
        used = {r.get("rule_id", "") for r in rules.get("rules", [])}
        n = 1
        while f"RULE_{n:03d}" in used:
            n += 1
        return f"RULE_{n:03d}"

    def add_rule(self, rule):
        """新增一条死规则。标题重复时拒绝并返回 False。"""
        rules = self.load_rules()
        rules.setdefault("rules", [])

        title = (rule.get("title") or "").strip()
        if not title:
            _log("错误：规则标题 (title) 不能为空。")
            return False

        for existing in rules["rules"]:
            if existing.get("title") == title:
                _log(f"警告：规则已存在：{title} ({existing.get('rule_id')})，未重复添加。")
                return False

        # 规范化默认字段
        rule.setdefault("rule_id", self.next_rule_id(rules))
        rule.setdefault("category", "其他")
        rule.setdefault("description", "")
        rule.setdefault("severity", "high")
        rule.setdefault("created_by", "unknown")
        rule["created_at"] = rule.get("created_at") or self._now()
        rule["trigger_keywords"] = _to_list(rule.get("trigger_keywords"))
        rule["must_execute_actions"] = _to_list(rule.get("must_execute_actions"))
        rule["forbidden_actions"] = _to_list(rule.get("forbidden_actions"))

        if rule.get("severity") not in VALID_SEVERITIES:
            rule["severity"] = "high"

        rules["rules"].append(rule)
        rules["last_updated"] = self._now()
        self._atomic_save(rules)
        _log(f"✅ 规则已添加：{rule['title']} ({rule['rule_id']})")
        return True

    # ------------------------------------------------------------------ #
    # 更新 / 删除规则
    # ------------------------------------------------------------------ #

    def update_rule(self, rule_id, updates):
        """更新指定规则的可写字段。"""
        rules = self.load_rules()
        for rule in rules.get("rules", []):
            if rule.get("rule_id") == rule_id:
                for key, value in updates.items():
                    if key == "rule_id" or key == "created_at":
                        continue  # 主键与创建时间不可改
                    if key in ("trigger_keywords", "must_execute_actions", "forbidden_actions"):
                        rule[key] = _to_list(value)
                    elif key == "severity" and value not in VALID_SEVERITIES:
                        _log(f"警告：无效的 severity：{value}，已忽略。")
                    else:
                        rule[key] = value
                rules["last_updated"] = self._now()
                self._atomic_save(rules)
                _log(f"✅ 规则已更新：{rule_id}")
                return True
        _log(f"警告：未找到规则：{rule_id}")
        return False

    def delete_rule(self, rule_id):
        """删除指定规则。"""
        rules = self.load_rules()
        initial_len = len(rules.get("rules", []))
        rules["rules"] = [r for r in rules.get("rules", []) if r.get("rule_id") != rule_id]
        if len(rules["rules"]) < initial_len:
            rules["last_updated"] = self._now()
            self._atomic_save(rules)
            _log(f"✅ 规则已删除：{rule_id}")
            return True
        _log(f"警告：未找到规则：{rule_id}")
        return False

    # ------------------------------------------------------------------ #
    # 查询规则
    # ------------------------------------------------------------------ #

    def query_rules(self, keyword=None, category=None):
        """按关键词 / 分类查询规则。

        - keyword：可传入一个或多个词；命中任意一个即算匹配（OR 语义）。
        - category：精确匹配规则分类。
        """
        rules = self.load_rules().get("rules", [])

        keywords = _split_text(keyword) if keyword else []
        keywords = [k.lower() for k in keywords]

        filtered = []
        for rule in rules:
            if category and rule.get("category") != category:
                continue
            if keywords:
                text = _rule_searchable_text(rule)
                if not any(_text_contains(text, kw) for kw in keywords):
                    continue
            filtered.append(rule)
        return filtered

    def get_rule(self, rule_id):
        """获取单条规则。"""
        for rule in self.load_rules().get("rules", []):
            if rule.get("rule_id") == rule_id:
                return rule
        return None

    def list_categories(self):
        """列出全部已使用的分类。"""
        cats = {r.get("category") for r in self.load_rules().get("rules", []) if r.get("category")}
        return sorted(cats)

    def list_all(self):
        """返回全部规则。"""
        return self.load_rules().get("rules", [])

    # ------------------------------------------------------------------ #
    # 场景匹配（核心：Codex 遇到情况时调用）
    # ------------------------------------------------------------------ #

    @staticmethod
    def is_self_inspection(text):
        """文本是否为「询问规则库自身」的元查询（供调用方标注返回语义）。"""
        return is_self_inspection_query(text)

    def check_situation(self, text):
        """把当前场景/任务文本与所有死规则比对，返回命中的规则列表。

        命中逻辑（两段式）：
        1. **元查询**（问「有哪些规则」这件事本身）-> 返回**全量**规则。
           这类文本不含任何 trigger_keywords，走关键词匹配必然为空，而空结果
           无法与「本任务不受任何规则约束」区分，属于静默失效。
           判据见 is_self_inspection_query()。
        2. **普通场景**：场景文本包含该规则的任意触发关键词，即视为命中。
           （若触发词为空，则不参与场景匹配，避免误伤。）
        """
        if not text or not text.strip():
            return []
        rules = self.load_rules().get("rules", [])
        if is_self_inspection_query(text):
            return list(rules)
        text_lower = text.lower()
        matched = []
        for rule in rules:
            triggers = [t.lower() for t in rule.get("trigger_keywords", []) if t.strip()]
            if not triggers:
                continue
            if any(_text_contains(text_lower, t) for t in triggers):
                matched.append(rule)
        return matched

    # ------------------------------------------------------------------ #
    # 展示辅助
    # ------------------------------------------------------------------ #

    @staticmethod
    def format_rule(rule):
        """把一条规则格式化为易读的文本块。"""
        lines = [
            f"[{rule.get('rule_id')}] {rule.get('title')} "
            f"[{rule.get('category')} / {rule.get('severity')}]"
        ]
        if rule.get("trigger_keywords"):
            lines.append(f"  触发词: {'、'.join(rule.get('trigger_keywords'))}")
        if rule.get("description"):
            lines.append(f"  说明: {rule.get('description')}")
        if rule.get("must_execute_actions"):
            lines.append("  ⛔ 必须执行:")
            for a in rule.get("must_execute_actions"):
                lines.append(f"    - {a}")
        if rule.get("forbidden_actions"):
            lines.append("  🚫 禁止操作:")
            for a in rule.get("forbidden_actions"):
                lines.append(f"    - {a}")
        lines.append(f"  创建: {rule.get('created_by')} @ {rule.get('created_at')}")
        return "\n".join(lines)


def _demo():
    """快速自检：展示解析器基本用法。"""
    parser = RuleParser()
    _log("== 规则库加载自检 ==")
    _log(f"规则文件: {parser.rules_file}")
    _log(f"分类: {parser.list_categories()}")
    _log(f"规则总数: {len(parser.list_all())}")


if __name__ == "__main__":
    _demo()
