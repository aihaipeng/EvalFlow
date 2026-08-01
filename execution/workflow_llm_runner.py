"""LLM Node execution adapter."""

from __future__ import annotations

import json
import time
from typing import Any

from execution.model_gateway import (
    build_model_request,
    parse_model_payload,
)
from execution.model_protocols import model_inference_url, model_protocol_headers
from execution.workflow_execution_store import (
    execution_error as _error,
    local_execution_time,
    seconds_to_milliseconds,
)
from execution.workflow_node_runner_base import NodeRunnerBase
from execution.workflow_values import (
    WorkflowOutputSourceError,
    WorkflowOutputTypeError,
    WorkflowValueError,
    collect_outputs,
    resolve_template,
    strict_json_clone,
)


class LlmNodeRunner(NodeRunnerBase):
    def run(
        self, workflow, node, node_execution_id, context, controller, on_running=None
    ):
        document = self._base_node(workflow, node, node_execution_id)
        document.update(
            {
                "model": None,
                "request": None,
                "response": None,
                "response_received": False,
                "usage": None,
                "usage_errors": [],
                "attempts": [],
            }
        )
        missing_fields = []
        if not node.model.provider_id.strip():
            missing_fields.append("model.provider_id")
        if not node.model.model_name.strip():
            missing_fields.append("model.model_name")
        for index, message in enumerate(node.context.messages):
            if message.role != "SYSTEM" and not message.content.strip():
                missing_fields.append(f"context.messages[{index}].content")
        last_message = node.context.messages[-1]
        if last_message.role != "USER":
            missing_fields.append(f"context.messages[{len(node.context.messages) - 1}].role")
        generation_parameters = node.generation.parameters
        parameters_text = node.generation.parameters_text.strip()
        if parameters_text:
            try:
                parsed_parameters = json.loads(parameters_text)
                if not isinstance(parsed_parameters, dict):
                    raise ValueError("高级参数必须是 JSON 对象")
                generation_parameters = parsed_parameters
            except (json.JSONDecodeError, ValueError):
                missing_fields.append("generation.parameters_text")
        if missing_fields:
            error = self._missing_configuration_error(
                "LLM_CONFIGURATION_INCOMPLETE",
                node.name,
                "未完成模型配置",
                missing_fields,
                "打开节点设置，选择供应商和模型，补全上下文，并确保高级参数是 JSON 对象",
            )
            self._fail_pending_configuration(document, error)
            return document, {}
        provider = self.model_repository.get(node.model.provider_id)
        if provider is None or node.model.model_name not in provider.models:
            error = self._missing_configuration_error(
                "LLM_MODEL_NOT_FOUND",
                node.name,
                f"引用的模型“{node.model.provider_id}/{node.model.model_name}”不存在或已被删除",
                [],
                "打开节点设置，重新选择模型管理中的可用模型",
            )
            self._fail_pending_configuration(document, error)
            return document, {}
        started = self._begin_business_node(document, node, controller, on_running)
        if started is None:
            return document, {}
        try:
            resolved_messages = []
            inputs: dict[str, Any] = {}
            for message in node.context.messages:
                content, used = resolve_template(
                    message.content, context, force_text=True
                )
                inputs.update(used)
                if message.role == "SYSTEM" and not content.strip():
                    continue
                if message.role != "SYSTEM" and not content.strip():
                    raise WorkflowValueError(
                        f"LLM {message.role} 消息解析后为空"
                    )
                resolved_messages.append(
                    {"role": message.role.lower(), "content": content}
                )
            document["inputs"] = inputs
            document["model"] = node.model.model_dump(mode="json")
            defaults = provider.model_configs.get(node.model.model_name)
            default_body = defaults.default_body if defaults else {}
            request_body = build_model_request(
                provider.protocol,
                model_name=node.model.model_name,
                messages=resolved_messages,
                model_defaults=default_body,
                model_parameters=generation_parameters,
            )
            url = model_inference_url(provider.protocol, provider.base_url)
            headers = model_protocol_headers(provider.protocol, provider.api_key)
            parse_response = lambda payload: parse_model_payload(
                provider.protocol, payload
            )
            request_body["stream"] = False
        except (WorkflowValueError, ValueError) as exc:
            code = (
                "LLM_MESSAGE_EMPTY"
                if str(exc).startswith("LLM ") and str(exc).endswith("消息解析后为空")
                else "LLM_EXECUTION_ERROR"
            )
            error = _error(code, str(exc))
            self._finish_node(document, "FAILED", started, error=error)
            return document, {}

        final_status = "FAILED"
        final_error = None
        outputs: dict[str, Any] = {}
        usage_total = {"input_tokens": 0, "output_tokens": 0, "total_tokens": 0}
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
                "request": strict_json_clone(request_body),
                "response": None,
                "response_received": False,
                "error": None,
                "truncated_fields": [],
            }
            document["attempts"].append(attempt)
            document["attempt_count"] = attempt_number
            document["request"] = strict_json_clone(request_body)
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
                            "method": "POST",
                            "url": url,
                            "headers": headers,
                            "body_mode": "JSON",
                            "body": request_body,
                            "execution_body_type": "raw",
                            "execution_body": request_body,
                        },
                        "network": {
                            "proxy": {
                                "mode": provider.proxy_mode,
                                "url": provider.proxy_url,
                                "username": provider.proxy_username,
                                "password": provider.proxy_password,
                            },
                            "verify_ssl": provider.verify_ssl,
                        },
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
                final_error = _error("LLM_TIMEOUT", "LLM 请求超时")
            elif not result.get("ok"):
                final_status = "FAILED"
                final_error = _error("LLM_REQUEST_FAILED", result.get("error") or "模型请求失败")
            else:
                response_fact = result["response"]["response"]
                raw_response = response_fact["body"]
                attempt["response"] = strict_json_clone(raw_response)
                attempt["response_received"] = True
                document["response"] = strict_json_clone(raw_response)
                document["response_received"] = True
                self._accumulate_usage(raw_response, usage_total)
                if response_fact["status_code"] < 200 or response_fact["status_code"] >= 300:
                    final_status = "FAILED"
                    final_error = _error(
                        "LLM_RESPONSE_ERROR",
                        f"供应商返回 HTTP {response_fact['status_code']}",
                        {"status_code": response_fact["status_code"]},
                    )
                else:
                    try:
                        parsed_response = parse_response(raw_response)
                    except ValueError as exc:
                        final_status = "FAILED"
                        final_error = _error(
                            "LLM_RESPONSE_PARSE_ERROR",
                            f"{provider.protocol} 响应解析失败: {exc}",
                            {"protocol": provider.protocol},
                        )
                        attempt.update({"status": "SUCCESS", "error": None})
                        break
                    try:
                        outputs = collect_outputs(
                            node.outputs,
                            {"response": raw_response, "result": parsed_response},
                        )
                    except WorkflowOutputSourceError as exc:
                        final_status = "FAILED"
                        final_error = _error(
                            "LLM_OUTPUT_SOURCE_EVALUATION_ERROR", str(exc)
                        )
                        attempt.update({"status": "SUCCESS", "error": None})
                        break
                    except WorkflowOutputTypeError as exc:
                        final_status = "FAILED"
                        final_error = _error("LLM_OUTPUT_TYPE_MISMATCH", str(exc))
                        attempt.update({"status": "SUCCESS", "error": None})
                        break
                    final_status = "SUCCESS"
                    final_error = None
            attempt.update({"status": final_status, "error": final_error})
            if final_status == "SUCCESS" or final_status == "INTERRUPTED":
                break
            if attempt_number <= node.execution.max_attempts:
                if self._wait_interruptibly(
                    controller,
                    seconds_to_milliseconds(node.execution.retry_interval_seconds),
                ):
                    break
        document["usage"] = usage_total if any(usage_total.values()) else None
        document["outputs"] = strict_json_clone(outputs) if final_status == "SUCCESS" else {}
        self._finish_node(document, final_status, started, error=final_error)
        return document, outputs if final_status == "SUCCESS" else {}

    @staticmethod
    def _accumulate_usage(response: Any, total: dict[str, int]) -> None:
        if not isinstance(response, dict) or not isinstance(response.get("usage"), dict):
            return
        usage = response["usage"]
        input_value = usage.get("prompt_tokens", usage.get("input_tokens", 0))
        output_value = usage.get("completion_tokens", usage.get("output_tokens", 0))
        if isinstance(input_value, int) and input_value >= 0:
            total["input_tokens"] += input_value
        if isinstance(output_value, int) and output_value >= 0:
            total["output_tokens"] += output_value
        total_value = usage.get("total_tokens")
        if isinstance(total_value, int) and total_value >= 0:
            total["total_tokens"] += total_value
        else:
            total["total_tokens"] = total["input_tokens"] + total["output_tokens"]
