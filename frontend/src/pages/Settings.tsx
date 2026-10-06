import { useEffect, useRef, useState } from "react"
import {
  errorMessage,
  fetchLinkedInFilterSettings,
  fetchLinkedInSearchSettings,
  saveLinkedInFilterSettings,
  saveLinkedInSearchSettings,
  updateUserSettings,
  uploadPrimaryResume,
} from "@/api"
import { useAsync } from "@/hooks/useAsync"
import type { LinkedInFilterSettings, Theme, UserProfile } from "@/types"
import {
  Badge,
  Button,
  Field,
  Icon,
  IconButton,
  Input,
  PageHeader,
  Select,
  Status,
  Textarea,
} from "@/components/ui"

const tabs = [
  "Identity & contact",
  "Background",
  "AI configuration",
  "Resume",
  "LinkedIn",
]
const defaultFilterPrompt =
  "Accept fresher or entry-level roles only. Accept roles requiring at most 1 year of experience. Accept the JD when no experience requirement is mentioned. Reject roles that clearly require more than 1 year of experience."

function buildSummary(profile: ProfileFields): string {
  return `Full Name: ${profile.name}\nEmail: ${profile.email}\nPhone: ${profile.phone}\nGitHub: ${profile.github}\nLinkedIn: ${profile.linkedin}\nPortfolio: ${profile.portfolio}\nSkills: ${profile.skills}\nExperience: ${profile.experience}\nProjects: ${profile.projects}\nBio: ${profile.bio}\nDrafting Instructions: ${profile.instructions}`
}

function basename(path: string | null | undefined): string {
  if (!path) return ""
  return path.split(/[\\/]/).pop() ?? path
}

interface ProfileFields {
  name: string
  email: string
  phone: string
  github: string
  linkedin: string
  portfolio: string
  skills: string
  experience: string
  projects: string
  bio: string
  instructions: string
  groq: string
  openrouter: string
  hf: string
  resumeRole: string
}

const emptyProfile: ProfileFields = {
  name: "",
  email: "",
  phone: "",
  github: "",
  linkedin: "",
  portfolio: "",
  skills: "",
  experience: "",
  projects: "",
  bio: "",
  instructions: "",
  groq: "",
  openrouter: "",
  hf: "",
  resumeRole: "",
}

function profileFromUser(user: UserProfile): ProfileFields {
  return {
    name: user.full_name ?? "",
    email: user.email ?? "",
    phone: user.phone ?? "",
    github: user.github_link ?? "",
    linkedin: user.linkedin_link ?? "",
    portfolio: user.portfolio_link ?? "",
    skills: user.skills ?? "",
    experience: user.experience ?? "",
    projects: user.projects ?? "",
    bio: user.standard_answers ?? "",
    instructions: user.system_prompt ?? "",
    groq: user.groq_api_key ?? "",
    openrouter: user.openrouter_api_key ?? "",
    hf: user.hf_token ?? "",
    resumeRole: user.resume_role ?? "",
  }
}

const sortOptions = [
  { value: "__linkedin_default__", label: "LinkedIn default" },
  { value: "latest", label: "Most recent" },
  { value: "relevance", label: "Most relevant" },
]
const dateOptions = [
  { value: "any", label: "Any time" },
  { value: "past_24_hours", label: "Past 24 hours" },
]
const defaultRoles = [
  "Generative AI Engineer",
  "AI Developer",
  "LLM Engineer",
  "Applied AI Engineer",
]

export default function Settings({
  theme,
  onTheme,
  user,
  reloadUser,
  notify,
  onResumes,
}: {
  theme: Theme
  onTheme: (theme: Theme) => void
  user: UserProfile | null
  reloadUser: () => void
  notify: (
    message: string,
    tone?: "neutral" | "success" | "warning" | "danger" | "violet",
  ) => void
  onResumes: () => void
}) {
  const [tab, setTab] = useState(tabs[0])
  const [saveStatus, setSaveStatus] = useState("")
  const [saveError, setSaveError] = useState(false)
  const [saving, setSaving] = useState(false)
  const [showSecrets, setShowSecrets] = useState<Record<string, boolean>>({})
  const [profile, setProfile] = useState<ProfileFields>(emptyProfile)
  const [profileSummary, setProfileSummary] = useState(
    buildSummary(emptyProfile),
  )
  const [filterPrompt, setFilterPrompt] = useState(defaultFilterPrompt)
  const [batchSize, setBatchSize] = useState("20")
  const [maxJdChars, setMaxJdChars] = useState("6000")
  const [maxExperience, setMaxExperience] = useState("1")
  const [acceptUnspecified, setAcceptUnspecified] = useState(true)
  const [modelLabel, setModelLabel] = useState("Groq — openai/gpt-oss-120b")
  const [defaultRole, setDefaultRole] = useState("")
  const [sortBy, setSortBy] = useState("relevance")
  const [datePosted, setDatePosted] = useState("any")
  const [savedRoles, setSavedRoles] = useState(
    "Generative AI Engineer\nAI Developer\nLLM Engineer\nApplied AI Engineer",
  )
  const [acceptFresher, setAcceptFresher] = useState(true)
  const [advanced, setAdvanced] = useState(false)
  const seededRef = useRef(false)
  const dirtyRef = useRef(false)
  const linkedinDirtyRef = useRef(false)

  const linkedin = useAsync(async () => {
    const [filter, search] = await Promise.all([
      fetchLinkedInFilterSettings(),
      fetchLinkedInSearchSettings(),
    ])
    return { filter: filter.settings, search: search.settings }
  })

  useEffect(() => {
    if (!user) return
    if (seededRef.current && dirtyRef.current) return
    const next = profileFromUser(user)
    setProfile(next)
    setProfileSummary(user.profile_summary || buildSummary(next))
    seededRef.current = true
    dirtyRef.current = false
  }, [user])

  useEffect(() => {
    if (!linkedin.data) return
    const { filter, search } = linkedin.data
    setFilterPrompt(filter.prompt || defaultFilterPrompt)
    setBatchSize(String(filter.batch_size))
    setMaxJdChars(String(filter.max_jd_chars))
    setMaxExperience(String(filter.max_experience_years))
    setAcceptUnspecified(filter.accept_unspecified_experience)
    setModelLabel(filter.model_label || `Groq — ${filter.model}`)
    setDefaultRole(search.default_role ?? "")
    setSortBy(search.sort_by || "relevance")
    setDatePosted(search.date_posted || "any")
    linkedinDirtyRef.current = false
  }, [linkedin.data])

  const update = (key: keyof ProfileFields, value: string) => {
    const next = { ...profile, [key]: value }
    setProfile(next)
    dirtyRef.current = true
    setProfileSummary(buildSummary(next))
  }

  const applySummary = () => {
    const map: Record<string, keyof ProfileFields> = {
      "Full Name": "name",
      Email: "email",
      Phone: "phone",
      GitHub: "github",
      LinkedIn: "linkedin",
      Portfolio: "portfolio",
      Skills: "skills",
      Experience: "experience",
      Projects: "projects",
      Bio: "bio",
      "Drafting Instructions": "instructions",
    }
    const next = { ...profile }
    let count = 0
    profileSummary.split("\n").forEach((line) => {
      const index = line.indexOf(":")
      if (index > 0) {
        const key = line.slice(0, index).trim()
        const value = line.slice(index + 1).trim()
        if (map[key] && value) {
          next[map[key]] = value
          count++
        }
      }
    })
    setProfile(next)
    dirtyRef.current = true
    setSaveError(false)
    setSaveStatus(
      count
        ? `Applied ${count} section(s) to your fields.`
        : "Nothing new to apply…",
    )
  }

  const save = async () => {
    if (saving) return
    setSaving(true)
    setSaveError(false)
    setSaveStatus("Saving configuration…")
    try {
      await updateUserSettings({
        full_name: profile.name,
        email: profile.email,
        phone: profile.phone,
        github_link: profile.github,
        linkedin_link: profile.linkedin,
        portfolio_link: profile.portfolio,
        skills: profile.skills,
        experience: profile.experience,
        projects: profile.projects,
        standard_answers: profile.bio,
        system_prompt: profile.instructions,
        groq_api_key: profile.groq,
        openrouter_api_key: profile.openrouter,
        hf_token: profile.hf,
        resume_role: profile.resumeRole,
        profile_summary: profileSummary,
      })
      dirtyRef.current = false
      if (linkedin.data && linkedinDirtyRef.current) {
        const years = Number(maxExperience)
        await Promise.all([
          saveLinkedInSearchSettings({
            default_role: defaultRole,
            sort_by:
              sortBy === "__linkedin_default__" || !sortBy
                ? "relevance"
                : sortBy,
            date_posted: datePosted || "any",
          }),
          saveLinkedInFilterSettings({
            prompt: filterPrompt,
            max_experience_years: Number.isFinite(years) ? years : undefined,
            accept_unspecified_experience: acceptUnspecified,
            batch_size: Number(batchSize) || undefined,
            max_jd_chars: Number(maxJdChars) || undefined,
          }),
        ])
        linkedinDirtyRef.current = false
      }
      reloadUser()
      setSaveStatus("Settings saved.")
      notify("Settings saved.", "success")
    } catch (cause: unknown) {
      const message = errorMessage(cause)
      setSaveError(true)
      setSaveStatus(message)
      notify(message, "danger")
    } finally {
      setSaving(false)
    }
  }

  const resetFilterPrompt = async () => {
    try {
      const result = await saveLinkedInFilterSettings({
        regenerate_prompt: true,
      })
      setFilterPrompt(result.settings.prompt || defaultFilterPrompt)
      notify("Filter prompt reset to default.", "success")
    } catch (cause: unknown) {
      notify(errorMessage(cause), "danger")
    }
  }

  const uploadPrimary = async (file?: File) => {
    if (!file) return
    try {
      await uploadPrimaryResume(file)
      reloadUser()
      notify("Resume updated", "success")
    } catch (cause: unknown) {
      notify(errorMessage(cause), "danger")
    }
  }

  const primaryFilename = basename(user?.resume_path) || "No file uploaded"
  const roleSelectValues = defaultRoles.includes(defaultRole)
    ? defaultRoles
    : defaultRole
      ? [defaultRole, ...defaultRoles]
      : defaultRoles

  return (
    <main className="content">
      <PageHeader
        eyebrow="Settings"
        title="Your global configuration"
        description="These details are injected into every draft, application, and reply the agent writes."
        actions={
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save changes"}
          </Button>
        }
      />
      <div
        className="settings-tabs"
        role="tablist"
        aria-label="Settings sections"
      >
        {tabs.map((item) => (
          <button
            role="tab"
            aria-selected={tab === item}
            className={tab === item ? "active" : ""}
            key={item}
            onClick={() => setTab(item)}
          >
            {item}
          </button>
        ))}
      </div>
      <section className="card settings-panel canonical-settings">
        {tab === "Identity & contact" && (
          <>
            <div className="panel-title">
              <span className="stat-icon violet">
                <Icon name="user" />
              </span>
              <div>
                <h2>Identity &amp; contact</h2>
                <p>Used to sign off outgoing applications and emails</p>
              </div>
            </div>
            <div className="form-row">
              <Field label="Full name">
                <Input
                  value={profile.name}
                  onChange={(event) => update("name", event.target.value)}
                />
              </Field>
              <Field label="Email">
                <Input
                  type="email"
                  value={profile.email}
                  onChange={(event) => update("email", event.target.value)}
                />
              </Field>
            </div>
            <div className="form-row">
              <Field label="Phone">
                <Input
                  value={profile.phone}
                  onChange={(event) => update("phone", event.target.value)}
                />
              </Field>
              <Field label="GitHub">
                <Input
                  value={profile.github}
                  onChange={(event) => update("github", event.target.value)}
                />
              </Field>
            </div>
            <div className="form-row">
              <Field label="LinkedIn">
                <Input
                  value={profile.linkedin}
                  onChange={(event) => update("linkedin", event.target.value)}
                />
              </Field>
              <Field label="Portfolio">
                <Input
                  value={profile.portfolio}
                  onChange={(event) => update("portfolio", event.target.value)}
                />
              </Field>
            </div>
            <Field label="Core skills">
              <Textarea
                rows={5}
                value={profile.skills}
                onChange={(event) => update("skills", event.target.value)}
              />
            </Field>
          </>
        )}
        {tab === "Background" && (
          <>
            <div className="prompt-box compact">
              <span className="stat-icon violet">
                <Icon name="sparkles" />
              </span>
              <div>
                <h2>How to generate your profile summary</h2>
                <button
                  className="prompt-copy-text"
                  onClick={() => {
                    navigator.clipboard.writeText(
                      "Summarize my professional profile using labelled sections for experience, projects, skills, bio, and drafting instructions.",
                    )
                    notify("Prompt copied.", "success")
                  }}
                >
                  Summarize my professional profile using labelled sections for
                  Command.<span>Copy prompt</span>
                </button>
              </div>
            </div>
            <Field
              label="Profile summary"
              hint="Changes in the fields rebuild this summary. Apply can update the fields from labelled lines."
            >
              <Textarea
                rows={12}
                value={profileSummary}
                onChange={(event) => setProfileSummary(event.target.value)}
              />
            </Field>
            <div className="inline-actions">
              <Button onClick={() => setProfileSummary(buildSummary(profile))}>
                Rebuild
              </Button>
              <Button variant="primary" onClick={applySummary}>
                Apply to fields
              </Button>
            </div>
            <Field label="Experience">
              <Textarea
                rows={6}
                value={profile.experience}
                onChange={(event) => update("experience", event.target.value)}
              />
            </Field>
            <Field label="Projects">
              <Textarea
                rows={6}
                value={profile.projects}
                onChange={(event) => update("projects", event.target.value)}
              />
            </Field>
            <Field label="Standard answers &amp; bio">
              <Textarea
                rows={6}
                value={profile.bio}
                onChange={(event) => update("bio", event.target.value)}
              />
            </Field>
          </>
        )}
        {tab === "AI configuration" && (
          <>
            <div className="panel-title">
              <span className="stat-icon blue">
                <Icon name="sparkles" />
              </span>
              <div>
                <h2>AI configuration</h2>
                <p>
                  Optional provider credentials used by the real application
                </p>
              </div>
            </div>
            {[
              ["groq", "Groq key", "Primary drafting model."],
              [
                "openrouter",
                "OpenRouter key",
                "Used automatically when Groq is unavailable.",
              ],
              [
                "hf",
                "Hugging Face token",
                "Optional. Raises OCR limits for poster processing.",
              ],
            ].map(([id, label, help]) => (
              <Field key={id} label={label} hint={help}>
                <div className="input-with-action">
                  <Input
                    type={showSecrets[id] ? "text" : "password"}
                    placeholder="Not configured"
                    value={profile[(id as keyof ProfileFields)]}
                    onChange={(event) =>
                      update(id as keyof ProfileFields, event.target.value)
                    }
                  />
                  <IconButton
                    className="input-action"
                    icon="eye"
                    label={`${showSecrets[id] ? "Hide" : "Show"} ${label}`}
                    onClick={() =>
                      setShowSecrets({ ...showSecrets, [id]: !showSecrets[id] })
                    }
                  />
                </div>
              </Field>
            ))}
            <Field label="Custom drafting instructions">
              <Textarea
                rows={8}
                value={profile.instructions}
                onChange={(event) => update("instructions", event.target.value)}
              />
            </Field>
          </>
        )}
        {tab === "Resume" && (
          <>
            <div className="panel-title">
              <span className="stat-icon green">
                <Icon name="document" />
              </span>
              <div>
                <h2>Primary resume</h2>
                <p>Used when no role-specific resume is selected</p>
              </div>
            </div>
            <label className="file-picker">
              <span>
                <Icon name="document" />
                <strong>{primaryFilename}</strong>
              </span>
              <span className="button button-secondary">Upload new</span>
              <input
                hidden
                type="file"
                accept="application/pdf"
                onChange={(event) => uploadPrimary(event.target.files?.[0])}
              />
            </label>
            <Field label="Target role for this resume">
              <Input
                value={profile.resumeRole}
                placeholder="e.g. AI Engineer"
                onChange={(event) => update("resumeRole", event.target.value)}
              />
            </Field>
            <Button variant="ghost" onClick={onResumes}>
              Manage role-specific resumes <Icon name="arrow" size={12} />
            </Button>
          </>
        )}
        {tab === "LinkedIn" && (
          <>
            <div className="panel-title">
              <span className="stat-icon blue">
                <Icon name="linkedin" />
              </span>
              <div>
                <h2>LinkedIn</h2>
                <p>Defaults for job collection and relevance filtering</p>
              </div>
            </div>
            {linkedin.error && (
              <div className="form-note err">
                LinkedIn settings could not be loaded ({linkedin.error}).
                Changes to this section will not be saved.
              </div>
            )}
            <h3 className="settings-subtitle">Search settings</h3>
            <div className="form-row">
              <Field label="Default role">
                <Select
                  value={defaultRole}
                  onChange={(event) => {
                    setDefaultRole(event.target.value)
                    linkedinDirtyRef.current = true
                  }}
                >
                  <option value="">Select a role…</option>
                  {roleSelectValues.map((role) => (
                    <option key={role} value={role}>
                      {role}
                    </option>
                  ))}
                </Select>
              </Field>
              <Field label="Default sort">
                <Select
                  value={sortBy}
                  onChange={(event) => {
                    setSortBy(event.target.value)
                    linkedinDirtyRef.current = true
                  }}
                >
                  {sortOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <div className="form-row">
              <Field
                label="Saved roles"
                hint="Session-only: the backend has no saved-roles field, so this list is not stored."
              >
                <Textarea
                  rows={5}
                  value={savedRoles}
                  onChange={(event) => setSavedRoles(event.target.value)}
                />
              </Field>
              <Field label="Default date">
                <Select
                  value={datePosted}
                  onChange={(event) => {
                    setDatePosted(event.target.value)
                    linkedinDirtyRef.current = true
                  }}
                >
                  {dateOptions.map((option) => (
                    <option key={option.value} value={option.value}>
                      {option.label}
                    </option>
                  ))}
                </Select>
              </Field>
            </div>
            <h3 className="settings-subtitle">Filtering settings</h3>
            <div className="settings-title-row">
              <Status tone="violet">Optimized filtering</Status>
              <span>
                <Badge tone="violet">{modelLabel}</Badge>
              </span>
            </div>
            <div className="form-row">
              <Field label="Maximum experience">
                <Select
                  value={maxExperience}
                  onChange={(event) => {
                    setMaxExperience(event.target.value)
                    linkedinDirtyRef.current = true
                  }}
                >
                  <option value="1">1 year</option>
                </Select>
              </Field>
              <div className="toggle-stack">
                <label title="The filter prompt always starts with the fresher/entry-level acceptance line.">
                  <input
                    type="checkbox"
                    checked={acceptFresher}
                    onChange={(event) => setAcceptFresher(event.target.checked)}
                  />
                  Accept fresher
                </label>
                <label>
                  <input
                    type="checkbox"
                    checked={acceptUnspecified}
                    onChange={(event) => {
                      setAcceptUnspecified(event.target.checked)
                      linkedinDirtyRef.current = true
                    }}
                  />
                  Accept unspecified experience
                </label>
              </div>
            </div>
            <Field
              label="Filter prompt"
              hint="Only cleaned job-description text is sent. Decisions are Yes/No per job."
            >
              <Textarea
                rows={7}
                value={filterPrompt}
                onChange={(event) => {
                  setFilterPrompt(event.target.value)
                  linkedinDirtyRef.current = true
                }}
              />
            </Field>
            <button
              className="advanced-toggle"
              onClick={() => setAdvanced(!advanced)}
            >
              Advanced options <span>{advanced ? "Hide" : "Show"}</span>
            </button>
            {advanced && (
              <div className="form-row advanced-panel">
                <Field label="Batch size">
                  <Input
                    type="number"
                    value={batchSize}
                    onChange={(event) => {
                      setBatchSize(event.target.value)
                      linkedinDirtyRef.current = true
                    }}
                  />
                </Field>
                <Field label="Maximum JD characters">
                  <Input
                    type="number"
                    value={maxJdChars}
                    onChange={(event) => {
                      setMaxJdChars(event.target.value)
                      linkedinDirtyRef.current = true
                    }}
                  />
                </Field>
              </div>
            )}
            <Button onClick={resetFilterPrompt}>Reset to default</Button>
          </>
        )}
        <div className="theme-setting">
          <div>
            <strong>Appearance</strong>
            <p>Use the same Command design system in dark or light mode.</p>
          </div>
          <div role="group" aria-label="Theme">
            <Button
              variant={theme === "dark" ? "primary" : "secondary"}
              icon="moon"
              onClick={() => onTheme("dark")}
            >
              Dark mode
            </Button>
            <Button
              variant={theme === "light" ? "primary" : "secondary"}
              icon="sun"
              onClick={() => onTheme("light")}
            >
              Light mode
            </Button>
          </div>
        </div>
        <footer className="settings-footer">
          <span
            className={
              saveStatus
                ? saveError
                  ? "form-note err"
                  : "form-note ok"
                : "form-note"
            }
          >
            {saveStatus}
          </span>
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save changes"}
          </Button>
        </footer>
      </section>
    </main>
  )
}

export function FilterSettings({ notify }: {
  notify?: (
    message: string,
    tone?: "neutral" | "success" | "warning" | "danger" | "violet",
  ) => void
} = {}) {
  const settings = useAsync(fetchLinkedInFilterSettings)
  const [prompt, setPrompt] = useState("")
  const [maxExperience, setMaxExperience] = useState("1")
  const [acceptUnspecified, setAcceptUnspecified] = useState(true)
  const [batchSize, setBatchSize] = useState("8")
  const [maxJdChars, setMaxJdChars] = useState("4000")
  const [saving, setSaving] = useState(false)
  const [status, setStatus] = useState("")
  const [statusError, setStatusError] = useState(false)
  const [advanced, setAdvanced] = useState(false)

  const apply = (value: LinkedInFilterSettings) => {
    setPrompt(value.prompt || defaultFilterPrompt)
    setMaxExperience(String(value.max_experience_years))
    setAcceptUnspecified(value.accept_unspecified_experience)
    setBatchSize(String(value.batch_size))
    setMaxJdChars(String(value.max_jd_chars))
  }

  useEffect(() => {
    if (settings.data) apply(settings.data.settings)
  }, [settings.data])

  const experienceOptions = ["0", "0.5", "1", "1.5", "2", "3", "5", "10"]
  if (!experienceOptions.includes(maxExperience)) {
    experienceOptions.push(maxExperience)
  }

  const save = async () => {
    if (saving) return
    setSaving(true)
    setStatusError(false)
    setStatus("Saving…")
    try {
      const years = Number(maxExperience)
      const result = await saveLinkedInFilterSettings({
        prompt,
        max_experience_years: Number.isFinite(years) ? years : undefined,
        accept_unspecified_experience: acceptUnspecified,
        batch_size: Number(batchSize) || undefined,
        max_jd_chars: Number(maxJdChars) || undefined,
      })
      apply(result.settings)
      setStatus(`Saved · prompt version ${result.settings.prompt_version}`)
      notify?.("Filter settings saved.", "success")
    } catch (cause: unknown) {
      setStatusError(true)
      setStatus(
        cause instanceof Error ? cause.message : "Could not save settings.",
      )
      notify?.(
        cause instanceof Error ? cause.message : "Could not save settings.",
        "danger",
      )
    } finally {
      setSaving(false)
    }
  }

  const resetPrompt = async () => {
    if (saving) return
    setSaving(true)
    setStatusError(false)
    setStatus("Resetting…")
    try {
      const result = await saveLinkedInFilterSettings({
        regenerate_prompt: true,
      })
      apply(result.settings)
      setStatus(`Reset · prompt version ${result.settings.prompt_version}`)
      notify?.("Filter prompt reset to default.", "success")
    } catch (cause: unknown) {
      setStatusError(true)
      setStatus(
        cause instanceof Error ? cause.message : "Could not reset the prompt.",
      )
      notify?.(
        cause instanceof Error ? cause.message : "Could not reset the prompt.",
        "danger",
      )
    } finally {
      setSaving(false)
    }
  }

  if (settings.loading && !settings.data) {
    return <p className="form-note">Loading filter settings…</p>
  }
  if (settings.error && !settings.data) {
    return (
      <p className="form-note err">
        LinkedIn filter settings could not be loaded ({settings.error}).
      </p>
    )
  }

  return (
    <div className="filter-settings">
      <div className="settings-title-row">
        <div>
          <Status tone="violet">Optimized filtering</Status>
          <p>
            Only cleaned job-description text is sent. Decisions are Yes/No per
            job.
          </p>
        </div>
        <Badge tone="violet">
          {settings.data?.settings.model_label ?? "Filtering model"}
        </Badge>
      </div>
      <div className="form-row">
        <Field label="Maximum experience">
          <Select
            value={maxExperience}
            onChange={(event) => setMaxExperience(event.target.value)}
          >
            {experienceOptions.map((value) => (
              <option key={value} value={value}>
                {value === "1" ? "1 year" : `${value} years`}
              </option>
            ))}
          </Select>
        </Field>
        <div className="toggle-stack">
          <label title="The filter prompt always starts with the fresher/entry-level acceptance line.">
            <input type="checkbox" checked disabled />
            Accept fresher
          </label>
          <label>
            <input
              type="checkbox"
              checked={acceptUnspecified}
              onChange={(event) => setAcceptUnspecified(event.target.checked)}
            />
            Accept unspecified experience
          </label>
        </div>
      </div>
      <Field
        label="Filtering prompt"
        hint="Editing the prompt bumps its version, so decided jobs are re-checked on the next filter run."
      >
        <Textarea
          rows={7}
          value={prompt}
          onChange={(event) => setPrompt(event.target.value)}
        />
      </Field>
      <button
        className="advanced-toggle"
        onClick={() => setAdvanced(!advanced)}
      >
        Advanced options <span>{advanced ? "Hide" : "Show"}</span>
      </button>
      {advanced && (
        <div className="form-row advanced-panel">
          <Field label="Batch size">
            <Input
              type="number"
              value={batchSize}
              onChange={(event) => setBatchSize(event.target.value)}
            />
          </Field>
          <Field label="Maximum JD characters">
            <Input
              type="number"
              value={maxJdChars}
              onChange={(event) => setMaxJdChars(event.target.value)}
            />
          </Field>
        </div>
      )}
      <div className="inline-actions">
        <Button disabled={saving} onClick={resetPrompt}>
          Reset to Default
        </Button>
        <Button variant="primary" disabled={saving} onClick={save}>
          {saving ? "Saving…" : "Save Changes"}
        </Button>
        <span className={statusError ? "form-note err" : "form-note"}>
          {status}
        </span>
      </div>
    </div>
  )
}
