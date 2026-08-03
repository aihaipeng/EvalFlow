import assert from "node:assert/strict";
import test from "node:test";

import {
  firstBatchErrorTarget,
  mapBatchSaveError,
  validateBatchRows,
  validateBatchSelections,
} from "../web/frontend/batch-validation.mjs";

const validVariable = (overrides = {}) => ({
  source: "TEST_SET",
  key: "question",
  value: "question",
  type: "string",
  ...overrides,
});

const validRule = (overrides = {}) => ({
  name: "答案一致",
  result_path: "answer",
  operator: "EQ",
  expected_value: "ok",
  type: "string",
  ...overrides,
});

test("legacy numeric zero and boolean false custom values are preserved", () => {
  const result = validateBatchRows({
    headers: ["question"],
    variables: [
      validVariable({
        source: "CUSTOM",
        key: "zero",
        value: 0,
        type: "integer",
      }),
      validVariable({
        source: "CUSTOM",
        key: "disabled",
        value: false,
        type: "boolean",
      }),
    ],
    rules: [],
  });

  assert.deepEqual(result.errors.variables, []);
  assert.deepEqual(
    result.variables.map(({ value }) => value),
    ["0", "false"],
  );
});

test("variable errors identify the exact row and field", () => {
  const result = validateBatchRows({
    headers: ["question"],
    variables: [
      validVariable(),
      validVariable({ value: "missing_column" }),
      validVariable({
        source: "CUSTOM",
        key: "question",
        value: "abc",
        type: "integer",
      }),
    ],
    rules: [],
  });

  assert.equal(
    result.errors.variables[1].key,
    "变量注入第 2 行 · Key：不能与第 1 行重复",
  );
  assert.equal(
    result.errors.variables[1].value,
    "变量注入第 2 行 · Value：请选择当前测试集中的字段",
  );
  assert.equal(
    result.errors.variables[2].key,
    "变量注入第 3 行 · Key：不能与第 1 行重复",
  );
  assert.match(result.errors.variables[2].value, /必须是整数/);
});

test("rule errors identify path, expected value, and type while NOT_EMPTY needs no expected value", () => {
  const result = validateBatchRows({
    headers: ["question"],
    variables: [validVariable()],
    rules: [
      validRule({ operator: "NOT_EMPTY", expected_value: "", type: "string" }),
      validRule({ result_path: "answer[bad" }),
      validRule({ operator: "REGEX", expected_value: "[", type: "string" }),
      validRule({ operator: "EXISTS", expected_value: "true", type: "string" }),
    ],
  });

  assert.deepEqual(result.errors.rules[0] || {}, {});
  assert.match(result.errors.rules[1].result_path, /路径格式无效/);
  assert.match(result.errors.rules[2].expected_value, /正则表达式无效/);
  assert.equal(
    result.errors.rules[3].type,
    "结果校验第 4 行 · 类型：使用“存在”时必须选择 boolean",
  );
});

test("422 validation locations map to top-level and repeated controls", () => {
  const errors = mapBatchSaveError({
    message: "validation failed",
    issues: [
      {
        loc: ["body", "name"],
        msg: "String should have at most 200 characters",
        type: "string_too_long",
      },
      {
        loc: ["body", "variables", 1, "value"],
        msg: "Field required",
        type: "missing",
      },
      {
        loc: ["body", "evaluation_rules", 2],
        msg: "Value error, 正则表达式无效",
        type: "value_error",
      },
    ],
  });

  assert.match(errors.form.name, /^任务名称：/);
  assert.match(errors.variables[1].value, /^变量注入第 2 行 · Value：/);
  assert.match(errors.rules[2].expected_value, /^结果校验第 3 行 · 预期值：/);
});

test("400 business errors map to actionable fields", () => {
  const variableError = mapBatchSaveError(
    {
      message:
        "变量 2 的自定义 value 与 integer 不匹配: 字符串不是严格 JSON number",
    },
    { variables: [validVariable(), validVariable({ key: "count" })] },
  );
  const displayError = mapBatchSaveError({
    message: "用例列不存在于测试集字段中: old_name",
  });

  assert.match(variableError.variables[1].value, /^变量注入第 2 行 · Value：/);
  assert.match(displayError.form.case_display_column, /^用例显示列：/);
});

test("first error target follows the visible form order", () => {
  const target = firstBatchErrorTarget({
    form: { case_concurrency: "并发数错误" },
    variables: [{}, { value: "变量值错误" }],
    rules: [{ result_path: "路径错误" }],
    sections: {},
  });

  assert.deepEqual(target, { kind: "form", field: "case_concurrency" });
});

test("display-column errors identify the exact top-level control", () => {
  assert.deepEqual(
    validateBatchSelections(
      { case_display_column: "old", rule_display_column: "also_old" },
      ["question", "expected"],
    ),
    {
      case_display_column: "用例显示列：请选择当前测试集中的字段",
      rule_display_column:
        "规则显示列：请选择当前测试集中的字段，或选择“不选择”",
    },
  );
});
