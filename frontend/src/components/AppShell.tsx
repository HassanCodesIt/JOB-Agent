import {
  useEffect,
  useRef,
  useState,
  type KeyboardEvent as ReactKeyboardEvent,
  type ReactNode,
} from "react"
import type { EmailAccounts, PageName, Theme, ToastMessage } from "@/types"
import { Badge, Button, Dialog, Field, Icon, IconButton, Input } from "./ui"

export interface SearchItem {
  id: string
  title: string
  subtitle: string
  category: "Page" | "Application" | "Conversation" | "Resume" | "Campaign" | "LinkedIn job"
  page: PageName
}

const workspace: Array<{
  page: PageName
  label: string
  icon: Parameters<typeof Icon>[0]["name"]
}> = [
  { page: "Dashboard", label: "Dashboard", icon: "apps" },
  { page: "Draft Studio", label: "Drafts", icon: "document" },
  { page: "Reply Center", label: "Reply center", icon: "mail" },
  { page: "Outreach", label: "Outreach", icon: "send" },
  {
    page: "LinkedIn Job Finder",
    label: "LinkedIn Job Finder",
    icon: "linkedin",
  },
  { page: "Resume Library", label: "Resumes", icon: "briefcase" },
]

function Sidebar({
  page,
  onNavigate,
  draftCount,
  weeklyCount,
  displayName,
  initials,
  collapsed,
  onCollapsed,
}: {
  page: PageName
  onNavigate: (page: PageName) => void
  draftCount: number | null
  weeklyCount: number | null
  displayName: string
  initials: string
  collapsed: boolean
  onCollapsed: () => void
}) {
  const pct =
    weeklyCount === null ? 0 : Math.min(100, Math.floor((weeklyCount / 15) * 100))
  return (
    <aside className="sidebar">
      <button
        className="brand"
        onClick={() => onNavigate("Dashboard")}
        aria-label="Command dashboard"
      >
        <span className="brand-mark">
          <Icon name="target" size={17} />
        </span>
        <span className="brand-copy">
          <strong>Command</strong>
          <small>Career workspace</small>
        </span>
      </button>
      <nav className="side-nav" aria-label="Workspace">
        <div className="nav-label">Workspace</div>
        {workspace.map((item) => (
          <button
            key={item.page}
            className={`nav-item ${page === item.page ? "active" : ""}`}
            aria-current={page === item.page ? "page" : undefined}
            onClick={() => onNavigate(item.page)}
            title={collapsed ? item.label : undefined}
          >
            <Icon name={item.icon} size={17} />
            <span>{item.label}</span>
            {item.page === "Draft Studio" &&
              draftCount !== null &&
              draftCount > 0 && (
                <span className="nav-count">{draftCount}</span>
              )}
          </button>
        ))}
        <div className="nav-label nav-section">Account</div>
        <button
          className={`nav-item ${page === "Sent History" ? "active" : ""}`}
          onClick={() => onNavigate("Sent History")}
          title={collapsed ? "Sent history" : undefined}
        >
          <Icon name="clock" size={17} />
          <span>Sent history</span>
        </button>
        <button
          className={`nav-item ${page === "Settings" ? "active" : ""}`}
          onClick={() => onNavigate("Settings")}
          title={collapsed ? "Settings" : undefined}
        >
          <Icon name="settings" size={17} />
          <span>Settings</span>
        </button>
      </nav>
      <div className="sidebar-bottom">
        <button
          className="collapse-nav"
          onClick={onCollapsed}
          aria-label={collapsed ? "Expand navigation" : "Collapse navigation"}
        >
          <Icon name="chevron" size={14} />
          <span>{collapsed ? "Expand" : "Collapse"}</span>
        </button>
        <section className="sidebar-promo">
          <span className="promo-icon">
            <Icon name="sparkles" size={15} />
          </span>
          <strong>Your weekly target</strong>
          <p>
            {weeklyCount === null ? "—" : weeklyCount} of 15 applications sent
          </p>
          <div className="progress-track">
            <span style={{ width: `${pct}%` }} />
          </div>
          <button onClick={() => onNavigate("Draft Studio")}>
            Review drafts <Icon name="arrow" size={12} />
          </button>
        </section>
        <button className="profile-card" onClick={() => onNavigate("Settings")}>
          <span className="avatar">{initials}</span>
          <span>
            <strong>{displayName}</strong>
            <small>Personal workspace</small>
          </span>
          <Icon name="more" size={16} />
        </button>
      </div>
    </aside>
  )
}

function Topbar({
  onMenu,
  onNavigate,
  onSync,
  theme,
  onTheme,
  searchItems,
  accounts,
}: {
  onMenu: () => void
  onNavigate: (page: PageName) => void
  onSync: () => void
  theme: Theme
  onTheme: () => void
  searchItems: SearchItem[]
  accounts: EmailAccounts | null
}) {
  const [accountOpen, setAccountOpen] = useState(false)
  const [connectOpen, setConnectOpen] = useState(false)
  const [query, setQuery] = useState("")
  const [searchOpen, setSearchOpen] = useState(false)
  const [activeResult, setActiveResult] = useState(0)
  const searchRef = useRef<HTMLInputElement>(null)

  const activeEmail = accounts
    ? (accounts.accounts[String(accounts.active)]?.email ?? "") || "—"
    : "—"
  const configuredAccounts = accounts
    ? Object.entries(accounts.accounts).filter(([, info]) => info.configured)
    : []

  useEffect(() => {
    const key = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        event.preventDefault()
        setSearchOpen(true)
        searchRef.current?.focus()
        searchRef.current?.select()
      }
      if (
        event.key === "/" &&
        !["INPUT", "TEXTAREA", "SELECT"].includes(
          (event.target as HTMLElement).tagName,
        )
      ) {
        event.preventDefault()
        setSearchOpen(true)
        searchRef.current?.focus()
      }
    }
    window.addEventListener("keydown", key)
    return () => window.removeEventListener("keydown", key)
  }, [])
  const results = query.trim()
    ? searchItems
        .filter((item) =>
          `${item.title} ${item.subtitle} ${item.category}`
            .toLowerCase()
            .includes(query.toLowerCase()),
        )
        .slice(0, 8)
    : searchItems.filter((item) => item.category === "Page").slice(0, 6)
  const chooseResult = (item: SearchItem) => {
    onNavigate(item.page)
    setQuery("")
    setSearchOpen(false)
  }
  const searchKey = (event: ReactKeyboardEvent<HTMLInputElement>) => {
    if (event.key === "Escape") {
      setSearchOpen(false)
      searchRef.current?.blur()
    }
    if (event.key === "ArrowDown") {
      event.preventDefault()
      setActiveResult((value) => Math.min(results.length - 1, value + 1))
    }
    if (event.key === "ArrowUp") {
      event.preventDefault()
      setActiveResult((value) => Math.max(0, value - 1))
    }
    if (event.key === "Enter" && results[activeResult]) {
      event.preventDefault()
      chooseResult(results[activeResult])
    }
  }

  return (
    <header className="topbar">
      <IconButton
        icon="menu"
        label="Open navigation"
        className="mobile-menu"
        onClick={onMenu}
      />
      <IconButton
        icon="search"
        label="Search Command"
        className="mobile-search-trigger"
        onClick={() => {
          setSearchOpen(true)
          window.setTimeout(() => searchRef.current?.focus(), 20)
        }}
      />
      <div className={`search-box ${searchOpen ? "open" : ""}`}>
        <Icon name="search" size={15} />
        <input
          ref={searchRef}
          id="globalSearch"
          type="search"
          value={query}
          onChange={(event) => setQuery(event.target.value)}
          onFocus={() => setSearchOpen(true)}
          onKeyDown={searchKey}
          placeholder="Search Command..."
          aria-label="Search Command"
          role="combobox"
          aria-expanded={searchOpen}
          aria-controls="commandSearchResults"
        />
        <span className="shortcut">Ctrl K</span>
        {searchOpen && (
          <div
            className="command-search"
            id="commandSearchResults"
            role="listbox"
          >
            <div className="command-search-head">
              <span>{query ? "Search results" : "Quick navigation"}</span>
              <kbd>↑↓ to navigate · Enter to open</kbd>
            </div>
            {results.length ? (
              results.map((item, index) => (
                <button
                  key={item.id}
                  role="option"
                  aria-selected={index === activeResult}
                  className={index === activeResult ? "active" : ""}
                  onMouseEnter={() => setActiveResult(index)}
                  onClick={() => chooseResult(item)}
                >
                  <span className="command-result-icon">
                    <Icon
                      name={
                        item.category === "Page"
                          ? "apps"
                          : item.category === "Application"
                            ? "briefcase"
                            : item.category === "Conversation"
                              ? "mail"
                              : item.category === "Resume"
                                ? "document"
                                : item.category === "Campaign"
                                  ? "send"
                                  : "linkedin"
                      }
                      size={15}
                    />
                  </span>
                  <span>
                    <strong>{item.title}</strong>
                    <small>{item.subtitle}</small>
                  </span>
                  <Badge tone="neutral">{item.category}</Badge>
                </button>
              ))
            ) : (
              <div className="command-empty">
                <Icon name="search" />
                <strong>No results for “{query}”</strong>
                <span>
                  Try a company, role, conversation, resume, or page name.
                </span>
              </div>
            )}
          </div>
        )}
      </div>
      <div className="topbar-actions">
        <div className="account-switcher">
          <button
            className="account-trigger"
            onClick={() => setAccountOpen(!accountOpen)}
            aria-expanded={accountOpen}
          >
            <span className="account-avatar">
              {activeEmail === "—" ? "?" : activeEmail[0]?.toUpperCase()}
            </span>
            <span className="account-copy">
              <small>Sending from</small>
              <strong>{activeEmail}</strong>
            </span>
            <Icon name="chevron" size={13} />
          </button>
          {accountOpen && (
            <div className="account-menu">
              <span>Connected accounts</span>
              {configuredAccounts.length ? (
                configuredAccounts.map(([slot, info]) => (
                  <button key={slot} onClick={() => setAccountOpen(false)}>
                    <span className="account-avatar">
                      {info.email[0]?.toUpperCase()}
                    </span>
                    <span>
                      <strong>{info.email}</strong>
                      <small>
                        {String(accounts?.active) === slot
                          ? "Active account"
                          : "Connected"}
                      </small>
                    </span>
                    {String(accounts?.active) === slot && (
                      <Icon name="check" size={14} />
                    )}
                  </button>
                ))
              ) : (
                <div className="command-empty">
                  <Icon name="mail" />
                  <strong>No accounts yet</strong>
                </div>
              )}
              <button
                onClick={() => {
                  setConnectOpen(true)
                  setAccountOpen(false)
                }}
              >
                <Icon name="add" size={14} />
                Connect another account
              </button>
            </div>
          )}
        </div>
        <IconButton
          icon={theme === "dark" ? "sun" : "moon"}
          label={`Switch to ${theme === "dark" ? "light" : "dark"} mode`}
          onClick={onTheme}
        />
        <Button
          className="sync-button"
          variant="ghost"
          icon="refresh"
          onClick={onSync}
        >
          Sync
        </Button>
        <Button
          className="topbar-add"
          variant="primary"
          icon="add"
          onClick={() => onNavigate("Add Application")}
        >
          Add application
        </Button>
      </div>
      <Dialog
        open={connectOpen}
        onClose={() => setConnectOpen(false)}
        title="Connect a sending account"
        description="Use an app password to connect another sending account."
        footer={
          <>
            <Button onClick={() => setConnectOpen(false)}>Cancel</Button>
            <Button variant="primary" onClick={() => setConnectOpen(false)}>
              Connect account
            </Button>
          </>
        }
      >
        <div className="form-stack">
          <Field label="Email address">
            <Input type="email" placeholder="you@example.com" />
          </Field>
          <Field
            label="App password"
            hint="For Google accounts, create an App password in your account security settings."
          >
            <Input type="password" placeholder="App password" />
          </Field>
        </div>
      </Dialog>
    </header>
  )
}

export function AppShell({
  page,
  onNavigate,
  menuOpen,
  setMenuOpen,
  draftCount,
  weeklyCount,
  displayName,
  initials,
  accounts,
  toast,
  onDismissToast,
  theme,
  onTheme,
  onSync,
  searchItems,
  children,
}: {
  page: PageName
  onNavigate: (page: PageName) => void
  menuOpen: boolean
  setMenuOpen: (open: boolean) => void
  draftCount: number | null
  weeklyCount: number | null
  displayName: string
  initials: string
  accounts: EmailAccounts | null
  toast: ToastMessage | null
  onDismissToast: () => void
  theme: Theme
  onTheme: () => void
  onSync: () => void
  searchItems: SearchItem[]
  children: ReactNode
}) {
  const [collapsed, setCollapsed] = useState(
    () => localStorage.getItem("command-sidebar") === "collapsed",
  )
  useEffect(
    () =>
      localStorage.setItem(
        "command-sidebar",
        collapsed ? "collapsed" : "expanded",
      ),
    [collapsed],
  )
  const navigate = (next: PageName) => {
    onNavigate(next)
    setMenuOpen(false)
  }
  return (
    <div className={`app-shell ${collapsed ? "sidebar-collapsed" : ""}`}>
      <div className={`sidebar-shell ${menuOpen ? "open" : ""}`}>
        <Sidebar
          page={page}
          onNavigate={navigate}
          draftCount={draftCount}
          weeklyCount={weeklyCount}
          displayName={displayName}
          initials={initials}
          collapsed={collapsed}
          onCollapsed={() => setCollapsed((value) => !value)}
        />
      </div>
      {menuOpen && (
        <button
          className="mobile-scrim"
          aria-label="Close navigation"
          onClick={() => setMenuOpen(false)}
        />
      )}
      <section className="main-shell">
        <Topbar
          onMenu={() => setMenuOpen(true)}
          onNavigate={navigate}
          onSync={onSync}
          theme={theme}
          onTheme={onTheme}
          searchItems={searchItems}
          accounts={accounts}
        />
        {children}
      </section>
      {toast && (
        <div
          className={`toast toast-${toast.tone ?? "neutral"}`}
          role={toast.tone === "danger" ? "alert" : "status"}
        >
          <span className="toast-symbol">
            <Icon
              name={
                toast.tone === "success"
                  ? "check"
                  : toast.tone === "warning" || toast.tone === "danger"
                    ? "warning"
                    : toast.tone === "violet"
                      ? "sparkles"
                      : "activity"
              }
              size={16}
            />
          </span>
          <span className="toast-message">{toast.message}</span>
          <IconButton
            icon="close"
            label="Dismiss notification"
            onClick={onDismissToast}
          />
        </div>
      )}
    </div>
  )
}
