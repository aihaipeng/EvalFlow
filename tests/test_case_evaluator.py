import pytest
from pydantic import ValidationError

from execution.case_evaluator import EvaluationRule, evaluate_case


def rule(**overrides):
    payload = {
        "result_path": "context.final_answer.status",
        "operator": "EQ",
        "expected_value": "PASS",
        "type": "string",
    }
    payload.update(overrides)
    return EvaluationRule.model_validate(payload)


def test_evaluator_reads_final_context_and_supports_typed_rules():
    context = {
        "final_answer": {"status": "PASS", "score": 0.95},
        "tags": ["cmdb"],
    }
    rules = [
        rule(name="最终状态"),
        rule(
            result_path="final_answer.status",
            operator="REGEX",
            expected_value=r"PA.*",
            type="string",
        ),
        rule(
            result_path="context.tags",
            operator="CONTAINS",
            expected_value="cmdb",
            type="string",
        ),
        rule(
            result_path="context.final_answer.score",
            operator="GTE",
            expected_value="0.9",
            type="number",
        ),
        rule(
            result_path="context.final_answer.status",
            operator="EXISTS",
            expected_value="true",
            type="boolean",
        ),
    ]

    evaluation = evaluate_case(context, rules)

    assert evaluation["verdict"] == "PASS"
    assert {item["status"] for item in evaluation["rules"]} == {"PASS"}
    assert evaluation["rules"][0]["actual"] == "PASS"
    assert evaluation["rules"][0]["name"] == "最终状态"
    assert evaluation["rules"][1]["name"] == ""
    assert evaluation["rules"][1]["result_path"] == "context.final_answer.status"


def test_evaluator_marks_any_failed_rule_and_missing_context_path():
    evaluation = evaluate_case(
        {"final_answer": {"status": "FAIL"}},
        [rule(), rule(result_path="context.final_answer.missing")],
    )

    assert evaluation["verdict"] == "FAIL"
    assert [item["status"] for item in evaluation["rules"]] == ["FAIL", "FAIL"]
    assert "结果路径不存在" in evaluation["rules"][1]["message"]


@pytest.mark.parametrize(
    ("value", "expected_status"),
    [
        (None, "FAIL"),
        ("", "FAIL"),
        ("   ", "FAIL"),
        ([], "FAIL"),
        ({}, "FAIL"),
        (0, "PASS"),
        (False, "PASS"),
        ("ready", "PASS"),
        ([0], "PASS"),
        ({"ready": False}, "PASS"),
    ],
)
def test_not_empty_uses_business_empty_semantics(value, expected_status):
    evaluation = evaluate_case(
        {"value": value},
        [
            rule(
                result_path="value",
                operator="NOT_EMPTY",
                expected_value="",
                type="string",
            )
        ],
    )

    assert evaluation["rules"][0]["status"] == expected_status
    assert evaluation["rules"][0]["expected"] is None


def test_not_empty_fails_when_context_path_is_missing():
    evaluation = evaluate_case(
        {},
        [rule(result_path="missing", operator="NOT_EMPTY", expected_value="", type="string")],
    )

    assert evaluation["verdict"] == "FAIL"
    assert "结果路径不存在" in evaluation["rules"][0]["message"]


def test_rule_validation_rejects_invalid_path_regex_and_exists_type():
    with pytest.raises(ValidationError, match="结果路径无效"):
        rule(result_path="final_answer[status")
    with pytest.raises(ValidationError, match="正则表达式无效"):
        rule(operator="REGEX", expected_value="[", type="string")
    with pytest.raises(ValidationError, match="boolean"):
        rule(operator="EXISTS", expected_value="true", type="string")
