import os
import json
from dotenv import load_dotenv
import base64
from openai import OpenAI

load_dotenv()

class OCRService:
    def __init__(self):
        self.default_token = os.getenv("HF_TOKEN")
        self.base_url = "https://router.huggingface.co/v1"
        self.model_id = "Qwen/Qwen3.6-27B:featherless-ai"

    def process_job_poster(self, image_path: str, api_key: str = None):
        """
        Processes a job poster image using Qwen/Qwen3.6-27B:featherless-ai via HuggingFace Router.
        """
        try:
            token = api_key if api_key else self.default_token
            client = OpenAI(
                base_url=self.base_url,
                api_key=token,
            )

            with open(image_path, "rb") as f:
                img_data = f.read()
                base64_image = base64.b64encode(img_data).decode("utf-8")

            prompt = """
            Extract high-quality job details from this poster image.
            Return ONLY a JSON object with the following fields:
            {
                "company_name": "...",
                "role_title": "...",
                "required_skills": ["...", "..."],
                "contact_email": "...",
                "cc_emails": ["email1@example.com", "email2@example.com"],
                "contact_phone": "...",
                "application_link": "...",
                "confidence_score": 0.0 to 1.0,
                "raw_text": "..."
            }
            
            CRITICAL INSTRUCTIONS:
            1. Check corners and bottom of the image for contact emails or phone numbers.
            2. Ensure "contact_email" is extracted if it exists anywhere in the text.
            3. Look for phrases like "CC:", "cc:", "Copy to:", "Also send to:", or any indication that additional emails should be CC'd.
            4. If CC emails are mentioned, extract them into the "cc_emails" array.
            5. If no CC is mentioned, return "cc_emails" as an empty array [].
            """

            response = client.chat.completions.create(
                model=self.model_id,
                messages=[
                    {
                        "role": "user",
                        "content": [
                            {
                                "type": "text",
                                "text": prompt
                            },
                            {
                                "type": "image_url",
                                "image_url": {
                                    "url": f"data:image/jpeg;base64,{base64_image}"
                                }
                            }
                        ]
                    }
                ],
                max_tokens=1024,
                temperature=0,
                response_format={"type": "json_object"}
            )

            result_text = response.choices[0].message.content
            data = json.loads(result_text)
            
            def clean(val):
                if not val or val in ["...", "None", "null", "unknown", "Unknown"]:
                    return None
                return str(val).strip()
            
            # Clean CC emails list
            cc_emails = data.get("cc_emails", [])
            if cc_emails and isinstance(cc_emails, list):
                cc_emails = [clean(email) for email in cc_emails if clean(email)]
            else:
                cc_emails = []

            return {
                "company_name": clean(data.get("company_name")),
                "role_title": clean(data.get("role_title")),
                "required_skills": data.get("required_skills", []),
                "contact_email": clean(data.get("contact_email")),
                "cc_emails": cc_emails,  # NEW: Include CC emails
                "contact_phone": clean(data.get("contact_phone")),
                "application_link": clean(data.get("application_link")),
                "confidence_score": data.get("confidence_score", 0.7),
                "raw_text": data.get("raw_text", "")
            }

        except Exception as e:
            error_msg = str(e).lower()
            print(f"OCR Error: {error_msg}")
            # Map specific errors to the key/model error for the frontend
            if "401" in error_msg or "invalid_api_key" in error_msg or "token" in error_msg or "429" in error_msg or "rate limit" in error_msg:
                return {"error": "API_KEY_OR_MODEL_ERROR", "detail": str(e)}
            return {"error": str(e)}

ocr_service = OCRService()
