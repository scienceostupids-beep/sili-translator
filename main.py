import os
import re
import requests
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse, PlainTextResponse
from deep_translator import GoogleTranslator, MyMemoryTranslator

# WARNING: SSL verification is disabled below as requested
requests.packages.urllib3.disable_warnings()
_old_request = requests.Session.request
def _new_request(self, *args, **kwargs):
    kwargs['verify'] = False
    return _old_request(self, *args, **kwargs)
requests.Session.request = _new_request

# Disabling docs_url and redoc_url completely removes the testing/documentation pages
app = FastAPI(docs_url=None, redoc_url=None)

MAX_CHARS = 15000
INTERNAL_SECRET = "sili_internal_translate_secret_2024"

def _normalize_target(code: str) -> str:
    """Map app canonical codes to targets translators accept."""
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

@app.get("/", response_class=PlainTextResponse)
async def root_simple():
    """Ultra-simple, minimal plain text overview of the service endpoints."""
    return (
        "Sili Translator API\n"
        "===================\n"
        "Status: Active\n\n"
        "Endpoints:\n"
        "- GET  /health     -> System health check\n"
        "- POST /translate -> Secure translation processor\n"
    )

@app.get("/health")
async def health_check():
    """Simple ping route to monitor deployment status."""
    return {"status": "healthy"}

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
    translated = None
    engine_used = "none"
    last_error = ""

    # PRIMARY ENGINE: Google Translate
    try:
        translated = GoogleTranslator(source="auto", target=target_norm).translate(plain)
        if translated and str(translated).strip():
            engine_used = "google"
    except Exception as e:
        last_error = f"Google engine failed: {str(e)}"

    # SECONDARY FALLBACK ENGINE: MyMemory Translate (Triggers automatically if Google throws errors)
    if not translated or not str(translated).strip():
        try:
            fallback_target = target_norm.split("-")[0] if "-" in target_norm else target_norm
            translated = MyMemoryTranslator(source="auto", target=fallback_target).translate(plain)
            if translated and str(translated).strip():
                engine_used = "mymemory"
        except Exception as e:
            last_error += f" | MyMemory engine fallback failed: {str(e)}"

    # Final evaluation validation
    if not translated or not str(translated).strip():
        return JSONResponse({"ok": False, "error": f"All engines exhausted. Details: {last_error}"}, status_code=502)

    return {"ok": True, "translated": str(translated).strip(), "engine": engine_used}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
