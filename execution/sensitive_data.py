"""Small helpers for removing configured secrets from user-visible errors."""

from __future__ import annotations

import re
from urllib.parse import quote, urlsplit, urlunsplit


_BEARER_VALUE = re.compile(r"(?i)(authorization\s*[:=]\s*bearer\s+)[^\s,;]+")


def proxy_url_with_auth(
    proxy_url: str,
    username: str | None = None,
    password: str | None = None,
) -> str:
    """Embed proxy credentials into a URL, shared by the async gateway and subprocess stack."""

    if not username:
        return proxy_url
    parsed = urlsplit(proxy_url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    port = f":{parsed.port}" if parsed.port is not None else ""
    credentials = quote(username, safe="")
    if password is not None:
        credentials += ":" + quote(password, safe="")
    netloc = f"{credentials}@{hostname}{port}"
    return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))


def redact_sensitive_text(text: str, *secrets: str | None) -> str:
    """Replace explicit secrets and Bearer values in diagnostic text."""

    redacted = text
    for secret in secrets:
        if secret:
            redacted = redacted.replace(secret, "[REDACTED]")
    return _BEARER_VALUE.sub(r"\1[REDACTED]", redacted)
