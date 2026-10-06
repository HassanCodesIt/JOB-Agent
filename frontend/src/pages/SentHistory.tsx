import { useState } from "react"
import { fetchSentEmail, fetchSentEmails } from "@/api"
import { useAsync } from "@/hooks/useAsync"
import type { PageName, SentEmailDetail, SentEmailItem } from "@/types"
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  Icon,
  LoadingState,
  PageHeader,
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

interface DetailState {
  loading: boolean
  error: string | null
  detail: SentEmailDetail | null
}

export default function SentHistory({
  navigate,
}: {
  navigate: (page: PageName) => void
}) {
  const history = useAsync(() => fetchSentEmails(60))
  const [selected, setSelected] = useState<SentEmailItem | null>(null)
  const [detail, setDetail] = useState<DetailState>({
    loading: false,
    error: null,
    detail: null,
  })

  const open = (item: SentEmailItem) => {
    setSelected(item)
    setDetail({ loading: true, error: null, detail: null })
    fetchSentEmail(item.id)
      .then((value) => setDetail({ loading: false, error: null, detail: value }))
      .catch((cause: unknown) =>
        setDetail({
          loading: false,
          error: cause instanceof Error ? cause.message : "Something went wrong.",
          detail: null,
        }),
      )
  }

  const items = history.data?.items ?? []
  const total = history.data?.total ?? 0
  const confirmed = history.data?.confirmed ?? 0
  const recent = items

  if (history.loading && !history.data) {
    return (
      <main className="content">
        <PageHeader
          eyebrow="Sent history"
          title="Everything you've delivered"
          description="Review emails, applications, and outreach sent through Command."
        />
        <LoadingState label="Loading sent history…" />
      </main>
    )
  }

  if (history.error && !history.data) {
    return (
      <main className="content">
        <PageHeader
          eyebrow="Sent history"
          title="Everything you've delivered"
          description="Review emails, applications, and outreach sent through Command."
        />
        <EmptyState
          icon="warning"
          title="Could not load sent history"
          description={history.error}
          action={<Button onClick={history.reload}>Retry</Button>}
        />
      </main>
    )
  }

  return (
    <main className="content">
      <PageHeader
        eyebrow="Sent history"
        title="Everything you've delivered"
        description="Review emails, applications, and outreach sent through Command."
        actions={
          <Button
            variant="primary"
            icon="add"
            onClick={() => navigate("Add Application")}
          >
            Add application
          </Button>
        }
      />
      <div className="stat-strip three">
        <div>
          <span>Emails delivered</span>
          <strong>{total}</strong>
        </div>
        <div>
          <span>Confirmed sent</span>
          <strong className="text-green">{confirmed}</strong>
        </div>
        <div>
          <span>Shown below</span>
          <strong>{recent.length}</strong>
        </div>
      </div>
      {recent.length ? (
        <section className="card list-rows">
          {recent.map((item) => (
            <button
              className="mail-row sent-row"
              data-search={`${item.company_name ?? ""} ${item.role ?? ""} ${item.subject}`}
              key={item.id}
              onClick={() => open(item)}
            >
              <span className="company-mark">
                {(item.company_name || item.recipient_email || "NA")[0]}
              </span>
              <span className="mail-copy">
                <strong>
                  {item.subject ||
                    (item.role ? `Email — ${item.role}` : "Email")}
                </strong>
                <small>
                  {item.recipient_email || "Unknown recipient"}
                  {item.company_name ? ` · ${item.company_name}` : ""}
                </small>
              </span>
              <Badge tone="success">
                {item.status === "sent"
                  ? "Sent"
                  : item.status.charAt(0).toUpperCase() + item.status.slice(1)}
              </Badge>
              <time>{formatDate(item.sent_at)}</time>
              <Icon name="eye" size={15} />
            </button>
          ))}
          {total > recent.length && (
            <div className="list-footer">
              Showing the latest {recent.length} of {total} emails.
            </div>
          )}
        </section>
      ) : (
        <EmptyState
          icon="send"
          title="No sent history yet"
          description="Send an application or review pending drafts to build your history."
          action={
            <Button onClick={() => navigate("Draft Studio")}>
              Review pending drafts
            </Button>
          }
        />
      )}
      <Dialog
        open={Boolean(selected)}
        onClose={() => setSelected(null)}
        title={
          selected?.subject ||
          (selected
            ? selected.role
              ? `Email — ${selected.role}`
              : "Email"
            : "Loading…")
        }
        description={
          selected
            ? `To: ${selected.recipient_email || "Unknown recipient"} · Sent ${formatDate(selected.sent_at)}`
            : undefined
        }
      >
        <div className="email-meta">
          <span>Company</span>
          <strong>{selected?.company_name || "—"}</strong>
        </div>
        <div className="email-body">
          {detail.loading && <span>Loading message…</span>}
          {!detail.loading && detail.error && (
            <span className="form-note err">{detail.error}</span>
          )}
          {!detail.loading && !detail.error && detail.detail?.body}
        </div>
      </Dialog>
    </main>
  )
}
