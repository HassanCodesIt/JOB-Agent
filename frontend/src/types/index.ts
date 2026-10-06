export type PageName = "Dashboard" | "Add Application" | "Draft Studio" | "Reply Center" | "Outreach" | "LinkedIn Job Finder" | "Resume Library" | "Sent History" | "Settings"

export type Tone = "neutral" | "violet" | "success" | "warning" | "danger"
export type Theme = "dark" | "light"
export type FilterStatus = "Not filtered" | "Accepted" | "Rejected" | "Needs Review" | "Error"
export type SearchStatus = "Completed" | "Failed" | "Stopped" | "Interrupted" | "Running"
export type SearchRunState = "ready" | "running" | "completed" | "failed" | "stopped" | "unavailable"
export type SearchMode = "Standard Job Search" | "Latest Jobs" | "Jobs Posted in Last 24 Hours" | "Top Matches" | "Home Feed" | "Continue Search"

export interface SourceLinks {
  linkedin?: string
  job?: string
  apply?: string
  image?: string
}

export interface LinkedInJob {
  id: string

  runId: string

  title: string

  company: string

  location: string

  experience: string

  employmentType: string

  salary?: string

  email?: string

  methods: string[]

  description: string

  fullText?: string

  skills: string[]

  responsibilities: string[]

  qualifications: string[]

  filterStatus: FilterStatus

  links: SourceLinks
}

export interface Application {
  id: string
  title: string
  company: string
  source: string
  location: string
  applicationUrl?: string
  description: string
  email?: string
  resumeId: string
  method: string
  status: "Draft" | "Processing" | "Awaiting response" | "Shortlisted" | "Positive response" | "Submitted" | "Blocked" | "OCR uncertain" | "Rejected"
  createdAt: string
  sourceLinks?: SourceLinks
}

export interface Draft {
  id: string
  applicationId: string
  to: string
  cc: string
  subject: string
  body: string
  type: "Email" | "Cover letter" | "Follow-up"
  tone: "Professional" | "Warm" | "Concise"
  resumeId: string
  state: "Needs review" | "Saved" | "Sent"
}

export interface Reply {
  id: string
  sender: string
  email: string
  company: string
  role: string
  subject: string
  preview: string
  body: string
  time: string
  status: "Unread" | "Follow-up" | "Interview" | "Archived"
  applicationId: string
  complete: boolean
}

export interface OutreachContact {
  id: string
  name: string
  company: string
  role: string
  contactStatus: "Needs follow-up" | "Draft" | "Sent" | "Completed"
  channel: "Email" | "LinkedIn"
  lastContact: string
  nextFollowUp: string
  email: string
}

export interface Campaign {
  id: string
  name: string
  sheetUrl: string
  createdAt: string
  status: "Active" | "Paused" | "Completed" | "Error"
  sent: number
  total: number
  targetRole: string
  dailyLimit?: number
  items: Array<{
    id: string
    recipient: string
    company: string
    status: "Sent" | "Error" | "Pending"
    sentAt: string
    error?: string
  }>
}

export interface Resume {
  id: string
  filename: string
  focus: string
  summary?: string
  updatedAt: string
  isDefault: boolean
  state: "Uploaded" | "Uploading"
}

export interface HistoryItem {
  id: string
  role: string
  company: string
  type: "Email" | "Cover letter" | "Outreach" | "Manual application"
  channel: string
  date: string
  status: "Sent" | "Applied" | "Completed"
  message: string
  recipient?: string
  subject?: string
}

export interface SearchRun {
  id: string
  mode: SearchMode
  role: string
  count: number
  status: SearchStatus
  time: string
}

export interface ToastMessage {
  id: number
  message: string
  tone?: Tone
}

export type ApplicationStatus = "draft" | "processing" | "awaiting_response" | "shortlisted" | "positive_response" | "submitted" | "blocked" | "ocr_uncertain" | "rejected"

export interface ApplicationSummary {
  id: number
  company_name: string | null
  role: string | null
  status: ApplicationStatus | string
  updated_at: string
  updated_label: string
  has_source: boolean
  has_email: boolean
  tone: string
}

export interface ApplicationsPage {
  total: number
  offset: number
  limit: number
  count: number
  has_more: boolean
  items: ApplicationSummary[]
}

export interface DashboardStats {
  total_applications: number
  submitted: number
  positive_responses: number
  awaiting_response: number
  shortlisted: number
  weekly_applications: number
  weekly_updated: number
  weekly_counts: number[]
  drafts_total: number
  inbox_conversations: number
}

export interface UserProfile {
  id: number
  full_name: string
  email: string
  phone?: string | null
  resume_path?: string | null
  skills?: string | null
  experience?: string | null
  projects?: string | null
  standard_answers?: string | null
  github_link?: string | null
  linkedin_link?: string | null
  portfolio_link?: string | null
  resume_role?: string | null
  resume_summary?: string | null
  profile_summary?: string | null
  system_prompt?: string | null
  groq_api_key?: string | null
  openrouter_api_key?: string | null
  hf_token?: string | null
}

export interface AccountInfo {
  email: string
  configured: boolean
}

export interface EmailAccounts {
  accounts: Record<string, AccountInfo>
  active: number
  free_slots: number[]
}

export interface ApplicationSource {
  company_name: string | null
  role: string | null
  ocr_text: string
}

export interface LastEmail {
  subject: string | null
  body: string | null
  recipient: string | null
  sent_at: string
}

export interface SentEmailItem {
  id: number
  subject: string
  recipient_email: string
  sent_at: string
  status: string
  company_name: string | null
  role: string | null
}

export interface SentEmailList {
  items: SentEmailItem[]
  total: number
  confirmed: number
}

export interface SentEmailDetail {
  id: number
  subject: string | null
  body: string
  recipient_email: string | null
  cc_emails: string | null
  sent_at: string
}

export interface RoleResume {
  id: number
  resume_name: string
  role: string
  summary: string | null
  file_path?: string | null
  created_at?: string | null
}

export interface LinkedInFilterSettings {
  prompt: string
  max_experience_years: number
  accept_unspecified_experience: boolean
  batch_size: number
  max_jd_chars: number
  model: string
  model_label: string
  prompt_version: number
}

export interface LinkedInSearchSettings {
  default_role: string | null

  sort_by: string

  date_posted: string
}

export interface LinkedInModeInfo {
  key: string

  label: string

  description: string

  searchable: boolean

  fixed_date: string | null

  fixed_sort: string | null
}

export interface LinkedInFacetOption {
  value: string

  label: string
}

export interface LinkedInRun {
  id: number

  mode: string

  mode_label: string

  role: string

  sort_by: string | null

  date_posted: string | null

  facets: string[]

  status: string

  process_state: string | null

  process_id: number | null

  started_at: string | null

  completed_at: string | null

  exit_code: number | null

  error_message: string | null

  collected_count: number

  filtered_count: number

  scraper_run_number: number | null
}

export interface LinkedInCounts {
  collected: number

  with_email: number

  no_email: number

  accepted: number

  accepted_email: number

  accepted_no_email: number

  pending: number

  runs: number
}

export interface LinkedInMeta {
  modes: LinkedInModeInfo[]

  sort_options: LinkedInFacetOption[]

  date_options: LinkedInFacetOption[]

  preset_roles: string[]

  search: { default_role: string | null; sort_by: string; date_posted: string }

  filter_settings: LinkedInFilterSettings

  active_run: LinkedInRun | null

  runs: LinkedInRun[]

  counts: LinkedInCounts

  model_label: string
}

export interface LinkedInJobLinks {
  post: string | null

  job: string | null

  apply: string | null

  image: string | null

  extra_apply: string[]
}

export interface LinkedInJobRecord {
  id: number

  run_id: number | null

  role: string

  company: string

  location: string

  experience: string

  employment_type: string

  salary: string | null

  email: string | null

  preview: string

  full_text: string

  skills: string[]

  responsibilities: string[]

  qualifications: string[]

  application_method: string | null

  methods: string[]

  instructions: string[]

  has_image: boolean

  image_based_job_post: boolean

  links: LinkedInJobLinks

  batch: string

  subs: string[]

  filter_status: string

  filter_error: string | null

  filtered_at: string | null

  filter_model: string | null

  filter_prompt_version: number | null

  application_id: number | null

  show_draft: boolean

  created_at: string | null
}

export interface LinkedInJobsPage {
  total: number

  offset: number

  limit: number

  count: number

  has_more: boolean

  items: LinkedInJobRecord[]
}

export interface LinkedInBrowserStatus {
  reachable: boolean

  cdp_url: string

  message: string | null
}

export interface LinkedInRunResponse {
  run: LinkedInRun
}

export interface LinkedInFilterSummary {
  scanned: number

  filtered: number

  skipped: number

  accepted: number

  rejected: number

  errors: number

  prompt_version: number

  model: string
}

export interface LinkedInFilterResponse {
  summary: LinkedInFilterSummary

  counts: LinkedInCounts
}

export interface LinkedInDraftApplyResult {
  application_id: number

  status: string

  reused: boolean

  message: string

  has_recipient?: boolean
}

export interface UserSettingsPayload {
  full_name?: string
  email?: string
  phone?: string
  github_link?: string
  linkedin_link?: string
  portfolio_link?: string
  skills?: string
  experience?: string
  projects?: string
  standard_answers?: string
  system_prompt?: string
  groq_api_key?: string
  openrouter_api_key?: string
  hf_token?: string
  resume_role?: string
  resume_summary?: string
  profile_summary?: string
}

export interface DraftListItem {
  id: number
  application_id: number
  company_name: string
  role: string
  recipient: string
  source: string
  created_at: string
}

export interface DraftListResponse {
  items: DraftListItem[]
  total: number
  processing: { id: number; company_name: string }[]
}

export interface DraftDetail {
  id: number
  application_id: number
  subject: string
  content: string
  company_name: string | null
  role: string | null
  recipient: string
  cc: string
  has_suggestion: boolean
  updated_at: string
}

export interface ResumeSuggestion {
  suggested_resume_id: number | null
  suggested_resume_name: string | null
  suggested_resume_role?: string | null
}

export interface ReplyGeneration {
  subject?: string
  body?: string
  error?: string
  detail?: string
}

export interface EmailEventItem {
  id: number
  application_id: number | null
  subject: string
  sender: string
  snippet: string
  received_at: string
  classification: string
  company_name: string | null
  role: string | null
  contact_email: string
  app_status: string | null
}

export interface EmailEventListResponse {
  items: EmailEventItem[]

  total: number
}

export interface CreatedApplication {
  id: number

  status: string
}

export interface ApplicationDetail {
  id: number

  status: ApplicationStatus | string

  company_name: string | null

  role: string | null

  contact_email: string | null

  contact_phone: string | null

  cc_emails: string | null

  application_url: string | null

  confidence_score: number | null

  suggested_resume_id: number | null

  suggested_resume_name: string | null

  created_at: string | null
}

export interface CampaignListItem {
  id: number

  name: string

  sheet_url: string | null

  header_row: number

  status: string

  total: number

  sent: number

  target_role: string

  instructions: string

  daily_limit: number | null

  created_at: string
}

export interface CampaignListResponse {
  items: CampaignListItem[]

  total: number

  sent_today: number
}

export interface CampaignItemRaw {
  id: number

  recipient_email: string

  recipient_name: string | null

  company: string

  status: string

  error_msg: string | null

  sent_at: string | null
}
