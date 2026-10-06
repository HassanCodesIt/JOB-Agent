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

import re

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

import email_config



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

def _shell_context(request: Request):
    """Values every page needs to render the shared app shell (sidebar counts, greeting date)."""

    ctx = {"now": datetime.datetime.utcnow()}

    try:
        db = SessionLocal()
        try:
            week_ago = ctx["now"] - datetime.timedelta(days=7)
            ctx["weekly_applications"] = db.query(models.JobApplication).filter(
                models.JobApplication.is_manual == True,
                models.JobApplication.created_at >= week_ago,
            ).count()
            ctx["nav_draft_count"] = db.query(models.Draft).count()
            user = db.query(models.User).first()
        finally:
            db.close()
    except Exception:
        user = None
        ctx.setdefault("weekly_applications", 0)
        ctx.setdefault("nav_draft_count", 0)

    ctx["shell_user"] = user
    ctx["display_name"] = (user.full_name if user and user.full_name else "Candidate")
    ctx["initials"] = ctx["display_name"][:2].upper()

    return ctx


templates = Jinja2Templates(directory="templates")
templates.context_processors.append(_shell_context)

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

                "portfolio_links": _profile_links(user),

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

            # 4b. NEW: Role-Based Resume Matching (opt-in only, skipped entirely by default)

            suggested_resume = None

            if job_app.suggest_resume_change:

                print(f"DEBUG: Matching role-specific resume for app {app_id}...")

                try:

                    all_resumes = db.query(models.RoleResume).all()

                    if all_resumes:

                        resume_list = [{"id": r.id, "role": r.role, "summary": r.summary} for r in all_resumes]

                        groq_backup_key = user.groq_backup_api_key if user and user.groq_backup_api_key else None

                        match_result = llm_service.match_resume(job_app.role, job_app.ocr_text, resume_list, api_key=groq_key, backup_api_key=groq_backup_key)

                        if match_result and match_result.get("suggested_resume_id"):

                            suggested_id = match_result["suggested_resume_id"]

                            suggested_resume = db.query(models.RoleResume).get(suggested_id)

                            if suggested_resume:

                                job_app.suggested_resume_id = suggested_resume.id

                                db.commit()

                                print(f"DEBUG: Selected resume {suggested_resume.id} for app {app_id}")

                except Exception as e:

                    suggested_resume = None

                    print(f"DEBUG: Resume matching error for app {app_id}: {e}")

            if suggested_resume:

                user_profile["relevant_resume_context"] = (

                    f"Relevant resume: {suggested_resume.role}. "

                    f"Summary: {suggested_resume.summary}"

                )

            else:

                print(f"DEBUG: No resume suggestion for app {app_id}. Using Primary Resume.")

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
    gh, li, po = data.get("github_link"), data.get("linkedin_link"), data.get("portfolio_link")
    if not (gh or li or po):
        legacy = _parse_legacy_portfolio_links(data.get("portfolio_links"))
        gh, li, po = legacy["github_link"], legacy["linkedin_link"], legacy["portfolio_link"]
    user.github_link = gh or None
    user.linkedin_link = li or None
    user.portfolio_link = po or None
    user.portfolio_links = " | ".join(x for x in (gh, li, po) if x) or None
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

    # Only show manually created/sent applications.
    # The full list is kept for the aggregate stats below, but the template only
    # ever renders the first page of rows; the rest arrives via /api/applications.

    apps = db.query(models.JobApplication).filter(models.JobApplication.is_manual == True).order_by(models.JobApplication.created_at.desc()).all()

    RECENT_APPLICATIONS_PAGE = 12
    recent_apps = [application_row_payload(row, index) for index, row in enumerate(apps[:RECENT_APPLICATIONS_PAGE])]

    

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

    # Weekly application volume for the dashboard sparkline (oldest bucket first)

    now = datetime.datetime.utcnow()

    week_ago = now - datetime.timedelta(days=7)

    weekly_counts = []

    for offset in range(7, -1, -1):
        start = now - datetime.timedelta(weeks=offset + 1)
        end = now - datetime.timedelta(weeks=offset)
        weekly_counts.append(sum(
            1 for a in apps if a.created_at is not None and start <= a.created_at < end
        ))

    weekly_updated = sum(
        1 for a in apps if a.updated_at is not None and a.updated_at >= week_ago
    )

    return templates.TemplateResponse("dashboard.html", {

        "request": request, 

        "applications": recent_apps, 

        "applications_total": len(apps),

        "applications_page_size": RECENT_APPLICATIONS_PAGE,

        "awaiting_count": len([a for a in apps if a.status == "awaiting_response"]),

        "positive_count": pos_count,

        "positive_apps": pos_apps,

        "sent_emails": sent_emails,

        "weekly_counts": weekly_counts,

        "weekly_updated": weekly_updated,

        "active_page": "dashboard"

    })



@app.post("/sync/")

async def sync_all(background_tasks: BackgroundTasks, db: Session = Depends(get_db)):
    # monitor_inbox is blocking (IMAP); run it off the event loop so other
    # requests stay responsive while a sync is in progress.
    await asyncio.to_thread(email_service.monitor_inbox)

    return {"message": "Sync complete"}


@app.get("/api/current-email")
def get_current_email():
    return {"emails": email_config.get_all_emails(), "index": email_config.get_active_index()}


@app.post("/api/switch-email")
def switch_email(data: dict = Body(...)):
    index = data.get("index")
    try:
        index = int(index)
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail="index must be a slot number")
    try:
        email_config.set_active_email(index)
    except ValueError as error:
        raise HTTPException(status_code=400, detail=str(error))
    return {"message": "Active email updated", "index": index}


@app.get("/api/accounts")
def list_accounts():
    return {
        "accounts": email_config.get_account_details(),
        "active": email_config.get_active_index(),
        "free_slots": email_config.free_slots(),
    }


@app.post("/api/accounts")
def add_account(data: dict = Body(...)):
    email = (data.get("email") or "").strip()
    password = (data.get("password") or "").strip()

    if not email or "@" not in email:
        raise HTTPException(status_code=400, detail="Enter a valid email address.")
    if not password:
        raise HTTPException(status_code=400, detail="Enter the app password for this account.")

    existing = email_config.get_all_emails()
    if email in [value for value in existing.values() if value]:
        raise HTTPException(status_code=400, detail="That email is already connected.")

    try:
        slot = email_config.add_account(email, password)
    except ValueError as error:
        raise HTTPException(status_code=409, detail=str(error))

    return {"message": "Account connected", "index": slot, "email": email}


@app.delete("/api/accounts/{slot}")
def remove_account(slot: int):
    if slot not in email_config.all_slots():
        raise HTTPException(status_code=404, detail="That account is not connected.")
    if email_config.get_active_index() == slot:
        raise HTTPException(status_code=400, detail="Switch to another account before removing this one.")
    email_config.remove_account(slot)
    return {"message": "Account removed"}


APPLICATION_TONES = ("violet", "blue", "coral", "green")


def application_row_payload(row, index=0):
    """Single shape for an application row, shared by the template and the paged API."""
    return {
        "id": row.id,
        "company_name": row.company_name,
        "role": row.role,
        "status": row.status,
        "updated_at": row.updated_at.strftime('%Y-%m-%d') if row.updated_at else '',
        "updated_label": row.updated_at.strftime('%b %d, %Y') if row.updated_at else '—',
        "has_source": bool(row.ocr_text),
        "has_email": bool(row.sent_emails),
        "tone": APPLICATION_TONES[index % len(APPLICATION_TONES)],
    }


@app.get("/api/applications")
def list_applications(limit: int = 12, offset: int = 0, format: str = "html", db: Session = Depends(get_db)):
    """Paged slice of recent applications so the dashboard never renders the full table.

    Default (format=html) is unchanged server-rendered markup for the Jinja page.
    format=json returns structured `items` (same row payload) for the React UI.
    """
    limit = max(1, min(limit, 50))
    offset = max(0, offset)

    query = db.query(models.JobApplication).filter(models.JobApplication.is_manual == True)
    total = query.count()
    rows = query.order_by(models.JobApplication.created_at.desc()).offset(offset).limit(limit).all()

    payload = {
        "total": total,
        "offset": offset,
        "limit": limit,
        "count": len(rows),
        "has_more": offset + len(rows) < total,
    }

    if format == "json":
        payload["items"] = [
            application_row_payload(row, offset + index)
            for index, row in enumerate(rows)
        ]
        return payload

    # Returned as ready-made markup so "load more" rows are identical to server-rendered ones.
    payload["html"] = "".join(
        templates.get_template("partials/application_row.html").render(
            item=application_row_payload(row, offset + index))
        for index, row in enumerate(rows)
    )
    return payload



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

    links = _parse_legacy_portfolio_links(user.portfolio_links)

    return templates.TemplateResponse("settings.html", {"request": request, "user": user,
        "link_github": user.github_link or links["github_link"],
        "link_linkedin": user.linkedin_link or links["linkedin_link"],
        "link_portfolio": user.portfolio_link or links["portfolio_link"]})


def _parse_legacy_portfolio_links(raw):
    """Split the old single-field 'LinkedIn: … | GitHub: …' string into the
    separate link columns. Any segment that is neither GitHub nor LinkedIn is
    treated as the generic portfolio/website link."""
    parts = {"github_link": "", "linkedin_link": "", "portfolio_link": ""}
    if not raw:
        return parts
    segments = re.split(r"\s*\|\s*|\s*,\s*|\n+", str(raw))
    others = []
    for seg in segments:
        seg = seg.strip()
        if not seg:
            continue
        low = seg.lower()
        if "github" in low:
            parts["github_link"] = seg.split(":", 1)[1].strip() if low.startswith("github") else seg
        elif "linkedin" in low:
            parts["linkedin_link"] = seg.split(":", 1)[1].strip() if low.startswith("linkedin") else seg
        else:
            others.append(seg)
    if others:
        parts["portfolio_link"] = " | ".join(others)
    return parts


def _profile_links(user):
    """One combined string of the candidate's public links for LLM context."""
    explicit = [x for x in (getattr(user, "github_link", ""), getattr(user, "linkedin_link", ""), getattr(user, "portfolio_link", "")) if x]
    if explicit:
        return "\n".join(explicit)
    return user.portfolio_links or ""



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

async def process_job_text(background_tasks: BackgroundTasks, data: schemas.JobTextRequest = Body(...), db: Session = Depends(get_db)):

    # Create application record

    new_app = models.JobApplication(

        ocr_text=data.text,

        status="processing",

        suggest_resume_change=bool(data.suggest_resume_change)

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

        "portfolio_links": _profile_links(user),

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

        raise HTTPException(status_code=400, detail="No contact email provided for this application")    # Get user's resume
    user = db.query(models.User).first()
    resume_path = user.resume_path if user else None

    # NEW: Handle resume_id selection (user accepted the role-specific resume suggestion)

    resume_id = data.get("resume_id")

    if resume_id:

        try:

            resume_id = int(resume_id)

        except (TypeError, ValueError):

            raise HTTPException(status_code=400, detail="Invalid resume selection")

        selected_resume = db.query(models.RoleResume).get(resume_id)

        if not selected_resume:

            raise HTTPException(status_code=400, detail="The suggested resume no longer exists. Your Primary Resume will be used instead.")

        if not selected_resume.file_path or not os.path.exists(selected_resume.file_path):

            raise HTTPException(status_code=400, detail="The suggested resume file is missing from the server. Your Primary Resume will be used instead.")

        resume_path = selected_resume.file_path

        print(f"DEBUG: Sending draft {draft_id} with role resume {resume_id} ({selected_resume.resume_name})")

    else:

        print(f"DEBUG: Sending draft {draft_id} with Primary Resume")

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
    """Aggregate dashboard counters as JSON.

    Definitions mirror the Jinja dashboard and shell context processors exactly
    (manual applications only; 8 weekly buckets; drafts_total = nav_draft_count)
    so both frontends show identical numbers. The original three keys are
    unchanged; the rest are additive.
    """
    now = datetime.datetime.utcnow()
    week_ago = now - datetime.timedelta(days=7)

    apps = db.query(models.JobApplication).filter(
        models.JobApplication.is_manual == True
    ).order_by(models.JobApplication.created_at.asc()).all()

    # 8 weekly buckets, oldest first — same math as the dashboard() sparkline.
    weekly_counts = []
    for offset in range(7, -1, -1):
        start = now - datetime.timedelta(weeks=offset + 1)
        end = now - datetime.timedelta(weeks=offset)
        weekly_counts.append(sum(
            1 for a in apps if a.created_at is not None and start <= a.created_at < end
        ))

    by_status = {}
    for a in apps:
        by_status[a.status] = by_status.get(a.status, 0) + 1

    return {
        "total_applications": len(apps),
        "submitted": by_status.get("submitted", 0),
        "positive_responses": by_status.get("positive_response", 0),
        "awaiting_response": by_status.get("awaiting_response", 0),
        "shortlisted": by_status.get("shortlisted", 0),
        "weekly_applications": sum(
            1 for a in apps if a.created_at is not None and a.created_at >= week_ago
        ),
        "weekly_updated": sum(
            1 for a in apps if a.updated_at is not None and a.updated_at >= week_ago
        ),
        "weekly_counts": weekly_counts,
        # Parity with the shell context processor (nav_draft_count).
        "drafts_total": db.query(models.Draft).count(),
        # Job-related inbound emails; the backend has no per-conversation
        # "response sent" state, so this is every recorded conversation.
        "inbox_conversations": db.query(models.EmailEvent).count(),
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



@app.get("/api/campaigns/")
def list_campaigns(db: Session = Depends(get_db)):
    """Campaign list for the React outreach page.

    The legacy /outreach page rendered these rows inline (plus today's sent
    count) and no JSON endpoint existed; GET /campaigns/{id} only returns
    id/status/sent/total, which the React page also polls for progress.
    """
    campaigns = (
        db.query(models.Campaign)
        .order_by(models.Campaign.created_at.desc())
        .all()
    )
    today = datetime.datetime.utcnow().date()
    sent_today = db.query(models.SentEmail).filter(
        models.SentEmail.sent_at >= datetime.datetime.combine(today, datetime.time.min),
        models.SentEmail.sent_at <= datetime.datetime.combine(today, datetime.time.max),
    ).count()
    return {
        "items": [
            {
                "id": c.id,
                "name": c.name,
                "sheet_url": c.sheet_url,
                "header_row": c.header_row,
                "status": c.status,
                "total": c.total_count or 0,
                "sent": c.sent_count or 0,
                "target_role": c.prompt_context_1 or "",
                "instructions": c.prompt_context_2 or "",
                "daily_limit": c.daily_limit,
                "created_at": c.created_at.strftime("%b %d, %Y") if c.created_at else "",
            }
            for c in campaigns
        ],
        "total": len(campaigns),
        "sent_today": sent_today,
    }

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


from fastapi import Form

@app.get("/resumes", response_class=HTMLResponse)
async def resumes_page(request: Request, db: Session = Depends(get_db)):
    if not is_setup_complete(db):
        return RedirectResponse(url="/setup", status_code=307)

    resumes = db.query(models.RoleResume).order_by(models.RoleResume.created_at.desc()).all()

    user = db.query(models.User).first()

    return templates.TemplateResponse("resumes.html", {"request": request, "resumes": resumes, "user": user, "active_page": "resumes"})

@app.get("/api/resumes/", response_model=List[schemas.RoleResumeResponse])
def list_role_resumes(db: Session = Depends(get_db)):
    return db.query(models.RoleResume).order_by(models.RoleResume.created_at.desc()).all()

@app.post("/api/resumes/")
def upload_role_resume(
    role: str = Form(...),
    summary: str = Form(""),
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    conflict = _resume_role_conflict(db, role)
    if conflict:
        raise HTTPException(status_code=400, detail=conflict)

    os.makedirs("uploads", exist_ok=True)

    # The resume name is the file name; if it collides with an existing
    # resume, append (1), (2), … so both files stay on disk.
    resume_name = os.path.basename((file.filename or "resume.pdf").replace("\\", "/"))
    stem, ext = os.path.splitext(resume_name)

    used = {os.path.basename(p) for p in _stored_resume_names(db) if p}
    candidate, n = resume_name, 1
    while candidate in used or os.path.exists(os.path.join("uploads", candidate)):
        candidate = f"{stem} ({n}){ext}"
        n += 1

    file_path = os.path.join("uploads", candidate)
    with open(file_path, "wb") as buffer:
        shutil.copyfileobj(file.file, buffer)

    new_resume = models.RoleResume(
        resume_name=candidate,
        role=role,
        summary=summary,
        file_path=os.path.abspath(file_path)
    )
    db.add(new_resume)
    db.commit()
    db.refresh(new_resume)
    return {"id": new_resume.id, "resume_name": new_resume.resume_name, "role": new_resume.role, "summary": new_resume.summary, "file_path": new_resume.file_path, "created_at": str(new_resume.created_at)}

@app.put("/api/resumes/{resume_id}")
def update_role_resume(resume_id: int, data: schemas.RoleResumeCreate, db: Session = Depends(get_db)):
    resume = db.query(models.RoleResume).get(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    conflict = _resume_role_conflict(db, data.role, exclude_id=resume_id)
    if conflict:
        raise HTTPException(status_code=400, detail=conflict)
    resume.role = data.role
    resume.summary = data.summary
    db.commit()
    db.refresh(resume)
    return {"id": resume.id, "resume_name": resume.resume_name, "role": resume.role, "summary": resume.summary}

def _stored_resume_names(db):
    return [r.file_path for r in db.query(models.RoleResume).all() if r.file_path]

def _resume_role_conflict(db, role, exclude_id=None):
    """Only one resume may target a given job role, including the primary resume."""
    role = (role or "").strip()
    if not role:
        return "A target role is required."
    for r in db.query(models.RoleResume).all():
        if exclude_id is not None and r.id == exclude_id:
            continue
        if r.role and r.role.strip().lower() == role.lower():
            return f"A resume for the role '{role}' already exists: {r.resume_name}."
    user = db.query(models.User).first()
    if user and user.resume_role and user.resume_role.strip().lower() == role.lower():
        return f"The primary resume already targets '{role}'. Give this resume a different role."
    return None

@app.delete("/api/resumes/{resume_id}")
def delete_role_resume(resume_id: int, db: Session = Depends(get_db)):
    resume = db.query(models.RoleResume).get(resume_id)
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    db.delete(resume)
    db.commit()
    return {"message": "Resume deleted"}

@app.get("/api/applications/{app_id}/suggestion")
def get_resume_suggestion(app_id: int, db: Session = Depends(get_db)):
    job_app = db.query(models.JobApplication).get(app_id)
    if not job_app or not job_app.suggested_resume_id:
        return {"suggested_resume_id": None, "suggested_resume_name": None}
    resume = db.query(models.RoleResume).get(job_app.suggested_resume_id)
    if not resume:
        return {"suggested_resume_id": None, "suggested_resume_name": None}
    return {
        "suggested_resume_id": resume.id,
        "suggested_resume_name": resume.resume_name,
        "suggested_resume_role": resume.role
    }

@app.get("/api/applications/{app_id}")
def get_application_detail(app_id: int, db: Session = Depends(get_db)):
    """Single-application status for the add-application processing poll.

    The legacy apply page polled /applications/{id}/draft/ (404 vs 200) which
    cannot distinguish still-processing from blocked, and carries no extracted
    data. This returns the real status plus whatever extraction actually found
    (company/role/contact, form-mapping confidence, resume suggestion).
    """
    job_app = db.query(models.JobApplication).get(app_id)
    if not job_app:
        raise HTTPException(status_code=404, detail="Application not found")
    suggested_name = None
    if job_app.suggested_resume_id:
        resume = db.query(models.RoleResume).get(job_app.suggested_resume_id)
        suggested_name = resume.resume_name if resume else None
    return {
        "id": job_app.id,
        "status": job_app.status,
        "company_name": job_app.company_name,
        "role": job_app.role,
        "contact_email": job_app.contact_email,
        "contact_phone": job_app.contact_phone,
        "cc_emails": job_app.cc_emails,
        "application_url": job_app.application_url,
        "confidence_score": job_app.confidence_score,
        "suggested_resume_id": job_app.suggested_resume_id if suggested_name else None,
        "suggested_resume_name": suggested_name,
        "created_at": job_app.created_at.isoformat() if job_app.created_at else None,
    }

@app.get("/api/sent-emails/")
def list_sent_emails(limit: int = 60, db: Session = Depends(get_db)):
    """Lightweight sent-history list (metadata only; bodies stay on demand).

    Mirrors the legacy /sent page exactly: every SentEmail outer-joined to its
    application, newest first, `limit` rows for the list (the page shows the
    latest 60), plus the same totals the legacy stat strip computes.
    """
    rows = (
        db.query(models.SentEmail, models.JobApplication)
        .outerjoin(models.JobApplication)
        .order_by(models.SentEmail.sent_at.desc())
        .all()
    )
    items = [
        {
            "id": email.id,
            "subject": email.subject or "",
            "recipient_email": email.recipient_email or "",
            "sent_at": str(email.sent_at or ""),
            "status": email.status or "sent",
            "company_name": app.company_name if app else None,
            "role": app.role if app else None,
        }
        for email, app in rows[: max(1, limit)]
    ]
    return {
        "items": items,
        "total": len(rows),
        "confirmed": sum(1 for email, _ in rows if (email.status or "sent") == "sent"),
    }

@app.get("/api/sent-emails/{email_id}")
def get_sent_email(email_id: int, db: Session = Depends(get_db)):
    """Full sent email, fetched on demand so the history page stays light."""
    email = db.query(models.SentEmail).get(email_id)
    if not email:
        raise HTTPException(status_code=404, detail="Email not found")
    return {
        "id": email.id,
        "subject": email.subject,
        "body": email.body or "",
        "recipient_email": getattr(email, "recipient_email", None) or getattr(email, "recipient", None),
        "cc_emails": getattr(email, "cc_emails", None),
        "sent_at": str(email.sent_at or "")
    }

@app.get("/api/drafts/")
def list_drafts(limit: int = 50, db: Session = Depends(get_db)):
    """Draft-studio list (metadata only; bodies load on demand via /api/drafts/{id}).

    Mirrors the legacy /drafts page: email drafts joined to their application,
    newest first (latest `limit` for the list panel) plus the applications
    currently being processed for the drafting-in-progress banner.
    """
    rows = (
        db.query(models.Draft, models.JobApplication)
        .join(models.JobApplication)
        .filter(models.Draft.draft_type == "email")
        .order_by(models.Draft.id.desc())
        .all()
    )
    processing_apps = (
        db.query(models.JobApplication)
        .filter(models.JobApplication.status == "processing")
        .all()
    )
    items = [
        {
            "id": draft.id,
            "application_id": draft.application_id,
            "company_name": app.company_name or "",
            "role": app.role or "",
            "recipient": app.contact_email or "",
            "source": app.source or "",
            "created_at": str(app.created_at or ""),
        }
        for draft, app in rows[: max(1, limit)]
    ]
    return {
        "items": items,
        "total": len(rows),
        "processing": [
            {"id": app.id, "company_name": app.company_name or ""}
            for app in processing_apps
        ],
    }

@app.get("/api/email-events/")
def list_email_events(limit: int = 100, db: Session = Depends(get_db)):
    """Reply-center conversation list (metadata only, newest first).

    Returns the same email events the legacy /replies page renders, joined to
    their application so the React inbox can compute counts and open
    conversations without a second request.
    """
    rows = (
        db.query(models.EmailEvent, models.JobApplication)
        .outerjoin(
            models.JobApplication,
            models.EmailEvent.application_id == models.JobApplication.id,
        )
        .order_by(models.EmailEvent.received_at.desc())
        .all()
    )
    items = [
        {
            "id": email.id,
            "application_id": app.id if app else None,
            "subject": email.subject or "",
            "sender": email.sender or "",
            "snippet": email.snippet or "",
            "received_at": str(email.received_at or ""),
            "classification": email.classification or "",
            "company_name": app.company_name if app else None,
            "role": app.role if app else None,
            "contact_email": (app.contact_email if app else None) or "",
            "app_status": app.status if app else None,
        }
        for email, app in rows[: max(1, limit)]
    ]
    return {"items": items, "total": len(rows)}

@app.get("/api/drafts/{draft_id}")
def get_draft_detail(draft_id: int, db: Session = Depends(get_db)):
    """Draft + application metadata, fetched on demand by the draft studio."""
    draft = db.query(models.Draft).get(draft_id)
    if not draft:
        raise HTTPException(status_code=404, detail="Draft not found")
    job_app = db.query(models.JobApplication).get(draft.application_id) if draft.application_id else None
    return {
        "id": draft.id,
        "application_id": draft.application_id,
        "subject": draft.subject or "Job Application",
        "content": draft.content or "",
        "company_name": (job_app.company_name if job_app else None),
        "role": (job_app.role if job_app else None),
        "recipient": (job_app.contact_email if job_app else "") or "",
        "cc": (getattr(job_app, "cc_emails", "") or "") if job_app else "",
        "has_suggestion": bool(job_app and job_app.suggested_resume_id),
        "updated_at": str(job_app.updated_at or "") if job_app else ""
    }

@app.get("/api/applications/{app_id}/source")
def get_application_source(app_id: int, db: Session = Depends(get_db)):
    """Full job description for an application, fetched on demand to keep pages light."""
    job_app = db.query(models.JobApplication).get(app_id)
    if not job_app:
        raise HTTPException(status_code=404, detail="Application not found")
    return {
        "company_name": job_app.company_name,
        "role": job_app.role,
        "ocr_text": job_app.ocr_text or ""
    }

@app.get("/api/applications/{app_id}/last-email")
def get_application_last_email(app_id: int, db: Session = Depends(get_db)):
    """Most recent email sent for an application, fetched on demand."""
    job_app = db.query(models.JobApplication).get(app_id)
    if not job_app or not job_app.sent_emails:
        raise HTTPException(status_code=404, detail="No email has been sent for this application")
    last = job_app.sent_emails[-1]
    return {
        "subject": last.subject,
        "body": last.body,
        "recipient": getattr(last, "recipient_email", None) or getattr(last, "recipient", None),
        "sent_at": str(getattr(last, "sent_at", "") or "")
    }


# ---------------------------------------------------------------------------
# LinkedIn Job Finder (native feature surface)
# ---------------------------------------------------------------------------
from linkedin_integration.routes import create_linkedin_router
from linkedin_integration import runner as linkedin_runner

app.include_router(
    create_linkedin_router(
        templates=templates,
        get_db=get_db,
        process_application=process_application,
        is_setup_complete=is_setup_complete,
    )
)


@app.on_event("startup")
async def linkedin_startup_event():
    """Re-attach to a scraper run that outlived a restart, or close it out."""
    try:
        resume_ids = await asyncio.to_thread(linkedin_runner.reconcile_runs_on_startup)
    except Exception as exc:  # never block app startup on reconciliation
        print(f"LinkedIn run reconciliation skipped: {exc}")
        return
    for run_id in resume_ids:
        asyncio.create_task(asyncio.to_thread(linkedin_runner.watch_run, run_id))


# ---------------------------------------------------------------------------
# React frontend (production build served by FastAPI on the same origin)
# ---------------------------------------------------------------------------
# Registered last so every existing page/API route keeps priority.
# The SPA currently lives at /app while the Jinja pages remain active;
# as React pages replace them (progressive retirement), the SPA entry moves
# to their paths. No existing route is modified here.
from pathlib import Path as _Path

from fastapi.responses import FileResponse as _FileResponse
from fastapi.responses import JSONResponse as _JSONResponse

FRONTEND_DIST = _Path(__file__).resolve().parent.parent / "frontend" / "dist"
_INDEX_FILE = FRONTEND_DIST / "index.html"

if (FRONTEND_DIST / "assets").is_dir():
    app.mount(
        "/assets",
        StaticFiles(directory=str(FRONTEND_DIST / "assets")),
        name="frontend_assets",
    )


def _spa_index():
    if _INDEX_FILE.is_file():
        return _FileResponse(_INDEX_FILE)
    return _JSONResponse(
        {
            "detail": "Frontend build not found. "
            "Run: cd frontend && pnpm install && pnpm build"
        },
        status_code=503,
    )


@app.get("/app", include_in_schema=False)
def spa_entry():
    return _spa_index()


@app.get("/app/{full_path:path}", include_in_schema=False)
def spa_fallback(full_path: str):
    return _spa_index()
