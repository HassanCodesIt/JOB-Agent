import re
import os
import json
from groq import Groq
from openai import OpenAI
from dotenv import load_dotenv

load_dotenv()

class LLMService:
    def __init__(self):
        self.api_key = os.getenv("GROQ_API_KEY")
        self.backup_api_key = os.getenv("GROQ_BACKUP_API_KEY")
        self.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
        self.model = "llama-3.3-70b-versatile"
        self.fallback_model = "openrouter/free"
        self._groq_client_cache = None
        self._openrouter_client_cache = None

    @property
    def groq_client(self):
        if self._groq_client_cache:
            return self._groq_client_cache
        if self.api_key:
            self._groq_client_cache = Groq(api_key=self.api_key)
            return self._groq_client_cache
        return None

    @property
    def openrouter_client(self):
        if self._openrouter_client_cache:
            return self._openrouter_client_cache
        if self.openrouter_api_key:
            self._openrouter_client_cache = OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=self.openrouter_api_key,
            )
            return self._openrouter_client_cache
        return None

    def _get_groq_client(self, api_key: str = None):
        if api_key:
            return Groq(api_key=api_key)
        return self.groq_client

    def _get_openrouter_client(self, api_key: str = None):
        if api_key:
            return OpenAI(
                base_url="https://openrouter.ai/api/v1",
                api_key=api_key,
            )
        return self.openrouter_client

    def call_with_fallback(self, messages, temperature=0, response_format=None, groq_key=None, groq_backup_key=None, openrouter_key=None):
        """
        Unified LLM call with automatic fallback: Primary Groq -> Backup Groq -> OpenRouter.
        """
        # Collect Groq keys to try
        groq_keys = []
        if groq_key:
            groq_keys.append(groq_key)
        elif self.api_key:
            groq_keys.append(self.api_key)
            
        if groq_backup_key:
            groq_keys.append(groq_backup_key)
        elif self.backup_api_key:
            groq_keys.append(self.backup_api_key)

        # 1. Try Groq keys in sequence
        for i, key in enumerate(groq_keys):
            try:
                name = "Primary" if i == 0 else f"Backup-{i}"
                print(f"DEBUG: Attempting Groq {name} ({self.model})...")
                client = Groq(api_key=key)
                completion = client.chat.completions.create(
                    model=self.model,
                    messages=messages,
                    temperature=temperature,
                    response_format=response_format
                )
                return completion.choices[0].message.content
            except Exception as e:
                err_str = str(e).lower()
                is_retryable = "429" in err_str or "rate limit" in err_str or "tokens per day" in err_str or "401" in err_str or "invalid api key" in err_str
                if not is_retryable:
                    print(f"ERROR: Groq {name} failed with non-retryable error: {e}")
                    raise e
                print(f"[FALLBACK] Groq {name} failed (Rate Limit/Invalid). Trying next...")

        # 2. Finally, Fallback to OpenRouter
        or_client = self._get_openrouter_client(openrouter_key)
        if or_client:
            try:
                print(f"DEBUG: Attempting OpenRouter ({self.fallback_model})...")
                completion = or_client.chat.completions.create(
                    model=self.fallback_model,
                    messages=messages,
                    temperature=temperature,
                    response_format=response_format,
                    extra_headers={
                        "HTTP-Referer": "https://github.com/candidate/AI-Job-Assistant",
                        "X-Title": "AI Job Assistant",
                    }
                )
                return completion.choices[0].message.content
            except Exception as e:
                print(f"ERROR: OpenRouter fallback also failed: {e}")
                raise e
        
        raise Exception("All Groq keys and OpenRouter (fallback) are unavailable or hit limits.")

    def extract_details_from_text(self, text: str, api_key: str = None, backup_api_key: str = None):
        # Regex fallback for email
        email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
        emails = re.findall(email_pattern, text)
        fallback_email = emails[0] if emails else None

        prompt = f"""
        Extract job details from the following raw text (could be from a job poster or description).
        Text:
        {text}
        
        Return a JSON object:
        {{
            "company_name": "...",
            "role": "...",
            "contact_email": "...",
            "cc_emails": ["email1@example.com", "email2@example.com"],
            "contact_phone": "...",
            "application_link": "..."
        }}
        
        CRITICAL INSTRUCTIONS:
        1. Search deeply for any email address and return it in "contact_email".
        2. Look for phrases like "CC:", "cc:", "Copy to:", "Also send to:", or any indication that additional emails should be CC'd.
        3. If CC emails are mentioned, extract them into the "cc_emails" array.
        4. If no CC is mentioned, return "cc_emails" as an empty array [].
        5. Common patterns: "Send to X with CC to Y", "Email: X, CC: Y", etc.
        """
        messages = [
            {"role": "system", "content": "You are a professional assistant specialized in extracting job details. Always return a valid JSON object. If a field is unknown, use null or empty array for cc_emails."},
            {"role": "user", "content": prompt}
        ]
        
        try:
            content = self.call_with_fallback(messages, temperature=0, response_format={"type": "json_object"}, groq_key=api_key, groq_backup_key=backup_api_key)
            data = json.loads(content)
            print(f"DEBUG: LLM Raw Extraction: {data}")
            
            # Clean up the data
            def clean(val):
                if not val or val in ["...", "None", "null", "unknown", "Unknown"]:
                    return None
                return str(val).strip()

            result = {
                "company_name": clean(data.get("company_name")),
                "role": clean(data.get("role")),
                "contact_email": clean(data.get("contact_email")),
                "cc_emails": data.get("cc_emails", []),
                "contact_phone": clean(data.get("contact_phone")),
                "application_link": clean(data.get("application_link")),
                "fallback_email": fallback_email
            }

            # Clean CC emails list
            if result.get("cc_emails") and isinstance(result["cc_emails"], list):
                result["cc_emails"] = [clean(email) for email in result["cc_emails"] if clean(email)]
            else:
                result["cc_emails"] = []

            if not result.get("contact_email") and fallback_email:
                result["contact_email"] = fallback_email
                print(f"DEBUG: Applied fallback email in LLMService: {fallback_email}")
            
            return result
        except Exception as e:
            error_msg = str(e).lower()
            if "api_key_or_model_error" in error_msg or "401" in error_msg or "429" in error_msg or "rate limit" in error_msg:
                return {"error": "API_KEY_OR_MODEL_ERROR", "detail": str(e), "fallback_email": fallback_email}
            raise e

    def map_fields(self, user_profile: dict, form_structure: list, api_key: str = None, backup_api_key: str = None):
        prompt = f"""
        Given the following user profile and a list of job application form fields, map the user profile data to the form fields.
        Also, extract the company name and the job role/title if possible from the form fields or labels.
        
        User Profile:
        {json.dumps(user_profile, indent=2)}
        
        Form Fields:
        {json.dumps(form_structure, indent=2)}
        
        Return a JSON object where keys are form field selectors (or names if selector missing) and values are the corresponding user data.
        Include a 'confidence_score' between 0 and 1.
        Include 'company_name' and 'role' if detected.
        
        Example Output:
        {{
            "field_mappings": {{
                "input[name='full_name']": "John Doe",
                "input[name='email']": "john@example.com"
            }},
            "company_name": "Google",
            "role": "Software Engineer",
            "confidence_score": 0.95
        }}
        """
        messages = [
            {"role": "system", "content": "You are a professional assistant specialized in mapping user data to job application forms."},
            {"role": "user", "content": prompt}
        ]
        try:
            content = self.call_with_fallback(messages, temperature=0.1, response_format={"type": "json_object"}, groq_key=api_key, groq_backup_key=backup_api_key)
            return json.loads(content)
        except Exception as e:
            error_msg = str(e).lower()
            if "api_key_or_model_error" in error_msg or "401" in error_msg or "429" in error_msg or "rate limit" in error_msg:
                return {"error": "API_KEY_OR_MODEL_ERROR", "detail": str(e)}
            raise e

    def generate_email_draft(self, user_profile: dict, job_details: dict, custom_system_prompt: str = None, api_key: str = None, backup_api_key: str = None, instructions: str = None):
        default_system_prompt = "You are a professional career coach and copywriter. You must always use the user's specific contact signature."
        system_prompt = custom_system_prompt if custom_system_prompt else default_system_prompt

        prompt = f"""
        Generate a professional job application email draft.
        User Profile: {json.dumps(user_profile, indent=2)}
        Job Details: {json.dumps(job_details, indent=2)}
        
        CRITICAL RULES:
        1. DO NOT mention "link", "URL", "job posting", "advertisement", or "as advertised"
        2. DO NOT reference where you found this opportunity
        3. Write as if you're reaching out directly to express interest in the role
        4. Be professional, concise, and personalized to the company and role
        """

        if instructions:
            prompt += f"\nSPECIFIC USER INSTRUCTIONS FOR THIS DRAFT:\n{instructions}\n"

        # Construct dynamic signature
        signature = f"Best regards,\n{user_profile.get('full_name', 'User')}"
        if user_profile.get('phone'):
            signature += f"\n📞 {user_profile.get('phone')}"
        if user_profile.get('email'):
            signature += f"\n📧 {user_profile.get('email')}"

        prompt += f"""
        Return a JSON object:
        {{
            "subject": "...",
            "body": "...",
            "detected_company": "...",
            "detected_role": "..."
        }}

        IMPORTANT: 
        1. Use double newlines (\\n\\n) between paragraphs for clear spacing.
        2. If job_details contains "Unknown Company", try to find the real company name in the "text" field.
        3. ALWAYS end the email with exactly this signature:
        {signature}
        """
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]
        try:
            content = self.call_with_fallback(messages, temperature=0.7, response_format={"type": "json_object"}, groq_key=api_key, groq_backup_key=backup_api_key)
            data = json.loads(content)
            
            # Clean up the metadata
            def clean(val):
                if not val or val in ["...", "None", "null", "unknown", "Unknown"]:
                    return None
                return str(val).strip()

            return {
                "subject": data.get("subject"),
                "body": data.get("body"),
                "detected_company": clean(data.get("detected_company")),
                "detected_role": clean(data.get("detected_role"))
            }

        except Exception as e:
            error_msg = str(e).lower()
            if "api_key_or_model_error" in error_msg or "401" in error_msg or "429" in error_msg or "rate limit" in error_msg:
                return {"error": "API_KEY_OR_MODEL_ERROR", "detail": str(e)}
            raise e

    def generate_reply(self, user_profile: dict, history: list, instructions: str = None, api_key: str = None, backup_api_key: str = None):
        client = self._get_client(api_key)
        if not client:
            return {"error": "API_KEY_OR_MODEL_ERROR", "detail": "No Groq API key found."}

        history_str = ""
        for item in history:
            role = "USER (ME)" if item.get('type') == 'sent' else "RECRUITER"
            history_str += f"{role}: {item.get('content')}\n\n"

        # Construct dynamic signature
        signature = f"Best regards,\n{user_profile.get('full_name', 'User')}"
        if user_profile.get('phone'):
            signature += f"\n📞 {user_profile.get('phone')}"
        if user_profile.get('email'):
            signature += f"\n📧 {user_profile.get('email')}"

        prompt = f"""
        Draft a professional reply to this job-related email thread.
        
        USER PROFILE:
        {json.dumps(user_profile, indent=2)}
        
        CONVERSATION HISTORY:
        {history_str}
        
        USER'S GOAL FOR THIS REPLY:
        {instructions if instructions else "Reply professionally based on the context."}
        
        Return a JSON object:
        {{
            "subject": "RE: ...",
            "body": "..."
        }}
        
        SIGNATURE REQUIREMENT:
        ALWAYS end the email with exactly this signature:
        {signature}
        """
        messages = [
            {"role": "system", "content": "You are a professional career assistant. Draft clear, polite, and effective job application replies."},
            {"role": "user", "content": prompt}
        ]
        try:
            content = self.call_with_fallback(messages, temperature=0.7, response_format={"type": "json_object"}, groq_key=api_key, groq_backup_key=backup_api_key)
            return json.loads(content)
        except Exception as e:
            error_msg = str(e)
            if "model_decommissioned" in error_msg or "401" in error_msg or "429" in error_msg or "rate limit" in error_msg:
                return {"error": "API_KEY_OR_MODEL_ERROR", "detail": error_msg}
            raise e

    def classify_email(self, subject: str, body: str, api_key: str = None, backup_api_key: str = None):
        client = self._get_client(api_key)
        # Body is already truncated in email_service, but adding safety here too
        safe_body = body[:4000]
        prompt = f"""
        Classify the following email from a company regarding a job application.
        Subject: {subject}
        Body: {safe_body}
        
        Categories: "positive" (interview invite, next steps), "neutral" (received application, general info), "rejection" (not moving forward).
        
        Also, TRY to detect the Company Name and the Job Position/Role mentioned.
        
        Return a JSON object:
        {{
            "classification": "positive/neutral/rejection",
            "reason": "short explanation",
            "company_name": "Detected Company Name or null",
            "role": "Detected Job Role or null"
        }}
        """
        messages = [
            {"role": "system", "content": "You are an expert email classifier and extractor."},
            {"role": "user", "content": prompt}
        ]
        try:
            content = self.call_with_fallback(messages, temperature=0, response_format={"type": "json_object"}, groq_key=api_key, groq_backup_key=backup_api_key)
            return json.loads(content)
        except Exception as e:
            error_msg = str(e)
            if "model_decommissioned" in error_msg or "401" in error_msg or "429" in error_msg or "rate limit" in error_msg:
                return {"error": "API_KEY_OR_MODEL_ERROR", "detail": error_msg}
            raise e

llm_service = LLMService()
