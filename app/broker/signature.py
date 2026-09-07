"""Webull OpenAPI HMAC-SHA1 signature (ported from reference/signature.ts)."""

from __future__ import annotations

import hashlib
import hmac
import secrets
from base64 import b64encode
from datetime import datetime, timezone
from urllib.parse import quote


def utc_timestamp() -> str:
    """ISO-8601 UTC timestamp without milliseconds, e.g. 2026-09-07T19:00:00Z."""
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def new_nonce() -> str:
    return secrets.token_hex(16)


def compact_json(value: object) -> str:
    """Compact JSON for body + MD5 (no spaces) — matches JSON.stringify."""
    import json

    return json.dumps(value, separators=(",", ":"), ensure_ascii=False)


def generate_webull_signature(
    *,
    path: str,
    app_key: str,
    app_secret: str,
    host: str,
    timestamp: str,
    nonce: str,
    query: dict[str, str] | None = None,
    body: str | None = None,
) -> str:
    """
    Webull OpenAPI HMAC-SHA1 signature.
    Signing headers: x-app-key, x-signature-algorithm, x-signature-version,
    x-signature-nonce, x-timestamp, host. (x-signature and x-version excluded.)
    """
    signing_params: dict[str, str] = {
        **(query or {}),
        "x-app-key": app_key,
        "x-signature-algorithm": "HMAC-SHA1",
        "x-signature-version": "1.0",
        "x-signature-nonce": nonce,
        "x-timestamp": timestamp,
        "host": host,
    }
    str1 = "&".join(f"{k}={signing_params[k]}" for k in sorted(signing_params))
    body_str = body or ""
    if body_str:
        str2 = hashlib.md5(body_str.encode("utf-8")).hexdigest().upper()
        str3 = f"{path}&{str1}&{str2}"
    else:
        str3 = f"{path}&{str1}"

    # urllib.parse.quote(str3, safe="") — encode everything
    encoded = quote(str3, safe="")
    signing_key = f"{app_secret}&"
    digest = hmac.new(
        signing_key.encode("utf-8"),
        encoded.encode("utf-8"),
        hashlib.sha1,
    ).digest()
    return b64encode(digest).decode("ascii")
