"""Evaluate final Workflow Context against typed, user-authored expectations."""

from __future__ import annotations

import json
import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from execution.workflow_values import (
    WorkflowOutputTypeError,
    WorkflowValueError,
    convert_output,
    resolve_path,
    strict_json_clone,
)


class _EvaluationModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class EvaluationRule(_EvaluationModel):
    """One typed assertion over the final Workflow Context."""

    result_path: str = Field(min_length=9, max_length=4000)
    operator: Literal[
        "EQ", "NE", "CONTAINS", "REGEX", "EXISTS", "GT", "GTE", "LT", "LTE", "JSON_EQUAL"
    ]
    expected_value: str = Field(default="", max_length=20000)
    type: Literal["string", "number", "integer", "boolean", "object", "array", "null"]

    @model_validator(mode="after")
    def validate_rule(self) -> "EvaluationRule":
        if not self.result_path.startswith("context."):
            raise ValueError("结果路径必须以 context. 开头")
        try:
            resolve_path({}, self.result_path[len("context.") :])
        except WorkflowValueError as exc:
            if "对象字段不存在" not in str(exc):
                raise ValueError(f"结果路径无效: {self.result_path}") from exc
        try:
            expected = convert_output(self.expected_value, self.type)
        except WorkflowOutputTypeError as exc:
            raise ValueError(f"预期值与 {self.type} 不匹配: {exc}") from exc
        if self.operator == "REGEX":
            if not isinstance(expected, str):
                raise ValueError("正则预期值必须是 string")
            try:
                re.compile(expected)
            except re.error as exc:
                raise ValueError(f"正则表达式无效: {exc}") from exc
        if self.operator == "EXISTS" and not isinstance(expected, bool):
            raise ValueError("存在性规则的预期值 type 必须是 boolean")
        return self

    @property
    def context_path(self) -> str:
        return self.result_path[len("context.") :]


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
        if isinstance(actual, (list, dict)):
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


def evaluate_case(context: dict[str, Any], rules: list[EvaluationRule]) -> dict[str, Any]:
    """Evaluate all rules with AND semantics and retain each rule's facts."""

    facts = []
    for rule in rules:
        actual_exists = True
        try:
            actual = resolve_path(context, rule.context_path)
        except WorkflowValueError:
            actual_exists = False
            actual = None
        try:
            expected = convert_output(rule.expected_value, rule.type)
            passed = (
                actual_exists is expected
                if rule.operator == "EXISTS"
                else _compare(rule.operator, actual, expected)
                if actual_exists
                else False
            )
            status = "PASS" if passed else "FAIL"
            message = None if passed else (
                f"结果路径不存在: {rule.result_path}"
                if not actual_exists else "实际值不符合预期"
            )
        except (TypeError, ValueError, re.error, WorkflowOutputTypeError) as exc:
            expected = None
            status = "ERROR"
            message = str(exc)
        facts.append(
            {
                "result_path": rule.result_path,
                "operator": rule.operator,
                "expected_value": rule.expected_value,
                "type": rule.type,
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
