"""Fail when committed OpenAPI input no longer matches the FastAPI application."""

from __future__ import annotations

from export_openapi import OUTPUT, canonical_schema


if __name__ == "__main__":
    expected = canonical_schema()
    actual = OUTPUT.read_text(encoding="utf-8") if OUTPUT.is_file() else ""
    if actual != expected:
        raise SystemExit("OpenAPI schema drift detected; run `npm run openapi:generate`.")
