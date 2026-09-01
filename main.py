import os
import uuid
import uvicorn
import requests
from fastapi import FastAPI, Request, Header
from fastapi.responses import JSONResponse, PlainTextResponse
from google.cloud import translate

app = FastAPI(docs_url=None, redoc_url=None)

# Secret header security password for your mobile app connection
INTERNAL_SECRET = "sili_internal_translate_secret_2024"

# ========================================================
# ENGINE 1: AZURE AI TRANSLATOR (MAIN PRIMARY)
# ========================================================
# Put your values here or configure them as environment variables on Render
AZURE_KEY = os.environ.get("AZURE_TRANSLATOR_KEY", "YOUR_KEY_1_HERE")
AZURE_ENDPOINT = os.environ.get("AZURE_TRANSLATOR_ENDPOINT", "https://microsofttranslator.com")
AZURE_REGION = os.environ.get("AZURE_TRANSLATOR_REGION", "francecentral")

is_azure_configured = (
    AZURE_KEY != "YOUR_KEY_1_HERE"
)

# ========================================================
# ENGINE 2: GOOGLE CLOUD TRANSLATION (SECONDARY FALLBACK)
# ========================================================
GOOGLE_PROJECT_ID = "sili-ca40d"

if os.path.exists("/etc/secrets/credentials.json"):
    CREDENTIALS_PATH = "/etc/secrets/credentials.json"
else:
    CREDENTIALS_PATH = "credentials.json"

try:
    translate_client = translate.TranslationServiceClient.from_service_account_json(CREDENTIALS_PATH)
    parent_path = f"projects/{GOOGLE_PROJECT_ID}/locations/global"
    print(f"🚀 SUCCESS: Google Translation engine loaded from {CREDENTIALS_PATH}")
except Exception as e:
    print(f"⚠️ WARNING: Google Credentials could not load: {e}")
    translate_client = None

# ========================================================
# SAFETY TRACKER FOR GOOGLE FALLBACK ONLY
# ========================================================
GOOGLE_CHARACTER_TRACKER = {
    "total_processed": 0,
    "max_free_limit": 500000 
}

def _normalize_target(code: str) -> str:
    """Standardizes language codes."""
    c = (code or "en").strip()
    return c.lower()

# ========================================================
# API ROUTING DEFINITIONS
# ========================================================
@app.get("/", response_class=PlainTextResponse)
async def root_simple():
    return (
        "Sili Hybrid Translator API\n"
        "===========================\n"
        "Status: Active\n"
        f"Primary Engine (Main): Azure AI Translator ({'CONFIGURED' if is_azure_configured else 'UNCONFIGURED'})\n"
        f"Fallback Engine (Backup): Google Cloud v3 ({'CONFIGURED' if translate_client else 'UNCONFIGURED'})\n\n"
        "Endpoints:\n"
        "- GET  /health     -> System health check\n"
        "- POST /translate -> Dual-engine secure translation processor\n"
    )

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "azure_configured": is_azure_configured,
        "google_configured": translate_client is not None,
        "google_fallback_quota_used": f"{GOOGLE_CHARACTER_TRACKER['total_processed']}/{GOOGLE_CHARACTER_TRACKER['max_free_limit']}"
    }

@app.post("/translate")
async def dual_translate_http(request: Request, x_internal_secret: str = Header(None, alias="X-Internal-Secret")):
    global translate_client
    
    # 1. Access security block authentication check
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
    incoming_chars = len(plain)
    target_norm = _normalize_target(target)

    # ----------------------------------------------------
    # ATTEMPT 1: MAIN PRIMARY ENGINE - Azure AI Translator
    # ----------------------------------------------------
    if is_azure_configured:
        try:
            base_url = AZURE_ENDPOINT.rstrip('/')
            constructed_url = f"{base_url}/translate"
            
            params = {
                'api-version': '3.0',
                'to': target_norm
            }
            headers = {
                'Ocp-Apim-Subscription-Key': AZURE_KEY,
                'Ocp-Apim-Subscription-Region': AZURE_REGION,
                'Content-type': 'application/json',
                'X-ClientTraceId': str(uuid.uuid4())
            }
            azure_body = [{'text': plain}]

            azure_response = requests.post(constructed_url, params=params, headers=headers, json=azure_body, timeout=5)
            
            if azure_response.status_code == 200:
                res_data = azure_response.json()
                
                # FIXED: Correct nested list structural access for Azure API responses
                translated_text = res_data[0]['translations'][0]['text']
                
                return {
                    "ok": True, 
                    "translated": translated_text.strip(), 
                    "engine": "azure_ai_translator"
                }
            else:
                print(f"⚠️ Primary Azure failed with status {azure_response.status_code}: {azure_response.text}. Dropping to fallback.")
        except Exception as azure_err:
            print(f"⚠️ Primary Azure encountered error: {azure_err}. Dropping to fallback.")
            
    # ----------------------------------------------------
    # ATTEMPT 2: BACKUP FALLBACK ENGINE - Google Cloud Translation
    # ----------------------------------------------------
    if translate_client:
        if GOOGLE_CHARACTER_TRACKER["total_processed"] + incoming_chars > GOOGLE_CHARACTER_TRACKER["max_free_limit"]:
            return JSONResponse({
                "ok": False, 
                "error": "Google Cloud fallback protection triggered. Budget safety limit reached."
            }, status_code=429)

        try:
            response = translate_client.translate_text(
                request={
                    "parent": parent_path,
                    "contents": [plain],
                    "mime_type": "text/plain",
                    "target_language_code": target_norm,
                }
            )
            
            translated_text = response.translations[0].translated_text
            GOOGLE_CHARACTER_TRACKER["total_processed"] += incoming_chars

            return {
                "ok": True, 
                "translated": translated_text.strip(), 
                "engine": "google_cloud_v3_fallback"
            }
        except Exception as google_err:
            return JSONResponse({
                "ok": False, 
                "error": f"Both Primary and Fallback engines failed. Google error: {str(google_err)}"
            }, status_code=502)

    return JSONResponse({
        "ok": False, 
        "error": "Translation engines unavailable. Core service configurations missing."
    }, status_code=500)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
