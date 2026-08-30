import os
import re
import requests
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse
from deep_translator import GoogleTranslator

# WARNING: SSL verification is disabled below as requested
requests.packages.urllib3.disable_warnings()
_old_request = requests.Session.request
def _new_request(self, *args, **kwargs):
    kwargs['verify'] = False
    return _old_request(self, *args, **kwargs)
requests.Session.request = _new_request

app = FastAPI()

MAX_CHARS = 15000

# HARDCODED SECRET (No environment variables needed on Render's dashboard)
INTERNAL_SECRET = "sili_internal_translate_secret_2024"

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

@app.post("/translate")
async def deep_translate_http(request: Request, x_internal_secret: str = Header(None)):
    if not INTERNAL_SECRET.strip():
        return JSONResponse({"ok": False, "error": "server_misconfigured"}, status_code=500)

    if (x_internal_secret or "").strip() != INTERNAL_SECRET.strip():
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    try:
        body = await request.json()
    except Exception:
        body = {}

    text = body.get("text")
    target = body.get("target")

    if not isinstance(text, str) or not text.strip():
        return JSONResponse({"ok": False, "error": "missing_text"}, status_code=400)
    if not isinstance(target, str) or not target.strip():
        return JSONResponse({"ok": False, "error": "missing_target"}, status_code=400)

    plain = text.strip()
    if len(plain) > MAX_CHARS:
        plain = plain[:MAX_CHARS]

    if not re.search(r"\w", plain, re.UNICODE):
        return JSONResponse({"ok": True, "translated": plain, "skipped": True}, status_code=200)

    target_norm = _normalize_target(target)
    try:
        translated = GoogleTranslator(
            source="auto",
            target=target_norm,
        ).translate(plain)
    except Exception as exc:
        return JSONResponse({"ok": False, "error": str(exc)}, status_code=502)

    if not translated or not str(translated).strip():
        return JSONResponse({"ok": False, "error": "empty_translation"}, status_code=502)

    return {"ok": True, "translated": str(translated).strip()}

if __name__ == "__main__":
    import uvicorn
    # This must remain dynamic so Render can successfully assign its dynamic port
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
