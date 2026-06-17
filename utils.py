import requests
import os
from dotenv import load_dotenv

load_dotenv()

N8N_WEBHOOK_URL = os.getenv("N8N_WEBHOOK_URL")

def notify_user(message: str, data: dict = None):
    print(f"NOTIFICATION: {message}")
    if N8N_WEBHOOK_URL:
        try:
            requests.post(N8N_WEBHOOK_URL, json={
                "message": message,
                "data": data
            })
        except Exception as e:
            print(f"Failed to send webhook to n8n: {e}")

def notify_blocked(application_id: int, url: str, screenshot_path: str):
    message = f"🚨 Application Blocked! Manual action required at {url}"
    notify_user(message, {
        "application_id": application_id,
        "url": url,
        "screenshot_path": screenshot_path,
        "reason": "CAPTCHA or human verification detected"
    })

def notify_positive_response(company: str, role: str):
    message = f"🎉 Congratulations! You received a positive response from {company} for {role}."
    notify_user(message, {
        "company": company,
        "role": role,
        "type": "positive_response"
    })
