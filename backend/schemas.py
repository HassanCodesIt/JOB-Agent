from pydantic import BaseModel
from typing import Optional, List
from datetime import datetime

class UserBase(BaseModel):
    full_name: str
    email: str
    phone: Optional[str] = None
    resume_path: Optional[str] = None
    skills: Optional[str] = None
    experience: Optional[str] = None
    projects: Optional[str] = None
    portfolio_links: Optional[str] = None
    standard_answers: Optional[str] = None

class UserCreate(UserBase):
    pass

class User(UserBase):
    id: int
    # Extended profile/settings fields consumed by the React Settings page.
    # Optional everywhere; mirrors what the legacy settings.html already reads
    # off the user row (including provider keys, which it embeds in the form).
    github_link: Optional[str] = None
    linkedin_link: Optional[str] = None
    portfolio_link: Optional[str] = None
    resume_role: Optional[str] = None
    resume_summary: Optional[str] = None
    profile_summary: Optional[str] = None
    system_prompt: Optional[str] = None
    groq_api_key: Optional[str] = None
    openrouter_api_key: Optional[str] = None
    hf_token: Optional[str] = None

    class Config:
        from_attributes = True

class JobApplicationBase(BaseModel):
    company_name: Optional[str] = None
    role: Optional[str] = None
    application_url: Optional[str] = None
    platform_type: Optional[str] = None
    status: str = "draft"
    confidence_score: Optional[float] = None
    contact_email: Optional[str] = None
    contact_phone: Optional[str] = None
    cc_emails: Optional[str] = None
    ocr_text: Optional[str] = None
    poster_path: Optional[str] = None

class JobApplicationCreate(JobApplicationBase):
    pass

class JobApplication(JobApplicationBase):
    id: int
    created_at: datetime
    updated_at: datetime

    class Config:
        from_attributes = True

class RoleResumeBase(BaseModel):
    resume_name: str
    role: str
    summary: Optional[str] = None

class RoleResumeCreate(RoleResumeBase):
    pass

class RoleResumeResponse(RoleResumeBase):
    id: int
    file_path: Optional[str] = None
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True

class ApplicationFormBase(BaseModel):
    application_id: int
    form_structure: str
    screenshot_path: Optional[str] = None

class ApplicationForm(ApplicationFormBase):
    id: int

    class Config:
        from_attributes = True

class DraftBase(BaseModel):
    application_id: int
    content: str
    draft_type: str
    is_ready: bool = False
    is_starred: bool = False

class Draft(DraftBase):
    id: int

    class Config:
        from_attributes = True

class SentEmailBase(BaseModel):
    application_id: Optional[int] = None
    recipient_email: str
    cc_emails: Optional[str] = None
    subject: str
    body: str

class SentEmail(SentEmailBase):
    id: int
    sent_at: datetime
    status: str

    class Config:
        from_attributes = True

class JobTextRequest(BaseModel):
    text: str
    instructions: Optional[str] = None  # Accepted for backward compatibility (consumed by other submission flows)
    suggest_resume_change: Optional[bool] = False  # Opt-in: match a role-specific resume for this JD

class DirectEmailRequest(BaseModel):
    app_id: Optional[int] = None
    recipient: Optional[str] = None
    subject: Optional[str] = None
    content: Optional[str] = None
    cc: Optional[str] = None

class ReplyGenerateRequest(BaseModel):
    app_id: int
    instructions: Optional[str] = None

# --- Career Ops Schemas ---
class CareerOpsJobItem(BaseModel):
    jd_text: str
    to_email: str
    company_name: Optional[str] = None

class CareerOpsBatchRequest(BaseModel):
    jobs: List[CareerOpsJobItem]

class CareerOpsJobResponse(BaseModel):
    id: int
    batch_id: str
    company_name: Optional[str] = None
    role: Optional[str] = None
    to_email: str
    status: str
    score: Optional[float] = None
    pdf_path: Optional[str] = None
    sent_at: Optional[datetime] = None
    error_message: Optional[str] = None
    created_at: datetime

    class Config:
        from_attributes = True

class CareerOpsBatchResponse(BaseModel):
    batch_id: str
    total_jobs: int
    message: str
