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
