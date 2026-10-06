import {
  useEffect,
  useRef,
  useState,
  type ClipboardEvent,
  type ChangeEvent,
} from "react"
import {
  errorMessage,
  fetchApplicationDetail,
  fetchDrafts,
  pasteJobPoster,
  submitJobText,
  submitJobUrl,
  uploadJobPoster,
} from "@/api"
import type { ApplicationDetail, CreatedApplication } from "@/types"
import { useAsync } from "@/hooks/useAsync"
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  Field,
  Icon,
  Input,
  PageHeader,
  Textarea,
} from "@/components/ui"

const delay = (ms: number) =>
  new Promise((resolve) => window.setTimeout(resolve, ms))

async function waitForDetail(
  appId: number,
): Promise<ApplicationDetail | null> {
  // Legacy apply page polled its draft endpoint 24×2.5s (60s window).
  for (let attempt = 0; attempt < 40; attempt += 1) {
    try {
      const detail = await fetchApplicationDetail(appId)
      if (detail.status !== "processing") return detail
    } catch {
      // Transient poll failure; retry inside the same window.
    }
    await delay(1500)
  }
  return null
}

export default function AddApplication({
  notify,
  revision,
  onDraftCreated,
  onOpenDrafts,
  onOpenResumes,
}: {
  notify: (
    message: string,
    tone?: "neutral" | "success" | "warning" | "danger" | "violet",
  ) => void
  revision: number
  onDraftCreated: () => void
  onOpenDrafts: () => void
  onOpenResumes: () => void
}) {
  const [jobText, setJobText] = useState("")
  const [instructions, setInstructions] = useState("")
  const [matchResume, setMatchResume] = useState(true)
  const [pasteOpen, setPasteOpen] = useState(false)
  const [linkOpen, setLinkOpen] = useState(false)
  const [status, setStatus] = useState<{
    title: string
    message: string
    success: boolean
  } | null>(null)
  const [processing, setProcessing] = useState(false)
  const [processingSource, setProcessingSource] = useState("details")
  const [processingPhase, setProcessingPhase] = useState(0)
  const [preview, setPreview] = useState("")
  const [previewFile, setPreviewFile] = useState<File | null>(null)
  const [jobUrl, setJobUrl] = useState("")
  const uploadRef = useRef<HTMLInputElement>(null)
  const recent = useAsync(() => fetchDrafts(6))
  const reloadRecent = recent.reload
  const seenRevision = useRef(revision)
  useEffect(() => {
    if (revision === seenRevision.current) return
    seenRevision.current = revision
    reloadRecent()
  }, [revision, reloadRecent])
  const items = recent.data?.items.slice(0, 6) ?? []
  const phases = processingSource.toLowerCase().includes("poster")
    ? [
        "Reading job poster",
        "Extracting job requirements",
        "Matching the best resume",
        "Generating your draft",
      ]
    : [
        "Reading job details",
        "Structuring requirements",
        "Matching the best resume",
        "Generating your draft",
      ]
  useEffect(() => {
    if (!processing) return
    setProcessingPhase(0)
    const interval = window.setInterval(
      () =>
        setProcessingPhase((value) => Math.min(phases.length - 1, value + 1)),
      2000,
    )
    return () => window.clearInterval(interval)
  }, [processing, processingSource])

  const runPipeline = async (
    source: string,
    intake: () => Promise<CreatedApplication>,
  ) => {
    setProcessingSource(source)
    setProcessing(true)
    setProcessingPhase(0)
    try {
      const created = await intake()
      setProcessingPhase(1)
      const detail = await waitForDetail(created.id)
      if (!detail) {
        setStatus({
          title: "Still processing",
          message:
            "The draft is still processing. Check the draft studio in a moment.",
          success: false,
        })
        return
      }
      if (detail.status === "blocked") {
        setStatus({
          title: "Processing failed",
          message:
            "Command marked this application as blocked — the job source could not be processed automatically. Paste the job details instead, or review it in Draft Studio.",
          success: false,
        })
        return
      }
      const lines = [
        `Draft ready for ${detail.company_name || "Unknown Company"} — ${
          detail.role || "Unknown Role"
        }.`,
      ]
      if (detail.contact_email) {
        lines.push(
          `Contact found: ${detail.contact_email}${
            detail.contact_phone ? ` · ${detail.contact_phone}` : ""
          }.`,
        )
      } else {
        lines.push("No contact email found in the job details.")
      }
      if (detail.confidence_score != null) {
        lines.push(
          `Form-field confidence: ${Math.round(detail.confidence_score * 100)}%.`,
        )
      }
      if (detail.suggested_resume_name) {
        lines.push(`Suggested resume: ${detail.suggested_resume_name}.`)
      }
      setStatus({
        title: "Draft ready",
        message: lines.join(" "),
        success: true,
      })
      notify(
        `Draft ready for ${detail.company_name || "Unknown Company"}.`,
        "success",
      )
      onDraftCreated()
    } catch (cause: unknown) {
      setStatus({
        title: "Something went wrong",
        message: errorMessage(cause),
        success: false,
      })
    } finally {
      setProcessing(false)
    }
  }
  const start = (
    details: string,
    source: string,
    intake: () => Promise<CreatedApplication>,
  ) => {
    if (!details.trim()) {
      setStatus({
        title: "Job details required",
        message:
          "Paste the job details before asking Command to create a draft.",
        success: false,
      })
      return
    }
    void runPipeline(source, intake)
  }
  const readFile = (file?: File, origin: "file" | "paste" = "file") => {
    if (!file) return
    if (!["image/png", "image/jpeg"].includes(file.type)) {
      setStatus({
        title: "Unsupported file",
        message: "Choose a JPG or PNG image.",
        success: false,
      })
      return
    }
    setPreviewFile(origin === "file" ? file : null)
    const reader = new FileReader()
    reader.onload = () => {
      setPreview(String(reader.result))
      setPasteOpen(true)
    }
    reader.readAsDataURL(file)
  }
  const pasteImage = (event: ClipboardEvent<HTMLDivElement>) => {
    const file = Array.from(event.clipboardData.items)
      .find((item) => item.type.startsWith("image/"))
      ?.getAsFile()
    if (file) readFile(file, "paste")
  }
  const processPoster = () => {
    setPasteOpen(false)
    const source = previewFile ? "Uploaded poster" : "Pasted poster"
    const image = preview
    const file = previewFile
    setPreview("")
    setPreviewFile(null)
    start(image, source, () =>
      file
        ? uploadJobPoster(file, instructions)
        : pasteJobPoster({ image, instructions }),
    )
  }

  return (
    <main className="content">
      <PageHeader
        eyebrow="AI application assistant"
        title="Launch an application"
        description="Turn job details into a thoughtful, tailored application."
      />
      <section className="workflow-map" aria-label="Application workflow">
        {[
          "Add job source",
          "Command analyzes",
          "Review draft",
          "Send or apply",
        ].map((label, index) => (
          <div className={index === 0 ? "active" : ""} key={label}>
            <span>{index + 1}</span>
            <strong>{label}</strong>
            {index < 3 && <Icon name="chevron" size={13} />}
          </div>
        ))}
      </section>
      <section className="intake-choice">
        <div>
          <span className="eyebrow">Choose a starting point</span>
          <h2>How do you have the job details?</h2>
          <p>
            Use the fastest source available. Every option creates the same
            reviewable draft.
          </p>
        </div>
        <div>
          <button onClick={() => document.getElementById("jobText")?.focus()}>
            <Icon name="document" />
            <span>
              <strong>Text</strong>
              <small>Paste job details</small>
            </span>
          </button>
          <button onClick={() => setPasteOpen(true)}>
            <Icon name="image" />
            <span>
              <strong>Poster</strong>
              <small>Paste an image</small>
            </span>
          </button>
          <button onClick={() => uploadRef.current?.click()}>
            <Icon name="upload" />
            <span>
              <strong>Upload</strong>
              <small>JPG or PNG</small>
            </span>
          </button>
          <button onClick={() => setLinkOpen(true)}>
            <Icon name="external" />
            <span>
              <strong>Link</strong>
              <small>Public job URL</small>
            </span>
          </button>
          <input
            ref={uploadRef}
            hidden
            type="file"
            accept="image/png,image/jpeg"
            onChange={(event: ChangeEvent<HTMLInputElement>) =>
              readFile(event.target.files?.[0], "file")
            }
          />
        </div>
      </section>
      <div className="launch-grid">
        <div className="launch-main">
          <section className="card quick-start-card">
            <div className="quick-card-head">
              <span className="stat-icon violet">
                <Icon name="sparkles" />
              </span>
              <div>
                <span className="eyebrow">Quick start</span>
                <h2>Paste job details</h2>
                <p>
                  Add the description, requirements, and any contact information
                  you have.
                </p>
              </div>
            </div>
            <Textarea
              id="jobText"
              rows={11}
              value={jobText}
              onChange={(event) => setJobText(event.target.value)}
              placeholder="Paste job details, requirements, and contact information here..."
            />
            <label className="check-row">
              <input
                type="checkbox"
                checked={matchResume}
                onChange={(event) => setMatchResume(event.target.checked)}
              />
              <span>
                <strong>Match the best resume</strong>
                <small>
                  Command can suggest a role-specific resume from your{" "}
                  <button type="button" onClick={onOpenResumes}>
                    Resume Library
                  </button>
                  .
                </small>
              </span>
            </label>
            <Button
              variant="primary"
              icon="sparkles"
              onClick={() =>
                start(jobText, "Pasted job details", () =>
                  submitJobText({
                    text: jobText,
                    instructions,
                    suggest_resume_change: matchResume,
                  }),
                )
              }
            >
              Process &amp; write draft
            </Button>
          </section>
          <section className="card instruction-card">
            <div>
              <span className="eyebrow">One-time instructions</span>
              <h2>Optional guidance used only for this draft</h2>
            </div>
            <Input
              id="applicationInstructions"
              value={instructions}
              onChange={(event) => setInstructions(event.target.value)}
              placeholder="e.g. Highlight my Python automation work and keep the email concise."
            />
          </section>
        </div>
        <aside className="recent-drafts card">
          <header>
            <div>
              <h2>Recent drafts</h2>
              <p>Continue where you left off</p>
            </div>
            <Badge>{items.length}</Badge>
          </header>
          {items.length ? (
            <div className="list-rows">
              {items.map((item, index) => (
                <button
                  className="draft-row"
                  data-search={`${item.company_name} ${item.role}`}
                  key={item.id}
                  onClick={onOpenDrafts}
                >
                  <span className={`company-mark ${index % 2 ? "blue" : ""}`}>
                    {(item.company_name || "Unknown")
                      .split(" ")
                      .map((word) => word[0])
                      .join("")
                      .slice(0, 2)}
                  </span>
                  <span>
                    <strong>{item.company_name || "Unknown Company"}</strong>
                    <small>{item.role || "Unknown Role"}</small>
                  </span>
                  <Icon name="chevron" size={13} />
                </button>
              ))}
            </div>
          ) : recent.error ? (
            <EmptyState
              icon="document"
              title="Recent drafts unavailable"
              description={recent.error}
            />
          ) : recent.loading ? (
            <EmptyState
              icon="document"
              title="Recent drafts"
              description="Loading your latest drafts..."
            />
          ) : (
            <EmptyState
              icon="document"
              title="No recent drafts"
              description="Your drafts will appear here once you launch an application."
            />
          )}
          <Button variant="ghost" onClick={onOpenDrafts}>
            View all drafts <Icon name="arrow" size={12} />
          </Button>
        </aside>
      </div>

      <Dialog
        open={pasteOpen}
        onClose={() => {
          setPasteOpen(false)
          setPreview("")
          setPreviewFile(null)
        }}
        title="Paste a job poster"
        description="Copy a screenshot, then paste it into the area below."
        footer={
          <>
            <Button
              onClick={() => {
                setPasteOpen(false)
                setPreview("")
                setPreviewFile(null)
              }}
            >
              Cancel
            </Button>
            <Button
              variant="primary"
              disabled={!preview}
              onClick={processPoster}
            >
              Process poster
            </Button>
          </>
        }
      >
        <div className="paste-zone" tabIndex={0} onPaste={pasteImage}>
          {preview ? (
            <img src={preview} alt="Pasted job poster preview" />
          ) : (
            <>
              <Icon name="image" size={28} />
              <strong>Paste your screenshot here</strong>
              <span>Press Ctrl/Cmd+V after copying a job poster.</span>
            </>
          )}
        </div>
      </Dialog>
      <Dialog
        open={linkOpen}
        onClose={() => setLinkOpen(false)}
        title="Import from a link"
        description="Add a public job URL to initialize the application assistant."
        footer={
          <>
            <Button onClick={() => setLinkOpen(false)}>Cancel</Button>
            <Button
              variant="primary"
              disabled={!jobUrl.trim()}
              onClick={() => {
                try {
                  new URL(jobUrl)
                  setLinkOpen(false)
                  start(jobUrl, "Public job URL", () => submitJobUrl(jobUrl))
                } catch {
                  setStatus({
                    title: "Something went wrong",
                    message: "Enter a complete public URL.",
                    success: false,
                  })
                }
              }}
            >
              Initialize agent
            </Button>
          </>
        }
      >
        <Field label="Job URL">
          <Input
            id="jobUrlField"
            type="url"
            value={jobUrl}
            onChange={(event) => setJobUrl(event.target.value)}
            placeholder="https://company.com/jobs/role"
          />
        </Field>
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
      {processing && (
        <div className="process-overlay" role="status">
          <div className="process-modal">
            <span className="spinner" />
            <span className="eyebrow">Preparing your application</span>
            <h2>{phases[processingPhase]}</h2>
            <p>
              Command is using the job context and your saved profile to prepare
              a reviewable draft.
            </p>
            <div className="phase-list">
              {phases.map((phase, index) => (
                <div
                  className={
                    index < processingPhase
                      ? "done"
                      : index === processingPhase
                        ? "active"
                        : ""
                  }
                  key={phase}
                >
                  <span>
                    {index < processingPhase ? (
                      <Icon name="check" size={12} />
                    ) : (
                      index + 1
                    )}
                  </span>
                  {phase}
                </div>
              ))}
            </div>
            <small>You’ll review everything before anything is sent.</small>
          </div>
        </div>
      )}
    </main>
  )
}
