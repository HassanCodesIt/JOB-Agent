import { useEffect, useRef, useState } from "react"
import {
  deleteDraftRequest,
  errorMessage,
  fetchDraftDetail,
  fetchDrafts,
  fetchResumeSuggestion,
  regenerateDraft,
  sendDraft,
} from "@/api"
import { useAsync } from "@/hooks/useAsync"
import type {
  DraftDetail,
  DraftListResponse,
  PageName,
  Resume,
  ResumeSuggestion,
} from "@/types"
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  Field,
  Icon,
  Input,
  LoadingState,
  PageHeader,
  Textarea,
} from "@/components/ui"

function formatDate(raw: string): string {
  if (!raw) return ""
  const normalized = raw.replace(" ", "T").replace(/(\.\d+)\d*/, "$1")
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return raw.split(" ")[0] ?? raw
  return date.toLocaleDateString("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
  })
}

interface ComposeForm {
  to: string
  cc: string
  subject: string
  body: string
}

interface DetailState {
  loading: boolean
  error: string | null
  detail: DraftDetail | null
}

export default function DraftStudio({
  resumes,
  navigate,
  notify,
  revision,
}: {
  resumes: Resume[]
  navigate: (page: PageName) => void
  revision: number
  notify: (
    message: string,
    tone?: "neutral" | "success" | "warning" | "danger" | "violet",
  ) => void
}) {
  const drafts = useAsync<DraftListResponse>(() => fetchDrafts(50))
  const [selectedId, setSelectedId] = useState<number | null>(null)
  const [detailAttempt, setDetailAttempt] = useState(0)
  const [detail, setDetail] = useState<DetailState>({
    loading: true,
    error: null,
    detail: null,
  })
  const [suggestion, setSuggestion] = useState<ResumeSuggestion | null>(null)
  const [formState, setFormState] = useState<ComposeForm | null>(null)
  const [regenerateOpen, setRegenerateOpen] = useState(false)
  const [deleteOpen, setDeleteOpen] = useState(false)
  const [sendConfirmOpen, setSendConfirmOpen] = useState(false)
  const [instructions, setInstructions] = useState("")
  const [recipientError, setRecipientError] = useState("")
  const [sending, setSending] = useState(false)
  const recipientRef = useRef<HTMLInputElement>(null)
  const sendingRef = useRef(false)
  const [status, setStatus] = useState<{
    title: string
    message: string
    success: boolean
  } | null>(null)

  const items = drafts.data?.items ?? []
  const total = drafts.data?.total ?? 0
  const processing = drafts.data?.processing ?? []
  const selected = items.find((item) => item.id === selectedId) ?? items[0]
  const form: ComposeForm | null =
    formState ??
    (selected
      ? { to: selected.recipient, cc: "", subject: "", body: "" }
      : null)
  const defaultResume = resumes.find((item) => item.isDefault)
  const suggestedResumeId = suggestion?.suggested_resume_id ?? null
  const hasSuggestion = Boolean(detail.detail?.has_suggestion && suggestedResumeId)
  const attachedResumeId =
    hasSuggestion && suggestedResumeId != null
      ? String(suggestedResumeId)
      : (defaultResume?.id ?? "primary")
  const attachmentName =
    resumes.find((item) => item.id === attachedResumeId)?.filename ||
    (hasSuggestion ? (suggestion?.suggested_resume_name ?? null) : null) ||
    "Primary resume"

  const reloadDrafts = drafts.reload
  const mountedRevision = useRef(revision)
  useEffect(() => {
    if (revision === mountedRevision.current) return
    mountedRevision.current = revision
    reloadDrafts()
  }, [revision, reloadDrafts])

  useEffect(() => {
    if (!selected) {
      setDetail({ loading: false, error: null, detail: null })
      setFormState(null)
      setSuggestion(null)
      return
    }
    let alive = true
    setDetail({ loading: true, error: null, detail: null })
    setFormState(null)
    setRecipientError("")
    Promise.all([
      fetchDraftDetail(selected.id),
      fetchResumeSuggestion(selected.application_id),
    ])
      .then(([draftDetail, resumeSuggestion]) => {
        if (!alive) return
        setDetail({ loading: false, error: null, detail: draftDetail })
        setFormState({
          to: draftDetail.recipient,
          cc: draftDetail.cc,
          subject: draftDetail.subject,
          body: draftDetail.content,
        })
        setSuggestion(resumeSuggestion)
      })
      .catch((cause: unknown) => {
        if (!alive) return
        setDetail({
          loading: false,
          error: errorMessage(cause),
          detail: null,
        })
        setFormState(null)
        setSuggestion(null)
      })
    return () => {
      alive = false
    }
  }, [selected?.id, detailAttempt])

  const choose = (id: number) => {
    setSelectedId(id)
  }
  const change = (key: keyof ComposeForm, value: string) => {
    if (key === "to" && value.trim()) setRecipientError("")
    setFormState((current) => {
      const base: ComposeForm = current ?? {
        to: selected?.recipient ?? "",
        cc: "",
        subject: "",
        body: "",
      }
      return { ...base, [key]: value }
    })
  }
  const regenerate = () => {
    if (!selected || detail.loading) return
    regenerateDraft(selected.id, instructions.trim() || null)
      .then((value) => {
        setFormState((current) => ({
          to: current?.to ?? form?.to ?? "",
          cc: current?.cc ?? form?.cc ?? "",
          subject: value.subject,
          body: value.content,
        }))
        setRegenerateOpen(false)
        setInstructions("")
        notify("Draft regenerated", "success")
      })
      .catch((cause: unknown) => notify(errorMessage(cause), "danger"))
  }
  const doSend = (useSuggested: boolean) => {
    if (!selected || !form || detail.loading || sendingRef.current) return
    sendingRef.current = true
    setSending(true)
    const payload = {
      content: form.body,
      recipient: form.to,
      subject: form.subject,
      cc: form.cc,
      ...(useSuggested && suggestedResumeId != null
        ? { resume_id: suggestedResumeId }
        : {}),
    }
    sendDraft(selected.id, payload)
      .then(() => {
        setStatus({
          title: "Application sent",
          message: useSuggested
            ? "The suggested resume was attached."
            : hasSuggestion
              ? "Your primary resume was used."
              : "Your application was marked as delivered from the active account.",
          success: true,
        })
        reloadDrafts()
      })
      .catch((cause: unknown) =>
        setStatus({
          title: "Send failed",
          message: errorMessage(cause),
          success: false,
        }),
      )
      .finally(() => {
        sendingRef.current = false
        setSending(false)
      })
  }
  const send = () => {
    if (sending) return
    if (!form?.to.trim()) {
      setRecipientError("Add a recipient before sending.")
      window.requestAnimationFrame(() => recipientRef.current?.focus())
      return
    }
    if (hasSuggestion) {
      setSendConfirmOpen(true)
      return
    }
    doSend(false)
  }
  const discard = () => {
    if (!selected) return
    deleteDraftRequest(selected.id)
      .then(() => {
        setDeleteOpen(false)
        setSelectedId(null)
        notify("Draft discarded", "success")
        reloadDrafts()
      })
      .catch((cause: unknown) => notify(errorMessage(cause), "danger"))
  }

  if (drafts.loading && !drafts.data) {
    return (
      <main className="content">
        <PageHeader
          eyebrow="Application workspace"
          title="Draft studio"
          description="Review, refine, and send your tailored application emails."
        />
        <LoadingState label="Loading drafts…" />
      </main>
    )
  }

  if (drafts.error && !drafts.data) {
    return (
      <main className="content">
        <PageHeader
          eyebrow="Application workspace"
          title="Draft studio"
          description="Review, refine, and send your tailored application emails."
        />
        <EmptyState
          icon="warning"
          title="Could not load drafts"
          description={drafts.error}
          action={<Button onClick={drafts.reload}>Retry</Button>}
        />
      </main>
    )
  }

  return (
    <main className="content">
      <PageHeader
        eyebrow="Application workspace"
        title="Draft studio"
        description="Review, refine, and send your tailored application emails."
        actions={
          <Button
            variant="primary"
            icon="add"
            onClick={() => navigate("Add Application")}
          >
            New draft
          </Button>
        }
      />
      {processing.length > 0 && (
        <section className="processing-banner">
          <span className="spinner" />
          <div>
            <strong>AI drafting in progress</strong>
            <p>
              Your workspace refreshes automatically once every draft is ready.
            </p>
            <div className="tag-row">
              {processing.map((item) => (
                <Badge key={item.id}>{item.company_name}</Badge>
              ))}
            </div>
          </div>
        </section>
      )}
      {total ? (
        <div className="draft-layout">
          <section className="card draft-list-card">
            <header className="card-header">
              <div>
                <h2>Your drafts</h2>
                <p>
                  {total} application{total === 1 ? "" : "s"} ready to review
                </p>
              </div>
              <button className="filter-button">
                <Icon name="filter" size={14} />
                Recent
              </button>
            </header>
            <div id="draftList">
              {items.map((row, index) => (
                <button
                  className={`draft-item ${
                    row.id === selected?.id ? "selected" : ""
                  }`}
                  data-search={`${row.company_name} ${row.role} ${row.recipient}`}
                  key={row.id}
                  onClick={() => choose(row.id)}
                >
                  <span className={`company-mark tone-${index % 4}`}>
                    {row.company_name
                      .split(" ")
                      .map((word) => word[0])
                      .join("")
                      .slice(0, 2)}
                  </span>
                  <span>
                    <strong>{row.company_name}</strong>
                    <small>{row.role}</small>
                    <em>{row.recipient || "No contact email"}</em>
                  </span>
                  <time>{formatDate(row.created_at)}</time>
                  <Icon name="chevron" size={13} />
                </button>
              ))}
            </div>
            {total > 50 && (
              <footer className="list-footer">
                <span>Showing 50 of {total}</span>
                <Button
                  variant="ghost"
                  onClick={() => navigate("Sent History")}
                >
                  see all activity
                </Button>
              </footer>
            )}
          </section>
          <section className="compose-card card">
            {detail.error ? (
              <EmptyState
                icon="warning"
                title="Could not load draft"
                description={detail.error}
                action={
                  <Button onClick={() => setDetailAttempt((value) => value + 1)}>
                    Retry
                  </Button>
                }
              />
            ) : selected && form ? (
              <div className={detail.loading ? "compose-loading" : ""}>
                <header className="compose-head">
                  <span className="company-mark">
                    {selected.company_name
                      .split(" ")
                      .map((word) => word[0])
                      .join("")
                      .slice(0, 2)}
                  </span>
                  <div>
                    <h2>{selected.company_name}</h2>
                    <p>{selected.role}</p>
                  </div>
                  <Badge tone="violet">AI draft generated</Badge>
                </header>
                {selected.source === "linkedin_automation" && (
                  <div className="import-note">
                    <Icon name="linkedin" size={14} />
                    Imported from LinkedIn Job Finder
                  </div>
                )}
                <div className="draft-readiness" aria-label="Draft readiness">
                  {form.to ? (
                    <span className="ready">
                      <Icon name="check" size={13} />
                      Recipient ready
                    </span>
                  ) : (
                    <button
                      className="needs-attention"
                      onClick={() => recipientRef.current?.focus()}
                    >
                      <Icon name="mail" size={13} />
                      Recipient needed
                    </button>
                  )}
                  <span className="ready">
                    <Icon name="document" size={13} />
                    Resume attached
                  </span>
                  <span>
                    <Icon name="sparkles" size={13} />
                    Review AI draft
                  </span>
                </div>
                {!selected.recipient && (
                  <div className="notice neutral">
                    <Icon name="mail" />
                    <div>
                      <strong>No email found</strong>
                      <p>
                        Add a recipient manually before sending, or use the
                        available LinkedIn/apply links.
                      </p>
                    </div>
                  </div>
                )}
                <div className="compose-fields">
                  <div
                    className={`address-row ${
                      recipientError ? "address-row-error" : ""
                    }`}
                  >
                    <label>To</label>
                    <Input
                      ref={recipientRef}
                      disabled={detail.loading}
                      value={form.to}
                      onChange={(event) => change("to", event.target.value)}
                      placeholder="Add a recipient"
                      aria-invalid={Boolean(recipientError)}
                      aria-describedby={
                        recipientError ? "recipient-error" : undefined
                      }
                    />
                    {recipientError && (
                      <span className="address-error" id="recipient-error">
                        {recipientError}
                      </span>
                    )}
                  </div>
                  <div className="address-row">
                    <label>CC</label>
                    <Input
                      disabled={detail.loading}
                      value={form.cc}
                      onChange={(event) => change("cc", event.target.value)}
                      placeholder="Optional"
                    />
                  </div>
                  <div className="address-row">
                    <label>Subject</label>
                    <Input
                      disabled={detail.loading}
                      value={form.subject}
                      onChange={(event) =>
                        change("subject", event.target.value)
                      }
                    />
                  </div>
                </div>
                <Textarea
                  id="fieldBody"
                  className="email-editor canonical-editor"
                  disabled={detail.loading}
                  value={form.body}
                  onChange={(event) => change("body", event.target.value)}
                  aria-label="Email body"
                />
                <footer className="compose-footer">
                  <div className="attachment-note">
                    <Icon name="document" />
                    <span>
                      <strong>Resume attached automatically</strong>
                      <small>{attachmentName}</small>
                    </span>
                    {hasSuggestion && (
                      <Badge tone="warning">Alternative resume available</Badge>
                    )}
                  </div>
                  <div>
                    <Button
                      variant="ghost"
                      icon="trash"
                      onClick={() => setDeleteOpen(true)}
                    >
                      Delete
                    </Button>
                    <Button
                      icon="refresh"
                      onClick={() => setRegenerateOpen(true)}
                    >
                      Regenerate
                    </Button>
                    <Button variant="primary" icon="send" onClick={send}>
                      Send application
                    </Button>
                  </div>
                </footer>
              </div>
            ) : (
              <EmptyState
                title="Choose a draft"
                description="Select an application to review its draft."
              />
            )}
          </section>
        </div>
      ) : (
        <EmptyState
          icon="document"
          title="No drafts waiting"
          description="Launch an application to create your first tailored draft."
          action={
            <Button
              variant="primary"
              onClick={() => navigate("Add Application")}
            >
              Launch an application
            </Button>
          }
        />
      )}
      <Dialog
        open={regenerateOpen}
        onClose={() => setRegenerateOpen(false)}
        title="Regenerate with AI"
        description="Tell the assistant what to change."
        footer={
          <>
            <Button onClick={() => setRegenerateOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={regenerate}>
              Regenerate
            </Button>
          </>
        }
      >
        <Field label="Instructions">
          <Textarea
            rows={4}
            value={instructions}
            onChange={(event) => setInstructions(event.target.value)}
            placeholder="Make it more formal, highlight my Python automation experience…"
          />
        </Field>
      </Dialog>
      <Dialog
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        title="Discard this draft?"
        description="The application record itself stays in your dashboard."
        footer={
          <>
            <Button onClick={() => setDeleteOpen(false)}>Cancel</Button>
            <Button variant="danger" onClick={discard}>
              Discard
            </Button>
          </>
        }
      >
        This draft email will be removed from your workspace.
      </Dialog>
      <Dialog
        open={sendConfirmOpen}
        onClose={() => setSendConfirmOpen(false)}
        title="Send a different resume?"
        description="Command found an alternative resume that may better match this role."
        footer={
          <>
            <Button
              onClick={() => {
                setSendConfirmOpen(false)
                doSend(false)
              }}
            >
              Use primary
            </Button>
            <Button
              variant="primary"
              onClick={() => {
                setSendConfirmOpen(false)
                doSend(true)
              }}
            >
              Send this resume
            </Button>
          </>
        }
      >
        Review the selected resume before completing the prototype send.
      </Dialog>
      <Dialog
        open={Boolean(status)}
        onClose={() => setStatus(null)}
        title={status?.title ?? ""}
      >
        <div
          className={`status-message ${status?.success ? "success" : "danger"}`}
        >
          {status?.message}
        </div>
        <Button
          className="full-button"
          variant="primary"
          onClick={() => setStatus(null)}
        >
          Got it
        </Button>
      </Dialog>
    </main>
  )
}
