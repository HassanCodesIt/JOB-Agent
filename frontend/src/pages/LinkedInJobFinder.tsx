import { useCallback, useEffect, useMemo, useRef, useState } from "react"
import type {
  FilterStatus,
  LinkedInJob,
  LinkedInJobRecord,
  LinkedInRun,
  SearchMode,
  SearchRun,
  SearchRunState,
} from "@/types"
import { JobDetailsDrawer, JobSourceMenu } from "@/components/JobDetailsDrawer"
import {
  ApiError,
  draftApplyLinkedInJob,
  errorMessage,
  fetchLinkedInBrowserStatus,
  fetchLinkedInMeta,
  fetchLinkedInRun,
  runLinkedInFilter,
  saveLinkedInSearchSettings,
  startLinkedInRun,
  stopLinkedInRun,
} from "@/api"
import { useAsync } from "@/hooks/useAsync"
import {
  Badge,
  Button,
  Dialog,
  EmptyState,
  Field,
  Icon,
  PageHeader,
  SearchInput,
  Select,
  Status,
  Tabs,
} from "@/components/ui"
import { FilterSettings } from "./Settings"

const modes: Array<{
  title: SearchMode
  icon: Parameters<typeof Icon>[0]["name"]
  description: string
}> = [
  {
    title: "Standard Job Search",
    icon: "search",
    description: "Run a focused search with editable filters.",
  },
  {
    title: "Latest Jobs",
    icon: "clock",
    description: "Find the newest relevant opportunities.",
  },
  {
    title: "Jobs Posted in Last 24 Hours",
    icon: "calendar",
    description: "Focus only on roles posted today.",
  },
  {
    title: "Top Matches",
    icon: "sparkles",
    description: "Prioritize relevant recent roles.",
  },
  {
    title: "Home Feed",
    icon: "home",
    description: "Review opportunities from your home feed.",
  },
  {
    title: "Continue Search",
    icon: "refresh",
    description: "Continue from a previous search.",
  },
]

const sortSelectOptions = [
  { value: "__linkedin_default__", label: "LinkedIn default" },
  { value: "latest", label: "Most recent" },
  { value: "relevance", label: "Most relevant" },
]
const dateSelectOptions = [
  { value: "any", label: "Any time" },
  { value: "past_24_hours", label: "Past 24 hours" },
]

type SortValue = "__linkedin_default__" | "latest" | "relevance"
type DateValue = "any" | "past_24_hours"

const filterStatusMap: Record<string, FilterStatus> = {
  pending: "Needs Review",
  accepted: "Accepted",
  rejected: "Rejected",
  error: "Error",
}

function toViewJob(record: LinkedInJobRecord): LinkedInJob {
  return {
    id: String(record.id),
    runId: record.run_id != null ? String(record.run_id) : "",
    title: record.role,
    company: record.company,
    location: record.location,
    experience: record.experience,
    employmentType: record.employment_type,
    salary: record.salary ?? undefined,
    email: record.email ?? undefined,
    methods: record.methods.length
      ? record.methods
      : record.application_method
        ? [record.application_method]
        : [],
    description: record.preview,
    fullText: record.full_text,
    skills: record.skills,
    responsibilities: record.responsibilities,
    qualifications: record.qualifications,
    filterStatus: filterStatusMap[record.filter_status] ?? "Needs Review",
    links: {
      linkedin: record.links.post ?? undefined,
      job: record.links.job ?? undefined,
      apply: record.links.apply ?? undefined,
      image: record.links.image ?? undefined,
    },
  }
}

function secondsSince(iso: string | null): number {
  if (!iso) return 0
  const started = Date.parse(
    iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`,
  )
  if (!Number.isFinite(started)) return 0
  return Math.max(0, Math.floor((Date.now() - started) / 1000))
}

function formatRunTime(iso: string | null): string {
  if (!iso) return "—"
  const date = new Date(
    `${iso.endsWith("Z") || iso.includes("+") ? iso : `${iso}Z`}`,
  )
  if (Number.isNaN(date.getTime())) return iso.replace("T", " ").slice(0, 16)
  const now = new Date()
  const startOfDay = (value: Date) =>
    new Date(value.getFullYear(), value.getMonth(), value.getDate()).getTime()
  const dayDiff = Math.round(
    (startOfDay(now) - startOfDay(date)) / (24 * 60 * 60 * 1000),
  )
  if (dayDiff === 0) {
    const hours = date.getHours()
    const period = hours >= 12 ? "PM" : "AM"
    const hour12 = hours % 12 === 0 ? 12 : hours % 12
    const minutes = String(date.getMinutes()).padStart(2, "0")
    return `Today, ${hour12}:${minutes} ${period}`
  }
  if (dayDiff === 1) return "Yesterday"
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" })
}

function runSearchStatus(status: string): SearchRun["status"] {
  if (status === "running") return "Running"
  if (status === "completed") return "Completed"
  if (status === "interrupted") return "Interrupted"
  return "Failed"
}

function runSortLabel(sortBy: string | null): string {
  if (sortBy === "latest") return "Most recent"
  if (sortBy === "relevance") return "Most relevant"
  return "LinkedIn default"
}

function runDateLabel(datePosted: string | null): string {
  if (datePosted === "past_24_hours") return "Past 24 hours"
  return "Any time"
}

function JobRow({
  job,
  onView,
  onDraft,
  onImage,
}: {
  job: LinkedInJob
  onView: () => void
  onDraft: () => void
  onImage: () => void
}) {
  const filterTone =
    job.filterStatus === "Accepted"
      ? "success"
      : job.filterStatus === "Rejected"
        ? "danger"
        : job.filterStatus === "Needs Review"
          ? "warning"
          : "neutral"
  return (
    <article className="job-row">
      <span className="company-mark">
        {job.company
          .split(" ")
          .map((word) => word[0])
          .join("")
          .slice(0, 2)}
      </span>
      <div className="job-main">
        <div className="job-title-line">
          <div>
            <h3>{job.title}</h3>
            <p>
              {job.company} · {job.location}
            </p>
          </div>
          <div>
            <Badge tone={filterTone}>Relevance: {job.filterStatus}</Badge>
            <Badge tone={job.email ? "success" : "neutral"}>
              {job.email ? "Email available" : "No email"}
            </Badge>
          </div>
        </div>
        <div className="job-meta">
          <span>{job.experience}</span>
          <span>{job.employmentType}</span>
          {job.salary && <span>{job.salary}</span>}
          <span>{job.methods.join(" · ")}</span>
          {job.links.image && (
            <span>
              <Icon name="image" size={13} /> Image post
            </span>
          )}
        </div>
        <p className="job-description">{job.description}</p>
        <div className="job-row-footer">
          <Button onClick={onView}>View details</Button>
          <JobSourceMenu job={job} onImage={onImage} />
          <Button
            variant={job.filterStatus === "Accepted" ? "primary" : "secondary"}
            icon="sparkles"
            onClick={onDraft}
          >
            Draft & Apply
          </Button>
        </div>
      </div>
    </article>
  )
}

function SearchStatusPanel({
  state,
  role,
  mode,
  sort,
  date,
  elapsed,
  count,
  errorText,
  browserMessage,
  onStop,
  onRetry,
  onView,
}: {
  state: SearchRunState
  role: string
  mode: string
  sort: string
  date: string
  elapsed: number
  count: number
  errorText?: string | null
  browserMessage?: string | null
  onStop: () => void
  onRetry: () => void
  onView: () => void
}) {
  if (state === "ready") return null
  const labels: Record<SearchRunState, {
    title: string
    tone: "neutral" | "success" | "warning" | "danger" | "violet"
    text: string
  }> = {
    ready: { title: "", tone: "neutral", text: "" },
    running: {
      title: "Searching LinkedIn...",
      tone: "violet",
      text: "The page remains available while this search runs.",
    },
    completed: {
      title: "Search completed",
      tone: "success",
      text: `${count} new ${
        count === 1 ? "job was" : "jobs were"
      } collected and imported.`,
    },
    failed: {
      title: "Search failed",
      tone: "danger",
      text:
        errorText ||
        "Command could not complete the search. Your previous results are unchanged.",
    },
    stopped: {
      title: "Search stopped",
      tone: "warning",
      text: "The current search was stopped. You can run it again when ready.",
    },
    unavailable: {
      title: "LinkedIn browser connection could not be established.",
      tone: "warning",
      text:
        browserMessage ||
        "Make sure your logged-in Chrome session is available.",
    },
  }
  const config = labels[state]
  return (
    <section className={`run-status run-${config.tone}`} aria-live="polite">
      <div className="run-title">
        <span className="run-symbol">
          {state === "running" ? (
            <span className="spinner" />
          ) : (
            <Icon name={state === "completed" ? "check" : "activity"} />
          )}
        </span>
        <div>
          <h3>{config.title}</h3>
          <p>{config.text}</p>
        </div>
        <Status tone={config.tone}>
          {state === "running"
            ? "Running"
            : state[0].toUpperCase() + state.slice(1)}
        </Status>
      </div>
      {state !== "unavailable" && (
        <div className="run-facts">
          <div>
            <span>Role</span>
            <strong>{role}</strong>
          </div>
          <div>
            <span>Mode</span>
            <strong>{mode}</strong>
          </div>
          <div>
            <span>Sort</span>
            <strong>{sort}</strong>
          </div>
          <div>
            <span>Date</span>
            <strong>{date}</strong>
          </div>
          <div>
            <span>Elapsed</span>
            <strong>{elapsed}s</strong>
          </div>
          <div>
            <span>Jobs collected</span>
            <strong>{count}</strong>
          </div>
        </div>
      )}
      {state === "running" && (
        <>
          <div className="progress-track">
            <span style={{ width: `${Math.min(92, 10 + elapsed * 13)}%` }} />
          </div>
          <Button icon="pause" onClick={onStop}>
            Stop Search
          </Button>
        </>
      )}
      {state === "completed" && (
        <Button variant="primary" onClick={onView}>
          View collected jobs
        </Button>
      )}
      {(state === "failed" || state === "stopped") && (
        <Button icon="refresh" onClick={onRetry}>
          {state === "stopped" ? "Run again" : "Retry"}
        </Button>
      )}
      {state === "unavailable" && (
        <div className="inline-actions">
          <Button variant="primary" icon="refresh" onClick={onRetry}>
            Retry
          </Button>
        </div>
      )}
    </section>
  )
}

export default function LinkedInJobFinder({
  jobs,
  loading,
  error,
  reloadJobs,
  notify,
  onDrafted,
}: {
  jobs: { items: LinkedInJobRecord[]; total: number } | null
  loading: boolean
  error: string | null
  reloadJobs: () => void
  notify: (
    message: string,
    tone?: "neutral" | "success" | "warning" | "danger" | "violet",
  ) => void
  onDrafted: (applicationId: number) => void
}) {
  const meta = useAsync(fetchLinkedInMeta)
  const browser = useAsync(fetchLinkedInBrowserStatus)
  const [role, setRole] = useState("")
  const [customRole, setCustomRole] = useState("")
  const [mode, setMode] = useState<SearchMode>("Standard Job Search")
  const [sort, setSort] = useState<SortValue>("__linkedin_default__")
  const [date, setDate] = useState<DateValue>("any")
  const [runState, setRunState] = useState<SearchRunState>("ready")
  const [activeRun, setActiveRun] = useState<LinkedInRun | null>(null)
  const [elapsed, setElapsed] = useState(0)
  const [starting, setStarting] = useState(false)
  const [jobTab, setJobTab] = useState("All")
  const [filteredTab, setFilteredTab] = useState("Accepted")
  const [emailTab, setEmailTab] = useState("All")
  const [resultView, setResultView] = useState<"Collected" | "Filtered">(
    "Collected",
  )
  const [query, setQuery] = useState("")
  const [selectedJob, setSelectedJob] = useState<LinkedInJob | null>(null)
  const [imageJob, setImageJob] = useState<LinkedInJob | null>(null)
  const [filtering, setFiltering] = useState(false)
  const [settingsOpen, setSettingsOpen] = useState(false)
  const [creatingId, setCreatingId] = useState<string | null>(null)
  const seededRef = useRef(false)
  const userStoppedRef = useRef(false)
  const pollRef = useRef<number | null>(null)

  const chosenRole = customRole.trim() || role
  const modeInfo = meta.data?.modes.find((item) => item.label === mode)
  const rule = useMemo(() => {
    if (!modeInfo) {
      return {
        sortValue: null as SortValue | null,
        dateValue: null as DateValue | null,
        locked: false,
        helper: "",
      }
    }
    if (!modeInfo.searchable) {
      return {
        sortValue: "__linkedin_default__" as SortValue,
        dateValue: "any" as DateValue,
        locked: true,
        helper: `These filters aren't used for ${mode}.`,
      }
    }
    if (modeInfo.fixed_sort || modeInfo.fixed_date) {
      return {
        sortValue:
          modeInfo.fixed_sort === "latest"
            ? "latest" as SortValue
            : modeInfo.fixed_sort === "relevance"
              ? "relevance" as SortValue
              : "__linkedin_default__" as SortValue,
        dateValue:
          modeInfo.fixed_date === "past_24_hours"
            ? "past_24_hours" as DateValue
            : "any" as DateValue,
        locked: true,
        helper: "",
      }
    }
    return {
      sortValue: null as SortValue | null,
      dateValue: null as DateValue | null,
      locked: false,
      helper: "",
    }
  }, [mode, modeInfo])

  const stopPolling = useCallback(() => {
    if (pollRef.current != null) {
      window.clearInterval(pollRef.current)
      pollRef.current = null
    }
  }, [])

  const finishRun = useCallback(
    (run: LinkedInRun) => {
      stopPolling()
      setActiveRun(run)
      if (userStoppedRef.current) {
        setRunState("stopped")
        notify("Search stopped.", "warning")
      } else if (run.status === "completed") {
        setRunState("completed")
        notify(
          `Search finished · ${run.collected_count} new ${
            run.collected_count === 1 ? "job" : "jobs"
          }`,
          "success",
        )
      } else {
        setRunState("failed")
        notify(
          run.error_message || "The LinkedIn search could not complete.",
          "danger",
        )
      }
      reloadJobs()
      meta.reload()
    },
    [meta, notify, reloadJobs, stopPolling],
  )

  const watchRun = useCallback(
    (runId: number) => {
      stopPolling()
      pollRef.current = window.setInterval(() => {
        fetchLinkedInRun(runId)
          .then(({ run }) => {
            setActiveRun(run)
            if (run.status !== "running") finishRun(run)
          })
          .catch(() => {
            // A transient poll failure keeps the current view; the next tick retries.
          })
      }, 2000)
    },
    [finishRun, stopPolling],
  )

  useEffect(() => stopPolling, [stopPolling])

  useEffect(() => {
    if (runState !== "running") return
    const interval = window.setInterval(
      () => setElapsed((value) => value + 1),
      1000,
    )
    return () => window.clearInterval(interval)
  }, [runState])

  useEffect(() => {
    const interval = window.setInterval(() => browser.reload(), 15000)
    return () => window.clearInterval(interval)
  }, [browser.reload])

  useEffect(() => {
    if (!meta.data || seededRef.current) return
    seededRef.current = true
    const { search, preset_roles, active_run } = meta.data
    if (search.default_role && preset_roles.includes(search.default_role)) {
      setRole(search.default_role)
    } else if (search.default_role) {
      setCustomRole(search.default_role)
      if (preset_roles[0]) setRole(preset_roles[0])
    } else if (preset_roles[0]) {
      setRole(preset_roles[0])
    }
    setSort(search.sort_by === "latest" ? "latest" : "__linkedin_default__")
    setDate(search.date_posted === "past_24_hours" ? "past_24_hours" : "any")
    if (active_run) {
      setActiveRun(active_run)
      setElapsed(secondsSince(active_run.started_at))
      setRunState("running")
      userStoppedRef.current = false
      watchRun(active_run.id)
    }
  }, [meta.data, watchRun])

  useEffect(() => {
    if (rule.locked && rule.sortValue && rule.dateValue) {
      setSort(rule.sortValue)
      setDate(rule.dateValue)
    }
  }, [rule])

  useEffect(() => {
    if (sort === "latest" && date !== "past_24_hours") {
      setSort("relevance")
    }
  }, [date, sort])

  const sortLockedByDate = date !== "past_24_hours"
  const sortHint =
    date === "past_24_hours"
      ? "Applies to Standard Job Search."
      : "Most recent needs Date posted: Past 24 hours."

  const scrollTo = (id: string) => {
    window.setTimeout(
      () => document.getElementById(id)?.scrollIntoView({ behavior: "smooth" }),
      0,
    )
  }

  const startSearch = async (options: { skipBrowserCheck?: boolean } = {}) => {
    if (starting || runState === "running") return
    if (!options.skipBrowserCheck && browser.data && !browser.data.reachable) {
      setRunState("unavailable")
      return
    }
    if (!chosenRole) {
      notify("Enter a job role before starting a LinkedIn search.", "warning")
      return
    }
    if (!modeInfo) {
      notify(
        "Search modes could not be loaded yet. Retry in a moment.",
        "danger",
      )
      return
    }
    const standard = modeInfo.key === "standard"
    const sortValue =
      sort === "latest" ? "latest" : sort === "relevance" ? "relevance" : null
    const dateValue: DateValue = date
    setStarting(true)
    try {
      const { run } = await startLinkedInRun({
        mode: modeInfo.key,
        role: chosenRole,
        sort_by: standard ? sortValue : null,
        date_posted: standard ? dateValue : null,
      })
      saveLinkedInSearchSettings({
        default_role: chosenRole,
        sort_by: sortValue ?? "relevance",
        date_posted: dateValue,
      }).catch(() => {
        // Defaults only preselect the form next time; a failure is not fatal.
      })
      userStoppedRef.current = false
      setActiveRun(run)
      setElapsed(0)
      setRunState("running")
      notify("LinkedIn search started", "violet")
      watchRun(run.id)
    } catch (cause: unknown) {
      const message = errorMessage(cause)
      if (cause instanceof ApiError && cause.status === 409) {
        try {
          const fresh = await fetchLinkedInMeta()
          if (fresh.active_run) {
            setActiveRun(fresh.active_run)
            setElapsed(secondsSince(fresh.active_run.started_at))
            setRunState("running")
            userStoppedRef.current = false
            watchRun(fresh.active_run.id)
            notify(message, "warning")
            return
          }
        } catch {
          // Fall through to the plain error below.
        }
      }
      if (cause instanceof ApiError && cause.status === 503) {
        setRunState("unavailable")
      }
      notify(message, "danger")
    } finally {
      setStarting(false)
    }
  }

  const stopSearch = async () => {
    if (!activeRun) return
    try {
      await stopLinkedInRun(activeRun.id)
      userStoppedRef.current = true
      setRunState("stopped")
      notify("Search stopped.", "warning")
    } catch (cause: unknown) {
      notify(errorMessage(cause), "danger")
    }
  }

  const retrySearch = async () => {
    try {
      const status = await fetchLinkedInBrowserStatus()
      browser.reload()
      if (status.reachable) {
        setRunState("ready")
        await startSearch({ skipBrowserCheck: true })
      } else {
        setRunState("unavailable")
        notify(
          status.message ||
            "LinkedIn browser connection could not be established.",
          "warning",
        )
      }
    } catch (cause: unknown) {
      notify(errorMessage(cause), "danger")
    }
  }

  const filterJobs = async () => {
    if (filtering || runState === "running") return
    setFiltering(true)
    notify("Filtering collected jobs...", "violet")
    try {
      const result = await runLinkedInFilter({ force: false })
      const summary = result.summary
      notify(
        `Filtering complete — ${summary.accepted} relevant · ${summary.rejected} rejected · ${summary.errors} errors`,
        "success",
      )
      setSelectedJob(null)
      setResultView("Filtered")
      reloadJobs()
      meta.reload()
      scrollTo("filtered-jobs")
    } catch (cause: unknown) {
      notify(errorMessage(cause), "danger")
    } finally {
      setFiltering(false)
    }
  }

  const draft = async (job: LinkedInJob) => {
    const jobId = Number(job.id)
    if (!Number.isInteger(jobId)) return
    setCreatingId(job.id)
    setSelectedJob(null)
    try {
      const result = await draftApplyLinkedInJob(jobId)
      notify(result.message, result.reused ? "neutral" : "success")
      setCreatingId(null)
      onDrafted(result.application_id)
    } catch (cause: unknown) {
      setCreatingId(null)
      notify(errorMessage(cause), "danger")
    }
  }

  const records = jobs?.items ?? []
  const viewJobs = useMemo(() => records.map(toViewJob), [records])
  const collectedJobs = useMemo(
    () =>
      viewJobs.filter(
        (job) =>
          (jobTab === "All" ||
            (jobTab === "With email" ? job.email : !job.email)) &&
          `${job.title} ${job.company} ${job.location}`
            .toLowerCase()
            .includes(query.toLowerCase()),
      ),
    [viewJobs, jobTab, query],
  )
  const filteredJobs = useMemo(
    () =>
      viewJobs.filter(
        (job) =>
          job.filterStatus === filteredTab &&
          (emailTab === "All" ||
            (emailTab === "With email" ? job.email : !job.email)),
      ),
    [viewJobs, filteredTab, emailTab],
  )
  const filteredTotal = viewJobs.filter((job) =>
    ["Accepted", "Needs Review", "Rejected"].includes(job.filterStatus),
  ).length
  const hasFilterErrors = viewJobs.some((job) => job.filterStatus === "Error")

  const browserState: "Connected" | "Checking" | "Not connected" = browser.error
    ? "Not connected"
    : browser.data
      ? browser.data.reachable
        ? "Connected"
        : "Not connected"
      : "Checking"

  const sortLabel =
    sortSelectOptions.find((option) => option.value === sort)?.label ??
    "LinkedIn default"
  const dateLabel =
    dateSelectOptions.find((option) => option.value === date)?.label ??
    "Any time"

  return (
    <main className="content">
      <PageHeader
        eyebrow="Job discovery"
        title="LinkedIn Job Finder"
        description="Collect jobs from your logged-in LinkedIn browser session, then filter and draft in Command."
        actions={
          <div className="connection-control">
            <Status
              tone={
                browserState === "Connected"
                  ? "success"
                  : browserState === "Checking"
                    ? "warning"
                    : "danger"
              }
            >
              {browserState}
            </Status>
            <Button icon="settings" onClick={() => setSettingsOpen(true)}>
              Filter settings
            </Button>
          </div>
        }
      />

      <section className="panel search-panel">
        <div className="section-header">
          <div>
            <h2>Search & Automation</h2>
            <p>
              Choose one role and the search approach that fits your next step.
            </p>
          </div>
        </div>
        {meta.error && !meta.data && (
          <div className="notice neutral compact-notice">
            <Icon name="activity" />
            <div>
              <strong>Search settings could not be loaded.</strong>
              <p>{meta.error}</p>
            </div>
            <Button icon="refresh" onClick={meta.reload}>
              Retry
            </Button>
          </div>
        )}
        <div className="search-fields">
          <Field label="Saved role" hint="Only one role is used per search.">
            <Select
              value={role}
              onChange={(event) => {
                setRole(event.target.value)
                setCustomRole("")
              }}
            >
              {(meta.data?.preset_roles ?? []).map((item) => (
                <option key={item}>{item}</option>
              ))}
            </Select>
          </Field>
          <div className="role-or">or</div>
          <Field label="Custom role" optional>
            <input
              className="input"
              value={customRole}
              onChange={(event) => setCustomRole(event.target.value)}
              placeholder="Enter a job role..."
            />
          </Field>
          <Field label="Sort by" hint={sortHint}>
            <Select
              value={rule.locked && rule.sortValue ? rule.sortValue : sort}
              disabled={rule.locked}
              onChange={(event) => setSort(event.target.value as SortValue)}
            >
              {sortSelectOptions.map((option) => (
                <option
                  key={option.value}
                  value={option.value}
                  disabled={option.value === "latest" && sortLockedByDate}
                >
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
          <Field label="Date posted" hint="Applies to Standard Job Search.">
            <Select
              value={rule.locked && rule.dateValue ? rule.dateValue : date}
              disabled={rule.locked}
              onChange={(event) => setDate(event.target.value as DateValue)}
            >
              {dateSelectOptions.map((option) => (
                <option key={option.value} value={option.value}>
                  {option.label}
                </option>
              ))}
            </Select>
          </Field>
        </div>
        {rule.helper && (
          <div className="inline-helper">
            <Icon name="activity" size={15} />
            {rule.helper}
          </div>
        )}
        <div className="mode-header">
          <div>
            <h3>Search mode</h3>
            <p>Select how Command should run this LinkedIn search.</p>
          </div>
          <span>1 selected</span>
        </div>
        <div className="mode-grid">
          {modes.map((item) => (
            <button
              key={item.title}
              disabled={runState === "running" || starting}
              className={`mode-card ${mode === item.title ? "selected" : ""}`}
              onClick={() => setMode(item.title)}
            >
              <span className="mode-icon">
                <Icon name={item.icon} size={17} />
              </span>
              <span>
                <strong>{item.title}</strong>
                <small>{item.description}</small>
              </span>
              <span className="radio">{mode === item.title && <span />}</span>
            </button>
          ))}
        </div>
        <div className="search-submit">
          <div>
            <strong>{chosenRole || "Choose a role"}</strong>
            <span>
              {mode} · {sortLabel} · {dateLabel}
            </span>
          </div>
          <Button
            variant="primary"
            icon="search"
            busy={starting || runState === "running"}
            disabled={
              starting ||
              runState === "running" ||
              browserState === "Checking" ||
              Boolean(meta.error && !meta.data)
            }
            onClick={() => void startSearch()}
          >
            {runState === "running" ? "Searching..." : "Run Search"}
          </Button>
        </div>
        <SearchStatusPanel
          state={runState}
          role={activeRun?.role || chosenRole || "—"}
          mode={activeRun?.mode_label || mode}
          sort={activeRun ? runSortLabel(activeRun.sort_by) : sortLabel}
          date={activeRun ? runDateLabel(activeRun.date_posted) : dateLabel}
          elapsed={elapsed}
          count={activeRun?.collected_count ?? 0}
          errorText={activeRun?.error_message}
          browserMessage={browser.data?.message}
          onStop={stopSearch}
          onRetry={() => {
            if (runState === "unavailable") retrySearch()
            else startSearch()
          }}
          onView={() => {
            setResultView("Collected")
            scrollTo("job-results")
          }}
        />
      </section>

      <section className="panel recent-searches">
        <div className="section-header">
          <div>
            <h2>Recent Searches</h2>
            <p>Return to the results of a previous run.</p>
          </div>
        </div>
        <div className="compact-list">
          {(meta.data?.runs ?? []).slice(0, 4).map((run) => (
            <div key={run.id}>
              <span className="list-icon">
                <Icon name="clock" size={15} />
              </span>
              <span>
                <strong>{run.mode_label}</strong>
                <small>{run.role || "—"}</small>
              </span>
              <span>{run.collected_count} jobs</span>
              <Badge
                tone={
                  run.status === "completed"
                    ? "success"
                    : run.status === "failed"
                      ? "danger"
                      : "warning"
                }
              >
                {runSearchStatus(run.status)}
              </Badge>
              <time>{formatRunTime(run.started_at)}</time>
              <Button
                variant="ghost"
                onClick={() => {
                  setJobTab("All")
                  setQuery("")
                  setResultView("Collected")
                  scrollTo("job-results")
                }}
              >
                View results
              </Button>
            </div>
          ))}
          {meta.data && meta.data.runs.length === 0 && (
            <div>
              <span className="list-icon">
                <Icon name="clock" size={15} />
              </span>
              <span>
                <strong>No searches yet</strong>
                <small>Run a search to see it here.</small>
              </span>
            </div>
          )}
        </div>
      </section>

      <div className="result-switch" id="job-results">
        <div role="tablist" aria-label="Job results">
          <button
            role="tab"
            aria-selected={resultView === "Collected"}
            className={resultView === "Collected" ? "active" : ""}
            onClick={() => setResultView("Collected")}
          >
            Collected <span>{records.length}</span>
          </button>
          <button
            role="tab"
            aria-selected={resultView === "Filtered"}
            className={resultView === "Filtered" ? "active" : ""}
            onClick={() => setResultView("Filtered")}
          >
            Filtered <span>{filteredTotal}</span>
          </button>
        </div>
        <span>
          {resultView === "Collected"
            ? "Review imported opportunities"
            : "Review relevance decisions"}
        </span>
      </div>

      <section
        className={`panel jobs-panel ${
          resultView !== "Collected" ? "result-panel-hidden" : ""
        }`}
        id="collected-jobs"
      >
        <div className="section-header">
          <div>
            <h2>
              Collected LinkedIn Jobs <Badge>{records.length} jobs</Badge>
            </h2>
            <p>
              Review concise job context before filtering, then run the
              relevance filter.
            </p>
          </div>
          <Button
            variant="primary"
            icon="filter"
            busy={filtering}
            disabled={filtering || runState === "running"}
            onClick={filterJobs}
          >
            {filtering
              ? `Filtering ${records.length} jobs...`
              : "Filter Collected Jobs"}
          </Button>
        </div>
        <div className="toolbar">
          <Tabs
            label="Collected jobs"
            active={jobTab}
            onChange={setJobTab}
            items={[
              { label: "All", count: records.length },
              {
                label: "With email",
                count: viewJobs.filter((job) => job.email).length,
              },
              {
                label: "Without email",
                count: viewJobs.filter((job) => !job.email).length,
              },
            ]}
          />
          <SearchInput
            value={query}
            onChange={setQuery}
            placeholder="Search collected jobs..."
          />
        </div>
        {jobTab === "Without email" && (
          <div className="notice neutral compact-notice">
            <Icon name="briefcase" />
            <div>
              <strong>These jobs are still actionable.</strong>
              <p>
                You can open LinkedIn, use an apply link, or draft an
                application manually.
              </p>
            </div>
          </div>
        )}
        {loading ? (
          <p className="form-note">Loading jobs…</p>
        ) : error ? (
          <div className="notice neutral compact-notice">
            <Icon name="activity" />
            <div>
              <strong>Jobs could not be loaded.</strong>
              <p>{error}</p>
            </div>
            <Button icon="refresh" onClick={reloadJobs}>
              Retry
            </Button>
          </div>
        ) : collectedJobs.length === 0 ? (
          <EmptyState
            icon="linkedin"
            title="No LinkedIn jobs collected yet."
            description="Run a Search to add collected results here."
            action={
              <Button
                variant="primary"
                onClick={() => {
                  setResultView("Collected")
                  window.scrollTo({ top: 0, behavior: "smooth" })
                }}
              >
                Run a Search
              </Button>
            }
          />
        ) : (
          <div className="job-list">
            {collectedJobs.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                onView={() => setSelectedJob(job)}
                onImage={() => setImageJob(job)}
                onDraft={() => draft(job)}
              />
            ))}
          </div>
        )}
      </section>

      <section
        className={`panel jobs-panel ${
          resultView !== "Filtered" ? "result-panel-hidden" : ""
        }`}
        id="filtered-jobs"
      >
        <div className="section-header">
          <div>
            <h2>Filtered Jobs</h2>
            <p>
              Review relevance decisions, then move accepted jobs into your
              normal Command workflow.
            </p>
          </div>
        </div>
        <div className="dual-tabs">
          <Tabs
            label="Filter decision"
            active={filteredTab}
            onChange={setFilteredTab}
            items={[
              {
                label: "Accepted",
                count: viewJobs.filter((job) => job.filterStatus === "Accepted")
                  .length,
              },
              {
                label: "Needs Review",
                count: viewJobs.filter(
                  (job) => job.filterStatus === "Needs Review",
                ).length,
              },
              {
                label: "Rejected",
                count: viewJobs.filter((job) => job.filterStatus === "Rejected")
                  .length,
              },
            ]}
          />
          <Tabs
            label="Email availability"
            active={emailTab}
            onChange={setEmailTab}
            items={[
              { label: "All" },
              { label: "With email" },
              { label: "Without email" },
            ]}
          />
        </div>
        {hasFilterErrors && (
          <div className="notice neutral compact-notice">
            <Icon name="activity" />
            <div>
              <strong>Some jobs could not be filtered.</strong>
              <p>
                The job details remain available. Retry filtering to request a
                new decision.
              </p>
            </div>
            <Button icon="refresh" disabled={filtering} onClick={filterJobs}>
              Retry Filtering
            </Button>
          </div>
        )}
        {loading ? (
          <p className="form-note">Loading jobs…</p>
        ) : error ? (
          <div className="notice neutral compact-notice">
            <Icon name="activity" />
            <div>
              <strong>Jobs could not be loaded.</strong>
              <p>{error}</p>
            </div>
            <Button icon="refresh" onClick={reloadJobs}>
              Retry
            </Button>
          </div>
        ) : filteredJobs.length === 0 ? (
          <EmptyState
            icon="filter"
            title="Filter your collected jobs to find relevant opportunities."
            description="Accepted and review-needed jobs will appear here."
          />
        ) : (
          <div className="job-list">
            {filteredJobs.map((job) => (
              <JobRow
                key={job.id}
                job={job}
                onView={() => setSelectedJob(job)}
                onImage={() => setImageJob(job)}
                onDraft={() => draft(job)}
              />
            ))}
          </div>
        )}
      </section>

      {creatingId && (
        <div className="transition-toast" role="status">
          <span className="spinner" />
          <div>
            <strong>Creating your Command application...</strong>
            <small>Preparing Draft Studio with the selected job context.</small>
          </div>
        </div>
      )}
      <JobDetailsDrawer
        job={selectedJob}
        onClose={() => setSelectedJob(null)}
        onDraft={draft}
        onImage={setImageJob}
      />
      <Dialog
        open={Boolean(imageJob)}
        onClose={() => setImageJob(null)}
        title="View Job Image"
        description="Opens the image from the LinkedIn post."
      >
        {imageJob?.links.image && (
          <figure className="image-viewer">
            <img
              src={imageJob.links.image}
              alt={`Image post for ${imageJob.title} at ${imageJob.company}`}
            />
            <figcaption>Image post · {imageJob.company}</figcaption>
          </figure>
        )}
      </Dialog>
      <Dialog
        open={settingsOpen}
        onClose={() => setSettingsOpen(false)}
        title="LinkedIn filtering settings"
        description="Changes affect how collected jobs are classified."
      >
        <FilterSettings notify={notify} />
      </Dialog>
    </main>
  )
}
