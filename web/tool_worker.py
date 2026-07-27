"""Compatibility entry point for the execution-owned Worker process."""

from execution.tool_worker import main, parse_raw_http_body

_parse_raw_http_body = parse_raw_http_body

__all__ = ["_parse_raw_http_body", "main"]


if __name__ == "__main__":
    main()
