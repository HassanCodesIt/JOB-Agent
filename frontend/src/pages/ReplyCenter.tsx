import { useEffect, useMemo, useRef, useState } from "react"
import { errorMessage, fetchEmailEvents, generateReply, sendReply, statusLabel } from "@/api"
import { useAsync } from "@/hooks/useAsync"
import type { EmailEventListResponse, PageName } from "@/types"
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  Icon,
  Input,
  LoadingState,
  PageHeader,
  Tabs,
  Textarea,
} from "@/components/ui"

interface Conversation {
  id: number
  applicationId: number | null
  sender: string
  email: string
  company: string
  role: string
  subject: string
  body: string
  time: string
  status: "Shortlisted" | "Follow-up"
  appStatus: string | null
  positive: boolean
  linked: boolean
}

function splitSender(raw: string): string {
  return (raw.includes("<") ? raw.split("<")[0] : raw).trim()
}

function senderEmail(raw: string, fallback: string): string {
  const match = raw.match(/<([^>]+)>/)
  return match ? match[1].trim() : fallback
}

function formatReceived(raw: string): string {
  if (!raw) return ""
  const normalized = raw.replace(" ", "T").replace(/(\.\d+)\d*/, "$1")
  const date = new Date(normalized)
  if (Number.isNaN(date.getTime())) return raw
  const now = new Date()
  const sameDay =
    date.getFullYear() === now.getFullYear() &&
    date.getMonth() === now.getMonth() &&
    date.getDate() === now.getDate()
  if (sameDay)
    return date.toLocaleTimeString("en-US", {
      hour: "2-digit",
      minute: "2-digit",
    })
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

export default function ReplyCenter({
  onSync,
  notify,
  navigate,
  revision,
}: {
  onSync: () => void
  navigate: (page: PageName) => void
  revision: number
  notify: (
    message: string,
    tone?: "neutral" | "success" | "warning" | "danger" | "violet",
  ) => void
}) {
  const inbox = useAsync<EmailEventListResponse>(() => fetchEmailEvents(100))
  const [selected, setSelected] = useState<Conversation | null>(null)
  const [unlinkedOpen, setUnlinkedOpen] = useState(false)
  const [draftVisible, setDraftVisible] = useState(false)
  const [generating, setGenerating] = useState(false)
  const [sending, setSending] = useState(false)
  const [instructions, setInstructions] = useState("")
  const [recipient, setRecipient] = useState("")
  const [subject, setSubject] = useState("")
  const [content, setContent] = useState("")
  const [status, setStatus] = useState<{
    title: string
    message: string
    success: boolean
  } | null>(null)
  const sendingRef = useRef(false)

  const reloadInbox = inbox.reload
  const mountedRevision = useRef(revision)
  useEffect(() => {
    if (revision === mountedRevision.current) return
    mountedRevision.current = revision
    reloadInbox()
  }, [revision, reloadInbox])

  const conversations = useMemo<Conversation[]>(
    () =>
      (inbox.data?.items ?? []).map((item) => {
        const linked = item.application_id != null && item.company_name != null
        const positive = item.classification === "positive"
        return {
          id: item.id,
          applicationId: linked ? item.application_id : null,
          sender: splitSender(item.sender),
          email: senderEmail(item.sender, linked ? item.contact_email : ""),
          company: item.company_name ?? "",
          role: item.role ?? "",
          subject: item.subject,
          body: item.snippet,
          time: formatReceived(item.received_at),
          status: positive ? ("Shortlisted" as const) : ("Follow-up" as const),
          appStatus: item.app_status,
          positive,
          linked,
        }
      }),
    [inbox.data],
  )

  const shortlisted = conversations.filter((item) => item.positive).length
  const related = conversations.filter(
    (item) => item.linked && !item.positive,
  ).length
  const unlinked = conversations.filter((item) => !item.linked).length
  const [filter, setFilter] = useState("Needs attention")
  const visibleReplies = conversations.filter((item) =>
    filter === "Unlinked" ? !item.linked : true,
  )

  const open = (reply: Conversation) => {
    if (!reply.linked) {
      setUnlinkedOpen(true)
      return
    }
    setSelected(reply)
    setDraftVisible(false)
    setRecipient(reply.email)
    setSubject(`RE: ${reply.subject}`)
    setContent("")
  }
  const generate = () => {
    if (!selected || generating) return
    setGenerating(true)
    generateReply(
      Number(selected.applicationId),
      instructions.trim() || null,
    )
      .then((value) => {
        if (value.error) {
          notify(value.detail ?? "The model could not draft a reply.", "danger")
          return
        }
        if (value.subject) setSubject(value.subject)
        setContent(value.body ?? "")
        setDraftVisible(true)
        notify("Reply drafted", "success")
      })
      .catch((cause: unknown) => notify(errorMessage(cause), "danger"))
      .finally(() => setGenerating(false))
  }
  const send = () => {
    if (!selected) return
    if (!recipient.trim()) {
      setStatus({
        title: "Missing recipient",
        message: "Add a recipient before sending this reply.",
        success: false,
      })
      return
    }
    if (!content.trim()) {
      setStatus({
        title: "Nothing to send",
        message: "Write or generate a reply before sending.",
        success: false,
      })
      return
    }
    if (sendingRef.current) return
    sendingRef.current = true
    setSending(true)
    sendReply({
      app_id: Number(selected.applicationId),
      recipient: recipient.trim(),
      subject,
      content,
    })
      .then(() => {
        setStatus({
          title: "Reply sent",
          message: "Your reply was marked as sent from the active account.",
          success: true,
        })
        window.setTimeout(() => {
          setSelected(null)
          setDraftVisible(false)
        }, 1800)
      })
      .catch((cause: unknown) =>
        setStatus({
          title: "Delivery failed",
          message: errorMessage(cause),
          success: false,
        }),
      )
      .finally(() => {
        sendingRef.current = false
        setSending(false)
      })
  }

  if (inbox.loading && !inbox.data) {
    return (
      <main className="content">
        <PageHeader
          eyebrow="Reply center"
          title="Inbox zero starts here"
          description="Review job-related conversations and respond from one focused workspace."
        />
        <LoadingState label="Loading conversations…" />
      </main>
    )
  }

  if (inbox.error && !inbox.data) {
    return (
      <main className="content">
        <PageHeader
          eyebrow="Reply center"
          title="Inbox zero starts here"
          description="Review job-related conversations and respond from one focused workspace."
        />
        <EmptyState
          icon="warning"
          title="Could not load conversations"
          description={inbox.error}
          action={<Button onClick={inbox.reload}>Retry</Button>}
        />
      </main>
    )
  }

  if (selected)
    return (
      <main className="content">
        <PageHeader
          eyebrow="Conversation"
          title={selected.company}
          description={`${selected.role} · ${selected.email}`}
          actions={
            <Button className="period-button" onClick={() => setSelected(null)}>
              <Icon name="back" size={13} />
              Back to reply center
            </Button>
          }
        />
        <div className="conversation-layout">
          <section className="card chat-container">
            <header className="card-header">
              <div>
                <h2>Conversation history</h2>
                <p>Started {selected.time}</p>
              </div>
              <Badge tone={selected.positive ? "success" : "neutral"}>
                {selected.status}
              </Badge>
            </header>
            <div id="chatHistory">
              <article className="message received">
                <div>
                  <strong>{selected.sender}</strong>
                  <time>{selected.time}</time>
                </div>
                <p>{selected.body}</p>
              </article>
              {draftVisible && content && (
                <article className="message sent">
                  <div>
                    <strong>ME</strong>
                    <time>Draft</time>
                  </div>
                  <p>{content}</p>
                </article>
              )}
            </div>
          </section>
          <div className="reply-column">
            {draftVisible && (
              <section className="compose-card card reply-draft-area">
                <header className="compose-head">
                  <span className="stat-icon violet">
                    <Icon name="sparkles" />
                  </span>
                  <div>
                    <h2>AI drafted reply</h2>
                    <p>Review, refine, then send</p>
                  </div>
                  <Badge tone="violet">Draft</Badge>
                </header>
                <div className="compose-fields">
                  <div className="address-row">
                    <label>To</label>
                    <Input
                      value={recipient}
                      onChange={(event) => setRecipient(event.target.value)}
                    />
                  </div>
                  <div className="address-row">
                    <label>Subject</label>
                    <Input
                      value={subject}
                      onChange={(event) => setSubject(event.target.value)}
                      placeholder="RE: Job Application"
                    />
                  </div>
                </div>
                <Textarea
                  className="email-editor reply-editor"
                  value={content}
                  onChange={(event) => setContent(event.target.value)}
                />
                <footer className="compose-footer">
                  <span>Sending from your active account</span>
                  <div>
                    <Button
                      onClick={() => {
                        setDraftVisible(false)
                        setContent("")
                      }}
                    >
                      Discard
                    </Button>
                    <Button variant="primary" icon="send" onClick={send}>
                      Send reply
                    </Button>
                  </div>
                </footer>
              </section>
            )}
            <section className="card instruction-card prompt-bar">
              <label className="reply-instructions">
                <span>Reply instructions</span>
                <Input
                  value={instructions}
                  onChange={(event) => setInstructions(event.target.value)}
                  placeholder="What should the reply cover?"
                />
                <small>
                  For example: Confirm availability for Tuesday at 3pm.
                </small>
              </label>
              <Button
                variant="primary"
                icon="sparkles"
                busy={generating}
                disabled={generating}
                onClick={generate}
              >
                {generating ? "Writing reply…" : "Draft with AI"}
              </Button>
            </section>
            {selected.linked && (
              <div className="related-record">
                <span>Related application</span>
                <strong>{selected.role}</strong>
                <Badge>{statusLabel(selected.appStatus ?? "draft")}</Badge>
              </div>
            )}
          </div>
        </div>
        <Dialog
          open={Boolean(status)}
          onClose={() => setStatus(null)}
          title={status?.title ?? ""}
        >
          <div
            className={`status-message ${
              status?.success ? "success" : "danger"
            }`}
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

  return (
    <main className="content">
      <PageHeader
        eyebrow="Reply center"
        title="Inbox zero starts here"
        description="Review job-related conversations and respond from one focused workspace."
        actions={
          <Button icon="refresh" onClick={onSync}>
            Refresh inbox
          </Button>
        }
      />
      <div className="stat-strip">
        <div>
          <span>Recent conversations</span>
          <strong>{conversations.length}</strong>
        </div>
        <div>
          <span>Shortlisted</span>
          <strong className="text-green">{shortlisted}</strong>
        </div>
        <div>
          <span>Job related</span>
          <strong>{related}</strong>
        </div>
        <div>
          <span>Unlinked</span>
          <strong>{unlinked}</strong>
        </div>
      </div>
      {conversations.length ? (
        <section className="card list-rows">
          <div className="inbox-toolbar">
            <div>
              <h2>Conversations</h2>
              <p>Recruiter activity ordered by attention needed.</p>
            </div>
            <Tabs
              label="Conversation filter"
              active={filter}
              onChange={setFilter}
              items={[
                {
                  label: "Needs attention",
                  count: conversations.length,
                },
                { label: "All", count: conversations.length },
                { label: "Unlinked", count: unlinked },
              ]}
            />
          </div>
          {visibleReplies.slice(0, 10).map((reply) => (
            <button
              className="mail-row"
              data-search={`${reply.sender} ${reply.subject} ${reply.company}`}
              key={reply.id}
              onClick={() => open(reply)}
            >
              <span className="company-mark">{reply.sender[0]}</span>
              <span className="mail-copy">
                <strong>{reply.sender}</strong>
                <b>{reply.subject}</b>
                <small>
                  {reply.body.slice(0, 120)}
                  {reply.body.length > 120 ? "…" : ""}
                </small>
              </span>
              {reply.positive && <Badge tone="success">Shortlisted</Badge>}
              {reply.linked && !reply.positive && <Badge>Job related</Badge>}
              <time>{reply.time}</time>
              <Icon name="chevron" size={13} />
            </button>
          ))}
          {visibleReplies.length === 0 && (
            <EmptyState
              icon="inbox"
              title="Nothing needs attention"
              description="You’re caught up. View all conversations to browse your history."
              action={
                <Button onClick={() => setFilter("All")}>
                  View all conversations
                </Button>
              }
            />
          )}
        </section>
      ) : (
        <EmptyState
          icon="inbox"
          title="Your inbox is empty"
          description="Sync your sending account to check for new replies."
          action={
            <Button icon="refresh" onClick={onSync}>
              Refresh inbox
            </Button>
          }
        />
      )}
      <Dialog
        open={unlinkedOpen}
        onClose={() => setUnlinkedOpen(false)}
        title="Not linked to an application"
        description="Create an application to continue this conversation in context."
        footer={
          <>
            <Button onClick={() => setUnlinkedOpen(false)}>Close</Button>
            <Button
              variant="primary"
              icon="add"
              onClick={() => {
                setUnlinkedOpen(false)
                navigate("Add Application")
              }}
            >
              Create application
            </Button>
          </>
        }
      >
        <p>
          This conversation has not been matched to a Command application yet.
          You can create one now or return to the inbox.
        </p>
      </Dialog>
    </main>
  )
}
