import requests
import json
import os
import sys
import datetime

# Add project root to allow imports from src
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from src.database import SessionLocal
from src import crud

LOG_FILE = "d:\\10739\\Exam-Analysis-RAG\\self_test.log"

def mask_key(api_key: str) -> str:
    if not api_key or len(api_key) <= 8:
        return "Invalid or too short to mask"
    return f"{api_key[:4]}...{api_key[-4:]}"

def log_message(message):
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(f"{datetime.datetime.now()}: {message}\n")

def run_test():
    # Clear previous log file
    if os.path.exists(LOG_FILE):
        os.remove(LOG_FILE)

    log_message("--- [STARTING SELF-TEST] ---")
    db = SessionLocal()
    try:
        provider_name = "ohmygpt"
        model_name = "gemini-pro-vision"
        
        log_message(f"Provider: {provider_name}, Model: {model_name}")
        
        api_provider_obj = crud.get_api_provider_by_name(db, provider_name)
        
        if not api_provider_obj or not api_provider_obj.api_url:
            log_message("ERROR: API Provider or URL not found in database.")
            return

        api_url = api_provider_obj.api_url
        api_key = api_provider_obj.api_key
        headers = {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json"
        }

        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "user", 
                    "content": [
                        {"type": "text", "text": "Hello"}
                    ]
                }
            ],
            "max_tokens": 1,
            "temperature": 0.1,
            "top_p": 0.9
        }

        log_message("--- Request Details ---")
        log_message(f"URL: {api_url}")
        log_message(f"Headers: {{'Authorization': f'Bearer {mask_key(api_key)}', 'Content-Type': 'application/json'}})")
        log_message(f"Payload: {json.dumps(payload, indent=2)}")

        try:
            response = requests.post(api_url, headers=headers, json=payload, timeout=20)
            
            log_message("--- Response Details ---")
            log_message(f"Status Code: {response.status_code}")
            log_message(f"Response Body: {response.text}")

            if response.status_code == 200:
                log_message("--- [RESULT: SUCCESS] ---")
            else:
                log_message("--- [RESULT: FAILED] ---")

        except requests.RequestException as e:
            log_message("--- [RESULT: FAILED WITH EXCEPTION] ---")
            log_message(f"Exception: {str(e)}")

    finally:
        db.close()
        log_message("--- [SELF-TEST COMPLETE] ---")

if __name__ == "__main__":
    run_test()
