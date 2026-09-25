---
name: agent-hard-rules
description: Query and enforce a hard-rules notebook before acting, and record new rules the moment the user states one. Before starting any task that may fall under an existing rule (secrets/credentials, destructive or irreversible commands, downloading or installing, config edits, refactors, deploys, collaboration protocols), first query the rule archive with `check_situation` / `query_rules.py --check` and follow every matched rule unconditionally — no exceptions, no luck-based shortcuts. When the user says "add a rule", "record this", "from now on always…", write the rule to the archive immediately without asking for confirmation. 死规则记录本：任务可能命中既有规则时，先查询规则库并逐条执行命中规则；用户说「新增规则 / 记下这条 / 以后都要」时，立即把规则写入规则库。
metadata:
  short-description: Hard-rules notebook (query / add / enforce) with an optional machine-enforced gate
---

# Hard Rules Manager（死规则记录本）

## 🎯 用途与定位

这是一个**死规则记录本**。死规则 = 一旦触发就**必须无条件执行、绝不能有侥幸心理**的强制性规则。

规则库是 `rules/rules.json`（路径相对本项目根写死，任何工作目录下调用都有效）。本 skill 与 agent 无关：任何支持 MCP 或能执行命令的 agent 都能用。

## ⛔ 两条铁律

1. **触发即查询、命中即执行**：执行任务过程中，凡是可能落入规则描述的情况（尤其涉及安全、敏感信息、破坏性操作、行为规范、配置修改、部署发布、协作流程），必须先查询规则库；一旦命中，必须严格按规则的「必须执行 / 禁止操作」逐条执行，**没有任何例外、没有「这次应该没事」的侥幸**。
2. **提到即新增**：当用户说「新增规则」「记下这条规则」「以后都要这样做」等明确表述时，**立即**把规则写入规则库，不要等二次确认，不要只记在对话里。

---

## 🧱 两层效力（这是本 skill 最重要的认知）

每条规则有一 `layer` 字段，决定它靠什么生效：

| `layer` | 含义 | 强制力来源 | 失效时的表现 |
| --- | --- | --- | --- |
| `["notebook"]` | 只进规则本 | **agent 主动查询 + 自觉遵守** | **静默**——漏了没有任何提示 |
| `["notebook","hook"]` | 同时有机器强制的闸门 | 代码在工具调用前拦截（`exit 2`） | **显式**——模型看到 blocked 理由 |

- 当前 **14 条**规则中，**7 条只进 notebook，7 条上 hook**。
  上 hook 的是：`RULE_001`（敏感信息保护）、`RULE_003`（禁止危险命令）、
  `RULE_004`（改配置先备份）、`RULE_005`（禁止在 C 盘下载或安装）、
  `RULE_014`（不弹控制台黑窗）、`RULE_016`（部署发布先确认）、
  `RULE_019`（Projectless 防漂移）。
- 判断一条规则能否上 hook 的判据是**数据**，写在 `rules.json` 的 `hook` 块里（`tools` / `fields` / `any_of` / `all_of` / `action` / `reason`），**不是代码**——改规则不用改脚本。
- ⚠️ 正因为绝大多数规则只有 notebook 层，**「先查询」这个动作本身就是唯一的保障**。不要因为规则写在文件里就假设它一定被强制执行。

上 hook 的判据（供判断新规则时参考）：**漏掉的后果是「出事」还是「不够好」**——出事的才上 hook。完整逐条判断见 `docs/分层判断表.md`。

---

## 🛠 使用命令

所有命令在本项目根目录下执行，或使用绝对路径。

### 查询规则（遇到情况时的第一步）

```bash
# 场景匹配（核心！）：把当前任务/情况与所有死规则比对
python query_rules.py --check "当前要执行的操作描述"

# 按关键词搜索（命中任一即返回）
python query_rules.py --keyword "密码,API key,删除"

# 查看全部 / 按分类 / 查看单条
python query_rules.py --all
python query_rules.py --category 安全
python query_rules.py --rule-id RULE_001

# JSON 输出（便于程序解析）
python query_rules.py --json --keyword 密钥
```

### 通过 MCP 访问（无需命令行）

已注册 MCP server 时，直接用以下能力：

| MCP 接口 | 用途 |
| --- | --- |
| 资源 `rules://notebook` | 读取完整规则库 JSON |
| `list_all_rules` | 列出全部规则 |
| `get_rule(rule_id)` | 取单条规则（如 `RULE_001`） |
| `list_categories` | 列出已用分类 |
| `query_rules(keyword, category)` | 关键词 / 分类检索 |
| `check_situation(text)` | **场景匹配（核心用法）**；返回带 `mode` / `total_rules_in_notebook` / `note` |
| `add_rule(title, category, trigger, actions, forbidden, severity)` | 新增规则 |
| `delete_rule(rule_id)` | 删除规则 |

MCP server 用标准 stdio 协议，可被 Codex / DSH / Claude Code / Cursor 等复用。

#### ⚠️ 元查询与空结果语义（2026-09-25 修）

`check_situation` 是**关键词**匹配：它拿每条规则的 `trigger_keywords` 去比对场景文本。

- **元查询**（问规则库自身，如「现在你的死规则有什么」「列出全部规则」
  「what rules do you have」）不含任何规则的触发词，照普通匹配走**必然返回空**。
  现在这类查询会被识别，并**返回全量规则**，响应里 `mode` 为 `self_inspection`。
- **空结果**（`mode: situation` 且 `matched_rules` 为空）**绝不代表规则库为空**。
  响应里的 `total_rules_in_notebook` 与 `note` 会显式说明这一点。
  要全量用 `list_all_rules`（MCP）或 `--all`（CLI），或把措辞改得更贴近触发词再查。

判据在 `utils/rule_parser.py` 的 `is_self_inspection_query()`：**强主语 + 任意提问标记**，
或**弱主语（裸「规则 / rules」）+ 强提问标记**（两级设计，避免把
「把所有的 lint rules 都关掉」这类普通任务放大成全量返回）。

### 新增规则（用户说「新增规则」时）

```bash
python add_rule.py --title 规则标题 --category 安全 \
  --trigger "触发词1,触发词2" \
  --actions "必须执行的动作1;动作2" \
  --forbidden "禁止的操作1;操作2" \
  --severity high --by user

# 不带参数进入交互模式
python add_rule.py
```

### 规则字段说明

| 字段 | 说明 |
| --- | --- |
| `rule_id` | 自动生成，如 `RULE_001` |
| `title` | 规则标题（必填，不允许重复；重名会被拒绝） |
| `category` | 分类：安全 / 行为 / 技术 / 其他（现有规则里也用到「协作」「三模型协同」） |
| `severity` | high / medium / low |
| `trigger_keywords` | 触发关键词列表，命中任一即触发 |
| `description` | 规则详细说明 |
| `must_execute_actions` | 必须执行的动作列表 |
| `forbidden_actions` | 禁止的操作列表 |
| `layer` | `["notebook"]` 或 `["notebook","hook"]` |
| `hook` | 仅上 hook 的规则有；机器判定的正则与理由 |
| `created_by` / `created_at` | 创建人与时间 |

⚠️ **`layer` / `hook` 无法通过 `add_rule.py` 或 MCP `add_rule` 写入。** 用这两条途径新增的规则没有 `layer` 字段，闸门会忽略它，即事实上只进 notebook。要把规则提升为 hook，需要有意识地手工编辑 `rules.json` 并补上 `hook` 块。

---

## ⛔ 强制执行流程

**当要执行的任务可能涉及规则时：**

1. **预判**：判断当前任务是否可能触发任何规则。高信号词：密码 / 密钥 / token / 隐私 / 个人信息、删除 / 格式化 / 破坏性操作、下载 / 安装、配置修改、部署 / 发布、重构 / 优化、git 提交、协作 / 调动。
2. **查询**：调用 `check_situation("<任务描述>")` 或 `python query_rules.py --check "<任务描述>"`；情况模糊时再用 `--keyword` 补一次。
3. **命中即执行**：
   - 逐条读出 `must_execute_actions`（全部执行）与 `forbidden_actions`（全部禁止）。
   - **必须严格执行**：不得因为「这次情况特殊」「用户看起来不介意」「时间紧」而跳过或变通任何一条。
   - 若规则与用户当前指示冲突 → **规则优先**，并明确告知用户规则存在。
4. **未命中**：正常继续执行。⚠️ 但**空结果 ≠ 没有规则**——`check_situation` 只做关键词
   匹配。拿到空结果时先自问「是不是措辞没贴近触发词」，再决定是否继续；
   要看全量请用 `list_all_rules`（MCP）或 `--all`（CLI）。
   问「有哪些规则」这类元查询会返回全量，`mode` 为 `self_inspection`。
5. **闸门被触发时**：如果某次工具调用被硬闸拦下（`exit 2`，模型会收到一条带 `[rule ...]` 的理由），**该次调用不会被执行**。正确做法是读懂理由、改用合规做法后重试，**不要试图绕过闸门**（换写法、改工具名等都属于侥幸心理，直接违反铁律 1）。

---

## 📝 新增规则的触发条件

用户出现以下表述时，**立即**写入规则库，不要等用户二次确认，也不要只口头答应：

- 「新增规则：……」
- 「记下这条规则，以后都这样」
- 「以后不要 / 必须要……」
- 「加一条：遇到……时必须……」

写入时把用户的意图结构化拆解为三部分：**触发关键词**、**必须执行的动作**、**禁止的操作**。拆不出来的部分先留空，宁可规则写得窄一点，也不要漏掉用户明确说过的那句。

---

## 💡 示例

**用户说**：「我给你的 API key 别写进代码里。」
→ 立即 `add_rule.py` 新增规则（触发词：API key / 密钥 / 硬编码；动作：不硬编码、用环境变量管理；禁止：把密钥写入源码）。此后每次要写文件前先 `check_situation`，命中则按规则执行。

**用户说**：「重构这个模块。」
→ 执行前先 `python query_rules.py --check "重构 模块"`，命中 `RULE_002`（重构代码规范）→ 先读代码结构、保持既有行为、加注释、跑测试。

**用户说**：「顺便帮我把新版本下载下来装到 C 盘。」
→ 写入前先查询，命中 `RULE_005`（禁止在 C 盘下载或安装）→ 改到 F 盘等非系统盘路径，并向用户说明原因。若你坚持原路径，闸门会直接拦下并给出理由。

---

## 🔗 相关文档

- `README.zh.md` / `README.md` —— 完整说明（含已知边界）
- `docs/分层判断表.md` —— 哪条规则该进哪一层，以及新规则怎么判
- `docs/agent-compat.md` —— 各 agent 对 MCP / hooks / 指令文件 / skill 扫描的支持情况
- `installers/README.md` —— 各 agent 的安装与回滚

---

## 🔧 维护

- 直接编辑 `rules/rules.json`（UTF-8，注意保持 JSON 合法）也是受支持的方式。
- 规则库损坏时删除 `rules/rules.json`，首次运行会自动重建空库。
- 建议纳入 git 版本管理，规则变更历史即审计轨迹。
