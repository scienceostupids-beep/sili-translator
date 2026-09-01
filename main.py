import os
import uvicorn
from fastapi import FastAPI, Request, Header, HTTPException
from fastapi.responses import JSONResponse, PlainTextResponse
from google.cloud import translate

app = FastAPI(docs_url=None, redoc_url=None)

# Secret header security password for your mobile app connection
INTERNAL_SECRET = "sili_internal_translate_secret_2024"

# Official Google Project ID setup
GOOGLE_PROJECT_ID = "sili-ca40d"

# Choose production secrets directory on Render, fallback to local project folder
if os.path.exists("/etc/secrets/credentials.json"):
    CREDENTIALS_PATH = "/etc/secrets/credentials.json"
else:
    CREDENTIALS_PATH = "credentials.json"

# Initialize Google Cloud Translation Client using your file
try:
    translate_client = translate.TranslationServiceClient.from_service_account_json(CREDENTIALS_PATH)
    parent_path = f"projects/{GOOGLE_PROJECT_ID}/locations/global"
    print(f"🚀 SUCCESS: Google Translation engine loaded from {CREDENTIALS_PATH}")
except Exception as e:
    print(f"❌ CRITICAL ERROR LOADING GOOGLE CREDENTIALS: {e}")
    translate_client = None

# Free monthly safety cap tracker (Resets on server restart)
CHARACTER_TRACKER = {
    "total_processed": 0,
    "max_free_limit": 500000
}

def _normalize_target(code: str) -> str:
    """Standardizes language codes for the Google Cloud engine."""
    c = (code or "en").strip()
    if "-" in c:
        # Converts codes like 'en-US' or 'zh-CN' to standard format if needed
        return c
    return c.lower()

@app.get("/", response_class=PlainTextResponse)
async def root_simple():
    return (
        "Sili Translator API\n"
        "===================\n"
        "Status: Active\n"
        "Engine: Google Cloud Translation v3\n\n"
        "Endpoints:\n"
        "- GET  /health     -> System health check\n"
        "- POST /translate -> Secure translation processor\n"
    )

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "engine_configured": translate_client is not None,
        "quota_used": f"{CHARACTER_TRACKER['total_processed']}/{CHARACTER_TRACKER['max_free_limit']}"
    }

@app.post("/translate")
async def google_translate_http(request: Request, x_internal_secret: str = Header(None, alias="X-Internal-Secret")):
    global translate_client
    
    # 1. Access security block authentication check
    if (x_internal_secret or "").strip() != INTERNAL_SECRET.strip():
        return JSONResponse({"ok": False, "error": "forbidden"}, status_code=403)

    if not translate_client:
        return JSONResponse({"ok": False, "error": "Google Translation Engine unconfigured."}, status_code=500)

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
    incoming_chars = len(plain)

    # 2. Strict Free Tier Guard Rail: Block requests if they push you past 500k chars
    if CHARACTER_TRACKER["total_processed"] + incoming_chars > CHARACTER_TRACKER["max_free_limit"]:
        return JSONResponse({
            "ok": False, 
            "error": "Monthly free character limit protection triggered. Blocked to prevent credit card billing."
        }, status_code=429)

    target_norm = _normalize_target(target)

    try:
        # 3. Fire official Google Cloud Translation Request
        # (Note: For high concurrency, wrapping this blocking sync SDK call in anyio.to_thread is recommended)
        response = translate_client.translate_text(
            request={
                "parent": parent_path,
                "contents": [plain],
                "mime_type": "text/plain",
                "target_language_code": target_norm,
            }
        )
        
        # Extract the string payload outcome safely
        translated_text = response.translations[0].translated_text
        
        # Commit character tracking statistics updates
        CHARACTER_TRACKER["total_processed"] += incoming_chars

        return {
            "ok": True, 
            "translated": translated_text.strip(), 
            "engine": "google_cloud_v3"
        }

    except Exception as e:
        return JSONResponse({
            "ok": False, 
            "error": f"Google Cloud Engine Failure: {str(e)}"
        }, status_code=502)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
