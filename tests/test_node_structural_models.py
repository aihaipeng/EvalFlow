import inspect
import json
import sqlite3

import pytest
from pydantic import BaseModel, ValidationError

import execution.node_structural_models as node_structural_module

from execution.node_structural_models import (
    NODE_STRUCTURAL_ADAPTER,
    NODE_STRUCTURAL_COLUMN_DESCRIPTIONS,
    NODE_STRUCTURAL_TABLE_DESCRIPTION,
    LEGACY_WORKFLOW_TABLES,
    NodeStructuralRepository,
    NodeStructuralRepositoryError,
)


NODE_IDS = {
    "START": "2f1a8c40-6b7d-4e92-a135-9c0d7b5e2f44",
    "SCRIPT": "550e8400-e29b-41d4-a716-446655440000",
    "LLM": "6ba7b810-9dad-41d1-80b4-00c04fd430c8",
    "HTTP": "7c9e6679-7425-40de-944b-e07fc1f90ae7",
    "END": "8d9e6679-7425-40de-944b-e07fc1f90ae7",
}


def test_every_defined_class_and_pydantic_field_has_documentation():
    defined_classes = [
        cls
        for _, cls in inspect.getmembers(node_structural_module, inspect.isclass)
        if cls.__module__ == node_structural_module.__name__
    ]

    assert defined_classes
    for cls in defined_classes:
        assert inspect.getdoc(cls), f"{cls.__name__} 缺少类说明"
        if issubclass(cls, BaseModel):
            for field_name, field in cls.model_fields.items():
                assert field.description, f"{cls.__name__}.{field_name} 缺少字段说明"


def node_payloads() -> list[dict]:
    execution = {
        "timeout_seconds": 30,
        "max_attempts": 2,
        "retry_interval_seconds": 0.5,
        "delay_seconds": 0,
    }
    return [
        {
            "id": NODE_IDS["START"],
            "type": "START",
            "name": "输入",
            "description": "提供初始变量",
            "inputs": [
                {"name": "conversation", "type": "string", "value": "请审核"},
                {"name": "retry_count", "type": "integer", "value": 3},
            ],
        },
        {
            "id": NODE_IDS["SCRIPT"],
            "type": "SCRIPT",
            "name": "规则校验",
            "description": "运行 Python 规则",
            "script": "result = context['conversation']",
            "execution": execution,
            "outputs": [{"name": "script_result", "type": "string", "source": "result"}],
        },
        {
            "id": NODE_IDS["LLM"],
            "type": "LLM",
            "name": "模型判断",
            "description": "调用已有模型",
            "model": {"provider_id": "provider-deepseek", "model_name": "deepseek-v4-pro"},
            "context": {
                "messages": [
                    {"role": "SYSTEM", "content": "你是质量审核员"},
                    {"role": "USER", "content": "以下是示例输入"},
                    {"role": "ASSISTANT", "content": "示例结论"},
                    {"role": "USER", "content": "请判断 ${conversation}"},
                ]
            },
            "generation": {"parameters": {"temperature": 0}},
            "execution": execution,
            "outputs": [
                {
                    "name": "llm_text",
                    "type": "string",
                    "source": "response.choices[0].message.content",
                }
            ],
        },
        {
            "id": NODE_IDS["HTTP"],
            "type": "HTTP",
            "name": "内网查询",
            "description": "调用内网 CMDB",
            "request": {
                "method": "POST",
                "url": "https://cmdb.internal/api/ci",
                "follow_redirects": True,
                "headers": [{"key": "Authorization", "value": "Bearer ${api_token}"}],
                "params": [{"key": "scope", "value": "${scope}"}],
                "body": {"type": "raw", "content": {"name": "${ci_name}"}},
            },
            "network": {
                "proxy": {"mode": "DIRECT", "url": None, "username": None, "password": None},
                "verify_ssl": True,
            },
            "response": {"mode": "AUTO", "success_statuses": ["200-299"]},
            "execution": {
                **execution,
                "retry_non_idempotent": False,
                "retry_statuses": [408, 429, 500, 502, 503, 504],
            },
            "outputs": [{"name": "ci_id", "type": "string", "source": "response.body.id"}],
        },
        {
            "id": NODE_IDS["END"],
            "type": "END",
            "name": "结束",
            "description": "结构终点",
        },
    ]


def test_initialize_creates_documented_node_table_and_removes_legacy_tables(tmp_path):
    database = tmp_path / "nodes.sqlite3"
    with sqlite3.connect(database) as connection:
        for table in LEGACY_WORKFLOW_TABLES:
            connection.execute(f'CREATE TABLE "{table}"(id TEXT PRIMARY KEY)')
        connection.execute("CREATE TABLE targets(id TEXT PRIMARY KEY, name TEXT NOT NULL)")
        connection.execute("INSERT INTO targets VALUES ('target-1', '保留的 Target')")

    NodeStructuralRepository(database).initialize()

    with sqlite3.connect(database) as connection:
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        columns = {
            row[1] for row in connection.execute("PRAGMA table_info(node_structural_models)")
        }
        indexes = {
            row[1] for row in connection.execute("PRAGMA index_list(node_structural_models)")
        }
        target = connection.execute("SELECT id, name FROM targets").fetchone()

    assert "node_structural_models" in tables
    assert set(LEGACY_WORKFLOW_TABLES).isdisjoint(tables)
    assert "targets" in tables
    assert target == ("target-1", "保留的 Target")
    assert columns == set(NODE_STRUCTURAL_COLUMN_DESCRIPTIONS)
    assert NODE_STRUCTURAL_TABLE_DESCRIPTION
    assert all(NODE_STRUCTURAL_COLUMN_DESCRIPTIONS.values())
    assert "node_structural_models_by_type_updated" in indexes


def test_repository_round_trips_all_five_node_types_after_restart(tmp_path):
    database = tmp_path / "nodes.sqlite3"
    repository = NodeStructuralRepository(database)
    created = [
        repository.create(
            NODE_STRUCTURAL_ADAPTER.validate_python(payload),
            timestamp=f"2026-07-26T10:00:0{index}.000+00:00",
        )
        for index, payload in enumerate(node_payloads())
    ]

    restarted = NodeStructuralRepository(database)
    restored = restarted.list()

    assert {record.node.type for record in restored} == {"START", "SCRIPT", "LLM", "HTTP", "END"}
    assert len(created) == len(restored) == 5
    assert restarted.get(NODE_IDS["SCRIPT"]).node.script == "result = context['conversation']"
    assert restarted.get(NODE_IDS["LLM"]).node.model.model_name == "deepseek-v4-pro"
    assert [
        message.role for message in restarted.get(NODE_IDS["LLM"]).node.context.messages
    ] == ["SYSTEM", "USER", "ASSISTANT", "USER"]
    assert restarted.get(NODE_IDS["HTTP"]).node.request.body.content == {"name": "${ci_name}"}


def test_database_separates_common_columns_from_type_definition_json(tmp_path):
    database = tmp_path / "nodes.sqlite3"
    repository = NodeStructuralRepository(database)
    node = NODE_STRUCTURAL_ADAPTER.validate_python(node_payloads()[1])
    repository.create(node, timestamp="2026-07-26T10:00:00.000+00:00")

    with sqlite3.connect(database) as connection:
        row = connection.execute(
            "SELECT id, type, name, description, definition_json FROM node_structural_models"
        ).fetchone()
    definition = json.loads(row[4])

    assert row[:4] == (node.id, "SCRIPT", "规则校验", "运行 Python 规则")
    assert set(definition) == {"script", "execution", "outputs"}
    assert not {"id", "type", "name", "description"} & set(definition)


def test_execution_seconds_support_fractions_and_reject_legacy_millisecond_fields():
    payload = node_payloads()[1]
    payload["execution"] = {
        "timeout_seconds": 0.125,
        "max_attempts": 1,
        "retry_interval_seconds": 0.25,
        "delay_seconds": 0.375,
    }

    node = NODE_STRUCTURAL_ADAPTER.validate_python(payload)

    assert node.execution.model_dump(mode="json") == payload["execution"]
    legacy = node_payloads()[1]
    legacy["execution"] = {
        "timeout_ms": 125,
        "max_attempts": 1,
        "delay_ms": 250,
    }
    with pytest.raises(ValidationError):
        NODE_STRUCTURAL_ADAPTER.validate_python(legacy)


@pytest.mark.parametrize("payload_index", [1, 2, 3])
def test_business_nodes_apply_complete_platform_execution_defaults(payload_index):
    payload = node_payloads()[payload_index]
    payload.pop("execution")

    node = NODE_STRUCTURAL_ADAPTER.validate_python(payload)

    assert node.execution.model_dump(mode="json", exclude_defaults=False) == {
        "timeout_seconds": 600.0,
        "max_attempts": 0,
        "retry_interval_seconds": 0.0,
        "delay_seconds": 0.0,
        **(
            {
                "retry_non_idempotent": False,
                "retry_statuses": [408, 429, 500, 502, 503, 504],
            }
            if payload["type"] == "HTTP"
            else {}
        ),
    }


@pytest.mark.parametrize("payload_index", [1, 2, 3])
def test_business_nodes_merge_partial_execution_with_platform_defaults(payload_index):
    payload = node_payloads()[payload_index]
    payload["execution"] = {"timeout_seconds": 45.5}

    node = NODE_STRUCTURAL_ADAPTER.validate_python(payload)

    assert node.execution.timeout_seconds == 45.5
    assert node.execution.max_attempts == 0
    assert node.execution.retry_interval_seconds == 0
    assert node.execution.delay_seconds == 0


def test_empty_execution_object_uses_platform_defaults():
    payload = node_payloads()[1]
    payload["execution"] = {}

    node = NODE_STRUCTURAL_ADAPTER.validate_python(payload)

    assert node.execution.model_dump(mode="json") == {
        "timeout_seconds": 600.0,
        "max_attempts": 0,
        "retry_interval_seconds": 0.0,
        "delay_seconds": 0.0,
    }


@pytest.mark.parametrize(
    ("node_type", "expected"),
    [
        ("SCRIPT", {"script": ""}),
        (
            "LLM",
            {
                "model": {"provider_id": "", "model_name": ""},
                "context": {
                    "messages": [
                        {"role": "SYSTEM", "content": ""},
                        {"role": "USER", "content": ""},
                    ]
                },
            },
        ),
        (
            "HTTP",
            {
                "request": {
                    "method": "POST",
                    "url": "",
                    "follow_redirects": True,
                    "headers": [],
                    "params": [],
                    "body": {"type": "none", "content": None, "template_text": None},
                }
            },
        ),
    ],
)
def test_business_nodes_allow_missing_runtime_configuration(node_type, expected):
    node = NODE_STRUCTURAL_ADAPTER.validate_python(
        {
            "id": NODE_IDS[node_type],
            "type": node_type,
            "name": f"空白 {node_type}",
            "description": "",
        }
    )

    dumped = node.model_dump(mode="json")
    for key, value in expected.items():
        assert dumped[key] == value


def test_llm_context_allows_incomplete_trailing_assistant_draft():
    payload = node_payloads()[2]
    payload["context"]["messages"] = payload["context"]["messages"][:3]
    payload["context"]["messages"][-1]["content"] = ""

    node = NODE_STRUCTURAL_ADAPTER.validate_python(payload)

    assert [message.role for message in node.context.messages] == [
        "SYSTEM",
        "USER",
        "ASSISTANT",
    ]


def test_llm_generation_allows_invalid_parameter_draft_text():
    payload = node_payloads()[2]
    payload["generation"] = {
        "parameters": {"temperature": 0},
        "parameters_text": '{"temperature":',
    }

    node = NODE_STRUCTURAL_ADAPTER.validate_python(payload)

    assert node.generation.parameters == {"temperature": 0}
    assert node.generation.parameters_text == '{"temperature":'


@pytest.mark.parametrize(
    "messages",
    [
        [],
        [{"role": "SYSTEM", "content": ""}],
        [
            {"role": "USER", "content": ""},
            {"role": "SYSTEM", "content": ""},
        ],
        [
            {"role": "SYSTEM", "content": ""},
            {"role": "USER", "content": ""},
            {"role": "USER", "content": ""},
        ],
        [
            {"role": "system", "content": ""},
            {"role": "user", "content": ""},
        ],
    ],
)
def test_llm_context_rejects_invalid_message_sequence(messages):
    payload = node_payloads()[2]
    payload["context"] = {"messages": messages}

    with pytest.raises(ValidationError):
        NODE_STRUCTURAL_ADAPTER.validate_python(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {
            "id": NODE_IDS["HTTP"],
            "type": "HTTP",
            "name": "错误 URL",
            "description": "",
            "request": {"url": "not-a-url"},
        },
        {
            "id": NODE_IDS["HTTP"],
            "type": "HTTP",
            "name": "错误 Proxy",
            "description": "",
            "network": {"proxy": {"mode": "CUSTOM", "url": "ftp://proxy"}},
        },
    ],
)
def test_nonempty_invalid_http_configuration_is_still_rejected(payload):
    with pytest.raises(ValidationError):
        NODE_STRUCTURAL_ADAPTER.validate_python(payload)


def test_http_request_url_trims_leading_and_trailing_whitespace():
    payload = node_payloads()[3]
    payload["request"]["url"] = "  https://example.com/path?q=a%20b  \r\n"

    node = NODE_STRUCTURAL_ADAPTER.validate_python(payload)

    assert node.request.url == "https://example.com/path?q=a%20b"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("timeout_seconds", 0.0009),
        ("timeout_seconds", float("inf")),
        ("retry_interval_seconds", 600.001),
        ("delay_seconds", float("nan")),
        ("delay_seconds", "1"),
    ],
)
def test_execution_seconds_reject_invalid_values(field, value):
    payload = node_payloads()[1]
    payload["execution"][field] = value

    with pytest.raises(ValidationError):
        NODE_STRUCTURAL_ADAPTER.validate_python(payload)


def test_update_preserves_created_at_and_delete_is_idempotent(tmp_path):
    repository = NodeStructuralRepository(tmp_path / "nodes.sqlite3")
    payload = node_payloads()[0]
    original = NODE_STRUCTURAL_ADAPTER.validate_python(payload)
    repository.create(original, timestamp="2026-07-26T10:00:00.000+00:00")
    updated = NODE_STRUCTURAL_ADAPTER.validate_python({**payload, "name": "新输入"})

    saved = repository.update(updated, timestamp="2026-07-26T11:00:00.000+00:00")

    assert saved.node.name == "新输入"
    assert saved.created_at == "2026-07-26T10:00:00.000+00:00"
    assert saved.updated_at == "2026-07-26T11:00:00.000+00:00"
    assert repository.list(node_type="START")[0].node.name == "新输入"
    assert repository.delete(original.id)
    assert not repository.delete(original.id)
    assert repository.get(original.id) is None


def test_repository_rejects_duplicate_id_unknown_update_and_invalid_filter(tmp_path):
    repository = NodeStructuralRepository(tmp_path / "nodes.sqlite3")
    node = NODE_STRUCTURAL_ADAPTER.validate_python(node_payloads()[4])
    repository.create(node)

    with pytest.raises(NodeStructuralRepositoryError, match="写入节点"):
        repository.create(node)
    with pytest.raises(NodeStructuralRepositoryError, match="节点不存在"):
        repository.update(
            NODE_STRUCTURAL_ADAPTER.validate_python(
                {**node_payloads()[4], "id": "9d9e6679-7425-40de-944b-e07fc1f90ae7"}
            )
        )
    with pytest.raises(NodeStructuralRepositoryError, match="节点类型无效"):
        repository.list(node_type="AGENT")


def test_repository_rejects_changing_node_type_after_creation(tmp_path):
    repository = NodeStructuralRepository(tmp_path / "nodes.sqlite3")
    start = NODE_STRUCTURAL_ADAPTER.validate_python(node_payloads()[0])
    repository.create(start)
    end_payload = {
        "id": start.id,
        "type": "END",
        "name": start.name,
        "description": start.description,
    }

    with pytest.raises(NodeStructuralRepositoryError, match="type 创建后不可修改"):
        repository.update(NODE_STRUCTURAL_ADAPTER.validate_python(end_payload))

    assert repository.get(start.id).node.type == "START"


@pytest.mark.parametrize(
    "mutate",
    [
        lambda payload: payload.update(id="not-a-uuid"),
        lambda payload: payload.update(extra="forbidden"),
        lambda payload: payload["inputs"].append(
            {"name": "conversation", "type": "string", "value": "duplicate"}
        ),
        lambda payload: payload["inputs"][0].update(type="integer"),
    ],
)
def test_start_contract_rejects_invalid_structural_models(mutate):
    payload = node_payloads()[0]
    mutate(payload)

    with pytest.raises(ValidationError):
        NODE_STRUCTURAL_ADAPTER.validate_python(payload)


def test_database_checks_reject_invalid_type_and_non_object_json(tmp_path):
    database = tmp_path / "nodes.sqlite3"
    NodeStructuralRepository(database).initialize()

    with sqlite3.connect(database) as connection:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO node_structural_models VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    NODE_IDS["START"], "AGENT", "Invalid", "", "{}",
                    "2026-07-26T10:00:00+00:00", "2026-07-26T10:00:00+00:00",
                ),
            )
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(
                "INSERT INTO node_structural_models VALUES (?, ?, ?, ?, ?, ?, ?)",
                (
                    NODE_IDS["START"], "START", "Invalid", "", "[]",
                    "2026-07-26T10:00:00+00:00", "2026-07-26T10:00:00+00:00",
                ),
            )
