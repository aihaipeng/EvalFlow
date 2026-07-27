"""Cancellable subprocess runtime shared by Workflow node executions."""

from __future__ import annotations

import json
import os
import queue
import signal
import subprocess
import sys
import threading
import time
from dataclasses import dataclass, field
from typing import Any
from collections.abc import Callable


TOOL_EXECUTION_TIMEOUT_SECONDS = 120
_STREAM_EVENT_PREFIX = "\x1e"
_PRE_CANCEL_TTL_SECONDS = 300


class ToolExecutionError(RuntimeError):
    pass


class ExecutionAlreadyRunningError(ToolExecutionError):
    pass


@dataclass
class _ExecutionState:
    process: subprocess.Popen[bytes] | None = None
    interrupted: bool = False
    created_at: float = field(default_factory=time.monotonic)
    lock: threading.Lock = field(default_factory=threading.Lock)


_EXECUTION_STATES: dict[str, _ExecutionState] = {}
_EXECUTION_STATES_LOCK = threading.Lock()


def _json_clone(value: Any, label: str) -> Any:
    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise ToolExecutionError(f"{label} 必须是合法 JSON: {exc}") from exc


def _prepare_execution(run_id: str) -> _ExecutionState:
    normalized = run_id.strip()
    if not normalized:
        raise ToolExecutionError("run_id 不能为空")
    now = time.monotonic()
    with _EXECUTION_STATES_LOCK:
        expired = [
            existing_id
            for existing_id, existing in _EXECUTION_STATES.items()
            if existing.process is None
            and existing.interrupted
            and now - existing.created_at > _PRE_CANCEL_TTL_SECONDS
        ]
        for existing_id in expired:
            del _EXECUTION_STATES[existing_id]
        state = _EXECUTION_STATES.get(normalized)
        if state is None:
            state = _ExecutionState()
            _EXECUTION_STATES[normalized] = state
            return state
    with state.lock:
        if state.process is not None and state.process.poll() is None:
            raise ExecutionAlreadyRunningError(f"运行任务已存在: {normalized}")
    return state


def _release_execution(run_id: str, state: _ExecutionState) -> None:
    with _EXECUTION_STATES_LOCK:
        if _EXECUTION_STATES.get(run_id) is state:
            del _EXECUTION_STATES[run_id]


def _terminate_process_tree(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is not None:
        return
    try:
        if os.name == "nt":
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                capture_output=True,
                check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        else:
            os.killpg(process.pid, signal.SIGKILL)
    except (OSError, subprocess.SubprocessError):
        pass
    if process.poll() is None:
        try:
            process.kill()
        except OSError:
            pass


def interrupt_tool_run(run_id: str) -> bool:
    normalized = run_id.strip()
    if not normalized:
        return False
    with _EXECUTION_STATES_LOCK:
        state = _EXECUTION_STATES.get(normalized)
        if state is None:
            _EXECUTION_STATES[normalized] = _ExecutionState(interrupted=True)
            return False
    with state.lock:
        state.interrupted = True
        process = state.process
    if process is None or process.poll() is not None:
        return False
    _terminate_process_tree(process)
    return True


def is_tool_run_active(run_id: str) -> bool:
    with _EXECUTION_STATES_LOCK:
        state = _EXECUTION_STATES.get(run_id)
    if state is None:
        return False
    with state.lock:
        return (
            not state.interrupted
            and state.process is not None
            and state.process.poll() is None
        )


def _parse_worker_line(raw_line: bytes) -> list[dict[str, Any]]:
    text = raw_line.decode("utf-8", errors="replace")
    parts = text.split(_STREAM_EVENT_PREFIX)
    events: list[dict[str, Any]] = []
    if parts[0]:
        events.append({"type": "log", "text": parts[0]})
    for part in parts[1:]:
        candidate = part.rstrip("\r\n")
        try:
            event = json.loads(candidate)
        except json.JSONDecodeError:
            events.append({"type": "log", "text": _STREAM_EVENT_PREFIX + part})
            continue
        if isinstance(event, dict):
            events.append(event)
    return events


def stream_tool_worker(
    payload: dict[str, Any],
    on_log: Callable[[str], None],
    run_id: str,
    timeout_seconds: float = TOOL_EXECUTION_TIMEOUT_SECONDS,
    on_console: Callable[[str, str], None] | None = None,
) -> dict[str, Any]:
    if timeout_seconds <= 0:
        raise ToolExecutionError("执行超时必须大于 0 秒")
    normalized_payload = _json_clone(payload, "Worker payload")
    stdout_parts: list[str] = []
    stderr_parts: list[str] = []
    console_parts: list[str] = []

    def with_streams(result: dict[str, Any]) -> dict[str, Any]:
        return {
            **result,
            "stdout": "".join(stdout_parts),
            "stderr": "".join(stderr_parts),
            "console": "".join(console_parts),
        }

    state = _prepare_execution(run_id)
    process: subprocess.Popen[bytes] | None = None
    try:
        with state.lock:
            if state.interrupted:
                return with_streams({"ok": False, "interrupted": True})
            process = subprocess.Popen(
                [sys.executable, "-m", "execution.tool_worker"],
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                creationflags=(
                    getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
                    | getattr(subprocess, "CREATE_NO_WINDOW", 0)
                )
                if os.name == "nt"
                else 0,
                start_new_session=os.name != "nt",
            )
            state.process = process

        assert process.stdin is not None
        assert process.stdout is not None
        assert process.stderr is not None
        process.stdin.write(
            json.dumps(normalized_payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
        )
        process.stdin.close()

        output_queue: queue.Queue[tuple[str, bytes | None]] = queue.Queue()

        def read_lines(stream, source: str) -> None:
            try:
                while True:
                    line = stream.readline()
                    if not line:
                        break
                    output_queue.put((source, line))
            finally:
                output_queue.put((source, None))

        for source, stream in (("stdout", process.stdout), ("stderr", process.stderr)):
            threading.Thread(
                target=read_lines,
                args=(stream, source),
                daemon=True,
            ).start()

        deadline = time.monotonic() + timeout_seconds
        closed_sources: set[str] = set()
        result: dict[str, Any] | None = None
        while len(closed_sources) < 2:
            with state.lock:
                if state.interrupted:
                    process.wait(timeout=5)
                    return with_streams({"ok": False, "interrupted": True})
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                message = f"执行超时，已终止子进程（{timeout_seconds:g} 秒）\n"
                stderr_parts.append(message)
                console_parts.append(message)
                on_log(message)
                _terminate_process_tree(process)
                process.wait(timeout=5)
                return with_streams({"ok": False, "timed_out": True})
            try:
                source, raw_line = output_queue.get(timeout=min(0.1, remaining))
            except queue.Empty:
                continue
            if raw_line is None:
                closed_sources.add(source)
                continue
            if source == "stderr":
                text = raw_line.decode("utf-8", errors="replace")
                stderr_parts.append(text)
                console_parts.append(text)
                on_log(text)
                if on_console is not None:
                    on_console("STDERR", text)
                continue
            for event in _parse_worker_line(raw_line):
                if event.get("type") == "log":
                    text = str(event.get("text", ""))
                    stream = event.get("stream", "stdout")
                    (stderr_parts if stream == "stderr" else stdout_parts).append(text)
                    console_parts.append(text)
                    on_log(text)
                    if on_console is not None:
                        on_console("STDERR" if stream == "stderr" else "STDOUT", text)
                elif event.get("type") == "result" and isinstance(event.get("result"), dict):
                    result = event["result"]

        process.wait(timeout=5)
        with state.lock:
            if state.interrupted:
                return with_streams({"ok": False, "interrupted": True})
        if result is None:
            message = "Worker 未返回执行结果\n"
            stderr_parts.append(message)
            console_parts.append(message)
            on_log(message)
            return with_streams({"ok": False})
        return with_streams(result)
    finally:
        if process is not None and process.poll() is None:
            _terminate_process_tree(process)
        _release_execution(run_id, state)
