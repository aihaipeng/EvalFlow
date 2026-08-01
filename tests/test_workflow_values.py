import pytest

from execution.workflow_values import (
    WorkflowOutputSourceError,
    WorkflowOutputTypeError,
    WorkflowValueError,
    convert_output,
    extract_output,
    parse_json_template,
    resolve_template,
)


def test_template_resolution_preserves_full_value_and_records_root_inputs():
    context = {"User": {"name": "张三", "roles": ["admin"]}, "count": 3}

    resolved, inputs = resolve_template(
        {"body": "${User}", "message": "你好 ${User.name} ${count}"}, context
    )

    assert resolved == {
        "body": {"name": "张三", "roles": ["admin"]},
        "message": "你好 张三 3",
    }
    assert inputs == context


def test_template_resolution_is_case_sensitive_and_supports_escape():
    resolved, inputs = resolve_template(r"\${Name} ${name}", {"name": "ok"})
    assert resolved == "${Name} ok"
    assert inputs == {"name": "ok"}
    with pytest.raises(WorkflowValueError, match="Name"):
        resolve_template("${Name}", {"name": "ok"})


def test_json_template_safely_injects_unquoted_and_quoted_string_variables():
    question = '中文 "quote" \\ path\nnext line'

    resolved, inputs = parse_json_template(
        '{"raw": ${input.question}, "quoted": "${input.question}"}',
        {"input": {"question": question}},
    )

    assert resolved == {"raw": question, "quoted": question}
    assert inputs == {"input": {"question": question}}


def test_json_template_rejects_invalid_final_json_and_missing_variables():
    with pytest.raises(WorkflowValueError, match="不是合法 JSON"):
        parse_json_template('{"question": ${input.question}', {"input": {"question": "x"}})
    with pytest.raises(WorkflowValueError, match="Context 变量不存在"):
        parse_json_template('{"question": ${missing}}', {})


@pytest.mark.parametrize(
    ("source", "expected"),
    [
        ("response.data[id==3]", {"id": 3, "name": "three"}),
        ("response.data[id>=2].name", ["two-hr", "three"]),
        ('response.data[name contain "two-"]', {"id": 2, "name": "two-hr"}),
        ("request.items[0].value", 7),
        ("request.items[-1].value", 9),
        ("request.items[-2].value", 7),
        ("response.missing", None),
    ],
)
def test_output_extraction_supports_fields_indexes_filters_and_operators(source, expected):
    facts = {
        "request": {"items": [{"value": 7}, {"value": 9}]},
        "response": {
            "data": [
                {"id": 1, "name": "one"},
                {"id": 2, "name": "two-hr"},
                {"id": 3, "name": "three"},
            ]
        },
    }
    assert extract_output(source, facts) == expected


def test_output_extraction_reads_last_llm_choice_with_python_negative_index():
    facts = {
        "response": {
            "choices": [
                {"message": {"content": "first choice"}},
                {"message": {"content": "last choice"}},
            ]
        }
    }

    assert (
        extract_output("response.choices[-1].message.content", facts)
        == "last choice"
    )


@pytest.mark.parametrize(
    "source",
    [
        "response.choices[-2].message.content",
        "response.choices[2].message.content",
    ],
)
def test_output_extraction_rejects_python_integer_indexes_outside_array(source):
    facts = {
        "response": {
            "choices": [
                {"message": {"content": "only choice"}},
            ]
        }
    }

    with pytest.raises(WorkflowOutputSourceError, match="数组下标越界"):
        extract_output(source, facts)


@pytest.mark.parametrize("source", ["response.choices[1:]", "response.choices[1+1]"])
def test_output_extraction_rejects_slices_and_index_expressions(source):
    with pytest.raises(WorkflowOutputSourceError, match="下标无效"):
        extract_output(source, {"response": {"choices": []}})


@pytest.mark.parametrize(
    ("source", "message"),
    [
        ("response.value[id==1]", "非数组值使用了过滤器"),
        ("response.data[value>\"1\"]", "排序比较只支持"),
        ("response.data[value contain 1]", "contain 只支持"),
        ("response.data[value==unquoted]", "严格 JSON scalar"),
    ],
)
def test_output_extraction_rejects_invalid_filter_types_and_literals(source, message):
    facts = {
        "response": {
            "value": {"id": 1},
            "data": [{"value": {"nested": True}}],
        }
    }

    with pytest.raises(WorkflowOutputSourceError, match=message):
        extract_output(source, facts)


def test_output_filter_uses_strict_json_equality_with_one_numeric_domain():
    facts = {
        "response": {
            "data": [
                {"value": True, "label": "boolean"},
                {"value": 1.0, "label": "number"},
            ]
        }
    }

    assert extract_output("response.data[value==1].label", facts) == "number"


@pytest.mark.parametrize(
    ("value", "target", "expected"),
    [
        ({"id": 3}, "string", '{"id":3}'),
        ("3", "integer", 3),
        (1.0, "integer", 1),
        ("1.25", "number", 1.25),
        ("FALSE", "boolean", False),
        ('{"id":3}', "object", {"id": 3}),
        ("[1,2]", "array", [1, 2]),
        ("null", "null", None),
    ],
)
def test_output_conversion_matrix(value, target, expected):
    assert convert_output(value, target) == expected


@pytest.mark.parametrize(
    ("value", "target"),
    [
        (" 3", "integer"),
        ("01", "number"),
        (1.2, "integer"),
        ("yes", "boolean"),
        (" null ", "null"),
        ("[]", "object"),
        ("0.123456789012345678901", "number"),
    ],
)
def test_output_conversion_rejects_undefined_or_lossy_paths(value, target):
    with pytest.raises(WorkflowOutputTypeError):
        convert_output(value, target)
