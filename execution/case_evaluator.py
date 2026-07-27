"""Structured evaluation of a Workflow result against literal or Excel expectations."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from execution.workflow_values import WorkflowValueError, resolve_path, strict_json_clone


class _EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ExpectedValue(_EvaluationModel):
    source: Literal["LITERAL", "EXCEL"] = "LITERAL"
    value: Any = None
    column: str | None = None

    @model_validator(mode="after")
    def validate_source(self) -> "ExpectedValue":
        if self.source == "EXCEL":
            if not self.column:
                raise ValueError("Excel 预期值必须选择列")
            if self.value is not None:
                raise ValueError("Excel 预期值不能同时配置固定值")
        else:
            if self.column is not None:
                raise ValueError("固定预期值不能配置 Excel 列")
            strict_json_clone(self.value)
        return self


class EvaluationRule(_EvaluationModel):
    name: str = Field(min_length=1, max_length=200)
    actual_path: str = Field(min_length=1, max_length=4000)
    operator: Literal[
        "EQ", "NE", "CONTAINS", "REGEX", "EXISTS", "GT", "GTE", "LT", "LTE", "JSON_EQUAL"
    ]
    expected: ExpectedValue = Field(default_factory=ExpectedValue)

    @model_validator(mode="after")
    def validate_rule(self) -> "EvaluationRule":
        try:
            resolve_path({}, self.actual_path)
        except WorkflowValueError as exc:
            if "对象字段不存在" not in str(exc):
                raise ValueError(f"实际值路径无效: {self.actual_path}") from exc
        if self.operator == "REGEX" and self.expected.source == "LITERAL":
            if not isinstance(self.expected.value, str):
                raise ValueError("正则预期值必须是字符串")
            try:
                re.compile(self.expected.value)
            except re.error as exc:
                raise ValueError(f"正则表达式无效: {exc}") from exc
        if self.operator == "EXISTS" and (
            self.expected.source != "LITERAL" or not isinstance(self.expected.value, bool)
        ):
            raise ValueError("存在性规则的固定预期值必须是 boolean")
        return self


def _json_equal(left: Any, right: Any) -> bool:
    return json.dumps(left, ensure_ascii=False, allow_nan=False, sort_keys=True) == json.dumps(
        right, ensure_ascii=False, allow_nan=False, sort_keys=True
    )


def _finite_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and (
        not isinstance(value, float) or math.isfinite(value)
    )


def _compare(operator: str, actual: Any, expected: Any) -> bool:
    if operator == "EQ":
        return type(actual) is type(expected) and actual == expected
    if operator == "NE":
        return not (type(actual) is type(expected) and actual == expected)
    if operator == "JSON_EQUAL":
        return _json_equal(actual, expected)
    if operator == "CONTAINS":
        if isinstance(actual, str) and isinstance(expected, str):
            return expected in actual
        if isinstance(actual, list):
            return expected in actual
        if isinstance(actual, dict):
            return expected in actual
        raise ValueError("包含运算要求实际值是字符串、数组或对象")
    if operator == "REGEX":
        if not isinstance(actual, str) or not isinstance(expected, str):
            raise ValueError("正则运算要求实际值和预期值都是字符串")
        return re.search(expected, actual) is not None
    if operator in {"GT", "GTE", "LT", "LTE"}:
        if not _finite_number(actual) or not _finite_number(expected):
            raise ValueError("数值比较要求实际值和预期值都是有限数字")
        return {
            "GT": actual > expected,
            "GTE": actual >= expected,
            "LT": actual < expected,
            "LTE": actual <= expected,
        }[operator]
    raise ValueError(f"不支持的校验运算符: {operator}")


def evaluate_case(
    result: dict[str, Any],
    source_values: dict[str, Any],
    rules: list[EvaluationRule],
) -> dict[str, Any]:
    """Evaluate all rules with AND semantics and retain per-rule facts."""

    facts = []
    for rule in rules:
        actual_exists = True
        try:
            actual = resolve_path(result, rule.actual_path)
        except WorkflowValueError:
            actual_exists = False
            actual = None
        try:
            if rule.expected.source == "EXCEL":
                if rule.expected.column not in source_values:
                    raise ValueError(f"Excel 预期列不存在: {rule.expected.column}")
                expected = strict_json_clone(source_values[rule.expected.column])
            else:
                expected = strict_json_clone(rule.expected.value)
            passed = (
                actual_exists is expected
                if rule.operator == "EXISTS"
                else _compare(rule.operator, actual, expected)
                if actual_exists
                else False
            )
            status = "PASS" if passed else "FAIL"
            message = None if passed else (
                f"结果路径不存在: {rule.actual_path}"
                if not actual_exists else "实际值不符合预期"
            )
        except (TypeError, ValueError, re.error) as exc:
            expected = None
            status = "ERROR"
            message = str(exc)
        facts.append(
            {
                "name": rule.name,
                "actual_path": rule.actual_path,
                "operator": rule.operator,
                "expected_source": rule.expected.source,
                "actual": strict_json_clone(actual),
                "expected": strict_json_clone(expected),
                "status": status,
                "message": message,
            }
        )
    verdict = (
        "ERROR" if any(item["status"] == "ERROR" for item in facts)
        else "FAIL" if any(item["status"] == "FAIL" for item in facts)
        else "PASS"
    )
    return {"verdict": verdict, "rules": facts}
