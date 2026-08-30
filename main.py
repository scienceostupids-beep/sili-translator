import os
import re
import time
import requests
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse, HTMLResponse
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

@app.get("/", response_class=HTMLResponse)
async def root_dashboard():
    """Renders a simple UI dashboard listing all endpoints when accessing the root URL."""
    html_content = """
    <!DOCTYPE html>
    <html>
    <head>
        <title>Sili Translator API Dashboard</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #0f172a; color: #f8fafc; padding: 40px; margin: 0; }
            .container { max-width: 800px; margin: 0 auto; background: #1e293b; padding: 30px; border-radius: 12px; box-shadow: 0 4px 6px -1px rgba(0,0,0,0.1); }
            h1 { color: #38bdf8; border-bottom: 2px solid #334155; padding-bottom: 10px; margin-top: 0; }
            p { color: #94a3b8; }
            .endpoint { border: 1px solid #334155; border-radius: 8px; padding: 15px; margin: 20px 0; background: #0f172a; }
            .method { display: inline-block; padding: 4px 8px; border-radius: 4px; font-weight: bold; font-size: 14px; margin-right: 10px; }
            .method.post { background-color: #10b981; color: #fff; }
            .method.get { background-color: #3b82f6; color: #fff; }
            .url { font-family: monospace; font-size: 16px; color: #e2e8f0; }
            .desc { margin: 10px 0 0 0; font-size: 14px; color: #94a3b8; }
            .btn-docs { display: inline-block; background-color: #38bdf8; color: #0f172a; padding: 10px 20px; text-decoration: none; border-radius: 6px; font-weight: bold; margin-top: 15px; transition: opacity 0.2s; }
            .btn-docs:hover { opacity: 0.9; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Sili Translator API Dashboard</h1>
            <p>Your translation microservice is live and running perfectly on Render.</p>
            
            <div class="endpoint">
                <span class="method get">GET</span>
                <span class="url">/</span>
                <p class="desc">Root path. Shows this endpoints dashboard overview UI.</p>
            </div>
            
            <div class="endpoint">
                <span class="method get">GET</span>
                <span class="url">/health</span>
                <p class="desc">Health check path. Returns server status for uptime monitoring pings.</p>
            </div>
            
            <div class="endpoint">
                <span class="method post">POST</span>
                <span class="url">/translate</span>
                <p class="desc">Main service path. Accepts translation requests via server-to-server calls.</p>
            </div>
            
            <div class="endpoint">
                <span class="method get">GET</span>
                <span class="url">/docs</span>
                <p class="desc">Interactive OpenAPI/Swagger user interface. Allows full live request testing right inside your web browser.</p>
            </div>

            <a href="/docs" class="btn-docs">Open Interactive Testing UI</a>
        </div>
    </body>
    </html>
    """
    return html_content

@app.get("/health")
async def health_check():
    """Simple ping route to monitor deployment status."""
    return {"status": "healthy", "timestamp": time.time()}

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
    if not isinstance(target, str) or not text.strip():
        return JSONResponse({"ok": False, "error": "missing_target"}, status_code=400)

    plain = text.strip()
    if len(plain) > MAX_CHARS:
        plain = plain[:MAX_CHARS]

    if not re.search(r"\w", plain, re.UNICODE):
        return JSONResponse({"ok": True, "translated": plain, "skipped": True}, status_code=200)

    target_norm = _normalize_target(target)
    
    # Retry loop mechanism to smooth out Google's 500 block errors
    translated = None
    last_exception = None
    
    for attempt in range(3):
        try:
            translated = GoogleTranslator(
                source="auto",
                target=target_norm,
            ).translate(plain)
            if translated and str(translated).strip():
                break  # Break out if successful translation achieved
        except Exception as exc:
            last_exception = exc
            time.sleep(1)  # Brief pause before retrying
            
    if not translated or not str(translated).strip():
        error_msg = str(last_exception) if last_exception else "empty_translation"
        return JSONResponse({"ok": False, "error": error_msg}, status_code=502)

    return {"ok": True, "translated": str(translated).strip()}

if __name__ == "__main__":
    import uvicorn
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
