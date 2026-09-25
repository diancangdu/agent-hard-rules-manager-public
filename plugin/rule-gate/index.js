// dsh-rule-gate — 死规则硬闸（原生 Cordis 插件，零外部依赖）
//
// 背景：原方案用 `@deepseek-ai/dsh-hooks-claude-code` 桥接 + hooks.local.json，
// 但该插件从未激活。两个原因（2026-09-25 实测确认）：
//   1. 插入名若指向**包目录**，ESM 的 `ERR_UNSUPPORTED_DIR_IMPORT` 会让 import 直接失败；
//   2. 该桥接声明了 `inject = ["shell", "sessionProjections"]`，而内联插件在 `apply`
//      阶段这些服务尚未就绪（探针实测四个服务全为 false），于是插件永远不激活。
//
// 本插件规避这两点：name 指向具体文件；不声明任何 inject，只挂
// `tools/pre-execute` 这一个拦截点（探针已实测该扩展点可用）。
//
// 规则来源：agent-hard-rules 的 rules/rules.json。只有同时满足
//   · `layer` 含 "hook"
//   · 带 `hook` 块且 `hook.action === "deny"`
// 的规则才参与拦截；判定逻辑与 python 版 pretooluse_guard.py 保持一致，
// 复用的是同一份正则（在 rules.json 里），不重复维护。
//
// 失效安全：读不到规则文件、JSON 坏、正则非法 —— 一律放行并记日志，绝不误伤。
import { readFileSync, appendFileSync, existsSync } from 'node:fs';
import { fileURLToPath } from 'node:url';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

// Rule file resolution order: env override, then the copy that ships in
// this repo (plugin/rule-gate/ -> ../../rules/rules.json).
const RULES_CANDIDATES = [
  process.env.HARD_RULES_FILE,
  fileURLToPath(new URL('../../rules/rules.json', import.meta.url)),
].filter((candidate) => typeof candidate === 'string' && candidate !== '');

// 日志落点允许用环境变量覆盖：回归测试据此写自己的临时日志，
// 而不再需要 rmSync 真实的 gate_events.jsonl（那会毁掉排障历史）。
const GATE_LOG = process.env.HARD_RULES_GATE_LOG || join(tmpdir(), 'hard-rules-gate.jsonl');
const GATE_DEBUG_LOG =
  process.env.HARD_RULES_GATE_DEBUG_LOG || join(tmpdir(), 'hard-rules-gate-debug.jsonl');

// 与 python 版 pretooluse_guard.py 的 TEXT_KEYS 对齐
const TEXT_KEYS = ['command', 'content', 'new_string', 'new_str', 'file_text', 'old_string', 'file_path'];

// 可能承载目标文件路径的字段名
const PATH_KEYS = ['file_path', 'filePath', 'path', 'paths'];

function record(entry) {
  try {
    appendFileSync(GATE_LOG, JSON.stringify({ ts: new Date().toISOString(), ...entry }) + '\n', 'utf8');
  } catch {
    // 日志失败不影响闸门
  }
}

function resolveRulesPath() {
  for (const candidate of RULES_CANDIDATES) {
    try {
      readFileSync(candidate, 'utf8');
      return candidate;
    } catch {
      // 试下一个
    }
  }
  return undefined;
}

function compileHookRules() {
  const path = resolveRulesPath();
  if (path === undefined) {
    record({ event: 'rules-missing', candidates: RULES_CANDIDATES });
    return [];
  }
  let doc;
  try {
    doc = JSON.parse(readFileSync(path, 'utf8'));
  } catch (error) {
    record({ event: 'rules-unparsable', path, error: String(error) });
    return [];
  }

  const out = [];
  for (const rule of doc?.rules ?? []) {
    const hook = rule?.hook;
    if (typeof hook !== 'object' || hook === null) continue;
    const layers = Array.isArray(rule.layer) ? rule.layer : [rule.layer];
    if (!layers.includes('hook')) continue;
    if (String(hook.action ?? 'deny').toLowerCase() !== 'deny') continue;

    const compileAll = (key) => {
      const compiled = [];
      for (const pattern of hook[key] ?? []) {
        // 规则文件里的正则沿用 python 语法，可能带 `(?i)` / `(?is)` / `(?ims)` 这类
        // 内联标志；JavaScript 不支持内联标志，需整体提取出来转成 flags。
        // 注意必须支持多字母组合（`(?is)` 这种），只剥 `(?i)` 会漏。
        let source = pattern;
        let flags = '';
        const inline = source.match(/^\(\?([a-zA-Z]+)\)/);
        if (inline) {
          flags = inline[1];
          source = source.slice(inline[0].length);
        }
        try {
          compiled.push(new RegExp(source, flags));
        } catch (error) {
          record({ event: 'bad-regex', rule: rule.rule_id, key, pattern, error: String(error) });
        }
      }
      return compiled;
    };
    const anyOf = compileAll('any_of');
    const allOf = compileAll('all_of');
    const pathAnyOf = compileAll('path_any_of');
    const pathNotAnyOf = compileAll('path_not_any_of');
    // path_must_exist：要求「目标路径已在磁盘上存在」本条规则才继续判。
    // 语义是「本规则只管**修改**，不管**新建**」—— 目标不存在时属于新建，
    // 没有覆盖风险，也没有可备份的东西，应放行（这也是 RULE_004 reason 里的自述承诺）。
    const pathMustExist = hook.path_must_exist === true;
    // 至少要有一个判定条件，否则这条规则无从触发
    if (anyOf.length === 0 && allOf.length === 0 && pathAnyOf.length === 0) continue;

    out.push({
      ruleId: rule.rule_id ?? '?',
      title: rule.title ?? '',
      tools: new Set(hook.tools ?? []),
      fields: hook.fields ?? TEXT_KEYS,
      anyOf,
      allOf,
      pathAnyOf,
      pathNotAnyOf,
      pathMustExist,
      pathExists: hook.path_exists ?? [],
      reason: hook.reason ?? `blocked by hard rule ${rule.rule_id ?? ''}`,
    });
  }
  return out;
}

function gatherText(input, fields) {
  const parts = [];
  for (const field of fields) {
    const value = input?.[field];
    if (typeof value === 'string') parts.push(value);
    else if (value !== undefined && value !== null && typeof value === 'object') {
      try {
        parts.push(JSON.stringify(value));
      } catch {
        // 忽略不可序列化的值
      }
    }
  }
  return parts.join('\n');
}

/** 取出本次调用涉及的文件路径（支持 file_path / filePath / path / paths）。 */
function gatherPaths(input) {
  const paths = [];
  for (const field of PATH_KEYS) {
    const value = input?.[field];
    if (typeof value === 'string') paths.push(value);
    else if (Array.isArray(value)) {
      for (const item of value) if (typeof item === 'string') paths.push(item);
    }
  }
  return paths;
}

/**
 * 判据用的路径存在性检查。
 *
 * 为什么需要它：像 RULE_004「改配置前必须已备份」这种规则，判据是**磁盘状态**
 * 而非调用参数文本，纯正则表达不了。这里允许把「同目录已有 .bak」这类事实
 * 作为放行条件。
 *
 * 两种占位符：
 *   $path            当前路径原样
 *   ${path}.bak      当前路径 + 后缀
 *   ${path}.dirname  当前路径所在目录
 *
 * 供 path_not_any_of 使用：命中即视为「已满足前置条件」，本条规则不成立。
 */
/** 单个路径是否存在（容错：非法路径按不存在处理）。 */
function pathExists(p) {
  try {
    return existsSync(p);
  } catch {
    return false;
  }
}

const EXISTS_PATTERNS = ['$path', '${path}.bak', '${path}.orig', '${path}.backup', '${path}.bak1', '${path}~'];

function hasPrerequisite(path) {
  for (const pattern of EXISTS_PATTERNS) {
    const candidate = pattern.replace('${path}', path).replace('$path', path);
    try {
      if (existsSync(candidate)) return true;
    } catch {
      // 忽略非法路径
    }
  }
  return false;
}

/** 从 hook 配置里取 path_exists 声明的占位符；缺省时用内置候选表。 */
function prerequisiteSatisfied(path, patterns) {
  const list = patterns && patterns.length > 0 ? patterns : null;
  if (list) {
    for (const pattern of list) {
      const candidate = pattern.replace('${path}', path).replace('$path', path);
      try {
        if (existsSync(candidate)) return true;
      } catch {
        // 忽略
      }
    }
    return false;
  }
  return hasPrerequisite(path);
}

/**
 * 判定一条规则是否命中。
 *
 * 判定顺序（由强到弱）：
 *   1. tools 白名单（规则声明了就必须匹配）
 *   2. path_any_of：文件路径命中任一模式
 *   3. path_must_exist：声明了则要求目标**已存在**；不存在（=新建）直接放行。
 *      必须早于第 5 步的 path_exists，否则新建文件会因没有 .bak 而被误拦。
 *   4. path_not_any_of：**排除**条件 —— 用于「已有备份就放行」这类动态判据。
 *      只要有任一路径命中排除模式，本条规则整体不成立。
 *   5. path_exists：声明了前置条件时，任一目标满足即放行
 *   6. any_of / all_of：在 fields 指定的文本上做正则匹配
 *
 * path_not_any_of 的存在让规则能表达「除…之外」，例如
 * 「写配置文件要拦，但同目录已有 .bak 就放行」。
 */
function evaluate(toolName, toolInput, rules) {
  const trace = process.env.HARD_RULES_GATE_DEBUG ? [] : null;

  for (const rule of rules) {
    if (rule.tools.size > 0 && !rule.tools.has(toolName)) {
      if (trace) trace.push({ rule: rule.ruleId, skip: 'tool' });
      continue;
    }

    const paths = gatherPaths(toolInput);

    if (rule.pathAnyOf.length > 0) {
      if (paths.length === 0) {
        if (trace) trace.push({ rule: rule.ruleId, skip: 'no-paths' });
        continue;
      }
      if (!paths.some((p) => rule.pathAnyOf.some((rx) => rx.test(p)))) {
        if (trace) trace.push({ rule: rule.ruleId, skip: 'path-any', paths });
        continue;
      }
    }

    // path_must_exist：目标必须已存在，本条规则才继续判。
    // 必须排在 path_exists（前置条件放行）**之前**：新建文件时找不到 .bak，
    // 若先判 path_exists 就会被拦，而新建恰恰无覆盖风险。
    // 命中「目标不存在」= 新建 → 放行。
    if (rule.pathMustExist && !paths.some(pathExists)) {
      if (trace) trace.push({ rule: rule.ruleId, skip: 'target-missing', paths });
      continue;
    }

    if (rule.pathNotAnyOf.length > 0) {
      // 命中排除条件即整条规则不成立（例如备份已存在）
      if (paths.some((p) => rule.pathNotAnyOf.some((rx) => rx.test(p)))) {
        if (trace) trace.push({ rule: rule.ruleId, skip: 'path-not' });
        continue;
      }
    }

    // path_exists：声明了前置条件（如「同目录已有备份」）时，
    // 只要任一路径满足该条件就放行。这是 RULE_004 这类规则的核心判据。
    // 未声明该字段的规则不受影响。
    if (rule.pathExists.length > 0) {
      if (paths.some((p) => prerequisiteSatisfied(p, rule.pathExists))) {
        if (trace) trace.push({ rule: rule.ruleId, skip: 'prereq-met' });
        continue;
      }
    }

    const text = gatherText(toolInput, rule.fields);
    const hasTextCond = rule.anyOf.length > 0 || rule.allOf.length > 0;
    if (!hasTextCond) {
      // 纯路径规则：走到这里就算命中
      if (trace) trace.push({ rule: rule.ruleId, hit: 'path-only', paths });
      return { rule, matched: paths.join(' | ').slice(0, 160) };
    }
    if (text.trim() === '') {
      if (trace) trace.push({ rule: rule.ruleId, skip: 'empty-text' });
      continue;
    }

    let matched = '';
    for (const rx of rule.anyOf) {
      const m = rx.exec(text);
      if (m) {
        matched = m[0].slice(0, 160);
        break;
      }
    }

    // all_of 的语义是「在 any_of 命中的基础上再附加条件」，**不是**独立的 OR 分支。
    // 早期版本把它当成独立条件，导致 `all_of: [^(?!...Hidden)...]`（一个排除条件）
    // 自己就成立，把所有命令都误判为命中 —— 这是个严重误伤，务必保持此顺序。
    if (rule.anyOf.length > 0) {
      if (matched === '') {
        if (trace) trace.push({ rule: rule.ruleId, skip: 'any-of-miss' });
        continue;
      }
      if (rule.allOf.length > 0 && !rule.allOf.every((rx) => rx.test(text))) {
        if (trace) trace.push({ rule: rule.ruleId, skip: 'all-of-reject' });
        continue;
      }
    } else if (rule.allOf.length > 0) {
      // 只声明 all_of 的规则：全部条件都必须成立
      if (!rule.allOf.every((rx) => rx.test(text))) {
        if (trace) trace.push({ rule: rule.ruleId, skip: 'all-of-miss' });
        continue;
      }
      matched = '(all_of)';
    }

    if (matched !== '') {
      if (trace) trace.push({ rule: rule.ruleId, hit: matched });
      return { rule, matched };
    }
    if (trace) trace.push({ rule: rule.ruleId, skip: 'no-text-match' });
  }
  return undefined;
}

export function apply(ctx, config) {
  const rules = compileHookRules();
  const enforce = config?.enforce !== false; // 默认拦截；显式 enforce:false 可切换为只记录

  record({
    event: 'gate-ready',
    rules: rules.map((r) => r.ruleId),
    enforce,
  });

  ctx.on('tools/pre-execute', async (exec, next) => {
    const toolName = exec?.name ?? '';
    const toolInput = exec?.arguments ?? {};
    const verdict = evaluate(toolName, toolInput, rules);

    // 仅在显式开启时记录判定中间态，供排障使用（默认关闭，不产生噪音）
    if (process.env.HARD_RULES_GATE_DEBUG) {
      try {
        appendFileSync(
          GATE_DEBUG_LOG,
          JSON.stringify({
            ts: new Date().toISOString(),
            tool: toolName,
            args: toolInput,
            verdict: verdict === undefined ? null : { rule: verdict.rule.ruleId, matched: verdict.matched },
          }) + '\n',
          'utf8'
        );
      } catch {
        // 忽略
      }
    }

    if (verdict === undefined) return next();

    const reason =
      `${verdict.rule.reason}\n[rule ${verdict.rule.ruleId} - ${verdict.rule.title}]\n` +
      `[matched: ${verdict.matched}]\n[tool: ${toolName}]`;

    record({ event: 'rule-hit', rule: verdict.rule.ruleId, tool: toolName, matched: verdict.matched, blocked: enforce });

    if (!enforce) return next();
    return { kind: 'deny', reason };
  });
}
