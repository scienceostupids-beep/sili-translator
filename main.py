"""
HTTPS Cloud Function: translate text via deep_translator (GoogleTranslator).

Called only by the Node RTDB function (server-to-server). Protect with
TRANSLATE_INTERNAL_SECRET (same value as Node env TRANSLATE_INTERNAL_SECRET).

Note: deep_translator uses unofficial Google Translate endpoints; reliability
and ToS differ from Cloud Translation API. No extra Google API billing, but
not suitable for all production loads.
"""

import json
import os
import re
import requests

from deep_translator import GoogleTranslator
from firebase_admin import initialize_app
from firebase_functions import https_fn, options

initialize_app()

# WARNING: SSL verification is disabled below as requested
requests.packages.urllib3.disable_warnings()
_old_request = requests.Session.request
def _new_request(self, *args, **kwargs):
    kwargs['verify'] = False
    return _old_request(self, *args, **kwargs)
requests.Session.request = _new_request

# Plain text only; avoid huge payloads
MAX_CHARS = 15000


def _normalize_target(code: str) -> str:
    """Map app canonical codes to targets GoogleTranslator accepts."""
    c = (code or "en").strip().lower()
    special = {
        "zh-cn": "zh-CN",
        "zh-tw": "zh-TW",
    }
    if c in special:
        return special[c]
    if "-" in c:
        base, region = c.split("-", 1)
        if len(region) <= 5:
            return f"{base}-{region.upper()}"
    return c


# Hardcoded for project: sili-ca40d
INTERNAL_SECRET = "sili_internal_translate_secret_2024"


def _is_configured() -> bool:
    return bool(INTERNAL_SECRET.strip())


def _resp(data: dict, status: int) -> https_fn.Response:
    return https_fn.Response(
        json.dumps(data),
        status=status,
        mimetype="application/json",
    )


@https_fn.on_request(
    region=options.SupportedRegion.EUROPE_WEST1,
    timeout_sec=120,
)
def deep_translate_http(req: https_fn.Request) -> https_fn.Response:
    if req.method != "POST":
        return _resp({"ok": False, "error": "method_not_allowed"}, 405)

    if not _is_configured():
        return _resp({"ok": False, "error": "server_misconfigured"}, 500)

    expected = INTERNAL_SECRET.strip()
    got = (req.headers.get("X-Internal-Secret") or "").strip()
    if got != expected:
        return _resp({"ok": False, "error": "forbidden"}, 403)

    try:
        body = req.get_json(silent=True) or {}
    except Exception:  # pylint: disable=broad-exception-caught
        body = {}

    text = body.get("text")
    target = body.get("target")

    if not isinstance(text, str) or not text.strip():
        return _resp({"ok": False, "error": "missing_text"}, 400)
    if not isinstance(target, str) or not target.strip():
        return _resp({"ok": False, "error": "missing_target"}, 400)

    plain = text.strip()
    if len(plain) > MAX_CHARS:
        plain = plain[:MAX_CHARS]

    # Skip if nothing translatable (only whitespace / punctuation)
    if not re.search(r"\w", plain, re.UNICODE):
        return _resp({"ok": True, "translated": plain, "skipped": True}, 200)

    target_norm = _normalize_target(target)

    try:
        translated = GoogleTranslator(
            source="auto",
            target=target_norm,
        ).translate(plain)
    except Exception as exc:  # pylint: disable=broad-exception-caught
        return _resp({"ok": False, "error": str(exc)}, 502)

    if not translated or not str(translated).strip():
        return _resp({"ok": False, "error": "empty_translation"}, 502)

    return _resp({"ok": True, "translated": str(translated).strip()}, 200)
