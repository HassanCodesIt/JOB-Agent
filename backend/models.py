from sqlalchemy import Column, Integer, String, Text, DateTime, ForeignKey, Float, Enum, Boolean
from sqlalchemy.orm import relationship
from database import Base
import datetime
import enum

class ApplicationStatus(enum.Enum):
    DRAFT = "draft"
    SUBMITTED = "submitted"
    BLOCKED = "blocked"
    RESPONDED = "responded"
    REJECTED = "rejected"
    SHORTLISTED = "shortlisted"
    POSITIVE = "positive_response"
    AWAITING_RESPONSE = "awaiting_response"
    OCR_UNCERTAIN = "ocr_uncertain"

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    full_name = Column(String)
    email = Column(String, unique=True, index=True)
    phone = Column(String)
    resume_path = Column(String)
    resume_role = Column(String)
    resume_summary = Column(Text)
    profile_summary = Column(Text)
    skills = Column(Text)
    experience = Column(Text)
    projects = Column(Text)
    portfolio_links = Column(Text)
    github_link = Column(String)
    linkedin_link = Column(String)
    portfolio_link = Column(String)
    standard_answers = Column(Text)
    system_prompt = Column(Text)
    groq_api_key = Column(String)
    groq_backup_api_key = Column(String)
    hf_token = Column(String)
    openrouter_api_key = Column(String)

class JobApplication(Base):
    __tablename__ = "job_applications"
    id = Column(Integer, primary_key=True, index=True)
    company_name = Column(String)
    role = Column(String)
    application_url = Column(String)
    platform_type = Column(String)
    status = Column(String, default="draft")
    confidence_score = Column(Float)
    contact_email = Column(String)
    contact_phone = Column(String)
    cc_emails = Column(String)  # Comma-separated CC emails extracted from job posting
    ocr_text = Column(Text)
    poster_path = Column(String)
    suggested_resume_id = Column(Integer, ForeignKey("role_resumes.id"))  # LLM-matched role-specific resume
    suggest_resume_change = Column(Boolean, default=False)  # Opt-in: LLM picks a role-specific resume for this app
    is_manual = Column(Boolean, default=True) # Distinguish between sent apps and inbox-only connections
    source = Column(String)  # e.g. "linkedin_automation"; NULL for the normal intake paths
    linkedin_job_id = Column(Integer, ForeignKey("linkedin_jobs.id"))  # originating LinkedIn Job Finder record
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    forms = relationship("ApplicationForm", back_populates="application")
    drafts = relationship("Draft", back_populates="application")
    sent_emails = relationship("SentEmail", back_populates="application")
    emails = relationship("EmailEvent", back_populates="application")

class RoleResume(Base):
    __tablename__ = "role_resumes"
    id = Column(Integer, primary_key=True, index=True)
    resume_name = Column(String)
    role = Column(String)
    summary = Column(Text)
    file_path = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class ApplicationForm(Base):
    __tablename__ = "application_forms"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("job_applications.id"))
    form_structure = Column(Text)
    screenshot_path = Column(String)
    
    application = relationship("JobApplication", back_populates="forms")

class Draft(Base):
    __tablename__ = "drafts"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("job_applications.id"))
    subject = Column(String)
    content = Column(Text)
    draft_type = Column(String)
    is_ready = Column(Boolean, default=False)
    is_starred = Column(Boolean, default=False)
    is_favorite = Column(Boolean, default=False)
    
    application = relationship("JobApplication", back_populates="drafts")

class EmailEvent(Base):
    __tablename__ = "email_events"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("job_applications.id"))
    subject = Column(String)
    sender = Column(String)
    snippet = Column(Text)
    received_at = Column(DateTime, default=datetime.datetime.utcnow)
    classification = Column(String)

    application = relationship("JobApplication", back_populates="emails")

class Response(Base):
    __tablename__ = "responses"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("job_applications.id"))
    content = Column(Text)
    received_at = Column(DateTime, default=datetime.datetime.utcnow)

class SentEmail(Base):
    __tablename__ = "sent_emails"
    id = Column(Integer, primary_key=True, index=True)
    application_id = Column(Integer, ForeignKey("job_applications.id"))
    recipient_email = Column(String)
    cc_emails = Column(String)  # Comma-separated CC emails
    subject = Column(String)
    body = Column(Text)
    sent_at = Column(DateTime, default=datetime.datetime.utcnow)
    status = Column(String, default="sent")

    application = relationship("JobApplication", back_populates="sent_emails")

class Campaign(Base):
    __tablename__ = "campaigns"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String)
    sheet_url = Column(String)
    header_row = Column(Integer, default=1)
    status = Column(String, default="active")  # active, paused, completed, error
    total_count = Column(Integer, default=0)
    sent_count = Column(Integer, default=0)
    prompt_context_1 = Column(Text) # User provided context
    prompt_context_2 = Column(Text) # User provided context
    daily_limit = Column(Integer, default=None)  # Max emails per day (None = unlimited)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    
    items = relationship("CampaignItem", back_populates="campaign")

class CampaignItem(Base):
    __tablename__ = "campaign_items"
    id = Column(Integer, primary_key=True, index=True)
    campaign_id = Column(Integer, ForeignKey("campaigns.id"))
    row_data = Column(Text) # JSON string of the row
    recipient_email = Column(String)
    recipient_name = Column(String)
    company = Column(String)
    status = Column(String, default="pending") # pending, sent, error
    error_msg = Column(Text)
    sent_at = Column(DateTime)
    
    campaign = relationship("Campaign", back_populates="items")

class CareerOpsJob(Base):
    __tablename__ = "career_ops_jobs"
    
    id = Column(Integer, primary_key=True, index=True)
    batch_id = Column(String, index=True)
    company_name = Column(String)
    role = Column(String)
    jd_text = Column(Text)
    to_email = Column(String)
    status = Column(String, default="pending")  # pending, processing, done, failed
    score = Column(Float)
    pdf_path = Column(String)
    email_subject = Column(String)
    email_body = Column(Text)
    keywords = Column(Text)  # JSON array of ATS keywords
    sent_at = Column(DateTime)
    error_message = Column(String)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class LinkedInRun(Base):
    """One LinkedIn Job Finder automation run launched from the dashboard."""

    __tablename__ = "linkedin_runs"

    id = Column(Integer, primary_key=True, index=True)
    scraper_run_number = Column(Integer, index=True)  # "Scraping Run N.json" number, once imported
    mode = Column(String)            # friendly mode key, e.g. "standard"
    entry_point = Column(String)     # scraper entry point file that was executed
    role = Column(String)
    sort_by = Column(String)
    date_posted = Column(String)
    configuration_json = Column(Text)  # JSON snapshot of the request that started the run
    summary_json = Column(Text)        # JSON copy of the scraper run summary block
    status = Column(String, default="running")  # running, completed, failed, interrupted
    process_id = Column(Integer)
    process_state = Column(String)   # polling state: started, exited, imported
    started_at = Column(DateTime, default=datetime.datetime.utcnow)
    completed_at = Column(DateTime)
    exit_code = Column(Integer)
    log_path = Column(String)
    error_message = Column(Text)
    collected_count = Column(Integer, default=0)
    filtered_count = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)


class LinkedInJob(Base):
    """A single job imported from a scraper JSON run file."""

    __tablename__ = "linkedin_jobs"

    id = Column(Integer, primary_key=True, index=True)
    linkedin_run_id = Column(Integer, ForeignKey("linkedin_runs.id"), index=True)
    linkedin_post_url = Column(String, index=True)  # LinkedIn post permalink (source identity)
    job_url = Column(String)                        # LinkedIn job listing URL
    apply_url = Column(String)                      # external application link
    image_url = Column(String)
    additional_apply_urls = Column(Text)            # JSON array of extra external apply links
    linkedin_post_urn = Column(String)
    company = Column(String)
    role = Column(String)
    author = Column(String)
    location = Column(String)
    experience = Column(String)
    employment_type = Column(String)
    salary = Column(String)
    email = Column(String)
    additional_emails = Column(Text)                # JSON array
    application_method = Column(String)
    application_methods = Column(Text)              # JSON array
    application_instructions = Column(Text)         # JSON array
    job_description = Column(Text)
    full_post = Column(Text)
    skills = Column(Text)                          # JSON array
    responsibilities = Column(Text)                # JSON array
    qualifications = Column(Text)                  # JSON array
    match_reasons = Column(Text)                   # JSON array
    has_image = Column(Boolean, default=False)
    image_based_job_post = Column(Boolean, default=False)
    filter_status = Column(String, default="pending", index=True)  # pending, accepted, rejected, error
    filter_batch = Column(String)                  # email | no_email
    filter_model = Column(String)
    filter_prompt_version = Column(Integer)
    filter_error = Column(Text)
    filtered_at = Column(DateTime)
    job_application_id = Column(Integer, ForeignKey("job_applications.id"))
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class LinkedInFilterSettings(Base):
    """User-editable relevance criteria for the manual LinkedIn filter step."""

    __tablename__ = "linkedin_filter_settings"

    id = Column(Integer, primary_key=True, index=True)
    prompt = Column(Text)                          # final editable instruction sent to the model
    max_experience_years = Column(Float, default=1.0)
    accept_unspecified_experience = Column(Boolean, default=True)
    batch_size = Column(Integer, default=8)
    max_jd_chars = Column(Integer, default=4000)
    model = Column(String, default="openai/gpt-oss-120b")
    prompt_version = Column(Integer, default=1)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)


class LinkedInSearchSettings(Base):
    """Defaults preselected on the LinkedIn Job Finder page."""

    __tablename__ = "linkedin_search_settings"

    id = Column(Integer, primary_key=True, index=True)
    default_role = Column(String)
    sort_by = Column(String, default="relevance")
    date_posted = Column(String, default="any")
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)

