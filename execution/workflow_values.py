"""Context template resolution, output extraction, and strict JSON conversion."""

from __future__ import annotations

import json
import math
import re
from copy import deepcopy
from decimal import Decimal, InvalidOperation
from typing import Any


_REFERENCE = re.compile(
    r"(?<!\\)\$\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])*)\}"
)
_FULL_REFERENCE = re.compile(
    r"^\$\{([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])*)\}$"
)
_JSON_NUMBER = re.compile(r"^-?(0|[1-9][0-9]*)(\.[0-9]+)?([eE][+-]?[0-9]+)?$")
_OUTPUT_INDEX = re.compile(r"^-?(?:0|[1-9][0-9]*)$")
_OUTPUT_KEY = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_PATH_PART = re.compile(r"([A-Za-z_][A-Za-z0-9_]*)|\[([0-9]+)\]")
_CONDITION = re.compile(
    r"^([A-Za-z_][A-Za-z0-9_]*(?:\.[A-Za-z_][A-Za-z0-9_]*|\[[0-9]+\])*)\s*(<=|>=|==|!=|<|>|contain)\s*(.+)$"
)


class WorkflowValueError(ValueError):
    """Context 引用、输出表达式或隐式转换无法按统一契约完成。"""


class WorkflowOutputSourceError(WorkflowValueError):
    """输出 source 无法按受限的 Python 字段和数组下标语义求值。"""


class WorkflowOutputTypeError(WorkflowValueError):
    """source 提取值无法按 outputs.type 的统一矩阵完成转换。"""


def strict_json_clone(value: Any) -> Any:
    """生成不含 NaN/Infinity、循环引用或非 JSON 对象的独立深拷贝。"""

    try:
        return json.loads(json.dumps(value, ensure_ascii=False, allow_nan=False))
    except (TypeError, ValueError, RecursionError) as exc:
        raise WorkflowValueError(f"值无法严格 JSON 序列化: {exc}") from exc


def _path_parts(path: str) -> list[str | int]:
    parts: list[str | int] = []
    position = 0
    while position < len(path):
        if path[position] == ".":
            position += 1
        match = _PATH_PART.match(path, position)
        if match is None:
            raise WorkflowValueError(f"变量路径语法无效: {path}")
        parts.append(match.group(1) if match.group(1) is not None else int(match.group(2)))
        position = match.end()
    return parts


def resolve_path(root: Any, path: str) -> Any:
    """按区分大小写的对象字段和数组下标读取一个值。"""

    current = root
    for part in _path_parts(path):
        if isinstance(part, int):
            if not isinstance(current, list) or part >= len(current):
                raise WorkflowValueError(f"数组下标不存在: {path}")
            current = current[part]
        else:
            if not isinstance(current, dict) or part not in current:
                raise WorkflowValueError(f"对象字段不存在: {path}")
            current = current[part]
    return current


def _context_value(context: dict[str, Any], path: str) -> tuple[str, Any]:
    root_name = re.match(r"^[A-Za-z_][A-Za-z0-9_]*", path).group(0)
    if root_name not in context:
        raise WorkflowValueError(f"Context 变量不存在: {root_name}")
    suffix = path[len(root_name) :]
    return root_name, resolve_path(context[root_name], suffix) if suffix else context[root_name]


def _stringify_template_value(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))


def resolve_template(
    value: Any,
    context: dict[str, Any],
    *,
    force_text: bool = False,
) -> tuple[Any, dict[str, Any]]:
    """递归解析 `${name.path[index]}`，并返回实际引用的 Context 根变量。"""

    referenced: dict[str, Any] = {}

    def resolve(item: Any) -> Any:
        if isinstance(item, list):
            return [resolve(child) for child in item]
        if isinstance(item, dict):
            return {key: resolve(child) for key, child in item.items()}
        if not isinstance(item, str):
            return strict_json_clone(item)

        full = _FULL_REFERENCE.fullmatch(item)
        if full and not force_text:
            root_name, resolved = _context_value(context, full.group(1))
            referenced.setdefault(root_name, strict_json_clone(context[root_name]))
            return strict_json_clone(resolved)

        def replace(match: re.Match[str]) -> str:
            root_name, resolved = _context_value(context, match.group(1))
            referenced.setdefault(root_name, strict_json_clone(context[root_name]))
            return _stringify_template_value(resolved)

        return _REFERENCE.sub(replace, item).replace(r"\${", "${")

    return resolve(value), referenced


def parse_json_template(
    template: str,
    context: dict[str, Any] | None = None,
) -> tuple[Any, dict[str, Any]]:
    """解析允许在 JSON 字符串外使用 `${...}` 的严格 JSON 模板。"""

    in_string = False
    escaped = False
    position = 0
    normalized: list[str] = []
    while position < len(template):
        character = template[position]
        if in_string:
            normalized.append(character)
            if escaped:
                escaped = False
            elif character == "\\":
                escaped = True
            elif character == '"':
                in_string = False
            position += 1
            continue
        if character == '"':
            in_string = True
            normalized.append(character)
            position += 1
            continue
        match = _REFERENCE.match(template, position)
        if match:
            normalized.append(json.dumps(match.group(0), ensure_ascii=False))
            position = match.end()
            continue
        normalized.append(character)
        position += 1

    try:
        parsed = json.loads("".join(normalized))
    except json.JSONDecodeError as exc:
        raise WorkflowValueError(f"HTTP Raw Body 解析变量后不是合法 JSON: {exc.msg}") from exc
    return resolve_template(parsed, context or {}, force_text=True)


def _parse_literal(text: str) -> Any:
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return text


def _compare(left: Any, operator: str, right: Any) -> bool:
    if operator == "contain":
        if isinstance(left, str) and isinstance(right, str):
            return right in left
        if isinstance(left, (list, dict)):
            return right in left
        return False
    if operator == "==":
        return left == right
    if operator == "!=":
        return left != right
    if isinstance(left, bool) or isinstance(right, bool):
        return False
    try:
        if operator == "<":
            return left < right
        if operator == ">":
            return left > right
        if operator == "<=":
            return left <= right
        if operator == ">=":
            return left >= right
    except TypeError:
        return False
    return False


def _read_output_part(current: Any, part: str | int) -> Any:
    if isinstance(current, list) and isinstance(part, str):
        values = [item[part] for item in current if isinstance(item, dict) and part in item]
        if not values:
            return None
        return values[0] if len(values) == 1 else values
    if isinstance(part, int):
        if not isinstance(current, list):
            raise WorkflowOutputSourceError("输出 source 对非数组值使用了数组下标")
        if part < -len(current) or part >= len(current):
            raise WorkflowOutputSourceError(f"输出 source 数组下标越界: {part}")
        return current[part]
    if not isinstance(current, dict) or part not in current:
        return None
    return current[part]


def extract_output(source: str, facts: dict[str, Any]) -> Any:
    """执行以 request/response 为根的字段、下标与数组过滤表达式。"""

    root = re.match(r"^[A-Za-z_][A-Za-z0-9_]*", source)
    if root is None or root.group(0) not in facts:
        raise WorkflowOutputSourceError("输出 source 必须以可用事实根开始")
    current: Any = facts[root.group(0)]
    position = root.end()
    while position < len(source):
        if source[position] == ".":
            match = re.match(r"[A-Za-z_][A-Za-z0-9_]*", source[position + 1 :])
            if match is None:
                raise WorkflowOutputSourceError(f"输出 source 字段语法无效: {source}")
            current = _read_output_part(current, match.group(0))
            position += 1 + match.end()
            continue
        if source[position] != "[":
            raise WorkflowOutputSourceError(f"输出 source 语法无效: {source}")
        end = source.find("]", position + 1)
        if end < 0:
            raise WorkflowOutputSourceError(f"输出 source 缺少 ]: {source}")
        content = source[position + 1 : end]
        condition = _CONDITION.fullmatch(content)
        if condition:
            if not isinstance(current, list):
                current = None
            else:
                right = _parse_literal(condition.group(3))
                matches = []
                for item in current:
                    try:
                        left = resolve_path(item, condition.group(1))
                    except WorkflowValueError:
                        continue
                    if _compare(left, condition.group(2), right):
                        matches.append(item)
                current = None if not matches else matches[0] if len(matches) == 1 else matches
        elif _OUTPUT_INDEX.fullmatch(content):
            current = _read_output_part(current, int(content))
        else:
            if _OUTPUT_KEY.fullmatch(content):
                key = content
            else:
                try:
                    key = json.loads(content)
                except json.JSONDecodeError as exc:
                    raise WorkflowOutputSourceError(
                        f"输出 source 下标无效: {content}"
                    ) from exc
            if not isinstance(key, str):
                raise WorkflowOutputSourceError(f"输出 source 下标无效: {content}")
            current = _read_output_part(current, key)
        position = end + 1
    return strict_json_clone(current)


def _json_type_matches(value: Any, target: str) -> bool:
    if target == "string":
        return isinstance(value, str)
    if target == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if target == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool) and (
            not isinstance(value, float) or math.isfinite(value)
        )
    if target == "boolean":
        return isinstance(value, bool)
    if target == "object":
        return isinstance(value, dict)
    if target == "array":
        return isinstance(value, list)
    return value is None


def convert_output(value: Any, target: str) -> Any:
    """按 WORKFLOW_SPEC 3.3 的统一矩阵转换并严格 JSON 深拷贝。"""

    try:
        strict_json_clone(value)
    except WorkflowValueError as exc:
        raise WorkflowOutputTypeError(str(exc)) from exc
    if _json_type_matches(value, target):
        return strict_json_clone(value)
    if target == "string":
        return json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    if target == "boolean" and isinstance(value, str) and value.lower() in {"true", "false"}:
        return value.lower() == "true"
    if target == "null" and value == "null":
        return None
    if target in {"object", "array"} and isinstance(value, str):
        try:
            parsed = json.loads(value)
        except json.JSONDecodeError as exc:
            raise WorkflowOutputTypeError(f"字符串不是合法 JSON {target}") from exc
        if _json_type_matches(parsed, target):
            return strict_json_clone(parsed)
        raise WorkflowOutputTypeError(f"字符串 JSON 根类型不是 {target}")
    if target in {"integer", "number"}:
        if isinstance(value, bool):
            raise WorkflowOutputTypeError("boolean 不能转换为数值")
        if isinstance(value, str):
            if not _JSON_NUMBER.fullmatch(value):
                raise WorkflowOutputTypeError("字符串不是严格 JSON number")
            try:
                decimal_value = Decimal(value)
            except InvalidOperation as exc:
                raise WorkflowOutputTypeError("数值字符串无法精确解析") from exc
        elif isinstance(value, (int, float)) and math.isfinite(value):
            decimal_value = Decimal(str(value))
        else:
            raise WorkflowOutputTypeError(f"值不能转换为 {target}")
        if target == "integer":
            if decimal_value != decimal_value.to_integral_value():
                raise WorkflowOutputTypeError("数值不是精确整数")
            return int(decimal_value)
        if decimal_value == decimal_value.to_integral_value():
            return int(decimal_value)
        converted = float(decimal_value)
        if not math.isfinite(converted) or Decimal(str(converted)) != decimal_value:
            raise WorkflowOutputTypeError("数值转换会产生精度丢失")
        return converted
    raise WorkflowOutputTypeError(f"值不能按统一矩阵转换为 {target}")


def collect_outputs(
    declarations: list[Any],
    facts: dict[str, Any],
) -> dict[str, Any]:
    """按声明顺序提取并转换全部输出；任一失败时不返回部分结果。"""

    outputs: dict[str, Any] = {}
    for declaration in declarations:
        value = extract_output(declaration.source, facts)
        outputs[declaration.name] = convert_output(value, declaration.type)
    return deepcopy(outputs)


def collect_end_results(declarations: list[Any], context: dict[str, Any]) -> dict[str, Any]:
    """按 END 声明从最终 Context 提取并转换 Workflow 结果。"""

    results: dict[str, Any] = {}
    for declaration in declarations:
        try:
            value = resolve_path(context, declaration.source)
        except WorkflowValueError as exc:
            raise WorkflowOutputSourceError(
                f"END 结果 source 无法读取: {declaration.source}"
            ) from exc
        results[declaration.name] = convert_output(value, declaration.type)
    return deepcopy(results)
