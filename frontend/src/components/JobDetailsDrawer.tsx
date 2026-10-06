import { useEffect, useRef, useState } from "react"
import type { LinkedInJob } from "@/types"
import { Badge, Button, Drawer, Icon, Status } from "./ui"

export function JobSourceActions({
  job,
  onImage,
  compact = false,
}: {
  job: LinkedInJob
  onImage: () => void
  compact?: boolean
}) {
  const open = (url?: string) =>
    url && window.open(url, "_blank", "noopener,noreferrer")
  return (
    <div className={`source-actions ${compact ? "compact" : ""}`}>
      {job.links.linkedin && (
        <Button
          variant="ghost"
          icon="external"
          onClick={() => open(job.links.linkedin)}
        >
          View LinkedIn Post
        </Button>
      )}
      {job.links.job && (
        <Button
          variant="ghost"
          icon="external"
          onClick={() => open(job.links.job)}
        >
          View Job
        </Button>
      )}
      {job.links.apply && (
        <Button
          variant="ghost"
          icon="external"
          onClick={() => open(job.links.apply)}
        >
          Open Apply Link
        </Button>
      )}
      {job.links.image && (
        <Button variant="ghost" icon="image" onClick={onImage}>
          View Job Image
        </Button>
      )}
    </div>
  )
}

export function JobSourceMenu({
  job,
  onImage,
}: {
  job: LinkedInJob
  onImage: () => void
}) {
  const [open, setOpen] = useState(false)
  const menuRef = useRef<HTMLDivElement>(null)
  const sources = [
    { label: "LinkedIn post", url: job.links.linkedin },
    { label: "Job page", url: job.links.job },
    { label: "Apply link", url: job.links.apply },
  ].filter((item) => item.url)
  const hasSources = sources.length > 0 || Boolean(job.links.image)

  useEffect(() => {
    if (!open) return
    const dismiss = (event: MouseEvent) => {
      if (!menuRef.current?.contains(event.target as Node)) setOpen(false)
    }
    const key = (event: KeyboardEvent) => {
      if (event.key === "Escape") setOpen(false)
    }
    document.addEventListener("mousedown", dismiss)
    window.addEventListener("keydown", key)
    return () => {
      document.removeEventListener("mousedown", dismiss)
      window.removeEventListener("keydown", key)
    }
  }, [open])

  if (!hasSources) return null
  return (
    <div className="source-menu" ref={menuRef}>
      <Button
        variant="ghost"
        icon="external"
        aria-expanded={open}
        aria-haspopup="menu"
        onClick={() => setOpen((value) => !value)}
      >
        Open source
      </Button>
      {open && (
        <div className="source-menu-popover" role="menu">
          {sources.map((source) => (
            <button
              key={source.label}
              role="menuitem"
              onClick={() => {
                window.open(source.url, "_blank", "noopener,noreferrer")
                setOpen(false)
              }}
            >
              <Icon name="external" size={14} />
              {source.label}
            </button>
          ))}
          {job.links.image && (
            <button
              role="menuitem"
              onClick={() => {
                onImage()
                setOpen(false)
              }}
            >
              <Icon name="image" size={14} />
              Job image
            </button>
          )}
        </div>
      )}
    </div>
  )
}

export function JobDetailsDrawer({
  job,
  onClose,
  onDraft,
  onImage,
}: {
  job: LinkedInJob | null
  onClose: () => void
  onDraft: (job: LinkedInJob) => void
  onImage: (job: LinkedInJob) => void
}) {
  const tone =
    job?.filterStatus === "Accepted"
      ? "success"
      : job?.filterStatus === "Rejected"
        ? "danger"
        : job?.filterStatus === "Needs Review"
          ? "warning"
          : "neutral"
  return (
    <Drawer
      open={Boolean(job)}
      onClose={onClose}
      title={job?.title ?? ""}
      description={job ? job.company : ""}
      footer={
        job && (
          <div className="drawer-action-row">
            <JobSourceActions job={job} onImage={() => onImage(job)} compact />
            <Button
              variant="primary"
              icon="sparkles"
              onClick={() => onDraft(job)}
            >
              Draft & Apply
            </Button>
          </div>
        )
      }
    >
      {job && (
        <>
          <div className="job-drawer-identity">
            <span className="company-mark">
              {job.company
                .split(" ")
                .map((word) => word[0])
                .join("")
                .slice(0, 2)}
            </span>
            <div>
              <Status tone={job.email ? "success" : "neutral"}>
                {job.email || "No email"}
              </Status>
              <Badge tone={tone}>{job.filterStatus}</Badge>
            </div>
          </div>
          {!job.email && (
            <div className="notice neutral">
              <Icon name="mail" />
              <div>
                <strong>No email found</strong>
                <p>
                  Add a recipient manually to send, or use the available
                  LinkedIn/apply links.
                </p>
              </div>
            </div>
          )}
          <dl className="detail-grid">
            <div>
              <dt>Location</dt>
              <dd>{job.location}</dd>
            </div>
            <div>
              <dt>Experience</dt>
              <dd>{job.experience}</dd>
            </div>
            <div>
              <dt>Employment type</dt>
              <dd>{job.employmentType}</dd>
            </div>
            <div>
              <dt>Salary</dt>
              <dd>{job.salary || "Not listed"}</dd>
            </div>
            <div className="detail-wide">
              <dt>Application methods</dt>
              <dd>{job.methods.join(", ")}</dd>
            </div>
          </dl>
          <div className="drawer-section">
            <h3>Job Description</h3>
            <p>{job.fullText || job.description}</p>
          </div>
          {job.skills.length > 0 && (
            <div className="drawer-section">
              <h3>Skills</h3>
              <div className="tag-list">
                {job.skills.map((skill) => (
                  <span key={skill}>{skill}</span>
                ))}
              </div>
            </div>
          )}
          {job.responsibilities.length > 0 && (
            <div className="drawer-section">
              <h3>Responsibilities</h3>
              <ul>
                {job.responsibilities.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
          {job.qualifications.length > 0 && (
            <div className="drawer-section">
              <h3>Qualifications</h3>
              <ul>
                {job.qualifications.map((item) => (
                  <li key={item}>{item}</li>
                ))}
              </ul>
            </div>
          )}
        </>
      )}
    </Drawer>
  )
}
