import imaplib
import email
from email.header import decode_header
import os
from dotenv import load_dotenv
from llm_service import llm_service
from database import SessionLocal
import models
import datetime
import email.utils

load_dotenv()

EMAIL_USER = os.getenv("EMAIL")
EMAIL_PASS = os.getenv("PASSWORD")
IMAP_SERVER = os.getenv("IMAP_SERVER")

class EmailService:
    def connect(self):
        mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        mail.login(EMAIL_USER, EMAIL_PASS)
        return mail

    def monitor_inbox(self, limit=20):
        """
        Syncs the latest emails from the primary inbox to mirror Gmail.
        """
        db = SessionLocal()
        try:
            mail = self.connect()
            mail.select("inbox")
            
            # Fetch the IDs of the last 'limit' emails
            status, messages = mail.search(None, 'ALL')
            if status != "OK":
                return
            
            email_ids = messages[0].split()
            # We fetch more than 10 to ensure we have a good buffer of latest activity
            recent_ids = email_ids[-limit:] 
            recent_ids.reverse() # Process newest first

            for num in recent_ids:
                try:
                    status, data = mail.fetch(num, '(RFC822)')
                    if status != "OK": continue

                    for response_part in data:
                        if isinstance(response_part, tuple):
                            msg = email.message_from_bytes(response_part[1])
                            
                            # Decode Subject
                            subject_raw = msg.get("Subject")
                            subject = ""
                            if subject_raw:
                                decoded = decode_header(subject_raw)
                                for part, encoding in decoded:
                                    if isinstance(part, bytes):
                                        subject += part.decode(encoding or "utf-8", errors="ignore")
                                    else:
                                        subject += part

                            sender = msg.get("From")
                            date_str = msg.get("Date")
                            
                            # Parse Date
                            received_at = datetime.datetime.utcnow()
                            if date_str:
                                try:
                                    received_dt = email.utils.parsedate_to_datetime(date_str)
                                    received_at = received_dt.replace(tzinfo=None)
                                except:
                                    pass

                            body = ""
                            if msg.is_multipart():
                                for part in msg.walk():
                                    if part.get_content_type() == "text/plain":
                                        payload = part.get_payload(decode=True)
                                        if payload: body = payload.decode(errors='ignore')
                                        break
                            else:
                                payload = msg.get_payload(decode=True)
                                if payload: body = payload.decode(errors='ignore')

                            # Avoid duplicates
                            existing_event = db.query(models.EmailEvent).filter(
                                models.EmailEvent.subject == subject,
                                models.EmailEvent.sender == sender
                            ).first()
                            
                            if existing_event: continue

                            # Classify with LLM
                            user = db.query(models.User).first()
                            groq_key = user.groq_api_key if user else None
                            groq_backup_key = user.groq_backup_api_key if user else None
                            
                            classification_result = llm_service.classify_email(subject, body[:4000], api_key=groq_key, backup_api_key=groq_backup_key)
                            classification = classification_result.get("classification", "neutral")
                            
                            import re
                            email_match = re.search(r'[\w\.-]+@[\w\.-]+', sender)
                            app_id = None
                            
                            if email_match:
                                clean_email = email_match.group(0)
                                # Try to find application
                                matching_app = db.query(models.JobApplication).filter(
                                    (models.JobApplication.contact_email == clean_email)
                                ).first()
                                
                                if matching_app:
                                    app_id = matching_app.id
                                    if classification == "positive" and matching_app.status != "positive_response":
                                        matching_app.status = "positive_response"
                                elif classification in ["positive", "neutral"]:
                                    # Create entry for unrecognized recruiter emails
                                    company = classification_result.get("company_name") or "Direct Connection"
                                    role = classification_result.get("role") or "Unknown Position"
                                    
                                    new_app = models.JobApplication(
                                        company_name=company,
                                        role=role,
                                        contact_email=clean_email,
                                        status="positive_response" if classification == "positive" else "awaiting_response",
                                        is_manual=False
                                    )
                                    db.add(new_app)
                                    db.flush()
                                    app_id = new_app.id

                            # Store EVERYTHING as requested
                            event = models.EmailEvent(
                                application_id=app_id,
                                subject=subject,
                                sender=sender,
                                snippet=body[:3000],
                                classification=classification,
                                received_at=received_at
                            )
                            db.add(event)
                except Exception as inner_e:
                    print(f"Skipping email {num} due to error: {inner_e}")
            
            db.commit()
            mail.logout()
        except Exception as e:
            print(f"Deep Sync Global Error: {e}")
        finally:
            db.close()

email_service = EmailService()
