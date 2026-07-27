import pytest
from pydantic import ValidationError

from execution.case_evaluator import EvaluationRule, evaluate_case


def rule(**overrides):
    payload = {
        "name": "answer matches",
        "actual_path": "answer.text",
        "operator": "EQ",
        "expected": {"source": "LITERAL", "value": "OK", "column": None},
    }
    payload.update(overrides)
    return EvaluationRule.model_validate(payload)


def test_evaluator_supports_literal_excel_regex_contains_and_numeric_rules():
    result = {"answer": {"text": "CI SWITCH_1 is healthy", "score": 0.95}, "tags": ["cmdb"]}
    source = {"expected_text": "CI SWITCH_1 is healthy", "minimum": 0.9}
    rules = [
        rule(expected={"source": "EXCEL", "column": "expected_text", "value": None}),
        rule(name="regex", operator="REGEX", expected={"source": "LITERAL", "value": r"SWITCH_\d", "column": None}),
        rule(name="contains", actual_path="tags", operator="CONTAINS", expected={"source": "LITERAL", "value": "cmdb", "column": None}),
        rule(name="score", actual_path="answer.score", operator="GTE", expected={"source": "EXCEL", "column": "minimum", "value": None}),
        rule(name="exists", actual_path="answer.text", operator="EXISTS", expected={"source": "LITERAL", "value": True, "column": None}),
    ]

    evaluation = evaluate_case(result, source, rules)

    assert evaluation["verdict"] == "PASS"
    assert {item["status"] for item in evaluation["rules"]} == {"PASS"}


def test_evaluator_distinguishes_failed_expectation_from_configuration_error():
    failed = evaluate_case(
        {"answer": {"text": "actual"}},
        {},
        [rule(expected={"source": "LITERAL", "value": "expected", "column": None})],
    )
    errored = evaluate_case(
        {"answer": {"text": "actual"}},
        {},
        [rule(operator="GT", expected={"source": "LITERAL", "value": 3, "column": None})],
    )

    assert failed["verdict"] == "FAIL"
    assert failed["rules"][0]["actual"] == "actual"
    assert errored["verdict"] == "ERROR"
    assert "有限数字" in errored["rules"][0]["message"]


def test_evaluator_reports_missing_result_and_excel_paths():
    missing_result = evaluate_case({}, {}, [rule()])
    missing_excel = evaluate_case(
        {"answer": {"text": "OK"}},
        {},
        [rule(expected={"source": "EXCEL", "column": "expected", "value": None})],
    )

    assert missing_result["verdict"] == "FAIL"
    assert "结果路径不存在" in missing_result["rules"][0]["message"]
    assert missing_excel["verdict"] == "ERROR"
    assert "Excel 预期列不存在" in missing_excel["rules"][0]["message"]


def test_rule_validation_rejects_invalid_regex_and_exists_expectation():
    with pytest.raises(ValidationError, match="正则表达式无效"):
        rule(operator="REGEX", expected={"source": "LITERAL", "value": "[", "column": None})
    with pytest.raises(ValidationError, match="boolean"):
        rule(operator="EXISTS", expected={"source": "LITERAL", "value": "true", "column": None})
