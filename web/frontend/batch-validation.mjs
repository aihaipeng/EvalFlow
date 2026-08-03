const VARIABLE_TYPES = new Set([
  "string",
  "number",
  "integer",
  "boolean",
  "object",
  "array",
  "null",
]);
const VARIABLE_SOURCES = new Set(["CUSTOM", "TEST_SET"]);
const RULE_OPERATORS = new Set([
  "EQ",
  "NE",
  "CONTAINS",
  "REGEX",
  "EXISTS",
  "NOT_EMPTY",
  "GT",
  "GTE",
  "LT",
  "LTE",
  "JSON_EQUAL",
]);
const CONTEXT_KEY = /^[A-Za-z_][A-Za-z0-9_]*$/;
const RESULT_PATH =
  /^[A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])*$/;
const JSON_NUMBER = /^-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?$/;

const FORM_FIELD_ORDER = [
  "name",
  "failure_retry_count",
  "test_set_id",
  "workflow_id",
  "case_display_column",
  "rule_display_column",
  "call_order",
  "case_concurrency",
];
const VARIABLE_FIELD_ORDER = ["source", "key", "value", "type"];
const RULE_FIELD_ORDER = [
  "name",
  "result_path",
  "operator",
  "expected_value",
  "type",
];

const FORM_LABELS = {
  name: "任务名称",
  failure_retry_count: "失败重试",
  test_set_id: "测试集",
  workflow_id: "工作流",
  case_display_column: "用例显示列",
  rule_display_column: "规则显示列",
  call_order: "执行顺序",
  case_concurrency: "并发数",
};
const VARIABLE_LABELS = {
  source: "来源",
  key: "Key",
  value: "Value",
  type: "类型",
};
const RULE_LABELS = {
  name: "校验项",
  result_path: "路径",
  operator: "运算符",
  expected_value: "预期值",
  type: "类型",
};

export function emptyBatchFieldErrors() {
  return { form: {}, variables: [], rules: [], sections: {}, summary: "" };
}

function rowMessage(section, index, label, message) {
  return `${section}第 ${index + 1} 行 · ${label}：${message}`;
}

function setRowError(collection, section, labels, index, field, message) {
  collection[index] ||= {};
  collection[index][field] ||= rowMessage(
    section,
    index,
    labels[field],
    message,
  );
}

function validateTypedText(value, type) {
  if (type === "string") return "";
  if (type === "boolean") {
    return /^(?:true|false)$/i.test(value) ? "" : "必须填写 true 或 false";
  }
  if (type === "null") return value === "null" ? "" : "必须填写 null";
  if (type === "number" || type === "integer") {
    if (!JSON_NUMBER.test(value) || !Number.isFinite(Number(value))) {
      return type === "integer" ? "必须是整数" : "必须是有限数字";
    }
    if (type === "integer" && !Number.isInteger(Number(value)))
      return "必须是整数";
    return "";
  }
  if (type === "object" || type === "array") {
    try {
      const parsed = JSON.parse(value);
      const matches =
        type === "array"
          ? Array.isArray(parsed)
          : parsed !== null &&
            typeof parsed === "object" &&
            !Array.isArray(parsed);
      return matches ? "" : `JSON 根类型必须是 ${type}`;
    } catch {
      return `必须是合法的 JSON ${type}`;
    }
  }
  return "类型无效";
}

export function validateBatchRows({
  headers = [],
  variables = [],
  rules = [],
}) {
  const errors = emptyBatchFieldErrors();
  const normalizedVariables = [];
  const normalizedRules = [];
  const headerSet = new Set(headers);
  const firstKeyRow = new Map();

  if (!variables.length) errors.sections.variables = "请至少添加一个变量注入";
  if (variables.length > 100)
    errors.sections.variables = "变量注入最多添加 100 行";

  variables.forEach((row, index) => {
    const source = String(row?.source ?? "").toUpperCase();
    const key = String(row?.key ?? "").trim();
    const type = String(row?.type ?? "");
    const textValue = String(row?.value ?? "");
    let value = textValue;

    if (!VARIABLE_SOURCES.has(source)) {
      setRowError(
        errors.variables,
        "变量注入",
        VARIABLE_LABELS,
        index,
        "source",
        "请选择测试集字段或自定义",
      );
    }
    if (!key) {
      setRowError(
        errors.variables,
        "变量注入",
        VARIABLE_LABELS,
        index,
        "key",
        "请输入变量名",
      );
    } else if (key.length > 200) {
      setRowError(
        errors.variables,
        "变量注入",
        VARIABLE_LABELS,
        index,
        "key",
        "不能超过 200 个字符",
      );
    } else if (!CONTEXT_KEY.test(key)) {
      setRowError(
        errors.variables,
        "变量注入",
        VARIABLE_LABELS,
        index,
        "key",
        "只能以字母或下划线开头，并使用字母、数字、下划线",
      );
    } else if (firstKeyRow.has(key)) {
      setRowError(
        errors.variables,
        "变量注入",
        VARIABLE_LABELS,
        index,
        "key",
        `不能与第 ${firstKeyRow.get(key) + 1} 行重复`,
      );
    } else {
      firstKeyRow.set(key, index);
    }

    if (!VARIABLE_TYPES.has(type)) {
      setRowError(
        errors.variables,
        "变量注入",
        VARIABLE_LABELS,
        index,
        "type",
        "请选择有效类型",
      );
    }

    if (source === "TEST_SET") {
      value = textValue.trim();
      if (!value) {
        setRowError(
          errors.variables,
          "变量注入",
          VARIABLE_LABELS,
          index,
          "value",
          "请选择测试集字段",
        );
      } else if (headers.length && !headerSet.has(value)) {
        setRowError(
          errors.variables,
          "变量注入",
          VARIABLE_LABELS,
          index,
          "value",
          "请选择当前测试集中的字段",
        );
      }
    } else if (source === "CUSTOM" && type === "null") {
      value = "null";
    } else if (source === "CUSTOM") {
      if (!textValue.trim()) {
        setRowError(
          errors.variables,
          "变量注入",
          VARIABLE_LABELS,
          index,
          "value",
          "请输入自定义值",
        );
      } else if (textValue.length > 20000) {
        setRowError(
          errors.variables,
          "变量注入",
          VARIABLE_LABELS,
          index,
          "value",
          "不能超过 20000 个字符",
        );
      } else if (VARIABLE_TYPES.has(type)) {
        const typeError = validateTypedText(textValue, type);
        if (typeError) {
          setRowError(
            errors.variables,
            "变量注入",
            VARIABLE_LABELS,
            index,
            "value",
            typeError,
          );
        }
      }
    }

    normalizedVariables.push({ source, key, value, type });
  });

  if (rules.length > 50) errors.sections.rules = "结果校验最多添加 50 行";
  rules.forEach((row, index) => {
    const name = String(row?.name ?? "").trim();
    const resultPath = String(row?.result_path ?? "")
      .trim()
      .replace(/^context\./, "");
    const operator = String(row?.operator ?? "");
    const type = operator === "NOT_EMPTY" ? "string" : String(row?.type ?? "");
    let expectedValue =
      operator === "NOT_EMPTY"
        ? ""
        : type === "null"
          ? "null"
          : String(row?.expected_value ?? "");

    if (name.length > 200) {
      setRowError(
        errors.rules,
        "结果校验",
        RULE_LABELS,
        index,
        "name",
        "不能超过 200 个字符",
      );
    }
    if (!resultPath) {
      setRowError(
        errors.rules,
        "结果校验",
        RULE_LABELS,
        index,
        "result_path",
        "请输入结果路径",
      );
    } else if (resultPath.length > 4000) {
      setRowError(
        errors.rules,
        "结果校验",
        RULE_LABELS,
        index,
        "result_path",
        "不能超过 4000 个字符",
      );
    } else if (!RESULT_PATH.test(resultPath)) {
      setRowError(
        errors.rules,
        "结果校验",
        RULE_LABELS,
        index,
        "result_path",
        "路径格式无效，请使用字段名、点号或数组下标",
      );
    }
    if (!RULE_OPERATORS.has(operator)) {
      setRowError(
        errors.rules,
        "结果校验",
        RULE_LABELS,
        index,
        "operator",
        "请选择有效运算符",
      );
    }
    if (operator !== "NOT_EMPTY" && !VARIABLE_TYPES.has(type)) {
      setRowError(
        errors.rules,
        "结果校验",
        RULE_LABELS,
        index,
        "type",
        "请选择有效类型",
      );
    }
    if (operator === "EXISTS" && type !== "boolean") {
      setRowError(
        errors.rules,
        "结果校验",
        RULE_LABELS,
        index,
        "type",
        "使用“存在”时必须选择 boolean",
      );
    } else if (operator !== "NOT_EMPTY" && VARIABLE_TYPES.has(type)) {
      if (expectedValue.length > 20000) {
        setRowError(
          errors.rules,
          "结果校验",
          RULE_LABELS,
          index,
          "expected_value",
          "不能超过 20000 个字符",
        );
      } else {
        const typeError = validateTypedText(expectedValue, type);
        if (typeError) {
          setRowError(
            errors.rules,
            "结果校验",
            RULE_LABELS,
            index,
            "expected_value",
            typeError,
          );
        }
      }
    }
    if (
      operator === "REGEX" &&
      type === "string" &&
      !errors.rules[index]?.expected_value
    ) {
      try {
        new RegExp(expectedValue);
      } catch {
        setRowError(
          errors.rules,
          "结果校验",
          RULE_LABELS,
          index,
          "expected_value",
          "正则表达式无效",
        );
      }
    }

    normalizedRules.push({
      name,
      result_path: resultPath,
      operator,
      expected_value: expectedValue,
      type,
    });
  });

  return { errors, variables: normalizedVariables, rules: normalizedRules };
}

export function validateBatchSelections(form, headers = []) {
  const errors = {};
  const headerSet = new Set(headers);
  const caseColumn = String(form?.case_display_column ?? "");
  const ruleColumn = String(form?.rule_display_column ?? "");
  if (!caseColumn) {
    errors.case_display_column = "用例显示列：请选择用于识别用例的字段";
  } else if (headers.length && !headerSet.has(caseColumn)) {
    errors.case_display_column = "用例显示列：请选择当前测试集中的字段";
  }
  if (ruleColumn && headers.length && !headerSet.has(ruleColumn)) {
    errors.rule_display_column =
      "规则显示列：请选择当前测试集中的字段，或选择“不选择”";
  }
  return errors;
}

function friendlyApiReason(issue) {
  const message = String(issue?.msg ?? "").replace(/^Value error,\s*/i, "");
  if (issue?.type === "missing") return "不能为空";
  if (issue?.type === "string_too_long") return "内容过长，请缩短后重试";
  if (issue?.type === "string_too_short") return "不能为空";
  if (issue?.type === "greater_than_equal") return "数值过小";
  if (issue?.type === "less_than_equal") return "数值过大";
  if (/Input should be/i.test(message)) return "填写的值不符合要求";
  return message || "填写的值不符合要求";
}

function inferRuleField(message) {
  if (/结果路径|path/i.test(message)) return "result_path";
  if (/存在性规则|boolean/i.test(message)) return "type";
  if (/预期值|正则|JSON|number|integer/i.test(message)) return "expected_value";
  return "expected_value";
}

function setMappedError(errors, kind, index, field, reason) {
  if (kind === "form") {
    errors.form[field] ||= `${FORM_LABELS[field] || field}：${reason}`;
    return;
  }
  const collection = kind === "variables" ? errors.variables : errors.rules;
  const section = kind === "variables" ? "变量注入" : "结果校验";
  const labels = kind === "variables" ? VARIABLE_LABELS : RULE_LABELS;
  setRowError(collection, section, labels, index, field, reason);
}

function mapApiIssue(errors, issue) {
  const loc = Array.isArray(issue?.loc)
    ? issue.loc.filter((part) => part !== "body")
    : [];
  const reason = friendlyApiReason(issue);
  if (loc[0] === "variables" && Number.isInteger(loc[1])) {
    const field = VARIABLE_FIELD_ORDER.includes(loc[2]) ? loc[2] : "value";
    setMappedError(errors, "variables", loc[1], field, reason);
    return true;
  }
  if (loc[0] === "evaluation_rules" && Number.isInteger(loc[1])) {
    const field = RULE_FIELD_ORDER.includes(loc[2])
      ? loc[2]
      : inferRuleField(reason);
    setMappedError(errors, "rules", loc[1], field, reason);
    return true;
  }
  if (FORM_FIELD_ORDER.includes(loc[0])) {
    setMappedError(errors, "form", null, loc[0], reason);
    return true;
  }
  return false;
}

function mapBusinessMessage(errors, message, variables) {
  let match = message.match(
    /变量\s+(\d+)\s+的\s*(source|key|type|测试集字段|自定义 value)/i,
  );
  if (match) {
    const token = match[2].toLowerCase();
    const field = ["source", "key", "type"].includes(token) ? token : "value";
    setMappedError(errors, "variables", Number(match[1]) - 1, field, message);
    return true;
  }
  match = message.match(/变量 key 不能重复:\s*(.+)$/i);
  if (match) {
    const index = Math.max(
      0,
      variables.findIndex(
        (row, rowIndex) =>
          rowIndex > 0 && String(row?.key ?? "").trim() === match[1].trim(),
      ),
    );
    setMappedError(errors, "variables", index, "key", message);
    return true;
  }
  const formMappings = [
    [/用例列/, "case_display_column"],
    [/规则列/, "rule_display_column"],
    [/调用顺序/, "call_order"],
    [/并发数/, "case_concurrency"],
    [/失败重试/, "failure_retry_count"],
    [/测试集/, "test_set_id"],
    [/工作流/, "workflow_id"],
  ];
  const mapping = formMappings.find(([pattern]) => pattern.test(message));
  if (mapping) {
    setMappedError(errors, "form", null, mapping[1], message);
    return true;
  }
  return false;
}

export function mapBatchSaveError(error, { variables = [] } = {}) {
  const errors = emptyBatchFieldErrors();
  const issues = Array.isArray(error?.issues) ? error.issues : [];
  let mapped = false;
  issues.forEach((issue) => {
    mapped = mapApiIssue(errors, issue) || mapped;
  });
  const message = String(error?.message ?? "").trim();
  if (!issues.length && message)
    mapped = mapBusinessMessage(errors, message, variables);
  errors.summary = mapped
    ? "任务中有字段需要修改，请检查标红位置"
    : message
      ? `任务保存失败：${message}。请检查配置或网络后重试`
      : "任务保存失败，请检查网络后重试";
  return errors;
}

export function hasBatchFieldErrors(errors) {
  return Boolean(firstBatchErrorTarget(errors));
}

export function firstBatchErrorTarget(errors) {
  for (const field of FORM_FIELD_ORDER) {
    if (errors?.form?.[field]) return { kind: "form", field };
  }
  if (errors?.sections?.variables)
    return { kind: "section", field: "variables" };
  for (let index = 0; index < (errors?.variables?.length || 0); index += 1) {
    for (const field of VARIABLE_FIELD_ORDER) {
      if (errors.variables[index]?.[field])
        return { kind: "variables", index, field };
    }
  }
  if (errors?.sections?.rules) return { kind: "section", field: "rules" };
  for (let index = 0; index < (errors?.rules?.length || 0); index += 1) {
    for (const field of RULE_FIELD_ORDER) {
      if (errors.rules[index]?.[field]) return { kind: "rules", index, field };
    }
  }
  return null;
}

export function mergeBatchFieldErrors(left, right) {
  const merged = emptyBatchFieldErrors();
  merged.form = { ...left?.form, ...right?.form };
  merged.sections = { ...left?.sections, ...right?.sections };
  const mergeRows = (a = [], b = []) => {
    const rows = [];
    for (let index = 0; index < Math.max(a.length, b.length); index += 1) {
      if (a[index] || b[index]) rows[index] = { ...a[index], ...b[index] };
    }
    return rows;
  };
  merged.variables = mergeRows(left?.variables, right?.variables);
  merged.rules = mergeRows(left?.rules, right?.rules);
  merged.summary = right?.summary || left?.summary || "";
  return merged;
}
