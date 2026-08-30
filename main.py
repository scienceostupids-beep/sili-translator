import os
import re
import requests
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse, PlainTextResponse
from libretranslatepy import LibreTranslateAPI

# Disable warnings as requested
requests.packages.urllib3.disable_warnings()

app = FastAPI(docs_url=None, redoc_url=None)

MAX_CHARS = 15000
INTERNAL_SECRET = "sili_internal_translate_secret_2024"

# Set up primary and secondary free LibreTranslate infrastructure endpoints
PRIMARY_LT = LibreTranslateAPI("https://discuss.online")
FALLBACK_LT = LibreTranslateAPI("https://libretranslate.de")

def _normalize_target(code: str) -> str:
    """Standardizes language codes for the LibreTranslate engine."""
    c = (code or "en").strip().lower()
    if "-" in c:
        return c.split("-", 1)[0]
    return c

@app.get("/", response_class=PlainTextResponse)
async def root_simple():
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
    return {"status": "healthy"}

@app.post("/translate")
async def deep_translate_http(request: Request, x_internal_secret: str = Header(None)):
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

    # PRIMARY ROUTE: Discuss.online LibreTranslate mirror (Fastest)
    try:
        translated = PRIMARY_LT.translate(plain, "auto", target_norm)
        if translated and str(translated).strip():
            engine_used = "libre_primary"
    except Exception as e:
        last_error = f"Primary mirror failed: {str(e)}"

    # INSTANT FALLBACK ROUTE: Main LibreTranslate node (Fires instantly if primary fails)
    if not translated or not str(translated).strip():
        try:
            translated = FALLBACK_LT.translate(plain, "auto", target_norm)
            if translated and str(translated).strip():
                engine_used = "libre_fallback"
        except Exception as e:
            last_error += f" | Fallback mirror failed: {str(e)}"

    if not translated or not str(translated).strip():
        return JSONResponse({"ok": False, "error": f"All engines exhausted. Details: {last_error}"}, status_code=502)

    return {"ok": True, "translated": str(translated).strip(), "engine": engine_used}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
