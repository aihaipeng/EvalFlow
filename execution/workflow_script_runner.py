"""SCRIPT Node execution adapter."""

from __future__ import annotations

from typing import Any

from execution.workflow_execution_store import (
    execution_error as _error,
    seconds_to_milliseconds,
)
from execution.workflow_node_runner_base import NodeRunnerBase
from execution.workflow_values import WorkflowValueError, convert_output, strict_json_clone


LOG_LIMIT_BYTES = 5 * 1024 * 1024


class ScriptNodeRunner(NodeRunnerBase):
    def run(
        self, workflow, node, node_execution_id, context, controller, on_running=None
    ):
        document = self._base_node(workflow, node, node_execution_id)
        document["logs"] = {"truncated": False, "captured_bytes": 0, "attempts": []}
        if not node.script.strip():
            error = self._missing_configuration_error(
                "SCRIPT_CONFIGURATION_INCOMPLETE",
                node.name,
                "未填写 Python 代码",
                ["script"],
                "打开节点设置，在 main.py 中填写需要执行的 Python 代码",
            )
            self._fail_pending_configuration(document, error)
            return document, {}
        started = self._begin_business_node(document, node, controller, on_running)
        if started is None:
            return document, {}
        final_error = None
        final_status = "FAILED"
        outputs: dict[str, Any] = {}
        for attempt_number in range(1, node.execution.max_attempts + 2):
            if controller.interrupted():
                final_status = "INTERRUPTED"
                final_error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
                break
            document["attempt_count"] = attempt_number
            document["inputs"] = strict_json_clone(context)
            attempt = {
                "attempt": attempt_number,
                "status": "RUNNING",
                "console": [],
                "error": None,
            }
            document["logs"]["attempts"].append(attempt)
            self.store.write_node(document)
            sequence = 0

            def on_console(stream: str, text: str) -> None:
                nonlocal sequence
                sequence += 1
                self._append_script_log(document["logs"], attempt, sequence, stream, text)
                self.store.write_node(document)

            controller.add_worker(node_execution_id)
            try:
                result = self.stream_worker(
                    {
                        "mode": "PYTHON",
                        "code": node.script,
                        "inputs": {},
                        "config": {},
                        "context": strict_json_clone(context),
                        "output_variable_names": [item.source for item in node.outputs],
                    },
                    lambda _text: None,
                    node_execution_id,
                    timeout_seconds=(
                        seconds_to_milliseconds(node.execution.timeout_seconds) / 1000
                    ),
                    on_console=on_console,
                )
            finally:
                controller.remove_worker(node_execution_id)
            if result.get("interrupted") or controller.interrupted():
                final_status = "INTERRUPTED"
                final_error = _error("WORKFLOW_ABORTED", "Workflow 已停止")
                attempt.update({"status": final_status, "error": final_error})
                break
            if result.get("timed_out"):
                final_status = "TIMEOUT"
                final_error = _error("SCRIPT_TIMEOUT", "SCRIPT 执行超时")
                attempt.update({"status": final_status, "error": final_error})
            elif not result.get("ok"):
                final_status = "FAILED"
                if result.get("error_code") == "SCRIPT_OUTPUT_SERIALIZATION_ERROR":
                    final_error = _error(
                        "SCRIPT_OUTPUT_SERIALIZATION_ERROR",
                        result.get("error") or "SCRIPT 输出无法严格 JSON 序列化",
                        {"name": result.get("serialization_variable_name")},
                    )
                else:
                    final_error = _error(
                        "SCRIPT_RUNTIME_ERROR",
                        result.get("error") or "SCRIPT 执行失败",
                    )
                attempt.update({"status": final_status, "error": final_error})
                if result.get("error_code") == "SCRIPT_OUTPUT_SERIALIZATION_ERROR":
                    break
            elif result.get("missing_variable_names"):
                missing_names = result["missing_variable_names"]
                missing = missing_names[0]
                final_status = "FAILED"
                final_error = _error(
                    "SCRIPT_OUTPUT_MISSING",
                    f"Python 顶层变量不存在: {', '.join(missing_names)}",
                    {"name": missing, "names": missing_names},
                )
                attempt.update({"status": final_status, "error": final_error})
                break
            else:
                try:
                    variables = result.get("python_variables") or {}
                    outputs = {
                        item.name: convert_output(variables[item.source], item.type)
                        for item in node.outputs
                    }
                except (WorkflowValueError, KeyError) as exc:
                    final_status = "FAILED"
                    final_error = _error("SCRIPT_OUTPUT_TYPE_MISMATCH", str(exc))
                    attempt.update({"status": final_status, "error": final_error})
                    break
                attempt.update({"status": "SUCCESS", "error": None})
                final_status = "SUCCESS"
                final_error = None
                break
            if attempt_number <= node.execution.max_attempts:
                if self._wait_interruptibly(
                    controller,
                    seconds_to_milliseconds(node.execution.retry_interval_seconds),
                ):
                    break
        document["outputs"] = strict_json_clone(outputs) if final_status == "SUCCESS" else {}
        self._finish_node(document, final_status, started, error=final_error)
        return document, outputs if final_status == "SUCCESS" else {}

    @staticmethod
    def _append_log_text(logs: dict[str, Any], text: str) -> str:
        remaining = LOG_LIMIT_BYTES - logs["captured_bytes"]
        if remaining <= 0:
            logs["truncated"] = True
            return ""
        encoded = text.encode("utf-8")
        kept = encoded[:remaining]
        while True:
            try:
                result = kept.decode("utf-8")
                break
            except UnicodeDecodeError:
                kept = kept[:-1]
        logs["captured_bytes"] += len(kept)
        if len(kept) < len(encoded):
            logs["truncated"] = True
        return result

    def _append_script_log(self, logs, attempt, sequence, stream, text):
        kept = self._append_log_text(logs, text)
        if kept:
            attempt["console"].append(
                {"sequence": sequence, "stream": stream, "content": kept}
            )
