import { useRef, useState } from "react"
import { errorMessage, deleteRoleResume, updateRoleResume, uploadRoleResume } from "@/api"
import { useAsync } from "@/hooks/useAsync"
import type { Resume } from "@/types"
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  Field,
  Icon,
  IconButton,
  Input,
  LoadingState,
  PageHeader,
  Textarea,
} from "@/components/ui"

const summaryPrompt = `Analyze my resume and return:
1. Target role
2. Professional summary
3. Core technical skills
4. Domain expertise
5. Strongest achievements
6. Tools and platforms
7. Leadership and collaboration
8. Education and certifications
9. Keywords for matching
10. A concise positioning statement

Put the final summary in one clean code block so I can copy it into Command.`

export default function ResumeLibrary({
  resumes,
  loading,
  error,
  reload,
  savePrimary,
  notify,
  onSettings,
}: {
  resumes: Resume[]
  loading: boolean
  error: string | null
  reload: () => void
  savePrimary: (focus: string, summary: string) => Promise<void>
  notify: (
    message: string,
    tone?: "neutral" | "success" | "warning" | "danger" | "violet",
  ) => void
  onSettings: () => void
}) {
  const [copyState, setCopyState] = useState<"idle" | "ok" | "err">("idle")
  const [role, setRole] = useState("")
  const [summary, setSummary] = useState("")
  const [file, setFile] = useState<File | null>(null)
  const [uploadStatus, setUploadStatus] = useState<{
    text: string
    error: boolean
  } | null>(null)
  const [uploading, setUploading] = useState(false)
  const [primaryEdit, setPrimaryEdit] = useState<Resume | null>(null)
  const [roleEdit, setRoleEdit] = useState<Resume | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<Resume | null>(null)
  const [busy, setBusy] = useState(false)
  const roleInput = useRef<HTMLInputElement>(null)
  const primary = resumes.find((item) => item.isDefault)
  const specific = resumes.filter((item) => !item.isDefault)
  const copy = async () => {
    try {
      await navigator.clipboard.writeText(summaryPrompt)
      setCopyState("ok")
    } catch {
      setCopyState("err")
    }
  }
  const upload = async () => {
    if (!role.trim()) {
      setUploadStatus({ text: "Add a target role first.", error: true })
      return
    }
    if (!file) {
      setUploadStatus({ text: "Choose a PDF file first.", error: true })
      return
    }
    if (
      resumes.some(
        (item) => item.focus.toLowerCase() === role.trim().toLowerCase(),
      )
    ) {
      setUploadStatus({
        text: "A resume already uses this target role.",
        error: true,
      })
      return
    }
    setUploading(true)
    try {
      await uploadRoleResume(role.trim(), summary, file)
      setUploadStatus({ text: "Resume uploaded. Refreshing…", error: false })
      notify("Resume uploaded.", "success")
      reload()
      window.setTimeout(() => {
        setRole("")
        setSummary("")
        setFile(null)
        setUploadStatus(null)
      }, 900)
    } catch (cause: unknown) {
      setUploadStatus({ text: errorMessage(cause), error: true })
    } finally {
      setUploading(false)
    }
  }
  const save = async (resume: Resume) => {
    setBusy(true)
    try {
      if (resume.isDefault) {
        await savePrimary(resume.focus, resume.summary ?? "")
      } else {
        await updateRoleResume(
          Number(resume.id),
          resume.filename,
          resume.focus,
          resume.summary ?? "",
        )
        reload()
      }
      setPrimaryEdit(null)
      setRoleEdit(null)
      notify("Resume changes saved.", "success")
    } catch (cause: unknown) {
      notify(errorMessage(cause), "danger")
    } finally {
      setBusy(false)
    }
  }
  const remove = async (resume: Resume) => {
    setBusy(true)
    try {
      await deleteRoleResume(Number(resume.id))
      reload()
      notify(`${resume.filename} deleted`, "success")
      setDeleteTarget(null)
    } catch (cause: unknown) {
      notify(errorMessage(cause), "danger")
    } finally {
      setBusy(false)
    }
  }

  if (loading && !resumes.length) {
    return (
      <main className="content">
        <PageHeader
          eyebrow="Resumes"
          title="Your resume library"
          description="Maintain one primary resume and focused versions for the roles you pursue."
        />
        <LoadingState label="Loading your resumes…" />
      </main>
    )
  }

  if (error && !resumes.length) {
    return (
      <main className="content">
        <PageHeader
          eyebrow="Resumes"
          title="Your resume library"
          description="Maintain one primary resume and focused versions for the roles you pursue."
        />
        <EmptyState
          icon="warning"
          title="Could not load your resumes"
          description={error}
          action={<Button onClick={reload}>Retry</Button>}
        />
      </main>
    )
  }

  return (
    <main className="content">
      <PageHeader
        eyebrow="Resumes"
        title="Your resume library"
        description="Maintain one primary resume and focused versions for the roles you pursue."
        actions={
          <Button
            variant="primary"
            icon="add"
            onClick={() => {
              roleInput.current?.scrollIntoView({
                behavior: "smooth",
                block: "center",
              })
              roleInput.current?.focus()
            }}
          >
            Add resume
          </Button>
        }
      />
      <section className="prompt-box card">
        <span className="stat-icon violet">
          <Icon name="sparkles" />
        </span>
        <div>
          <h2>How to generate a resume summary</h2>
          <p>
            Copy this prompt into your preferred assistant, upload your resume
            there, then paste the result below.
          </p>
          <button
            id="summaryPrompt"
            className="prompt-copy-text"
            onClick={copy}
          >
            <pre>{summaryPrompt}</pre>
            <span>
              <Icon name="document" size={14} />
              Copy prompt
            </span>
          </button>
          <small className={`prompt-help ${copyState}`}>
            {copyState === "ok"
              ? "Prompt copied."
              : copyState === "err"
                ? "Could not copy. Select the text manually."
                : "Click the prompt to copy it."}
          </small>
        </div>
      </section>
      <div className="launch-grid resume-layout">
        <div className="launch-main">
          <section className="card primary-resume-card">
            <header>
              <span className="stat-icon green">
                <Icon name="document" />
              </span>
              <div>
                <span className="eyebrow">Primary resume</span>
                <h2>
                  {primary?.filename || "No primary resume uploaded yet."}
                </h2>
                <p>
                  {primary
                    ? `${primary.focus}${
                        primary.summary ? " · summary added" : ""
                      }`
                    : "Upload your primary resume from global settings."}
                </p>
              </div>
            </header>
            <Button onClick={onSettings}>Manage in settings</Button>
          </section>
          <section className="card role-resume-card">
            <header>
              <span className="stat-icon blue">
                <Icon name="upload" />
              </span>
              <div>
                <span className="eyebrow">Add role-specific resume</span>
                <h2>Tailor your next application</h2>
                <p>Store a PDF and summary for a specific target role.</p>
              </div>
            </header>
            <Field label="Target role" required>
              <Input
                ref={roleInput}
                id="newResumeRole"
                value={role}
                onChange={(event) => setRole(event.target.value)}
                placeholder="e.g. AI Engineer"
              />
            </Field>
            <Field
              label="Resume PDF"
              required
              hint="Duplicate filenames receive an automatic (1), (2) suffix."
            >
              <Input
                id="newResumeFile"
                type="file"
                accept="application/pdf"
                onChange={(event) => setFile(event.target.files?.[0] ?? null)}
              />
            </Field>
            <Field label="Resume summary">
              <Textarea
                id="newResumeSummary"
                rows={8}
                value={summary}
                onChange={(event) => setSummary(event.target.value)}
                placeholder="Paste the generated summary here..."
              />
            </Field>
            {uploadStatus && (
              <div className={`form-note ${uploadStatus.error ? "err" : "ok"}`}>
                {uploadStatus.text}
              </div>
            )}
            <Button
              id="btnUploadResume"
              variant="primary"
              icon="upload"
              onClick={upload}
              disabled={uploading}
            >
              {uploading ? "Uploading…" : "Upload resume"}
            </Button>
          </section>
        </div>
        <aside className="recent-drafts resume-gallery card">
          <header>
            <div>
              <h2>Resume gallery</h2>
              <p>{resumes.length} in your library</p>
            </div>
            <Badge>{resumes.length}</Badge>
          </header>
          {primary && (
            <div className="draft-row primary-resume">
              <span className="company-mark green">
                <Icon name="document" size={15} />
              </span>
              <span>
                <strong>{primary.filename}</strong>
                <small>
                  {primary.focus} {primary.summary && "· summary added"}
                </small>
              </span>
              <Badge tone="success">Primary</Badge>
              <IconButton
                icon="edit"
                label="Edit primary resume"
                onClick={() => setPrimaryEdit({ ...primary })}
              />
            </div>
          )}
          {specific.length ? (
            specific.map((resume) => (
              <div
                className="draft-row"
                data-search={`${resume.filename} ${resume.focus}`}
                key={resume.id}
              >
                <span className="company-mark">
                  <Icon name="document" size={15} />
                </span>
                <span>
                  <strong>{resume.filename}</strong>
                  <small>
                    {resume.focus} {resume.summary && "· summary added"}
                  </small>
                </span>
                <IconButton
                  icon="edit"
                  label={`Edit ${resume.filename}`}
                  onClick={() => setRoleEdit({ ...resume })}
                />
                <IconButton
                  icon="trash"
                  label={`Delete ${resume.filename}`}
                  className="icon-button-danger"
                  onClick={() => setDeleteTarget(resume)}
                />
              </div>
            ))
          ) : (
            <EmptyState
              icon="document"
              title="No role-specific resumes yet…"
              description="Add one for the roles you apply to most often."
            />
          )}
        </aside>
      </div>
      <Dialog
        open={Boolean(primaryEdit)}
        onClose={() => setPrimaryEdit(null)}
        title="Edit primary resume"
        description={primaryEdit?.filename}
        footer={
          <>
            <Button onClick={() => setPrimaryEdit(null)}>Cancel</Button>
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => primaryEdit && save(primaryEdit)}
            >
              {busy ? "Saving…" : "Save changes"}
            </Button>
          </>
        }
      >
        {primaryEdit && (
          <div className="form-stack">
            <Field label="Filename">
              <Input value={primaryEdit.filename} readOnly />
            </Field>
            <Field label="Target role">
              <Input
                value={primaryEdit.focus}
                onChange={(event) =>
                  setPrimaryEdit({ ...primaryEdit, focus: event.target.value })
                }
              />
            </Field>
            <Field label="Summary">
              <Textarea
                rows={8}
                value={primaryEdit.summary || ""}
                onChange={(event) =>
                  setPrimaryEdit({
                    ...primaryEdit,
                    summary: event.target.value,
                  })
                }
              />
            </Field>
          </div>
        )}
      </Dialog>
      <Dialog
        open={Boolean(roleEdit)}
        onClose={() => setRoleEdit(null)}
        title="Edit role resume"
        description="Rename by re-uploading the file."
        footer={
          <>
            <Button onClick={() => setRoleEdit(null)}>Cancel</Button>
            <Button
              variant="primary"
              disabled={busy}
              onClick={() => roleEdit && save(roleEdit)}
            >
              {busy ? "Saving…" : "Save changes"}
            </Button>
          </>
        }
      >
        {roleEdit && (
          <div className="form-stack">
            <Field label="Filename" hint="Rename by re-uploading the file.">
              <Input value={roleEdit.filename} readOnly />
            </Field>
            <Field label="Target role">
              <Input
                value={roleEdit.focus}
                onChange={(event) =>
                  setRoleEdit({ ...roleEdit, focus: event.target.value })
                }
              />
            </Field>
            <Field label="Summary">
              <Textarea
                rows={8}
                value={roleEdit.summary || ""}
                onChange={(event) =>
                  setRoleEdit({ ...roleEdit, summary: event.target.value })
                }
              />
            </Field>
          </div>
        )}
      </Dialog>
      <Dialog
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="Delete this resume?"
        description="Any pending suggestion using it will fall back to your primary resume."
        footer={
          <>
            <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button
              variant="danger"
              disabled={busy}
              onClick={() => deleteTarget && remove(deleteTarget)}
            >
              {busy ? "Deleting…" : "Delete"}
            </Button>
          </>
        }
      >
        This role-specific resume will be removed from your library.
      </Dialog>
    </main>
  )
}
