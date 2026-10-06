import { useCallback, useEffect, useState, type CSSProperties } from "react"
import type {
  ApplicationSummary,
  DashboardStats,
  PageName,
} from "@/types"
import {
  deleteApplication,
  errorMessage,
  fetchApplicationSource,
  fetchApplications,
  fetchLastEmail,
  statusLabel,
  statusTone,
} from "@/api"
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  Icon,
  IconButton,
  LoadingState,
  PageHeader,
} from "@/components/ui"

const PAGE_SIZE = 12

function sparklineHeights(counts: number[]): number[] {
  const peak = Math.max(...counts, 0) || 1
  return counts.map((count) => Math.floor((count / peak) * 100))
}

export default function Dashboard({
  stats,
  statsLoading,
  statsError,
  reloadStats,
  displayName,
  revision,
  navigate,
  notify,
}: {
  stats: DashboardStats | null
  statsLoading: boolean
  statsError: string | null
  reloadStats: () => void
  displayName: string
  revision: number
  navigate: (page: PageName) => void
  notify: (
    message: string,
    tone?: "neutral" | "success" | "warning" | "danger" | "violet",
  ) => void
}) {
  const [items, setItems] = useState<ApplicationSummary[]>([])
  const [totalRows, setTotalRows] = useState(0)
  const [hasMore, setHasMore] = useState(false)
  const [listLoading, setListLoading] = useState(true)
  const [listError, setListError] = useState<string | null>(null)
  const [loadingMore, setLoadingMore] = useState(false)
  const [deleting, setDeleting] = useState(false)
  const [viewer, setViewer] = useState<{
    title: string
    body: string
    meta?: string
    loading?: boolean
  } | null>(null)
  const [deleteTarget, setDeleteTarget] = useState<ApplicationSummary | null>(
    null,
  )

  const loadFirstPage = useCallback(async () => {
    setListLoading(true)
    setListError(null)
    try {
      const page = await fetchApplications(0, PAGE_SIZE)
      setItems(page.items)
      setTotalRows(page.total)
      setHasMore(page.has_more)
    } catch (cause) {
      setListError(errorMessage(cause))
    } finally {
      setListLoading(false)
    }
  }, [])

  useEffect(() => {
    void loadFirstPage()
  }, [loadFirstPage, revision])

  const loadMore = async () => {
    setLoadingMore(true)
    try {
      const page = await fetchApplications(items.length, PAGE_SIZE)
      setItems((current) => [...current, ...page.items])
      setTotalRows(page.total)
      setHasMore(page.has_more)
    } catch (cause) {
      notify(errorMessage(cause), "danger")
    } finally {
      setLoadingMore(false)
    }
  }

  const openSource = async (application: ApplicationSummary) => {
    const meta = [application.company_name, application.role]
      .filter(Boolean)
      .join(" · ")
    setViewer({
      title: "Original job details",
      body: "",
      meta: meta || undefined,
      loading: true,
    })
    try {
      const source = await fetchApplicationSource(application.id)
      setViewer({
        title: "Original job details",
        body:
          source.ocr_text.trim() ||
          "No job source is stored for this application.",
        meta: meta || undefined,
      })
    } catch (cause) {
      setViewer({
        title: "Original job details",
        body: errorMessage(cause),
        meta: meta || undefined,
      })
    }
  }

  const openLastEmail = async (application: ApplicationSummary) => {
    setViewer({
      title: `Application — ${application.role ?? ""}`.trim(),
      body: "",
      meta: undefined,
      loading: true,
    })
    try {
      const email = await fetchLastEmail(application.id)
      setViewer({
        title: `Application — ${application.role ?? ""}`.trim(),
        body: email.body || email.subject || "No email content available.",
        meta: email.recipient ? `To: ${email.recipient}` : undefined,
      })
    } catch (cause) {
      setViewer({
        title: `Application — ${application.role ?? ""}`.trim(),
        body: errorMessage(cause),
      })
    }
  }

  const confirmDelete = async () => {
    if (!deleteTarget) return
    setDeleting(true)
    try {
      await deleteApplication(deleteTarget.id)
      setDeleteTarget(null)
      notify("Application deleted", "success")
      await loadFirstPage()
      reloadStats()
    } catch (cause) {
      notify(errorMessage(cause), "danger")
    } finally {
      setDeleting(false)
    }
  }

  const total = stats?.total_applications ?? null
  const awaiting = stats?.awaiting_response ?? null
  const ready = stats?.drafts_total ?? null
  const conversations = stats?.inbox_conversations ?? null
  const weekly = stats?.weekly_applications ?? null
  const weeklyUpdated = stats?.weekly_updated ?? null
  const positive = stats
    ? stats.positive_responses + stats.shortlisted
    : null
  const successRate =
    stats && stats.total_applications
      ? Math.round(
          ((stats.positive_responses + stats.shortlisted) /
            stats.total_applications) *
            100,
        )
      : 0
  const openItems =
    ready !== null && conversations !== null && awaiting !== null
      ? ready + conversations + awaiting
      : null
  const insightTitle = stats
    ? stats.weekly_applications >= 5
      ? "You're building momentum"
      : stats.weekly_applications > 0
        ? "You're off to a good start"
        : "Time to launch your first one"
    : statsLoading
      ? "Loading insights…"
      : "Insights unavailable"
  const firstName = displayName === "…" ? "" : displayName.split(/\s+/)[0]
  const today = new Intl.DateTimeFormat("en", {
    weekday: "long",
    month: "long",
    day: "2-digit",
  }).format(new Date())
  const heights = stats ? sparklineHeights(stats.weekly_counts) : []

  return (
    <main className="content">
      <PageHeader
        eyebrow={today}
        title={firstName ? `Good morning, ${firstName}` : "Good morning"}
        description="Keep your applications moving and stay close to every opportunity."
        actions={
          <Button
            className="period-button"
            onClick={() => navigate("Sent History")}
          >
            View 30-day history <Icon name="arrow" size={13} />
          </Button>
        }
      />
      <section className="attention-panel">
        <div className="attention-heading">
          <div>
            <span className="eyebrow">Today</span>
            <h2>What needs your attention</h2>
          </div>
          {statsError && !stats ? (
            <span>
              {statsError}{" "}
              <Button variant="ghost" icon="refresh" onClick={reloadStats}>
                Retry
              </Button>
            </span>
          ) : (
            <span>
              {openItems === null ? "…" : `${openItems} open items`}
            </span>
          )}
        </div>
        <div className="attention-actions">
          <button
            className="attention-item primary"
            onClick={() => navigate("Draft Studio")}
          >
            <span className="attention-icon">
              <Icon name="document" />
            </span>
            <span>
              <strong>
                {ready === null
                  ? "…"
                  : `${ready} draft${ready === 1 ? "" : "s"} ready to review`}
              </strong>
              <small>
                Review content, recipient, and attached resume before sending.
              </small>
            </span>
            <span>
              Review drafts <Icon name="arrow" size={13} />
            </span>
          </button>
          <button
            className="attention-item"
            onClick={() => navigate("Reply Center")}
          >
            <span className="attention-icon">
              <Icon name="inbox" />
            </span>
            <span>
              <strong>
                {conversations === null
                  ? "…"
                  : `${conversations} conversation${conversations === 1 ? "" : "s"} need a response`}
              </strong>
              <small>Prioritize recruiter and interview messages.</small>
            </span>
            <Icon name="chevron" size={14} />
          </button>
          <button
            className="attention-item"
            onClick={() => navigate("Sent History")}
          >
            <span className="attention-icon">
              <Icon name="clock" />
            </span>
            <span>
              <strong>
                {awaiting === null
                  ? "…"
                  : `${awaiting} application${awaiting === 1 ? "" : "s"} awaiting response`}
              </strong>
              <small>Review what was sent before following up.</small>
            </span>
            <Icon name="chevron" size={14} />
          </button>
        </div>
      </section>
      <div className="stats-grid">
        <article className="stat-card featured">
          <div className="stat-top">
            <span className="stat-icon violet">
              <Icon name="briefcase" />
            </span>
            <span className="trend positive">
              {weekly === null ? "…" : `+${weekly} this week`}
            </span>
          </div>
          <strong className="stat-value">{total ?? "—"}</strong>
          <span className="stat-label">Total applications</span>
          <div className="sparkline">
            {heights.map((height, index) => (
              <i key={index} style={{ height: `${height}%` }} />
            ))}
          </div>
        </article>
        <article className="stat-card">
          <div className="stat-top">
            <span className="stat-icon orange">
              <Icon name="clock" />
            </span>
            <span className="stat-note">
              {stats && total
                ? `${Math.round((awaiting! / total) * 100)}% of total`
                : "…% of total"}
            </span>
          </div>
          <strong className="stat-value">{awaiting ?? "—"}</strong>
          <span className="stat-label">Awaiting response</span>
          <small>
            {weeklyUpdated === null ? "…" : `${weeklyUpdated} updated this week`}
          </small>
        </article>
        <article className="stat-card">
          <div className="stat-top">
            <span className="stat-icon blue">
              <Icon name="document" />
            </span>
            <Button variant="ghost" onClick={() => navigate("Draft Studio")}>
              Review drafts
            </Button>
          </div>
          <strong className="stat-value">{ready ?? "—"}</strong>
          <span className="stat-label">Drafts ready</span>
          <small>Ready for your review</small>
        </article>
        <article className="stat-card">
          <div className="stat-top">
            <span className="stat-icon green">
              <Icon name="trend" />
            </span>
            <span className="trend positive">
              {positive === null ? "…" : `${positive} shortlisted`}
            </span>
          </div>
          <strong className="stat-value">
            {stats ? `${successRate}%` : "—"}
          </strong>
          <span className="stat-label">Success rate</span>
          <small>
            {!stats
              ? "…"
              : positive
                ? "Positive conversations are growing"
                : "Send applications to build momentum"}
          </small>
        </article>
      </div>

      <button
        className="linkedin-dashboard-entry"
        onClick={() => navigate("LinkedIn Job Finder")}
      >
        <span className="stat-icon blue">
          <Icon name="linkedin" />
        </span>
        <span>
          <strong>Find Jobs on LinkedIn</strong>
          <small>
            Collect opportunities, filter the best matches, and draft in
            Command.
          </small>
        </span>
        <Icon name="arrow" />
      </button>

      <div className="dashboard-grid">
        <section className="card applications-card">
          <header className="card-header">
            <div>
              <h2>Recent applications</h2>
              <p>Your latest outreach and activity</p>
            </div>
            <Button variant="ghost" onClick={() => navigate("Sent History")}>
              View all {listLoading ? "…" : totalRows}
            </Button>
          </header>
          {listLoading ? (
            <LoadingState label="Loading applications…" />
          ) : listError ? (
            <EmptyState
              icon="warning"
              title="Couldn't load applications."
              description={listError}
              action={
                <Button icon="refresh" onClick={() => void loadFirstPage()}>
                  Retry
                </Button>
              }
            />
          ) : items.length ? (
            <>
              <div className="table-head application-columns">
                <span>Company &amp; role</span>
                <span>Status</span>
                <span>Last activity</span>
                <span />
              </div>
              <div id="applicationList">
                {items.map((application) => {
                  const company = application.company_name?.trim() || "—"
                  const role = application.role?.trim() || "—"
                  const label = statusLabel(application.status)
                  return (
                    <div
                      className="application-row application-columns"
                      data-search={`${company} ${role} ${label}`}
                      key={application.id}
                    >
                      <div className="company-cell">
                        <span className="company-mark">
                          {company
                            .split(" ")
                            .map((word) => word[0])
                            .join("")
                            .slice(0, 2)
                            .toUpperCase()}
                        </span>
                        <span>
                          <strong>{company}</strong>
                          <small>{role}</small>
                        </span>
                      </div>
                      <Badge tone={statusTone(application.status)}>
                        {label}
                      </Badge>
                      <time>{application.updated_label}</time>
                      <div className="row-actions">
                        <IconButton
                          icon="eye"
                          label="View source"
                          onClick={() => void openSource(application)}
                        />
                        <IconButton
                          icon="mail"
                          label="View last email"
                          onClick={() => void openLastEmail(application)}
                        />
                        <IconButton
                          icon="trash"
                          label="Delete application"
                          className="icon-button-danger"
                          onClick={() => setDeleteTarget(application)}
                        />
                      </div>
                    </div>
                  )
                })}
              </div>
              {hasMore && (
                <footer className="list-footer">
                  <span>
                    Showing {items.length} of {totalRows}
                  </span>
                  <Button
                    busy={loadingMore}
                    disabled={loadingMore}
                    onClick={() => void loadMore()}
                  >
                    Load more
                  </Button>
                </footer>
              )}
            </>
          ) : (
            <EmptyState
              icon="inbox"
              title="No applications yet."
              description="Add your first application to start building your workspace."
              action={
                <Button
                  variant="primary"
                  onClick={() => navigate("Add Application")}
                >
                  Add your first application
                </Button>
              }
            />
          )}
        </section>
        <aside className="card insights-card">
          <header>
            <div>
              <span className="eyebrow">Smart insights</span>
              <h2>{insightTitle}</h2>
            </div>
            <small>Updated just now</small>
          </header>
          <div
            className="weekly-ring"
            style={
              {
                "--ring-progress": stats
                  ? `${Math.min(100, (stats.weekly_applications / 15) * 100)}%`
                  : "0%",
              } as CSSProperties
            }
          >
            <span>
              <strong>{weekly ?? "—"}</strong>
              <small>this week</small>
            </span>
          </div>
          <p>
            {!stats ? (
              statsError ? (
                "Stats could not be loaded right now."
              ) : (
                "…"
              )
            ) : stats.weekly_applications ? (
              "Keep reviewing drafts and following up while the details are fresh."
            ) : (
              "Launch an application or discover a role to begin."
            )}
          </p>
          <div className="insight-metrics">
            <div>
              <span>Applications</span>
              <strong>{weekly ?? "—"}</strong>
            </div>
            <div>
              <span>Shortlisted</span>
              <strong>{positive ?? "—"}</strong>
            </div>
            <div>
              <span>Drafts waiting</span>
              <strong>{ready ?? "—"}</strong>
            </div>
          </div>
          <Button
            className="insight-button"
            onClick={() => navigate("Reply Center")}
          >
            Explore replies <Icon name="arrow" size={13} />
          </Button>
        </aside>
      </div>
      <Dialog
        open={Boolean(viewer)}
        onClose={() => setViewer(null)}
        title={viewer?.title ?? "Loading…"}
        description={viewer?.meta}
      >
        <div className="email-body">
          {viewer?.loading ? "Loading…" : viewer?.body}
        </div>
      </Dialog>
      <Dialog
        open={Boolean(deleteTarget)}
        onClose={() => setDeleteTarget(null)}
        title="Delete this application?"
        description="This removes the application and its related drafts."
        footer={
          <>
            <Button onClick={() => setDeleteTarget(null)}>Cancel</Button>
            <Button
              variant="danger"
              busy={deleting}
              disabled={deleting}
              onClick={() => void confirmDelete()}
            >
              Delete
            </Button>
          </>
        }
      >
        This action cannot be undone.
      </Dialog>
    </main>
  )
}
