"""HTTP Node execution adapter."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any

from execution.workflow_execution_store import (
    execution_error as _error,
    local_execution_time,
    seconds_to_milliseconds,
)
from execution.workflow_node_runner_base import NodeRunnerBase
from execution.workflow_values import (
    ContextVariableNotFoundError,
    WorkflowOutputSourceError,
    WorkflowOutputTypeError,
    WorkflowValueError,
    collect_outputs,
    parse_json_template,
    resolve_template,
    strict_json_clone,
)


class HttpNodeRunner(NodeRunnerBase):
    def run(
        self, workflow, node, node_execution_id, context, controller, on_running=None
    ):
        document = self._base_node(workflow, node, node_execution_id)
        document.update(
            {"network": node.network.model_dump(mode="json"), "request": None, "redirects": [], "response": None, "attempts": []}
        )
        missing_fields = []
        if not node.request.url.strip():
            missing_fields.append("request.url")
        if node.network.proxy.mode == "CUSTOM" and not node.network.proxy.url:
            missing_fields.append("network.proxy.url")
        if missing_fields:
            error = self._missing_configuration_error(
                "HTTP_CONFIGURATION_INCOMPLETE",
                node.name,
                "未完成请求配置",
                missing_fields,
                "打开节点设置，填写请求 URL；CUSTOM 模式还必须填写 Proxy URL",
            )
            self._fail_pending_configuration(document, error)
            return document, {}
        try:
            resolved_url, url_inputs = resolve_template(node.request.url, context)
            headers = []
            inputs = dict(url_inputs)
            for header in node.request.headers:
                value, used = resolve_template(header.value, context, force_text=True)
                headers.append({"key": header.key, "value": value})
                inputs.update(used)
            params = []
            for parameter in node.request.params:
                value, used = resolve_template(parameter.value, context)
                if isinstance(value, (dict, list)):
                    raise WorkflowValueError("HTTP Query 参数必须是 JSON 标量")
                params.append([parameter.key, value])
                inputs.update(used)
            if node.request.body.type == "raw" and node.request.body.template_text is not None:
                body, body_inputs = parse_json_template(node.request.body.template_text, context)
            else:
                structural_body = node.request.body.model_dump(mode="json")["content"]
                body, body_inputs = resolve_template(structural_body, context)
            inputs.update(body_inputs)
            document["inputs"] = inputs
        except ContextVariableNotFoundError as exc:
            error = _error(
                "CONTEXT_VARIABLE_NOT_FOUND",
                str(exc),
                {"name": exc.name, "path": exc.path},
            )
            self._finish_pending_node(document, "FAILED", error)
            return document, {}
        except WorkflowValueError as exc:
            error = _error("HTTP_EXECUTION_ERROR", str(exc))
            self._finish_pending_node(document, "FAILED", error)
            return document, {}

        started = self._begin_business_node(document, node, controller, on_running)
        if started is None:
            return document, {}

        body_mode = {
            "none": "NONE",
            "raw": "JSON",
            "form_data": "FORM_DATA",
            "form_urlencoded": "FORM_URLENCODED",
        }[node.request.body.type]
        final_status = "FAILED"
        final_error = None
        outputs: dict[str, Any] = {}
        for attempt_number in range(1, node.execution.max_attempts + 2):
            if controller.interrupted():
                final_status = "INTERRUPTED"
                final_error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
                break
            attempt_started = time.monotonic()
            attempt = {
                "attempt": attempt_number,
                "status": "RUNNING",
                "started_at": local_execution_time(),
                "finished_at": None,
                "duration_ms": None,
                "request": None,
                "redirects": [],
                "response": None,
                "error": None,
            }
            document["attempts"].append(attempt)
            document["attempt_count"] = attempt_number
            self.store.write_node(document)
            controller.add_worker(node_execution_id)
            try:
                result = self.stream_worker(
                    {
                        "mode": "RAW_HTTP",
                        "inputs": {},
                        "config": {
                            "timeout_seconds": seconds_to_milliseconds(
                                node.execution.timeout_seconds
                            )
                            / 1000
                        },
                        "request": {
                            "method": node.request.method,
                            "url": resolved_url,
                            "headers": headers,
                            "params": params,
                            "body_mode": body_mode,
                            "body": body,
                            "follow_redirects": node.request.follow_redirects,
                            "response_mode": node.response.mode,
                            "execution_body_type": node.request.body.type,
                            "execution_body": body,
                        },
                        "network": node.network.model_dump(mode="json"),
                    },
                    lambda _text: None,
                    node_execution_id,
                    timeout_seconds=(
                        seconds_to_milliseconds(node.execution.timeout_seconds) / 1000 + 2
                    ),
                )
            finally:
                controller.remove_worker(node_execution_id)
            attempt["finished_at"] = local_execution_time()
            attempt["duration_ms"] = max(0, round((time.monotonic() - attempt_started) * 1000))
            if result.get("interrupted") or controller.interrupted():
                final_status = "INTERRUPTED"
                final_error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
            elif result.get("timed_out"):
                final_status = "TIMEOUT"
                final_error = _error("HTTP_TIMEOUT", "HTTP 请求超时")
            elif not result.get("ok"):
                final_status = "FAILED"
                worker_error_code = result.get("error_code")
                if worker_error_code == "HTTP_RESPONSE_PARSE_ERROR":
                    final_error = _error(
                        worker_error_code,
                        result.get("error") or "HTTP 响应 Body 解析失败",
                    )
                else:
                    final_error = _error(
                        "HTTP_CONNECTION_ERROR",
                        result.get("error") or "HTTP 请求失败",
                        {"stage": "TCP", "raw_error": result.get("error")},
                    )
            else:
                facts = result["response"]
                attempt.update(
                    {
                        "request": facts["request"],
                        "redirects": facts["redirects"],
                        "response": facts["response"],
                    }
                )
                document.update(
                    {
                        "request": facts["request"],
                        "redirects": facts["redirects"],
                        "response": facts["response"],
                    }
                )
                status_code = facts["response"]["status_code"]
                if not self._status_success(status_code, node.response.success_statuses):
                    final_status = "FAILED"
                    final_error = _error(
                        "HTTP_STATUS_ERROR",
                        f"HTTP 返回状态码 {status_code}",
                        {"status_code": status_code},
                    )
                else:
                    try:
                        outputs = collect_outputs(
                            node.outputs,
                            {"request": facts["request"], "response": facts["response"]},
                        )
                    except WorkflowOutputSourceError as exc:
                        final_status = "FAILED"
                        final_error = _error(
                            "HTTP_OUTPUT_SOURCE_EVALUATION_ERROR", str(exc)
                        )
                        attempt.update({"status": "SUCCESS", "error": None})
                        break
                    except WorkflowOutputTypeError as exc:
                        final_status = "FAILED"
                        final_error = _error("HTTP_OUTPUT_TYPE_MISMATCH", str(exc))
                        attempt.update({"status": "SUCCESS", "error": None})
                        break
                    final_status = "SUCCESS"
                    final_error = None
            attempt.update({"status": final_status, "error": final_error})
            if final_status in {"SUCCESS", "INTERRUPTED"}:
                break
            failed_status = (
                attempt["response"]["status_code"]
                if attempt.get("response") is not None
                else None
            )
            retryable_failure = (
                final_error.get("code") != "HTTP_RESPONSE_PARSE_ERROR"
                and (failed_status is None or failed_status in node.execution.retry_statuses)
            )
            can_retry = (
                node.request.method not in {"POST", "PATCH"}
                or node.execution.retry_non_idempotent
            ) and retryable_failure
            if attempt_number <= node.execution.max_attempts and can_retry:
                retry_after_ms = self._retry_after_milliseconds(
                    attempt.get("response")
                )
                if self._wait_interruptibly(
                    controller,
                    (
                        retry_after_ms
                        if retry_after_ms is not None
                        else seconds_to_milliseconds(
                            node.execution.retry_interval_seconds
                        )
                    ),
                ):
                    break
            else:
                break
        document["outputs"] = strict_json_clone(outputs) if final_status == "SUCCESS" else {}
        self._finish_node(document, final_status, started, error=final_error)
        return document, outputs if final_status == "SUCCESS" else {}

    @staticmethod
    def _retry_after_milliseconds(response: Any) -> int | None:
        if not isinstance(response, dict) or not isinstance(response.get("headers"), list):
            return None
        values = [
            header.get("value")
            for header in response["headers"]
            if isinstance(header, dict)
            and isinstance(header.get("key"), str)
            and header["key"].lower() == "retry-after"
        ]
        if len(values) != 1 or not isinstance(values[0], str):
            return None
        value = values[0].strip()
        if value.isascii() and value.isdigit():
            return seconds_to_milliseconds(int(value))
        try:
            retry_at = parsedate_to_datetime(value)
        except (TypeError, ValueError, OverflowError):
            return None
        if retry_at.tzinfo is None:
            return None
        delay_seconds = max(
            0.0,
            (retry_at.astimezone(timezone.utc) - datetime.now(timezone.utc)).total_seconds(),
        )
        return seconds_to_milliseconds(delay_seconds)

    @staticmethod
    def _status_success(status: int, declarations: list[int | str]) -> bool:
        for declaration in declarations:
            if isinstance(declaration, int) and status == declaration:
                return True
            if isinstance(declaration, str):
                start, end = (int(part) for part in declaration.split("-"))
                if start <= status <= end:
                    return True
        return False
