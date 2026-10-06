import type { Application, Draft, Resume } from "@/types"
import { Badge, Button, Field, Input, Select, Status, Textarea } from "./ui"

export function DraftEditor({
  application,
  draft,
  resumes,
  onChange,
  onGenerate,
  onSave,
  onSent,
}: {
  application: Application
  draft: Draft
  resumes: Resume[]
  onChange: (draft: Draft) => void
  onGenerate: () => void
  onSave: () => void
  onSent: () => void
}) {
  const noRecipient = !draft.to.trim()
  return (
    <div className="draft-workspace">
      <header className="draft-context">
        <div>
          <div className="kicker">
            {application.source === "LinkedIn Job Finder"
              ? "Imported from LinkedIn Job Finder"
              : application.source}
          </div>
          <h2>{application.title}</h2>
          <p>
            {application.company} · {application.location}
          </p>
        </div>
        <Badge
          tone={
            application.status === "Awaiting response" ? "success" : "violet"
          }
        >
          {application.status}
        </Badge>
      </header>
      {!application.email && (
        <div className="notice neutral">
          <span className="notice-symbol">@</span>
          <div>
            <strong>No email found</strong>
            <p>
              No email was found for this job. You can add a recipient manually
              or use the available application links.
            </p>
          </div>
        </div>
      )}
      {application.sourceLinks && (
        <div className="context-links">
          {application.sourceLinks.linkedin && (
            <a
              href={application.sourceLinks.linkedin}
              target="_blank"
              rel="noreferrer"
            >
              View LinkedIn Post
            </a>
          )}
          {application.sourceLinks.job && (
            <a
              href={application.sourceLinks.job}
              target="_blank"
              rel="noreferrer"
            >
              View Job
            </a>
          )}
          {application.sourceLinks.apply && (
            <a
              href={application.sourceLinks.apply}
              target="_blank"
              rel="noreferrer"
            >
              Open Apply Link
            </a>
          )}
        </div>
      )}
      <div className="editor-controls">
        <Field label="Resume">
          <Select
            value={draft.resumeId}
            onChange={(event) =>
              onChange({ ...draft, resumeId: event.target.value })
            }
          >
            {resumes.map((resume) => (
              <option key={resume.id} value={resume.id}>
                {resume.filename}
              </option>
            ))}
          </Select>
        </Field>
        <Field label="Draft type">
          <Select
            value={draft.type}
            onChange={(event) =>
              onChange({ ...draft, type: event.target.value as Draft["type"] })
            }
          >
            <option>Email</option>
            <option>Cover letter</option>
            <option>Follow-up</option>
          </Select>
        </Field>
        <Field label="Tone">
          <Select
            value={draft.tone}
            onChange={(event) =>
              onChange({ ...draft, tone: event.target.value as Draft["tone"] })
            }
          >
            <option>Professional</option>
            <option>Warm</option>
            <option>Concise</option>
          </Select>
        </Field>
      </div>
      <div className="email-editor">
        <div className="address-row">
          <label>To</label>
          <Input
            value={draft.to}
            onChange={(event) => onChange({ ...draft, to: event.target.value })}
            placeholder="Add a recipient"
          />
        </div>
        <div className="address-row">
          <label>CC</label>
          <Input
            value={draft.cc}
            onChange={(event) => onChange({ ...draft, cc: event.target.value })}
            placeholder="Optional"
          />
        </div>
        <div className="address-row">
          <label>Subject</label>
          <Input
            value={draft.subject}
            onChange={(event) =>
              onChange({ ...draft, subject: event.target.value })
            }
          />
        </div>
        <Textarea
          className="draft-body"
          value={draft.body}
          onChange={(event) => onChange({ ...draft, body: event.target.value })}
          aria-label="Draft body"
        />
      </div>
      {noRecipient && (
        <Status tone="warning">
          Add a recipient before marking this draft as sent.
        </Status>
      )}
      <footer className="editor-footer">
        <div>
          <Button icon="sparkles" onClick={onGenerate}>
            Generate draft
          </Button>
          <Button variant="ghost" icon="refresh" onClick={onGenerate}>
            Revise
          </Button>
        </div>
        <div>
          <Button onClick={onSave}>Save draft</Button>
          <Button
            variant="primary"
            icon="send"
            disabled={noRecipient}
            onClick={onSent}
          >
            Mark as sent
          </Button>
        </div>
      </footer>
    </div>
  )
}
