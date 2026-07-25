from copy import deepcopy

import pytest
from pydantic import ValidationError

from execution.workflow_contract import (
    ERROR_CODES,
    WorkflowContractError,
    WorkflowDefinition,
    ensure_strict_json,
    normalize_context_name,
    value_matches_type,
)


WORKFLOW_ID = "123e4567-e89b-42d3-a456-426614174000"
START_ID = "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44"
SCRIPT_ID = "550e8400-e29b-41d4-a716-446655440000"
END_ID = "0f8fad5b-d9cb-469f-a165-70867728950e"
EDGE_ONE = "4c1f2e3d-6b7a-48c9-9d01-23456789abcd"
EDGE_TWO = "5d2e3f4a-7b8c-49d0-a123-456789abcdef"


def workflow_payload() -> dict:
    return {
        "workflow_id": WORKFLOW_ID,
        "name": "Contract test",
        "description": "",
        "nodes": [
            {
                "id": START_ID,
                "type": "START",
                "name": "Input",
                "description": "",
                "inputs": [{"name": "Conversation", "type": "string", "data": "hello"}],
            },
            {
                "id": SCRIPT_ID,
                "type": "SCRIPT",
                "name": "Transform",
                "description": "",
                "script": 'value = get_val("conversation")',
                "execution": {"timeout_ms": 1000, "max_attempts": 0, "delay_ms": 0},
                "outputs": [{"name": "Result", "type": "string"}],
            },
            {"id": END_ID, "type": "END", "name": "End", "description": ""},
        ],
        "edges": [
            {"edge_id": EDGE_ONE, "source": START_ID, "target": SCRIPT_ID},
            {"edge_id": EDGE_TWO, "source": SCRIPT_ID, "target": END_ID},
        ],
    }


def test_contract_accepts_start_script_end_and_normalizes_context_names():
    workflow = WorkflowDefinition.model_validate(workflow_payload())

    assert workflow.workflow_id == WORKFLOW_ID
    assert workflow.nodes[0].inputs[0].name == "conversation"
    assert workflow.nodes[1].outputs[0].name == "result"
    assert workflow.model_dump(mode="json")["edges"][0]["edge_id"] == EDGE_ONE


def test_contract_supports_parallel_branches_that_join_at_end():
    payload = workflow_payload()
    http_id = "6ba7b810-9dad-41d1-80b4-00c04fd430c8"
    join_id = "7c9e6679-7425-40de-944b-e07fc1f90ae7"
    payload["nodes"].extend(
        [
            {
                "id": http_id,
                "type": "HTTP",
                "name": "Lookup",
                "description": "",
                "request": {
                    "method": "GET",
                    "url": "https://example.test/items",
                    "follow_redirects": True,
                    "headers": [],
                    "params": [],
                    "body": {"type": "none", "content": None},
                },
                "network": {"proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None}, "verify_ssl": True},
                "response": {"body_type": "json"},
                "execution": {"timeout_ms": 1000, "max_attempts": 1, "delay_ms": 0},
                "outputs": [{"name": "http_result", "type": "object", "path": "$.response.body"}],
            },
            {
                "id": join_id,
                "type": "SCRIPT",
                "name": "Join",
                "description": "",
                "script": "pass",
                "execution": {"timeout_ms": 1000, "max_attempts": 0, "delay_ms": 0},
                "outputs": [{"name": "joined", "type": "string"}],
            },
        ]
    )
    payload["edges"] = [
        {"edge_id": EDGE_ONE, "source": START_ID, "target": SCRIPT_ID},
        {"edge_id": EDGE_TWO, "source": START_ID, "target": http_id},
        {"edge_id": "8d2e3f4a-7b8c-49d0-a123-456789abcdef", "source": SCRIPT_ID, "target": join_id},
        {"edge_id": "9e2e3f4a-7b8c-49d0-a123-456789abcdef", "source": http_id, "target": join_id},
        {"edge_id": "aa2e3f4a-7b8c-49d0-a123-456789abcdef", "source": join_id, "target": END_ID},
    ]

    workflow = WorkflowDefinition.model_validate(payload)

    assert len(workflow.nodes) == 5


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("abc", "string"),
        (1, "integer"),
        (1, "number"),
        (1.5, "number"),
        (True, "boolean"),
        ({"id": "x"}, "object"),
        (["x"], "array"),
        (None, "null"),
    ],
)
def test_value_types_follow_strict_json_rules(value, expected):
    assert value_matches_type(value, expected)


def test_integer_does_not_accept_boolean_or_float():
    assert not value_matches_type(True, "integer")
    assert not value_matches_type(1.0, "integer")


def test_context_name_is_lowercase_and_rejects_invalid_names():
    assert normalize_context_name("Result_1") == "result_1"
    with pytest.raises(WorkflowContractError):
        normalize_context_name("1result")


def test_strict_json_rejects_non_finite_values():
    with pytest.raises(WorkflowContractError):
        ensure_strict_json({"value": float("nan")})


def test_contract_rejects_duplicate_context_outputs_across_nodes():
    payload = workflow_payload()
    payload["nodes"].append(
        {
            "id": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
            "type": "SCRIPT",
            "name": "Duplicate",
            "description": "",
            "script": "pass",
            "execution": {"timeout_ms": 1000, "max_attempts": 0, "delay_ms": 0},
            "outputs": [{"name": "RESULT", "type": "string"}],
        }
    )
    payload["edges"].append(
        {"edge_id": "8d2e3f4a-7b8c-49d0-a123-456789abcdef", "source": SCRIPT_ID, "target": "6ba7b810-9dad-41d1-80b4-00c04fd430c8"}
    )
    payload["edges"].append(
        {"edge_id": "9e2e3f4a-7b8c-49d0-a123-456789abcdef", "source": "6ba7b810-9dad-41d1-80b4-00c04fd430c8", "target": END_ID}
    )

    with pytest.raises(ValidationError, match="globally unique"):
        WorkflowDefinition.model_validate(payload)


def test_contract_rejects_non_uuid4_identity_fields():
    payload = workflow_payload()
    payload["workflow_id"] = "123e4567-e89b-12d3-a456-426614174000"

    with pytest.raises(ValidationError, match="UUIDv4"):
        WorkflowDefinition.model_validate(payload)


def test_contract_rejects_llm_reserved_parameter_keys():
    payload = workflow_payload()
    payload["nodes"][1] = {
        "id": SCRIPT_ID,
        "type": "LLM",
        "name": "LLM",
        "description": "",
        "model": {"provider_id": "provider-a", "model_name": "model-a"},
        "prompt": {"system": "", "user": "Hello"},
        "generation": {"stream": False, "parameters": {"model": "override"}},
        "execution": {"timeout_ms": 1000, "max_attempts": 0, "delay_ms": 0},
        "outputs": [],
    }

    with pytest.raises(ValidationError, match="reserved keys"):
        WorkflowDefinition.model_validate(payload)


def test_contract_rejects_context_reference_without_an_upstream_producer():
    payload = workflow_payload()
    payload["nodes"][1]["script"] = 'value = get_val("missing")'

    with pytest.raises(ValidationError, match="does not exist"):
        WorkflowDefinition.model_validate(payload)


def test_contract_rejects_context_reference_from_a_parallel_branch():
    payload = workflow_payload()
    parallel_id = "6ba7b810-9dad-41d1-80b4-00c04fd430c8"
    payload["nodes"].append(
        {
            "id": parallel_id,
            "type": "SCRIPT",
            "name": "Parallel",
            "description": "",
            "script": 'value = get_val("result")',
            "execution": {"timeout_ms": 1000, "max_attempts": 0, "delay_ms": 0},
            "outputs": [{"name": "parallel_result", "type": "string"}],
        }
    )
    payload["edges"].append(
        {"edge_id": "8d2e3f4a-7b8c-49d0-a123-456789abcdef", "source": START_ID, "target": parallel_id}
    )
    payload["edges"].append(
        {"edge_id": "9e2e3f4a-7b8c-49d0-a123-456789abcdef", "source": parallel_id, "target": END_ID}
    )

    with pytest.raises(ValidationError, match="not provided by an upstream"):
        WorkflowDefinition.model_validate(payload)


def test_contract_rejects_duplicate_http_header_names_ignoring_case():
    payload = workflow_payload()
    payload["nodes"][1] = {
        "id": SCRIPT_ID,
        "type": "HTTP",
        "name": "HTTP",
        "description": "",
        "request": {
            "method": "GET",
            "url": "https://example.test",
            "follow_redirects": True,
            "headers": [{"key": "X-Trace", "value": "1"}, {"key": "x-trace", "value": "2"}],
            "params": [],
            "body": {"type": "none", "content": None},
        },
        "network": {"proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None}, "verify_ssl": True},
        "response": {"body_type": "json"},
        "execution": {"timeout_ms": 1000, "max_attempts": 0, "delay_ms": 0},
        "outputs": [],
    }

    with pytest.raises(ValidationError, match="unique ignoring case"):
        WorkflowDefinition.model_validate(payload)


def test_error_catalog_contains_empty_prompt_code():
    assert "LLM_PROMPT_EMPTY" in ERROR_CODES
