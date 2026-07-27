from __future__ import annotations

import json
import sqlite3
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from fastapi.testclient import TestClient

from execution import ModelProviderRecord, ModelProviderRepository
from web import routes_model_providers
from web.app import app, create_app


def _body(**overrides) -> dict:
    body = {
        "name": "DeepSeek",
        "website_url": "https://www.deepseek.com",
        "api_key": "local-secret",
        "base_url": "https://api.deepseek.com",
        "protocol": "OPENAI_COMPATIBLE",
        "model_endpoint": "https://api.deepseek.com/v1/models",
        "models": ["deepseek-chat", "deepseek-reasoner"],
    }
    body.update(overrides)
    return body


def _isolated_app(tmp_path):
    database_path = tmp_path / "run_storage" / "agent_bench.sqlite3"
    application = create_app(
        database_path=database_path,
        execution_root=tmp_path / "workflow-executions",
    )
    return database_path, application


def test_model_provider_repository_restart_round_trip(tmp_path):
    database_path = tmp_path / "agent_bench.sqlite3"
    repository = ModelProviderRepository(database_path)
    created = repository.create(
        ModelProviderRecord(
            id="provider-1",
            **_body(
                proxy_mode="CUSTOM",
                proxy_url="http://proxy.local:8080",
                model_configs={
                    "deepseek-chat": {
                        "context_window": 128000,
                        "max_output_tokens": 8192,
                        "default_body": {"temperature": 0.2},
                    }
                },
            ),
        )
    )

    restored = ModelProviderRepository(database_path).get(created.id)
    assert restored is not None
    assert restored.api_key == "local-secret"
    assert restored.models == ["deepseek-chat", "deepseek-reasoner"]
    assert restored.proxy_mode == "CUSTOM"
    assert restored.proxy_url == "http://proxy.local:8080"
    assert restored.model_configs["deepseek-chat"].context_window == 128000
    assert restored.model_configs["deepseek-chat"].default_body == {
        "temperature": 0.2
    }

    updated = ModelProviderRecord(
        id=created.id,
        created_at=created.created_at,
        **_body(name="更新供应商", models=["deepseek-chat"]),
    )
    assert repository.update(updated).name == "更新供应商"
    assert repository.delete(created.id) is True
    assert repository.delete(created.id) is False


@pytest.mark.parametrize("proxy_mode", ["SYSTEM", "DIRECT", "CUSTOM"])
def test_verify_ssl_is_independent_from_proxy_mode(tmp_path, proxy_mode):
    overrides = {"proxy_mode": proxy_mode, "verify_ssl": False}
    if proxy_mode == "CUSTOM":
        overrides["proxy_url"] = "http://proxy.local:8080"
    record = ModelProviderRepository(tmp_path / "models.sqlite3").create(
        ModelProviderRecord(**_body(**overrides))
    )

    assert record.proxy_mode == proxy_mode
    assert record.verify_ssl is False

    connection_values = {
        "base_url": "https://api.example.com",
        "api_key": "secret",
        "proxy_mode": proxy_mode,
        "verify_ssl": False,
    }
    if proxy_mode == "CUSTOM":
        connection_values["proxy_url"] = "http://proxy.local:8080"
    connection = routes_model_providers.ProviderConnectionRequest(
        **connection_values
    )
    assert connection.verify_ssl is False


def test_model_provider_repository_migrates_existing_table(tmp_path):
    database_path = tmp_path / "agent_bench.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE model_providers (
                id TEXT PRIMARY KEY, name TEXT, website_url TEXT, api_key TEXT NOT NULL,
                base_url TEXT NOT NULL, protocol TEXT NOT NULL, model_endpoint TEXT,
                models_json TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO model_providers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy", "Legacy", None, "secret", "https://api.example.com",
                "OPENAI_COMPATIBLE", None, '["model-1"]', "now", "now",
            ),
        )
    restored = ModelProviderRepository(database_path).get("legacy")
    assert restored is not None
    assert restored.proxy_mode == "SYSTEM"
    assert restored.proxy_url is None
    assert restored.verify_ssl is True
    assert restored.model_configs == {}


def test_model_provider_repository_migrates_negative_ssl_setting(tmp_path):
    database_path = tmp_path / "agent_bench.sqlite3"
    with sqlite3.connect(database_path) as connection:
        connection.execute(
            """
            CREATE TABLE model_providers (
                id TEXT PRIMARY KEY, name TEXT, website_url TEXT, api_key TEXT NOT NULL,
                base_url TEXT NOT NULL, protocol TEXT NOT NULL,
                proxy_mode TEXT NOT NULL, proxy_url TEXT, proxy_username TEXT,
                proxy_password TEXT, skip_ssl_verify INTEGER NOT NULL,
                model_endpoint TEXT, models_json TEXT NOT NULL,
                model_configs_json TEXT NOT NULL, created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            )
            """
        )
        connection.execute(
            "INSERT INTO model_providers VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                "legacy-insecure", "Legacy", None, "secret",
                "https://api.example.com", "OPENAI_COMPATIBLE", "DIRECT",
                None, None, None, 1, None, '["model-1"]', '{}', "now", "now",
            ),
        )

    restored = ModelProviderRepository(database_path).get("legacy-insecure")
    assert restored is not None
    assert restored.verify_ssl is False


def test_model_provider_api_crud_and_list_hides_api_key(tmp_path):
    database_path, application = _isolated_app(tmp_path)
    with TestClient(application) as client:
        created_response = client.post("/api/model-providers", json=_body())
        assert created_response.status_code == 200
        created = created_response.json()["provider"]
        assert created["api_key"] == "local-secret"
        assert created["verify_ssl"] is True

        listed = client.get("/api/model-providers").json()["providers"]
        assert len(listed) == 1
        assert "api_key" not in listed[0]
        assert "proxy_url" not in listed[0]
        assert "model_configs" not in listed[0]
        assert "verify_ssl" not in listed[0]
        assert listed[0]["proxy_mode"] == "SYSTEM"
        assert client.get(f"/api/model-providers/{created['id']}").json()["provider"] == created

        updated_response = client.put(
            f"/api/model-providers/{created['id']}",
            json=_body(name="  企业模型网关  ", api_key="changed-secret", models=["m-1"]),
        )
        assert updated_response.status_code == 200
        updated = updated_response.json()["provider"]
        assert updated["name"] == "企业模型网关"
        assert updated["api_key"] == "changed-secret"
        assert ModelProviderRepository(database_path).get(created["id"]).api_key == "changed-secret"

        deleted = client.delete(f"/api/model-providers/{created['id']}")
        assert deleted.status_code == 200
        assert "api_key" not in deleted.json()["provider"]
        assert client.get(f"/api/model-providers/{created['id']}").status_code == 404


def test_model_provider_repository_is_app_scoped_and_database_isolated(tmp_path):
    first = create_app(
        database_path=tmp_path / "first.sqlite3",
        execution_root=tmp_path / "first-executions",
    )
    second = create_app(
        database_path=tmp_path / "second.sqlite3",
        execution_root=tmp_path / "second-executions",
    )

    with TestClient(first) as first_client, TestClient(second) as second_client:
        created = first_client.post("/api/model-providers", json=_body())
        assert created.status_code == 200
        provider_id = created.json()["provider"]["id"]

        assert second_client.get("/api/model-providers").json()["providers"] == []
        assert (
            first.state.workflow_services.model_repository.get(provider_id)
            is not None
        )
        assert first.state.workflow_services.model_repository is not second.state.workflow_services.model_repository


@pytest.mark.parametrize(
    "overrides",
    [
        {"api_key": "   "},
        {"base_url": "not-a-url"},
        {"base_url": "https://user:password@example.com"},
        {"website_url": "ftp://example.com"},
        {"models": []},
        {"models": ["ok", "  "]},
        {"models": [123]},
        {"protocol": "UNKNOWN"},
        {"protocol": "MANUAL"},
        {"proxy_mode": "CUSTOM", "proxy_url": None},
        {"proxy_mode": "CUSTOM", "proxy_url": "ftp://proxy.example.com"},
        {"model_configs": {"missing-model": {"context_window": 1000}}},
        {"model_configs": {"deepseek-chat": {"context_window": 0}}},
    ],
)
def test_model_provider_api_rejects_invalid_records(tmp_path, overrides):
    _database_path, application = _isolated_app(tmp_path)
    with TestClient(application) as client:
        assert client.post(
            "/api/model-providers", json=_body(**overrides)
        ).status_code == 422


def test_model_endpoint_candidates_and_payload_shapes():
    assert routes_model_providers.build_model_candidates("https://api.example.com") == [
        "https://api.example.com/v1/models",
        "https://api.example.com/models",
    ]
    assert routes_model_providers.build_model_candidates(
        "https://api.example.com/compatible-mode/v1"
    ) == ["https://api.example.com/compatible-mode/v1/models"]
    assert routes_model_providers.build_model_candidates(
        "https://api.example.com/v1/chat/completions"
    ) == ["https://api.example.com/v1/models"]
    assert routes_model_providers.extract_models(
        {"data": [{"id": "z"}, {"name": "a", "ownedBy": "vendor"}, "m"]}
    ) == [
        {"id": "a", "owned_by": "vendor"},
        {"id": "m", "owned_by": None},
        {"id": "z", "owned_by": None},
    ]


def test_latency_and_openai_compatible_model_discovery(tmp_path, monkeypatch):
    seen_authorization = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path == "/v1/models":
                seen_authorization.append(self.headers.get("Authorization"))
                payload = json.dumps({"data": [{"id": "model-b"}, {"id": "model-a"}]})
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(payload.encode())))
                self.end_headers()
                self.wfile.write(payload.encode())
                return
            self.send_response(401)
            self.end_headers()

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    base_url = f"http://127.0.0.1:{server.server_port}"
    client = TestClient(app)
    try:
        latency = client.post(
            "/api/model-providers/latency",
            json={"base_url": base_url, "api_key": "secret-never-echo"},
        )
        models = client.post(
            "/api/model-providers/models",
            json={"base_url": base_url, "api_key": "secret-never-echo"},
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert latency.status_code == 200
    assert latency.json()["status_code"] == 401
    assert models.status_code == 200
    assert models.json()["protocol"] == "OPENAI_COMPATIBLE"
    assert [item["id"] for item in models.json()["models"]] == ["model-a", "model-b"]
    assert seen_authorization == ["Bearer secret-never-echo"]
    assert "secret-never-echo" not in models.text


def test_anthropic_model_discovery_uses_selected_protocol_headers(tmp_path, monkeypatch):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            seen.append(
                {
                    "path": self.path,
                    "api_key": self.headers.get("x-api-key"),
                    "version": self.headers.get("anthropic-version"),
                    "authorization": self.headers.get("authorization"),
                }
            )
            payload = json.dumps({"data": [{"id": "claude-sonnet"}]})
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload.encode())))
            self.end_headers()
            self.wfile.write(payload.encode())

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = TestClient(app).post(
            "/api/model-providers/models",
            json={
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "api_key": "anthropic-secret",
                "protocol": "ANTHROPIC",
                "proxy_mode": "DIRECT",
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status_code == 200
    assert response.json()["protocol"] == "ANTHROPIC"
    assert seen == [
        {
            "path": "/v1/models",
            "api_key": "anthropic-secret",
            "version": "2023-06-01",
            "authorization": None,
        }
    ]


@pytest.mark.parametrize("protocol", ["OPENAI_COMPATIBLE", "ANTHROPIC"])
def test_model_availability_runs_real_inference_with_current_configuration(
    tmp_path, monkeypatch, protocol
):
    seen = []

    class Handler(BaseHTTPRequestHandler):
        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["content-length"])))
            seen.append(
                {
                    "path": self.path,
                    "authorization": self.headers.get("authorization"),
                    "api_key": self.headers.get("x-api-key"),
                    "body": body,
                }
            )
            if protocol == "ANTHROPIC":
                response_body = {
                    "content": [{"type": "text", "text": "模型连接正常。"}],
                    "stop_reason": "end_turn",
                    "usage": {"input_tokens": 8, "output_tokens": 6},
                }
            else:
                response_body = {
                    "choices": [
                        {
                            "message": {"content": "模型连接正常。"},
                            "finish_reason": "stop",
                        }
                    ]
                }
            payload = json.dumps(response_body, ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("content-type", "application/json")
            self.send_header("content-length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def log_message(self, *_args):
            return

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        response = TestClient(app).post(
            "/api/model-providers/test-model",
            json={
                "base_url": f"http://127.0.0.1:{server.server_port}",
                "api_key": "model-test-secret",
                "protocol": protocol,
                "proxy_mode": "SYSTEM",
                "model_name": "test-model",
                "default_body": {
                    "temperature": 0.2,
                    "model": "must-be-overridden",
                    "messages": [],
                    "stream": True,
                },
            },
        )
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=2)

    assert response.status_code == 200
    result = response.json()
    assert result["available"] is True
    assert result["status_code"] == 200
    assert result["output"] == "模型连接正常。"
    assert "model-test-secret" not in response.text
    request = seen[0]
    assert request["body"]["model"] == "test-model"
    assert request["body"]["messages"][0]["role"] == "user"
    assert request["body"]["stream"] is False
    assert request["body"]["temperature"] == 0.2
    if protocol == "ANTHROPIC":
        assert request["path"] == "/v1/messages"
        assert request["api_key"] == "model-test-secret"
        assert request["authorization"] is None
        assert request["body"]["max_tokens"] == 8192
    else:
        assert request["path"] == "/chat/completions"
        assert request["authorization"] == "Bearer model-test-secret"
        assert request["api_key"] is None


def test_model_discovery_error_never_echoes_api_key(tmp_path, monkeypatch):
    response = TestClient(app).post(
        "/api/model-providers/models",
        json={"base_url": "http://127.0.0.1:1", "api_key": "secret-never-echo"},
    )
    assert response.status_code == 502
    assert "secret-never-echo" not in response.text
