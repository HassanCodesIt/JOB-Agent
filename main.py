import sys
import asyncio

if sys.platform == 'win32':
    asyncio.set_event_loop_policy(asyncio.WindowsProactorEventLoopPolicy())

from fastapi import FastAPI, Depends, HTTPException, BackgroundTasks, File, UploadFile, Request, Body
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from database import SessionLocal, engine, Base
import models
import schemas
from typing import List
import os
import json
import shutil
import base64
import datetime
from automation_service import automation_service
from llm_service import llm_service
from ocr_service import ocr_service
from email_service import email_service
from utils import notify_blocked, notify_user
from bulk_service import bulk_service

# Create tables
models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="Auto Job Application Agent")

@app.on_event("startup")
async def startup_event():
    # Automatically pause any active campaigns on startup
    db = SessionLocal()
    try:
        bulk_service.pause_all_active_campaigns(db)
    finally:
        db.close()

# Static files and templates
app.mount("/static", StaticFiles(directory="static"), name="static")
templates = Jinja2Templates(directory="templates")
os.makedirs("templates", exist_ok=True)
os.makedirs("static", exist_ok=True)

# Dependency
def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()

async def process_application(app_id: int):
    db = SessionLocal()
    try:
        job_app = db.query(models.JobApplication).get(app_id)
        if not job_app:
            return

        try:
            # 1. Detect form structure (only if URL is present)
            form_structure = []
            screenshot_path = None
            
            if job_app.application_url and job_app.application_url.startswith("http"):
                result, screenshot_path = await automation_service.detect_form(job_app.application_url)
                
                if result == "blocked":
                    job_app.status = "blocked"
                    db.commit()
                    notify_blocked(app_id, job_app.application_url, screenshot_path)
                    return
                
                form_structure = result
                # Save form structure
                db_form = models.ApplicationForm(
                    application_id=app_id,
                    form_structure=json.dumps(form_structure),
                    screenshot_path=screenshot_path
                )
                db.add(db_form)
            else:
                print(f"Skipping form detection for app {app_id} (no valid URL)")
            
            # 2. Get User Profile
            user = db.query(models.User).first()
            if not user:
                job_app.status = "blocked"
                db.commit()
                notify_user(f"Action Required: No user profile found for app {app_id}")
                return

            user_profile = {
                "full_name": user.full_name,
                "email": user.email,
                "phone": user.phone,
                "skills": user.skills,
                "experience": user.experience,
                "projects": user.projects,
                "portfolio_links": user.portfolio_links,
                "standard_answers": user.standard_answers
            }

            # 3. Data Extraction & Mapping
            groq_key = user.groq_api_key if user and user.groq_api_key else None
            
            print(f"DEBUG: Processing app {app_id} with Groq Key: {'Set' if groq_key else 'Not Set'}")

            # If we don't have essential details, try to extract them again (or initial extract)
            if job_app.ocr_text:
                print(f"DEBUG: Raw Text Length: {len(job_app.ocr_text)}")
                print(f"DEBUG: Extracting details from text for app {app_id}...")
                text_details = {}
                try:
                    text_details = llm_service.extract_details_from_text(job_app.ocr_text, api_key=groq_key)
                except Exception as e:
                    print(f"DEBUG: Unexpected error in extraction for app {app_id}: {e}")
                    text_details = {"error": "UNEXPECTED_ERROR", "detail": str(e)}

                # HARD FALLBACK: Regex scan first
                if not job_app.contact_email:
                    import re
                    email_pattern = r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}'
                    emails = re.findall(email_pattern, job_app.ocr_text)
                    if emails:
                        job_app.contact_email = emails[0]
                        print(f"DEBUG: Found email via direct regex in main.py: {job_app.contact_email}")

                if text_details.get("error") == "API_KEY_OR_MODEL_ERROR":
                    print(f"DEBUG: LLM extraction failed for app {app_id} (API ERROR). Using regex only.")
                
                # Update fields if they are missing
                job_app.company_name = job_app.company_name or text_details.get("company_name")
                job_app.role = job_app.role or text_details.get("role")
                
                if not job_app.contact_email:
                    extracted_email = text_details.get("contact_email")
                    if extracted_email and "@" in str(extracted_email):
                        job_app.contact_email = extracted_email
                
                print(f"DEBUG: Extracted so far: Company={job_app.company_name}, Role={job_app.role}, Email={job_app.contact_email}")

                if not job_app.contact_phone:
                    job_app.contact_phone = text_details.get("contact_phone")
                if not job_app.application_url:
                    job_app.application_url = text_details.get("application_link")
                
                # NEW: Extract and store CC emails
                if text_details.get("cc_emails") and isinstance(text_details["cc_emails"], list):
                    cc_list = [email for email in text_details["cc_emails"] if email and "@" in email]
                    if cc_list:
                        job_app.cc_emails = ', '.join(cc_list)
                        print(f"DEBUG: Auto-detected CC emails: {job_app.cc_emails}")

            mapping_result = {}
            if form_structure:
                print(f"DEBUG: Mapping fields for app {app_id}...")
                try:
                    mapping_result = llm_service.map_fields(user_profile, form_structure, api_key=groq_key)
                    if mapping_result.get("error") == "API_KEY_OR_MODEL_ERROR":
                        print(f"DEBUG: Mapping failed for app {app_id}")
                    else:
                        job_app.confidence_score = mapping_result.get("confidence_score", 0)
                        job_app.company_name = mapping_result.get("company_name", job_app.company_name)
                        job_app.role = mapping_result.get("role", job_app.role)
                        
                        mapping_dict = mapping_result.get("field_mappings", {})
                        new_mapping_draft = models.Draft(
                            application_id=app_id,
                            content=json.dumps(mapping_dict),
                            draft_type="form_mapping"
                        )
                        db.add(new_mapping_draft)
                        db.commit()

                        asyncio.create_task(automation_service.fill_form(
                            job_app.application_url, 
                            mapping_dict, 
                            resume_path=user.resume_path
                        ))
                except Exception as e:
                    print(f"DEBUG: Mapping error for app {app_id}: {e}")
            
            # 5. Create Email Draft
            print(f"DEBUG: Generating email draft for app {app_id}...")
            job_details = {
                "company": job_app.company_name,
                "role": job_app.role,
                "url": job_app.application_url,
                "text": job_app.ocr_text,
                "contact_email": job_app.contact_email
            }
            
            email_data = {}
            try:
                email_data = llm_service.generate_email_draft(user_profile, job_details, custom_system_prompt=user.system_prompt, api_key=groq_key)
            except Exception as e:
                print(f"DEBUG: Email generation error for app {app_id}: {e}")
                email_data = {"error": "GENERATION_ERROR", "detail": str(e)}

            if email_data.get("error"):
                print(f"DEBUG: Using template fallback for email for app {app_id}")
                subject = f"Job Application: {job_app.role}"
                user_phone = user.phone if user.phone and user.phone.startswith('+') else f"+91 {user.phone}"
                body = f"Dear Hiring Manager,\n\nI am writing to express my interest in the {job_app.role} position at {job_app.company_name}.\n\nAttached is my resume for your review.\n\nBest regards,\n{user.full_name}\n{user_phone}\n{user.email}"
            else:
                subject = email_data.get("subject")
                body = email_data.get("body")
                
                # BACKFILL: If company/role was unknown, use what the email draft found
                if (not job_app.company_name or job_app.company_name == "Unknown Company") and email_data.get("detected_company"):
                    job_app.company_name = email_data.get("detected_company")
                    print(f"DEBUG: Backfilled Company from draft: {job_app.company_name}")
                if (not job_app.role or job_app.role == "Unknown Role") and email_data.get("detected_role"):
                    job_app.role = email_data.get("detected_role")
                    print(f"DEBUG: Backfilled Role from draft: {job_app.role}")
            
            # FINAL DEFAULTS
            job_app.company_name = job_app.company_name or "Unknown Company"
            job_app.role = job_app.role or "Unknown Role"

            new_email_draft = models.Draft(
                application_id=app_id,
                subject=subject,
                content=body,
                draft_type="email",
                is_ready=True
            )
            db.add(new_email_draft)
            
            # Final sanity check for email: if still blank, try one last regex search on the draft itself (rarely works but safe)
            if not job_app.contact_email:
                import re
                draft_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', body)
                if draft_emails:
                    # Ignore own email
                    for e in draft_emails:
                        if e.lower() != user.email.lower():
                            job_app.contact_email = e
                            print(f"DEBUG: Found email in draft body: {e}")
                            break

            # Set status to draft even if partial
            job_app.status = "draft"
            db.commit()
            print(f"DEBUG: Application {app_id} successfully moved to 'draft' status.")
            notify_user(f"Drafts ready for {job_app.company_name}")

        except Exception as e:
            job_app.status = "blocked"
            print(f"ERROR: Exception in process_application {app_id}: {e}")
            db.commit()
            notify_user(f"System Error for app {app_id}: {str(e)}")
    finally:
        db.close()


# Frontend Routes
from fastapi.responses import RedirectResponse
from pdfminer.high_level import extract_text

def is_setup_complete(db: Session):
    user = db.query(models.User).first()
    return user is not None and bool(user.full_name) and bool(user.email)

@app.get("/setup", response_class=HTMLResponse)
async def setup_page(request: Request, db: Session = Depends(get_db)):
    if is_setup_complete(db):
        return RedirectResponse(url="/", status_code=307)
    return templates.TemplateResponse("setup.html", {"request": request})

@app.post("/setup/parse-resume")
async def parse_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
        
    try:
        raw_text = extract_text(file_path)
        if not raw_text.strip():
            raise HTTPException(status_code=400, detail="Could not extract text from the PDF.")
            
        groq_key = os.getenv("GROQ_API_KEY")
        if not groq_key:
            raise HTTPException(status_code=400, detail="Groq API key not configured in environment (.env).")
            
        prompt = f"""
        Extract professional details from the following resume raw text.
        Return ONLY a JSON object with the following fields:
        {{
            "full_name": "candidate name",
            "email": "contact email",
            "phone": "contact phone number",
            "portfolio_links": "LinkedIn/GitHub/website links as a single string",
            "skills": "list of key skills as a comma-separated string",
            "experience": "brief experience summary / timeline",
            "projects": "list of key projects and technologies used"
        }}
        
        Resume Text:
        \"\"\"{raw_text}\"\"\"
        """
        
        from openai import OpenAI
        client = OpenAI(
            base_url="https://api.groq.com/openai/v1",
            api_key=groq_key
        )
        
        response = client.chat.completions.create(
            model="llama-3.3-70b-versatile",
            messages=[
                {{"role": "user", "content": prompt}}
            ],
            temperature=0,
            response_format={{"type": "json_object"}}
        )
        
        result_text = response.choices[0].message.content
        data = json.loads(result_text)
        data["resume_path"] = os.path.abspath(file_path)
        return data
        
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to parse resume: {str(e)}")

@app.post("/setup/save")
async def save_profile(data: dict = Body(...), db: Session = Depends(get_db)):
    user = db.query(models.User).first()
    if not user:
        user = models.User()
        db.add(user)
        
    user.full_name = data.get("full_name")
    user.email = data.get("email")
    user.phone = data.get("phone")
    user.portfolio_links = data.get("portfolio_links")
    user.skills = data.get("skills")
    user.experience = data.get("experience")
    user.projects = data.get("projects")
    user.system_prompt = data.get("system_prompt")
    
    if data.get("resume_path"):
        user.resume_path = data.get("resume_path")
        
    user.groq_api_key = os.getenv("GROQ_API_KEY")
    user.groq_backup_api_key = os.getenv("GROQ_BACKUP_API_KEY")
    user.hf_token = os.getenv("HF_TOKEN")
    user.openrouter_api_key = os.getenv("OPENROUTER_API_KEY")
    
    db.commit()
    return {{"message": "Profile saved successfully"}}

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request, db: Session = Depends(get_db)):
    if not is_setup_complete(db):
        return RedirectResponse(url="/setup", status_code=307)
    # Only show manually created/sent applications
    apps = db.query(models.JobApplication).filter(models.JobApplication.is_manual == True).order_by(models.JobApplication.created_at.desc()).all()
    
    # Find positive response count (only for manual apps)
    pos_count = db.query(models.JobApplication).filter(
        models.JobApplication.is_manual == True,
        models.JobApplication.status == "positive_response"
    ).count()
    
    pos_apps = db.query(models.JobApplication).filter(
        models.JobApplication.is_manual == True,
        models.JobApplication.status == "positive_response"
    ).all()
    
    # NEW: Fetch sent emails
    sent_emails = db.query(models.SentEmail).order_by(models.SentEmail.sent_at.desc()).all()
    
    return templates.TemplateResponse("dashboard.html", {
        "request": request, 
        "applications": apps, 
        "positive_count": pos_count,
        "positive_apps": pos_apps,
        "sent_emails": sent_emails,
        "active_page": "dashboard"
    })

@app.post("/sync/")
async def sync_all(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    email_service.monitor_inbox()
    return {"message": "Sync complete"}

@app.get("/sent", response_class=HTMLResponse)
async def sent_mails_page(request: Request, db: Session = Depends(get_db)):
    if not is_setup_complete(db):
        return RedirectResponse(url="/setup", status_code=307)
    sent_emails = db.query(models.SentEmail).order_by(models.SentEmail.sent_at.desc()).all()
    # Join with JobApplication to get company/role info
    sent_with_info = db.query(models.SentEmail, models.JobApplication).outerjoin(models.JobApplication).order_by(models.SentEmail.sent_at.desc()).all()
    
    return templates.TemplateResponse("sent_mails.html", {
        "request": request,
        "sent_emails": sent_with_info
    })

@app.get("/apply", response_class=HTMLResponse)
async def apply_page(request: Request, db: Session = Depends(get_db)):
    if not is_setup_complete(db):
        return RedirectResponse(url="/setup", status_code=307)
    drafts = db.query(models.Draft).order_by(models.Draft.id.desc()).all()
    emails = db.query(models.EmailEvent).order_by(models.EmailEvent.received_at.desc()).all()
    user = db.query(models.User).first()
    # Join Draft with JobApplication to get company name
    drafts_with_info = db.query(models.Draft, models.JobApplication).join(models.JobApplication).order_by(models.Draft.id.desc()).all()
    
    return templates.TemplateResponse("apply.html", {
        "request": request,
        "recent_drafts": drafts_with_info,
        "emails": emails,
        "user": user,
        "active_page": "apply"
    })

@app.get("/settings", response_class=HTMLResponse)
async def settings_page(request: Request, db: Session = Depends(get_db)):
    if not is_setup_complete(db):
        return RedirectResponse(url="/setup", status_code=307)
    user = db.query(models.User).first()
    if not user:
        user = models.User(full_name="Candidate Name")
        db.add(user)
        db.commit()
        db.refresh(user)
    return templates.TemplateResponse("settings.html", {"request": request, "user": user})

@app.post("/user/update/")
async def update_user_settings(data: dict = Body(...), db: Session = Depends(get_db)):
    user = db.query(models.User).first()
    if not user:
        user = models.User(full_name="Candidate Name")
        db.add(user)
    
    for key, value in data.items():
        if hasattr(user, key):
            setattr(user, key, value)
    
    db.commit()
    return {"message": "Settings updated successfully"}

@app.post("/user/resume/")
async def upload_resume(file: UploadFile = File(...), db: Session = Depends(get_db)):
    os.makedirs("uploads", exist_ok=True)
    file_path = f"uploads/{file.filename}"
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    user = db.query(models.User).first()
    if not user:
        user = models.User(full_name="Default User")
        db.add(user)
    
    user.resume_path = os.path.abspath(file_path)
    db.commit()
    return {"message": "Resume uploaded successfully", "path": user.resume_path}

@app.post("/applications/text/")
async def process_job_text(background_tasks: BackgroundTasks, text: str = Body(..., embed=True), db: Session = Depends(get_db)):
    # Create application record
    new_app = models.JobApplication(
        ocr_text=text,
        status="processing"
    )
    db.add(new_app)
    db.commit()
    db.refresh(new_app)
    
    # Trigger background processing (LLM extraction and draft generation)
    background_tasks.add_task(process_application, new_app.id)
    return new_app

@app.post("/user/system_prompt/")
async def update_system_prompt(prompt: str = Body(..., embed=True), db: Session = Depends(get_db)):
    user = db.query(models.User).first()
    if not user:
        user = models.User(full_name="Candidate Name")
        db.add(user)
    
    user.system_prompt = prompt
    db.commit()
    return {"message": "Drafting instructions updated successfully"}

@app.post("/user/groq_api_key/")
async def update_groq_api_key(api_key: str = Body(..., embed=True), db: Session = Depends(get_db)):
    user = db.query(models.User).first()
    if not user:
        user = models.User(full_name="Candidate Name")
        db.add(user)
    user.groq_api_key = api_key
    db.commit()
    return {"message": "Groq API Key updated successfully"}

@app.post("/user/hf_token/")
async def update_hf_token(token: str = Body(..., embed=True), db: Session = Depends(get_db)):
    user = db.query(models.User).first()
    if not user:
        user = models.User(full_name="Candidate Name")
        db.add(user)
    user.hf_token = token
    db.commit()
    return {"message": "HuggingFace Token updated successfully"}

@app.post("/drafts/regenerate/{draft_id}")
async def regenerate_draft(draft_id: int, data: dict = Body(None), db: Session = Depends(get_db)):
    instructions = data.get("instructions") if data else None
    
    draft = db.query(models.Draft).get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    job_app = draft.application
    user = db.query(models.User).first()
    
    if not user or not job_app:
        raise HTTPException(status_code=400, detail="Missing user or application data")

    user_profile = {
        "full_name": user.full_name,
        "email": user.email,
        "phone": user.phone,
        "skills": user.skills,
        "experience": user.experience,
        "projects": user.projects,
        "portfolio_links": user.portfolio_links,
        "standard_answers": user.standard_answers
    }

    job_details = {
        "company": job_app.company_name,
        "role": job_app.role,
        "url": job_app.application_url,
        "text": job_app.ocr_text
    }

    groq_key = user.groq_api_key if user and user.groq_api_key else None
    email_data = llm_service.generate_email_draft(
        user_profile, 
        job_details, 
        custom_system_prompt=user.system_prompt, 
        api_key=groq_key,
        instructions=instructions
    )
    
    if email_data.get("error") == "API_KEY_OR_MODEL_ERROR":
        raise HTTPException(status_code=401, detail=email_data.get("detail"))
    
    draft.subject = email_data.get("subject")
    draft.content = email_data.get("body")
    db.commit()
    
    return {"message": "Draft regenerated successfully", "subject": draft.subject, "content": draft.content}

from email_sender import send_email

@app.get("/drafts", response_class=HTMLResponse)
async def drafts_page(request: Request, db: Session = Depends(get_db)):
    if not is_setup_complete(db):
        return RedirectResponse(url="/setup", status_code=307)
    # Fetch email drafts
    drafts_with_info = db.query(models.Draft, models.JobApplication).join(models.JobApplication).filter(models.Draft.draft_type == "email").order_by(models.Draft.id.desc()).all()
    
    # Fetch apps that are currently being processed
    processing_apps = db.query(models.JobApplication).filter(models.JobApplication.status == "processing").all()
    
    # Fetch apps that are blocked (need user action)
    blocked_apps = db.query(models.JobApplication).filter(models.JobApplication.status == "blocked").order_by(models.JobApplication.updated_at.desc()).all()
    
    user = db.query(models.User).first()
    
    return templates.TemplateResponse("drafts.html", {
        "request": request,
        "drafts": drafts_with_info,
        "processing_apps": processing_apps,
        "active_page": "drafts"
    })

@app.get("/replies", response_class=HTMLResponse)
async def replies_page(request: Request, db: Session = Depends(get_db)):
    if not is_setup_complete(db):
        return RedirectResponse(url="/setup", status_code=307)
    import datetime
    # Fetch latest 10 emails as they appear in Gmail
    emails = db.query(models.EmailEvent).order_by(models.EmailEvent.received_at.desc()).limit(10).all()
    
    return templates.TemplateResponse("replies.html", {
        "request": request,
        "emails": emails,
        "now": datetime.datetime.utcnow(),
        "active_page": "replies"
    })

@app.get("/replies/{app_id}", response_class=HTMLResponse)
async def reply_editor(app_id: int, request: Request, db: Session = Depends(get_db)):
    if not is_setup_complete(db):
        return RedirectResponse(url="/setup", status_code=307)
    app = db.query(models.JobApplication).get(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    
    # Get all communications
    received = db.query(models.EmailEvent).filter(models.EmailEvent.application_id == app_id).all()
    sent = db.query(models.SentEmail).filter(models.SentEmail.application_id == app_id).all()
    
    # Merge and sort by time
    history = []
    for r in received:
        history.append({"type": "received", "sender": r.sender, "content": r.snippet, "time": r.received_at, "subject": r.subject})
    for s in sent:
        history.append({"type": "sent", "sender": "ME", "content": s.body, "time": s.sent_at, "subject": s.subject})
    
    history.sort(key=lambda x: x["time"])
    
    return templates.TemplateResponse("reply_editor.html", {
        "request": request,
        "app": app,
        "history": history,
        "active_page": "replies"
    })

@app.post("/replies/generate")
async def generate_ai_reply(data: schemas.ReplyGenerateRequest, db: Session = Depends(get_db)):
    app_id = data.app_id
    instructions = data.instructions
    
    app = db.query(models.JobApplication).get(app_id)
    user = db.query(models.User).first()
    
    if not app or not user:
        raise HTTPException(status_code=400, detail="Data missing")
        
    # Build history for LLM
    received = db.query(models.EmailEvent).filter(models.EmailEvent.application_id == app_id).all()
    sent = db.query(models.SentEmail).filter(models.SentEmail.application_id == app_id).all()
    
    history = []
    for r in received:
        history.append({"type": "received", "content": r.snippet})
    for s in sent:
        history.append({"type": "sent", "content": s.body})
        
    groq_key = user.groq_api_key
    user_profile = {
        "full_name": user.full_name,
        "email": user.email,
        "skills": user.skills,
        "experience": user.experience
    }
    
    reply = llm_service.generate_reply(user_profile, history, instructions, api_key=groq_key)
    return reply

@app.post("/emails/send/direct")
async def send_direct_email(data: schemas.DirectEmailRequest, db: Session = Depends(get_db)):
    print(f"DEBUG: DIRECT SEND REQUEST RECEIVED: {data}")
    
    app_id = data.app_id
    recipient = data.recipient
    subject = data.subject or "Reply"
    content = data.content
    cc = data.cc

    if not recipient or not content:
        print("DEBUG: Direct send failed - missing recipient or content")
        raise HTTPException(status_code=400, detail="Recipient and content are required")

    user = db.query(models.User).first()
    resume_path = user.resume_path if user else None

    print(f"DEBUG: Attempting to send email to {recipient} via send_email...")
    from email_sender import send_email
    success = send_email(recipient, subject, content, attachment_path=resume_path, cc=cc)
    
    if success:
        print("DEBUG: Email sent successfully via SMTP")
        sent_email_record = models.SentEmail(
            application_id=app_id,
            recipient_email=recipient,
            cc_emails=cc if isinstance(cc, str) else None,
            subject=subject,
            body=content
        )
        db.add(sent_email_record)
        
        if app_id:
            app = db.query(models.JobApplication).get(app_id)
            if app:
                app.status = "shortlisted"
        
        db.commit()
        return {"status": "success", "message": "Email sent successfully"}
    else:
        print("DEBUG: Email send failed in SMTP layer")
        raise HTTPException(status_code=500, detail="SMTP Delivery failed. Check credentials or recipient email.")

@app.post("/emails/send/{draft_id}")
async def send_draft_email(draft_id: int, data: dict = Body(...), db: Session = Depends(get_db)):
    draft = db.query(models.Draft).get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    
    job_app = draft.application
    
    # Get values from body or defaults
    email_content = data.get("content") or draft.content
    recipient_email = data.get("recipient") or (job_app.contact_email if job_app else None)
    subject = data.get("subject") or draft.subject or (f"Job Application: {job_app.role}" if job_app else "Job Application")
    cc_emails = data.get("cc")  # NEW: Get CC emails from request

    if not recipient_email:
        raise HTTPException(status_code=400, detail="No contact email provided for this application")

    # Get user's resume
    user = db.query(models.User).first()
    resume_path = user.resume_path if user else None

    # Send email with CC support
    success = send_email(
        recipient_email, 
        subject, 
        email_content, 
        attachment_path=resume_path,
        cc=cc_emails
    )
    
    if success:
        if job_app:
            job_app.status = "awaiting_response"
            job_app.contact_email = recipient_email # Save it if it was manually entered
        
        # NEW: Record the sent email with CC
        cc_string = None
        if cc_emails:
            if isinstance(cc_emails, list):
                cc_string = ', '.join(cc_emails)
            else:
                cc_string = cc_emails
        
        sent_email_record = models.SentEmail(
            application_id=job_app.id if job_app else None,
            recipient_email=recipient_email,
            cc_emails=cc_string,
            subject=subject,
            body=email_content
        )
        db.add(sent_email_record)
        
        # Update draft with final sent content and subject
        draft.content = email_content
        draft.subject = subject
        db.commit()
        return {"message": "Email sent successfully with resume attached"}
    else:
        raise HTTPException(status_code=500, detail="Failed to send email")

# User Profile Endpoints
@app.post("/user/", response_model=schemas.User)
def create_user(user: schemas.UserCreate, db: Session = Depends(get_db)):
    db_user = models.User(**user.dict())
    db.add(db_user)
    db.commit()
    db.refresh(db_user)
    return db_user

@app.get("/user/", response_model=schemas.User)
def get_user(db: Session = Depends(get_db)):
    user = db.query(models.User).first()
    if not user:
        raise HTTPException(status_code=404, detail="User not found")
    return user

# Application Endpoints
@app.post("/applications/job/", response_model=schemas.JobApplication)
def apply_to_job(job_url: str, background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    new_app = models.JobApplication(application_url=job_url, status="processing")
    db.add(new_app)
    db.commit()
    db.refresh(new_app)
    background_tasks.add_task(process_application, new_app.id)
    return new_app

@app.post("/applications/poster/")
async def upload_poster(background_tasks: BackgroundTasks, file: UploadFile = File(...), db: Session = Depends(get_db)):
    file_path = f"posters/{file.filename}"
    os.makedirs("posters", exist_ok=True)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)
    
    user = db.query(models.User).first()
    ocr_api_key = user.hf_token if user and user.hf_token else None
    ocr_data = ocr_service.process_job_poster(file_path, api_key=ocr_api_key)
    if ocr_data.get("error") == "API_KEY_OR_MODEL_ERROR":
        raise HTTPException(status_code=401, detail=ocr_data.get("detail"))
    if "error" in ocr_data:
        raise HTTPException(status_code=500, detail=ocr_data["error"])
    
    status = "draft"
    if ocr_data.get("confidence_score", 1.0) < 0.6:
        status = "ocr_uncertain"
    
    # NEW: Extract CC emails from OCR
    cc_emails_list = ocr_data.get("cc_emails", [])
    cc_emails_string = ', '.join(cc_emails_list) if cc_emails_list else None

    new_app = models.JobApplication(
        company_name=ocr_data.get("company_name"),
        role=ocr_data.get("role_title"),
        contact_email=ocr_data.get("contact_email"),
        contact_phone=ocr_data.get("contact_phone"),
        cc_emails=cc_emails_string,  # NEW: Store CC emails
        application_url=ocr_data.get("application_link"),
        ocr_text=ocr_data.get("raw_text"),
        poster_path=file_path,
        status="processing"
    )
    db.add(new_app)
    db.commit()
    db.refresh(new_app)
    
    # Trigger background email writing and refinement
    background_tasks.add_task(process_application, new_app.id)
    
    if status == "ocr_uncertain":
        notify_user(f"OCR Uncertain for poster: {file.filename}. Please review.")
    
    return new_app

@app.get("/applications/{app_id}/draft/", response_model=schemas.Draft)
def get_application_draft(app_id: int, db: Session = Depends(get_db)):
    draft = db.query(models.Draft).filter(models.Draft.application_id == app_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    return draft


@app.post("/applications/{app_id}/submit/")
async def submit_application(app_id: int, db: Session = Depends(get_db)):
    job_app = db.query(models.JobApplication).get(app_id)
    if not job_app:
        raise HTTPException(status_code=404, detail="Application not found")
    
    job_app.status = "submitted"
    db.commit()
    return {"message": "Application marked as submitted", "status": "submitted"}

@app.post("/applications/{app_id}/draft/toggle-star/")
def toggle_draft_star(app_id: int, db: Session = Depends(get_db)):
    draft = db.query(models.Draft).filter(models.Draft.application_id == app_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft.is_starred = not draft.is_starred
    db.commit()
    return {"is_starred": draft.is_starred}

@app.post("/applications/{app_id}/draft/toggle-favorite/")
def toggle_draft_favorite(app_id: int, db: Session = Depends(get_db)):
    draft = db.query(models.Draft).filter(models.Draft.application_id == app_id).first()
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    draft.is_favorite = not draft.is_favorite
    db.commit()
    return {"is_favorite": draft.is_favorite}

@app.get("/applications/", response_model=List[schemas.JobApplication])
def list_applications(db: Session = Depends(get_db)):
    return db.query(models.JobApplication).all()

@app.get("/applications/poll-emails/")
def poll_emails():
    email_service.monitor_inbox()
    return {"message": "Polled inbox for new emails"}

@app.get("/stats/")
def get_stats(db: Session = Depends(get_db)):
    total = db.query(models.JobApplication).filter(models.JobApplication.is_manual == True).count()
    submitted = db.query(models.JobApplication).filter(
        models.JobApplication.is_manual == True,
        models.JobApplication.status == "submitted"
    ).count()
    responded_pos = db.query(models.JobApplication).filter(
        models.JobApplication.is_manual == True,
        models.JobApplication.status == "positive_response"
    ).count()
    return {
        "total_applications": total,
        "submitted": submitted,
        "positive_responses": responded_pos
    }

@app.delete("/drafts/{draft_id}")
def delete_draft(draft_id: int, db: Session = Depends(get_db)):
    draft = db.query(models.Draft).get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    db.delete(draft)
    db.commit()
    return {"message": "Draft deleted successfully"}

@app.delete("/applications/{app_id}")
def delete_application(app_id: int, db: Session = Depends(get_db)):
    app = db.query(models.JobApplication).get(app_id)
    if not app:
        raise HTTPException(status_code=404, detail="Application not found")
    
    # Delete related records
    db.query(models.Draft).filter(models.Draft.application_id == app_id).delete()
    db.query(models.ApplicationForm).filter(models.ApplicationForm.application_id == app_id).delete()
    db.query(models.EmailEvent).filter(models.EmailEvent.application_id == app_id).delete()
    db.query(models.Response).filter(models.Response.application_id == app_id).delete()
    
    db.delete(app)
    db.commit()
    return {"message": "Application deleted successfully"}

# --- OUTREACH / BULK SEND FEATURES ---
from bulk_service import bulk_service

@app.get("/outreach", response_class=HTMLResponse)
@app.get("/outreach", response_class=HTMLResponse)
async def outreach_page(request: Request, db: Session = Depends(get_db)):
    if not is_setup_complete(db):
        return RedirectResponse(url="/setup", status_code=307)
    campaigns = db.query(models.Campaign).order_by(models.Campaign.created_at.desc()).all()
    user = db.query(models.User).first()
    
    # Calculate emails sent today
    today = datetime.datetime.utcnow().date()
    sent_today = db.query(models.SentEmail).filter(
        models.SentEmail.sent_at >= datetime.datetime.combine(today, datetime.time.min),
        models.SentEmail.sent_at <= datetime.datetime.combine(today, datetime.time.max)
    ).count()
    
    return templates.TemplateResponse("outreach.html", {
        "request": request,
        "campaigns": campaigns,
        "user": user,
        "active_page": "outreach",
        "sent_today": sent_today
    })

@app.post("/campaigns/start")
async def start_campaign(
    background_tasks: BackgroundTasks,
    name: str = Body(...),
    sheet_url: str = Body(...),
    header_row: int = Body(1),
    context1: str = Body(""),
    context2: str = Body(""),
    daily_limit: int = Body(None),
    db: Session = Depends(get_db)
):
    try:
        # Create campaign synchronously first
        campaign_id = await bulk_service.create_campaign(db, name, sheet_url, header_row, context1, context2, daily_limit)
        
        # Start background processing
        background_tasks.add_task(bulk_service.run_campaign_loop, campaign_id)
        
        return {"message": "Campaign started", "campaign_id": campaign_id}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/campaigns/{campaign_id}/retry")
async def retry_campaign(
    background_tasks: BackgroundTasks,
    campaign_id: int, 
    payload: dict = Body(None), # Optional JSON payload
    db: Session = Depends(get_db)
):
    try:
        new_header_row = None
        if payload and "header_row" in payload:
            try:
                new_header_row = int(payload["header_row"])
            except:
                pass # Ignore invalid int

        # Retry importing items
        await bulk_service.retry_campaign(db, campaign_id, new_header_row=new_header_row)
        
        # Start background processing again
        background_tasks.add_task(bulk_service.run_campaign_loop, campaign_id)
        
        return {"message": "Campaign retried and started"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.post("/campaigns/{campaign_id}/pause")
async def pause_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(models.Campaign).get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign.status = "paused"
    db.commit()
    return {"status": "paused"}

@app.post("/campaigns/{campaign_id}/resume")
async def resume_campaign(
    background_tasks: BackgroundTasks,
    campaign_id: int, 
    db: Session = Depends(get_db)
):
    campaign = db.query(models.Campaign).get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404, detail="Campaign not found")
    
    campaign.status = "active"
    db.commit()
    
    # Restart the loop (it handles checking for existing items)
    background_tasks.add_task(bulk_service.run_campaign_loop, campaign_id)
    
    return {"status": "active"}

@app.post("/campaigns/{campaign_id}/retry_failed")
async def retry_failed_items(
    background_tasks: BackgroundTasks,
    campaign_id: int, 
    db: Session = Depends(get_db)
):
    try:
        count = await bulk_service.retry_failed_items(db, campaign_id)
        # Restart the loop
        background_tasks.add_task(bulk_service.run_campaign_loop, campaign_id)
        return {"message": f"Retrying {count} failed items"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/campaigns/{campaign_id}")
async def get_campaign(campaign_id: int, db: Session = Depends(get_db)):
    campaign = db.query(models.Campaign).get(campaign_id)
    if not campaign:
        raise HTTPException(status_code=404)
    # Return basic stats for polling
    return {
        "id": campaign.id,
        "status": campaign.status,
        "sent": campaign.sent_count,
        "total": campaign.total_count
    }

@app.get("/campaigns/{campaign_id}/items")
async def get_campaign_items(campaign_id: int, db: Session = Depends(get_db)):
    # Return full list of items for the details view
    items = db.query(models.CampaignItem).filter(models.CampaignItem.campaign_id == campaign_id).order_by(models.CampaignItem.id.asc()).all()
    if not items:
        return []
    
    result = []
    for i in items:
        result.append({
            "id": i.id,
            "recipient_email": i.recipient_email,
            "recipient_name": i.recipient_name,
            "company": i.company,
            "status": i.status, # pending, sent, error
            "error_msg": i.error_msg,
            "sent_at": i.sent_at.isoformat() if i.sent_at else None
        })
    return result

@app.post("/applications/poster/paste/")
async def paste_poster(background_tasks: BackgroundTasks, data: dict = Body(...), db: Session = Depends(get_db)):
    image_data = data.get("image") # base64 string
    if not image_data:
        raise HTTPException(status_code=400, detail="No image data provided")
    
    # Remove prefix if present
    if "base64," in image_data:
        image_data = image_data.split("base64,")[1]
    
    try:
        img_bytes = base64.b64decode(image_data)
        file_name = f"pasted_poster_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}.png"
        file_path = f"posters/{file_name}"
        os.makedirs("posters", exist_ok=True)
        
        with open(file_path, "wb") as buffer:
            buffer.write(img_bytes)
        
        user = db.query(models.User).first()
        ocr_api_key = user.hf_token if user and user.hf_token else None
        ocr_data = ocr_service.process_job_poster(file_path, api_key=ocr_api_key)
        if ocr_data.get("error") == "API_KEY_OR_MODEL_ERROR":
            raise HTTPException(status_code=401, detail=ocr_data.get("detail"))
        if "error" in ocr_data:
            raise HTTPException(status_code=500, detail=ocr_data["error"])
        
        # NEW: Extract CC emails from OCR
        cc_emails_list = ocr_data.get("cc_emails", [])
        cc_emails_string = ', '.join(cc_emails_list) if cc_emails_list else None
        
        new_app = models.JobApplication(
            company_name=ocr_data.get("company_name"),
            role=ocr_data.get("role_title"),
            contact_email=ocr_data.get("contact_email"),
            contact_phone=ocr_data.get("contact_phone"),
            cc_emails=cc_emails_string,  # NEW: Store CC emails
            application_url=ocr_data.get("application_link"),
            ocr_text=ocr_data.get("raw_text"),
            poster_path=file_path,
            status="processing"
        )
        db.add(new_app)
        db.commit()
        db.refresh(new_app)
        
        background_tasks.add_task(process_application, new_app.id)
        return new_app
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to process pasted image: {str(e)}")
