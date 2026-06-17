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
    skills = Column(Text)
    experience = Column(Text)
    projects = Column(Text)
    portfolio_links = Column(Text)
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
    is_manual = Column(Boolean, default=True) # Distinguish between sent apps and inbox-only connections
    created_at = Column(DateTime, default=datetime.datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.datetime.utcnow, onupdate=datetime.datetime.utcnow)
    
    forms = relationship("ApplicationForm", back_populates="application")
    drafts = relationship("Draft", back_populates="application")
    sent_emails = relationship("SentEmail", back_populates="application")
    emails = relationship("EmailEvent", back_populates="application")

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
