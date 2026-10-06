import { useEffect, useState } from "react"
import {
  errorMessage,
  fetchCampaignItems,
  fetchCampaignProgress,
  pauseCampaign,
  resumeCampaign,
  retryCampaign,
  retryFailedCampaignItems,
  startCampaign,
} from "@/api"
import type { Campaign, CampaignListResponse } from "@/types"
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  Field,
  Icon,
  Input,
  PageHeader,
  Select,
  Textarea,
} from "@/components/ui"

const capitalize = (value: string) =>
  value ? value.charAt(0).toUpperCase() + value.slice(1) : value

type DisplayCampaign = Campaign & { headerRow?: number }

function mapCampaign(item: CampaignListResponse["items"][number]): DisplayCampaign {
  return {
    id: String(item.id),
    name: item.name,
    sheetUrl: item.sheet_url ?? "",
    createdAt: item.created_at,
    status: capitalize(item.status) as Campaign["status"],
    sent: item.sent,
    total: item.total,
    targetRole: item.target_role,
    dailyLimit: item.daily_limit ?? undefined,
    headerRow: item.header_row,
    items: [],
  }
}

export default function Outreach({
  data,
  loading,
  error,
  reload,
  notify,
}: {
  data: CampaignListResponse | null
  loading: boolean
  error: string | null
  reload: () => void
  notify: (
    message: string,
    tone?: "neutral" | "success" | "warning" | "danger" | "violet",
  ) => void
}) {
  const [newOpen, setNewOpen] = useState(false)
  const [details, setDetails] = useState<DisplayCampaign | null>(null)
  const [detailItems, setDetailItems] = useState<Campaign["items"] | null>(null)
  const [detailError, setDetailError] = useState<string | null>(null)
  const [retry, setRetry] = useState<DisplayCampaign | null>(null)
  const [form, setForm] = useState({
    name: "",
    url: "",
    header: "1",
    role: "",
    instructions: "",
    limit: "",
  })
  const [progress, setProgress] = useState<
    Record<string, { sent: number; total: number; status: string }>
  >({})
  const base = (data?.items ?? []).map(mapCampaign)
  const campaigns = base.map((item) => {
    // Live progress only applies while the campaign is still running; once the
    // list refresh shows a terminal state (completed) the server data wins so
    // a stale snapshot can never mask the final status.
    const snapshot = progress[item.id]
    return snapshot && item.status === "Active"
      ? {
          ...item,
          sent: snapshot.sent,
          total: snapshot.total,
          status: snapshot.status as Campaign["status"],
        }
      : item
  })
  const sentToday = data?.sent_today ?? 0

  useEffect(() => {
    const running = (data?.items ?? []).filter(
      (item) => item.status === "active" || item.status === "paused",
    )
    if (!running.length) return
    let alive = true
    const tick = async () => {
      for (const item of running) {
        try {
          const snapshot = await fetchCampaignProgress(item.id)
          if (!alive) return
          setProgress((current) => ({
            ...current,
            [String(item.id)]: {
              sent: snapshot.sent,
              total: snapshot.total,
              status: capitalize(snapshot.status),
            },
          }))
          if (snapshot.status !== item.status) {
            reload()
            return
          }
        } catch {
          // Transient network hiccup: retry on the next tick (legacy parity).
        }
      }
    }
    void tick()
    const interval = window.setInterval(() => void tick(), 5000)
    return () => {
      alive = false
      window.clearInterval(interval)
    }
  }, [data, reload])

  const updateStatus = async (id: string, status: Campaign["status"]) => {
    try {
      if (status === "Paused") await pauseCampaign(Number(id))
      else await resumeCampaign(Number(id))
      notify(
        status === "Paused" ? "Campaign paused." : "Campaign resumed.",
        "success",
      )
      reload()
    } catch (cause: unknown) {
      notify(errorMessage(cause), "danger")
    }
  }
  const openDetails = (campaign: DisplayCampaign) => {
    setDetails(campaign)
    setDetailItems(null)
    setDetailError(null)
    fetchCampaignItems(Number(campaign.id))
      .then((rows) =>
        setDetailItems(
          rows.map((row) => ({
            id: String(row.id),
            recipient: row.recipient_name || row.recipient_email || "Unknown",
            company: row.company || "—",
            status:
              row.status === "sent"
                ? "Sent"
                : row.status === "error"
                  ? "Error"
                  : "Pending",
            sentAt: row.sent_at ? new Date(row.sent_at).toLocaleString() : "—",
            error: row.error_msg || undefined,
          })),
        ),
      )
      .catch((cause: unknown) => setDetailError(errorMessage(cause)))
  }
  const start = async () => {
    if (!form.name.trim() || !form.url.trim()) {
      notify("Missing details", "danger")
      return
    }
    try {
      await startCampaign({
        name: form.name.trim(),
        sheet_url: form.url.trim(),
        header_row: parseInt(form.header, 10) || 1,
        context1: form.role.trim(),
        context2: form.instructions.trim(),
        daily_limit: Number(form.limit) || undefined,
      })
      setNewOpen(false)
      notify("Campaign started.", "success")
      reload()
    } catch (cause: unknown) {
      notify(errorMessage(cause), "danger")
    }
  }
  return (
    <main className="content">
      <PageHeader
        eyebrow="Outreach"
        title="Build meaningful connections"
        description="Run focused outreach campaigns from published contact sheets."
        actions={
          <Button variant="primary" icon="add" onClick={() => setNewOpen(true)}>
            New campaign
          </Button>
        }
      />
      <div className="stat-strip">
        <div>
          <span>Sent today</span>
          <strong className="text-green">{sentToday}</strong>
        </div>
        <div>
          <span>Total campaigns</span>
          <strong>{campaigns.length}</strong>
        </div>
        <div>
          <span>Running now</span>
          <strong>
            {campaigns.filter((item) => item.status === "Active").length}
          </strong>
        </div>
        <div>
          <span>Paused</span>
          <strong>
            {campaigns.filter((item) => item.status === "Paused").length}
          </strong>
        </div>
      </div>
      {loading && !data ? (
        <EmptyState
          icon="send"
          title="Loading campaigns"
          description="Fetching your outreach campaigns..."
        />
      ) : error ? (
        <EmptyState
          icon="send"
          title="Campaigns unavailable"
          description={error}
          action={
            <Button variant="primary" onClick={reload}>
              Try again
            </Button>
          }
        />
      ) : campaigns.length ? (
        <div className="campaign-stack">
          {campaigns.map((campaign) => {
            const pct = campaign.total
              ? Math.round((campaign.sent / campaign.total) * 100)
              : 0
            const tone =
              campaign.status === "Active"
                ? "success"
                : campaign.status === "Paused"
                  ? "warning"
                  : campaign.status === "Error"
                    ? "danger"
                    : "violet"
            return (
              <article
                className="campaign-card card"
                data-search={`${campaign.name} ${campaign.targetRole}`}
                key={campaign.id}
              >
                <header>
                  <div>
                    <h2>{campaign.name}</h2>
                    <p>Created {campaign.createdAt}</p>
                  </div>
                  <div>
                    <strong>
                      {campaign.sent} / {campaign.total}
                    </strong>
                    <small>emails sent</small>
                  </div>
                </header>
                <div
                  className={`progress-track campaign-${campaign.status.toLowerCase()}`}
                >
                  <span style={{ width: `${pct}%` }} />
                </div>
                <div className="campaign-meta">
                  <Badge tone={tone}>{campaign.status}</Badge>
                  <span>{pct}% completed</span>
                </div>
                <div className="campaign-next">
                  <Icon
                    name={
                      campaign.status === "Active"
                        ? "activity"
                        : campaign.status === "Paused"
                          ? "pause"
                          : campaign.sent < campaign.total
                            ? "refresh"
                            : "check"
                    }
                    size={14}
                  />
                  <span>
                    <strong>
                      {campaign.status === "Active"
                        ? "Sending is in progress"
                        : campaign.status === "Paused"
                          ? "Campaign is paused"
                          : campaign.sent < campaign.total
                            ? `${campaign.total - campaign.sent} contacts need attention`
                            : "Campaign is complete"}
                    </strong>
                    <small>
                      {campaign.status === "Active"
                        ? "Progress updates automatically. Pause only if you need to change the source sheet."
                        : campaign.status === "Paused"
                          ? "Resume when the source sheet is ready."
                          : campaign.sent < campaign.total
                            ? "Review details or retry failed recipients."
                            : "Open details to review delivery history."}
                    </small>
                  </span>
                </div>
                <footer>
                  {campaign.total === 0 && campaign.status === "Completed" && (
                    <Button icon="refresh" onClick={() => setRetry(campaign)}>
                      Retry
                    </Button>
                  )}
                  {campaign.status === "Completed" &&
                    campaign.sent < campaign.total && (
                      <Button
                        icon="refresh"
                        onClick={() => {
                          retryFailedCampaignItems(Number(campaign.id))
                            .then(() => {
                              notify("Retrying failed recipients.", "violet")
                              reload()
                            })
                            .catch((cause: unknown) =>
                              notify(errorMessage(cause), "danger"),
                            )
                        }}
                      >
                        Retry failed
                      </Button>
                    )}
                  {campaign.status === "Active" && (
                    <Button
                      icon="pause"
                      onClick={() => updateStatus(campaign.id, "Paused")}
                    >
                      Pause
                    </Button>
                  )}
                  {campaign.status === "Paused" && (
                    <Button
                      icon="play"
                      onClick={() => updateStatus(campaign.id, "Active")}
                    >
                      Resume
                    </Button>
                  )}
                  <Button
                    icon="external"
                    onClick={() =>
                      window.open(
                        campaign.sheetUrl,
                        "_blank",
                        "noopener,noreferrer",
                      )
                    }
                  >
                    Sheet
                  </Button>
                  <Button onClick={() => openDetails(campaign)}>
                    Details
                  </Button>
                </footer>
              </article>
            )
          })}
        </div>
      ) : (
        <EmptyState
          icon="send"
          title="No campaigns yet"
          description="Start an outreach campaign from a published contact sheet."
          action={
            <Button variant="primary" onClick={() => setNewOpen(true)}>
              Start outreach
            </Button>
          }
        />
      )}
      <Dialog
        open={newOpen}
        onClose={() => setNewOpen(false)}
        title="New campaign"
        description="Publish your sheet first: File → Share → Publish to web → CSV."
        footer={
          <>
            <Button onClick={() => setNewOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={start}>
              Start campaign
            </Button>
          </>
        }
      >
        <div className="form-stack">
          <Field label="Campaign name" required>
            <Input
              value={form.name}
              onChange={(event) =>
                setForm({ ...form, name: event.target.value })
              }
            />
          </Field>
          <Field label="Sheet URL" required>
            <Input
              type="url"
              value={form.url}
              onChange={(event) =>
                setForm({ ...form, url: event.target.value })
              }
              placeholder="Published CSV URL"
            />
          </Field>
          <div className="form-row">
            <Field label="Header row">
              <Input
                type="number"
                min="1"
                value={form.header}
                onChange={(event) =>
                  setForm({ ...form, header: event.target.value })
                }
              />
            </Field>
            <Field label="Daily limit" optional>
              <Input
                type="number"
                min="1"
                value={form.limit}
                onChange={(event) =>
                  setForm({ ...form, limit: event.target.value })
                }
              />
            </Field>
          </div>
          <Field label="Target role / vacancy">
            <Input
              value={form.role}
              onChange={(event) =>
                setForm({ ...form, role: event.target.value })
              }
            />
          </Field>
          <Field label="Additional instructions" optional>
            <Textarea
              rows={4}
              value={form.instructions}
              onChange={(event) =>
                setForm({ ...form, instructions: event.target.value })
              }
            />
          </Field>
        </div>
      </Dialog>
      <Dialog
        open={Boolean(details)}
        onClose={() => setDetails(null)}
        title={details?.name ?? "Loading…"}
        description="Campaign delivery details"
      >
        <div className="table-container">
          {detailError ? (
            <p className="error-copy">{detailError}</p>
          ) : detailItems === null ? (
            <p className="muted">Loading…</p>
          ) : detailItems.length === 0 ? (
            <p className="muted">No recipients found in this sheet.</p>
          ) : (
            <table>
              <thead>
                <tr>
                  <th>Recipient</th>
                  <th>Company</th>
                  <th>Status</th>
                  <th>Sent at</th>
                </tr>
              </thead>
              <tbody>
                {detailItems.slice(0, 200).map((item) => (
                  <tr key={item.id}>
                    <td>{item.recipient}</td>
                    <td>{item.company}</td>
                    <td>
                      <Badge
                        tone={
                          item.status === "Sent"
                            ? "success"
                            : item.status === "Error"
                              ? "danger"
                              : "neutral"
                        }
                      >
                        {item.status}
                      </Badge>
                      {item.error && (
                        <small className="error-copy">{item.error}</small>
                      )}
                    </td>
                    <td>{item.sentAt}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
          {detailItems && detailItems.length > 200 && (
            <p>Showing the first 200 recipients.</p>
          )}
        </div>
      </Dialog>
      <Dialog
        open={Boolean(retry)}
        onClose={() => setRetry(null)}
        title="Retry campaign"
        description="Confirm the sheet header row before retrying."
        footer={
          <>
            <Button onClick={() => setRetry(null)}>Cancel</Button>
            <Button
              variant="primary"
              onClick={() => {
                if (retry) {
                  const header = document.getElementById(
                    "retryHeaderRow",
                  ) as HTMLSelectElement | null
                  const headerRow = parseInt(header?.value ?? "1", 10) || 1
                  retryCampaign(Number(retry.id), headerRow)
                    .then(() => {
                      notify("Campaign retried.", "success")
                      reload()
                    })
                    .catch((cause: unknown) =>
                      notify(errorMessage(cause), "danger"),
                    )
                }
                setRetry(null)
              }}
            >
              Retry
            </Button>
          </>
        }
      >
        <Field label="Header row">
          <Select
            id="retryHeaderRow"
            defaultValue={
              retry?.headerRow != null && retry.headerRow >= 1 && retry.headerRow <= 3
                ? String(retry.headerRow)
                : "1"
            }
          >
            <option>1</option>
            <option>2</option>
            <option>3</option>
          </Select>
        </Field>
      </Dialog>
    </main>
  )
}
