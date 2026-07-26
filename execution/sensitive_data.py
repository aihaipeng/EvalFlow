"""Small helpers for removing configured secrets from user-visible errors."""

from __future__ import annotations

import re


_BEARER_VALUE = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+")


def redact_sensitive_text(text: str, *secrets: str | None) -> str:
    """Replace explicit secrets and Bearer values in diagnostic text."""

    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return _BEARER_VALUE.sub(r"\1[REDACTED]", redacted)
