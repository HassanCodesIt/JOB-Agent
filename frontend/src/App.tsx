import { useEffect, useMemo, useState } from "react"
import { AppShell, type SearchItem } from "@/components/AppShell"
import {
  errorMessage,
  fetchAccounts,
  fetchApplications,
  fetchCampaigns,
  fetchEmailEvents,
  fetchLinkedInJobs,
  fetchRoleResumes,
  fetchStats,
  fetchUser,
  statusLabel,
  syncInbox,
  updateUserSettings,
} from "@/api"
import { useAsync } from "@/hooks/useAsync"
import type { PageName, Resume, Theme, ToastMessage, Tone } from "@/types"
import AddApplication from "@/pages/AddApplication"
import Dashboard from "@/pages/Dashboard"
import DraftStudio from "@/pages/DraftStudio"
import LinkedInJobFinder from "@/pages/LinkedInJobFinder"
import Outreach from "@/pages/Outreach"
import ReplyCenter from "@/pages/ReplyCenter"
import ResumeLibrary from "@/pages/ResumeLibrary"
import SentHistory from "@/pages/SentHistory"
import Settings from "@/pages/Settings"

interface SearchPage {
  title: string
  subtitle: string
  page: PageName
}

export default function App() {
  const [page, setPage] = useState<PageName>("Dashboard")
  const [menuOpen, setMenuOpen] = useState(false)
  const [revision, setRevision] = useState(0)
  const shell = useAsync(async () => {
    const [accounts, stats] = await Promise.all([fetchAccounts(), fetchStats()])
    const user = await fetchUser().catch(() => null)
    return { user, accounts, stats }
  })
  const roleResumes = useAsync(fetchRoleResumes)
  const libraryResumes = useMemo<Resume[]>(() => {
    const user = shell.data?.user
    const primary: Resume | null =
      user?.resume_path != null && user.resume_path !== ""
        ? {
            id: "primary",
            filename: user.resume_path.split(/[\\/]/).pop() ?? user.resume_path,
            focus: user.resume_role ?? "",
            summary: user.resume_summary ?? undefined,
            updatedAt: "",
            isDefault: true,
            state: "Uploaded",
          }
        : null
    const roleSpecific = (roleResumes.data ?? []).map((item) => ({
      id: String(item.id),
      filename: item.resume_name,
      focus: item.role,
      summary: item.summary ?? undefined,
      updatedAt: item.created_at ?? "",
      isDefault: false,
      state: "Uploaded" as const,
    }))
    return primary ? [primary, ...roleSpecific] : roleSpecific
  }, [roleResumes.data, shell.data?.user])
  const savePrimaryResume = async (focus: string, summary: string) => {
    await updateUserSettings({ resume_role: focus, resume_summary: summary })
    shell.reload()
  }
  const campaigns = useAsync(fetchCampaigns)
  const applicationList = useAsync(() => fetchApplications(0, 60))
  const inbox = useAsync(() => fetchEmailEvents(60))
  const linkedinJobs = useAsync(() => fetchLinkedInJobs({ limit: 200 }))
  const [toast, setToast] = useState<ToastMessage | null>(null)
  const [theme, setTheme] = useState<Theme>(() =>
    localStorage.getItem("command-theme") === "light" ? "light" : "dark",
  )

  useEffect(() => {
    document.documentElement.dataset.theme = theme
    localStorage.setItem("command-theme", theme)
  }, [theme])

  const notify = (message: string, tone: Tone = "neutral") =>
    setToast({ id: Date.now(), message, tone })
  useEffect(() => {
    if (!toast) return
    const timeout = window.setTimeout(() => setToast(null), 2600)
    return () => window.clearTimeout(timeout)
  }, [toast])

  const navigate = (next: PageName) => {
    setPage(next)
    window.scrollTo({ top: 0, behavior: "smooth" })
  }
  const draftFromLinkedIn = (_applicationId: number) => {
    shell.reload()
    setRevision((value) => value + 1)
    linkedinJobs.reload()
    navigate("Draft Studio")
  }
  const sync = () => {
    notify("Syncing Gmail and refreshing your workspace...", "violet")
    syncInbox()
      .then(() => {
        notify("Workspace synced.", "success")
        setRevision((value) => value + 1)
        shell.reload()
      })
      .catch((cause: unknown) => notify(errorMessage(cause), "danger"))
  }
  const searchItems = useMemo<SearchItem[]>(() => {
    const pages: SearchPage[] = [
      {
        title: "Dashboard",
        subtitle: "Job-search overview and next actions",
        page: "Dashboard",
      },
      {
        title: "Add application",
        subtitle: "Start from details, a poster, or a link",
        page: "Add Application",
      },
      {
        title: "Draft Studio",
        subtitle: "Review and send application drafts",
        page: "Draft Studio",
      },
      {
        title: "Reply Center",
        subtitle: "Recruiter conversations that need attention",
        page: "Reply Center",
      },
      {
        title: "Outreach",
        subtitle: "Proactive contact campaigns",
        page: "Outreach",
      },
      {
        title: "LinkedIn Job Finder",
        subtitle: "Collect and filter LinkedIn opportunities",
        page: "LinkedIn Job Finder",
      },
      {
        title: "Resume Library",
        subtitle: "Primary and role-specific resumes",
        page: "Resume Library",
      },
      {
        title: "Sent History",
        subtitle: "Everything delivered through Command",
        page: "Sent History",
      },
      {
        title: "Settings",
        subtitle: "Identity, background, AI, resume, and LinkedIn",
        page: "Settings",
      },
    ]
    return [
      ...pages.map((item) => ({
        ...item,
        id: `page-${item.page}`,
        category: "Page" as const,
      })),
      ...(applicationList.data?.items ?? []).map((item) => ({
        id: `application-${item.id}`,
        title: `${item.company_name ?? "Untitled company"} — ${item.role ?? "Untitled role"}`,
        subtitle: `${statusLabel(item.status)} · ${item.updated_label}`,
        category: "Application" as const,
        page: "Draft Studio" as const,
      })),
      ...(inbox.data?.items ?? []).map((item) => ({
        id: `reply-${item.id}`,
        title: item.subject || "(no subject)",
        subtitle: item.company_name
          ? `${item.sender} · ${item.company_name}`
          : item.sender,
        category: "Conversation" as const,
        page: "Reply Center" as const,
      })),
      ...libraryResumes.map((item) => ({
        id: `resume-${item.id}`,
        title: item.filename,
        subtitle: `${item.focus}${item.isDefault ? " · Primary" : ""}`,
        category: "Resume" as const,
        page: "Resume Library" as const,
      })),
      ...(campaigns.data?.items ?? []).map((item) => ({
        id: `campaign-${item.id}`,
        title: item.name,
        subtitle: `${item.status.charAt(0).toUpperCase()}${item.status.slice(1)} · ${item.sent} of ${item.total} sent`,
        category: "Campaign" as const,
        page: "Outreach" as const,
      })),
      ...(linkedinJobs.data?.items ?? []).map((item) => ({
        id: `linkedin-${item.id}`,
        title: item.role,
        subtitle: `${item.company} · ${item.location}`,
        category: "LinkedIn job" as const,
        page: "LinkedIn Job Finder" as const,
      })),
    ]
  }, [
    applicationList.data,
    campaigns.data,
    inbox.data,
    libraryResumes,
    linkedinJobs.data,
  ])

  let screen
  switch (page) {
    case "Dashboard":
      screen = (
        <Dashboard
          stats={shell.data?.stats ?? null}
          statsLoading={shell.loading}
          statsError={shell.error}
          reloadStats={shell.reload}
          displayName={
            shell.data?.user?.full_name?.trim() ||
            (shell.loading ? "…" : "Candidate")
          }
          revision={revision}
          navigate={navigate}
          notify={notify}
        />
      )
      break
    case "Add Application":
      screen = (
        <AddApplication
          notify={notify}
          revision={revision}
          onDraftCreated={() => {
            shell.reload()
            setRevision((value) => value + 1)
          }}
          onOpenDrafts={() => navigate("Draft Studio")}
          onOpenResumes={() => navigate("Resume Library")}
        />
      )
      break
    case "Draft Studio":
      screen = (
        <DraftStudio
          resumes={libraryResumes}
          navigate={navigate}
          notify={notify}
          revision={revision}
        />
      )
      break
    case "Reply Center":
      screen = (
        <ReplyCenter
          onSync={sync}
          notify={notify}
          navigate={navigate}
          revision={revision}
        />
      )
      break
    case "Outreach":
      screen = (
        <Outreach
          data={campaigns.data}
          loading={campaigns.loading}
          error={campaigns.error}
          reload={campaigns.reload}
          notify={notify}
        />
      )
      break
    case "LinkedIn Job Finder":
      screen = (
        <LinkedInJobFinder
          jobs={linkedinJobs.data}
          loading={linkedinJobs.loading}
          error={linkedinJobs.error}
          reloadJobs={linkedinJobs.reload}
          notify={notify}
          onDrafted={draftFromLinkedIn}
        />
      )
      break
    case "Resume Library":
      screen = (
        <ResumeLibrary
          resumes={libraryResumes}
          loading={roleResumes.loading}
          error={roleResumes.error}
          reload={roleResumes.reload}
          savePrimary={savePrimaryResume}
          notify={notify}
          onSettings={() => navigate("Settings")}
        />
      )
      break
    case "Sent History":
      screen = <SentHistory navigate={navigate} />
      break
    case "Settings":
      screen = (
        <Settings
          theme={theme}
          onTheme={setTheme}
          user={shell.data?.user ?? null}
          reloadUser={shell.reload}
          notify={notify}
          onResumes={() => navigate("Resume Library")}
        />
      )
      break
  }

  return (
    <AppShell
      page={page}
      onNavigate={navigate}
      menuOpen={menuOpen}
      setMenuOpen={setMenuOpen}
      draftCount={shell.data?.stats.drafts_total ?? null}
      weeklyCount={shell.data?.stats.weekly_applications ?? null}
      displayName={
        shell.data?.user?.full_name?.trim() ||
        (shell.loading ? "…" : "Candidate")
      }
      initials={(
        shell.data?.user?.full_name?.trim() ||
        (shell.loading ? "…" : "Candidate")
      )
        .slice(0, 2)
        .toUpperCase()}
      accounts={shell.data?.accounts ?? null}
      toast={toast}
      onDismissToast={() => setToast(null)}
      theme={theme}
      onTheme={() =>
        setTheme((current) => (current === "dark" ? "light" : "dark"))
      }
      onSync={sync}
      searchItems={searchItems}
    >
      {screen}
    </AppShell>
  )
}
