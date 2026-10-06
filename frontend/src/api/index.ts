import { request } from "./client"
import type {
  ApplicationDetail,
  ApplicationSource,
  ApplicationStatus,
  ApplicationsPage,
  CampaignItemRaw,
  CampaignListResponse,
  CreatedApplication,
  DashboardStats,
  DraftDetail,
  DraftListResponse,
  EmailAccounts,
  EmailEventListResponse,
  LastEmail,
  LinkedInBrowserStatus,
  LinkedInDraftApplyResult,
  LinkedInFilterResponse,
  LinkedInFilterSettings,
  LinkedInJobsPage,
  LinkedInMeta,
  LinkedInRunResponse,
  LinkedInSearchSettings,
  ReplyGeneration,
  ResumeSuggestion,
  RoleResume,
  SentEmailDetail,
  SentEmailList,
  UserProfile,
  UserSettingsPayload,
} from "@/types"
import type { Tone } from "@/types"

export { ApiError } from "./client"

export function fetchUser(): Promise<UserProfile> {
  return request<UserProfile>("/user/")
}

export function fetchAccounts(): Promise<EmailAccounts> {
  return request<EmailAccounts>("/api/accounts")
}

export function fetchStats(): Promise<DashboardStats> {
  return request<DashboardStats>("/stats/")
}

export function fetchSentEmails(limit = 60): Promise<SentEmailList> {
  return request<SentEmailList>(`/api/sent-emails/?limit=${limit}`)
}

export function fetchSentEmail(id: number): Promise<SentEmailDetail> {
  return request<SentEmailDetail>(`/api/sent-emails/${id}`)
}

export function fetchRoleResumes(): Promise<RoleResume[]> {
  return request<RoleResume[]>("/api/resumes/")
}

export function uploadRoleResume(
  role: string,
  summary: string,
  file: File,
): Promise<RoleResume> {
  const body = new FormData()
  body.append("role", role)
  body.append("summary", summary)
  body.append("file", file)
  return request<RoleResume>("/api/resumes/", { method: "POST", body })
}

export function updateRoleResume(
  resumeId: number,
  resumeName: string,
  role: string,
  summary: string,
): Promise<RoleResume> {
  return request<RoleResume>(`/api/resumes/${resumeId}`, {
    method: "PUT",
    body: JSON.stringify({ resume_name: resumeName, role, summary }),
  })
}

export function deleteRoleResume(
  resumeId: number,
): Promise<{ message: string }> {
  return request<{ message: string }>(`/api/resumes/${resumeId}`, {
    method: "DELETE",
  })
}

export function updateUserSettings(
  payload: UserSettingsPayload,
): Promise<{ message: string }> {
  return request<{ message: string }>("/user/update/", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function uploadPrimaryResume(
  file: File,
): Promise<{
  message: string
  path: string
}> {
  const body = new FormData()
  body.append("file", file)
  return request<{ message: string; path: string }>("/user/resume/", {
    method: "POST",
    body,
  })
}

export function fetchLinkedInFilterSettings(): Promise<{
  settings: LinkedInFilterSettings
}> {
  return request<{ settings: LinkedInFilterSettings }>(
    "/api/linkedin/filter-settings",
  )
}

export function saveLinkedInFilterSettings(payload: {
  prompt?: string
  max_experience_years?: number
  accept_unspecified_experience?: boolean
  batch_size?: number
  max_jd_chars?: number
  regenerate_prompt?: boolean
}): Promise<{ settings: LinkedInFilterSettings }> {
  return request<{ settings: LinkedInFilterSettings }>(
    "/api/linkedin/filter-settings",
    { method: "POST", body: JSON.stringify(payload) },
  )
}

export function fetchLinkedInSearchSettings(): Promise<{
  settings: LinkedInSearchSettings
}> {
  return request<{ settings: LinkedInSearchSettings }>(
    "/api/linkedin/search-settings",
  )
}

export function saveLinkedInSearchSettings(payload: {
  default_role?: string
  sort_by?: string
  date_posted?: string
}): Promise<{ settings: LinkedInSearchSettings }> {
  return request<{ settings: LinkedInSearchSettings }>(
    "/api/linkedin/search-settings",
    { method: "POST", body: JSON.stringify(payload) },
  )
}

export function fetchLinkedInMeta(): Promise<LinkedInMeta> {
  return request<LinkedInMeta>("/api/linkedin/meta")
}

export function fetchLinkedInBrowserStatus(): Promise<LinkedInBrowserStatus> {
  return request<LinkedInBrowserStatus>("/api/linkedin/browser-status")
}

export function fetchLinkedInJobs(
  options: {
    scope?: string
    batch?: string
    sub?: string
    run_id?: number
    limit?: number
    offset?: number
  } = {},
): Promise<LinkedInJobsPage> {
  const params = new URLSearchParams({ format: "json" })
  if (options.scope) params.set("scope", options.scope)
  if (options.batch) params.set("batch", options.batch)
  if (options.sub) params.set("sub", options.sub)
  if (options.run_id != null) params.set("run_id", String(options.run_id))
  if (options.limit != null) params.set("limit", String(options.limit))
  if (options.offset != null) params.set("offset", String(options.offset))
  return request<LinkedInJobsPage>(`/api/linkedin/jobs?${params.toString()}`)
}

export function startLinkedInRun(payload: {
  mode: string
  role: string
  sort_by?: string | null
  date_posted?: string | null
}): Promise<LinkedInRunResponse> {
  return request<LinkedInRunResponse>("/api/linkedin/runs/start", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function fetchLinkedInRun(runId: number): Promise<LinkedInRunResponse> {
  return request<LinkedInRunResponse>(`/api/linkedin/runs/${runId}`)
}

export function stopLinkedInRun(runId: number): Promise<LinkedInRunResponse> {
  return request<LinkedInRunResponse>(`/api/linkedin/runs/${runId}/stop`, {
    method: "POST",
  })
}

export function runLinkedInFilter(
  payload: { force?: boolean; run_id?: number } = {},
): Promise<LinkedInFilterResponse> {
  return request<LinkedInFilterResponse>("/api/linkedin/filter", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function draftApplyLinkedInJob(
  jobId: number,
  payload: { suggest_resume_change?: boolean } = {},
): Promise<LinkedInDraftApplyResult> {
  return request<LinkedInDraftApplyResult>(
    `/api/linkedin/jobs/${jobId}/draft-apply`,
    { method: "POST", body: JSON.stringify(payload) },
  )
}

export function fetchApplications(
  offset = 0,
  limit = 12,
): Promise<ApplicationsPage> {
  return request<ApplicationsPage>(
    `/api/applications?format=json&limit=${limit}&offset=${offset}`,
  )
}

export function fetchApplicationSource(
  appId: number,
): Promise<ApplicationSource> {
  return request<ApplicationSource>(`/api/applications/${appId}/source`)
}

export function fetchLastEmail(appId: number): Promise<LastEmail> {
  return request<LastEmail>(`/api/applications/${appId}/last-email`)
}

export function deleteApplication(appId: number): Promise<{ message: string }> {
  return request<{ message: string }>(`/applications/${appId}`, {
    method: "DELETE",
  })
}

export function syncInbox(): Promise<{ message: string }> {
  return request<{ message: string }>("/sync/", { method: "POST" })
}

export function fetchDrafts(limit = 50): Promise<DraftListResponse> {
  return request<DraftListResponse>(`/api/drafts/?limit=${limit}`)
}

export function fetchDraftDetail(draftId: number): Promise<DraftDetail> {
  return request<DraftDetail>(`/api/drafts/${draftId}`)
}

export function regenerateDraft(
  draftId: number,
  instructions: string | null,
): Promise<{ message: string; subject: string; content: string }> {
  return request<{ message: string; subject: string; content: string }>(
    `/drafts/regenerate/${draftId}`,
    {
      method: "POST",
      body: JSON.stringify({ instructions }),
    },
  )
}

export function deleteDraftRequest(
  draftId: number,
): Promise<{ message: string }> {
  return request<{ message: string }>(`/drafts/${draftId}`, {
    method: "DELETE",
  })
}

export function sendDraft(
  draftId: number,
  payload: {
    content: string
    recipient: string
    subject: string
    cc?: string
    resume_id?: number
  },
): Promise<{ message: string }> {
  return request<{ message: string }>(`/emails/send/${draftId}`, {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function fetchResumeSuggestion(
  appId: number,
): Promise<ResumeSuggestion> {
  return request<ResumeSuggestion>(`/api/applications/${appId}/suggestion`)
}

export function fetchEmailEvents(limit = 100): Promise<EmailEventListResponse> {
  return request<EmailEventListResponse>(`/api/email-events/?limit=${limit}`)
}

export function generateReply(
  appId: number,
  instructions: string | null,
): Promise<ReplyGeneration> {
  return request<ReplyGeneration>("/replies/generate", {
    method: "POST",
    body: JSON.stringify({ app_id: appId, instructions }),
  })
}

export function sendReply(payload: {
  app_id: number
  recipient: string
  subject: string
  content: string
}): Promise<{ status: string; message: string }> {
  return request<{ status: string; message: string }>("/emails/send/direct", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function submitJobText(payload: {
  text: string
  instructions?: string
  suggest_resume_change?: boolean
}): Promise<CreatedApplication> {
  return request<CreatedApplication>("/applications/text/", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function submitJobUrl(jobUrl: string): Promise<CreatedApplication> {
  return request<CreatedApplication>(
    `/applications/job/?job_url=${encodeURIComponent(jobUrl)}`,
    { method: "POST" },
  )
}

export function pasteJobPoster(payload: {
  image: string
  instructions?: string
}): Promise<CreatedApplication> {
  return request<CreatedApplication>("/applications/poster/paste/", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function uploadJobPoster(
  file: File,
  instructions?: string,
): Promise<CreatedApplication> {
  const form = new FormData()
  form.append("file", file)
  if (instructions) form.append("instructions", instructions)
  return request<CreatedApplication>("/applications/poster/", {
    method: "POST",
    body: form,
  })
}

export function fetchApplicationDetail(
  appId: number,
): Promise<ApplicationDetail> {
  return request<ApplicationDetail>(`/api/applications/${appId}`)
}

export function fetchCampaigns(): Promise<CampaignListResponse> {
  return request<CampaignListResponse>("/api/campaigns/")
}

export function fetchCampaignItems(
  campaignId: number,
): Promise<CampaignItemRaw[]> {
  return request<CampaignItemRaw[]>(`/campaigns/${campaignId}/items`)
}

export function fetchCampaignProgress(
  campaignId: number,
): Promise<{ id: number; status: string; sent: number; total: number }> {
  return request<{ id: number; status: string; sent: number; total: number }>(
    `/campaigns/${campaignId}`,
  )
}

export function startCampaign(payload: {
  name: string
  sheet_url: string
  header_row: number
  context1: string
  context2: string
  daily_limit?: number
}): Promise<{ message: string; campaign_id: number }> {
  return request<{ message: string; campaign_id: number }>("/campaigns/start", {
    method: "POST",
    body: JSON.stringify(payload),
  })
}

export function pauseCampaign(campaignId: number): Promise<{ status: string }> {
  return request<{ status: string }>(`/campaigns/${campaignId}/pause`, {
    method: "POST",
  })
}

export function resumeCampaign(
  campaignId: number,
): Promise<{ status: string }> {
  return request<{ status: string }>(`/campaigns/${campaignId}/resume`, {
    method: "POST",
  })
}

export function retryCampaign(
  campaignId: number,
  headerRow?: number,
): Promise<{ message: string }> {
  return request<{ message: string }>(`/campaigns/${campaignId}/retry`, {
    method: "POST",
    body: JSON.stringify(headerRow ? { header_row: headerRow } : {}),
  })
}

export function retryFailedCampaignItems(
  campaignId: number,
): Promise<{ message: string }> {
  return request<{ message: string }>(`/campaigns/${campaignId}/retry_failed`, {
    method: "POST",
  })
}

const STATUS_LABELS: Record<string, string> = {
  draft: "Draft",
  processing: "Processing",
  awaiting_response: "Awaiting response",
  shortlisted: "Shortlisted",
  positive_response: "Positive response",
  submitted: "Submitted",
  blocked: "Blocked",
  ocr_uncertain: "OCR uncertain",
  rejected: "Rejected",
}

export function statusLabel(status: ApplicationStatus | string): string {
  return STATUS_LABELS[status] ?? status
}

export function statusTone(status: ApplicationStatus | string): Tone {
  if (status === "shortlisted" || status === "positive_response")
    return "success"
  if (status === "awaiting_response" || status === "ocr_uncertain")
    return "warning"
  if (status === "rejected" || status === "blocked") return "danger"
  return "violet"
}

export function errorMessage(error: unknown): string {
  if (error instanceof Error) return error.message
  return "Something went wrong."
}
