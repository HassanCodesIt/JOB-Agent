# AI Job Assistant — UI/UX Discovery Document

Reverse-engineered reference for reproducing the existing "Command — Career Workspace" UI.
**No part of this document proposes a redesign.** Every screen, class name, string, state, and
interaction below is transcribed from the inspected source, with exact file/line references.
Anything that cannot be proven from code is marked:

- `Not determinable from inspected code.`
- `Backend capability — no confirmed current UI.`

Inspected root: `C:\Users\hassa\OneDrive\Desktop\GJ Projects\AI Job assistant`

---

## 1. Architecture overview

- Server-rendered **FastAPI + Jinja2** app; one shared shell template (`templates/base.html`)
  extended by every page except `/setup`, which is a standalone document.
- **Vanilla JS only** — no framework, no build step. One shared behaviour layer
  `static/app.js` (exposes `window.ui` plus legacy globals) and per-page inline
  `<script>` blocks inside `{% block scripts %}`.
- **One stylesheet**: `static/style.css` (hand-written, 3395 lines, sectioned 1–12 plus
  Settings / Onboarding / Utilities blocks). Cache-busted with `?v=2.0` (base) and `?v=3` (setup).
- Icons are an **inline SVG sprite** in `base.html` (`<symbol id="i-…">`, base.html:15–117);
  `setup.html` carries its own reduced sprite (setup.html:15–38).
- A Jinja **context processor** supplies shell values to every page:
  `now`, `weekly_applications`, `nav_draft_count`, `shell_user`, `display_name`, `initials`
  (main.py:91–121, registered main.py:120–121).
- Data layer: SQLAlchemy models (`models.py`), Pydantic schemas (`schemas.py`);
  DB tables auto-created on boot (main.py:61).
- Services behind the UI: `llm_service.py` (Groq `openai/gpt-oss-120b` + OpenRouter fallback),
  `ocr_service.py` (poster OCR via HF Router), `email_service.py` (IMAP inbox sync + LLM
  classification), `email_sender.py` (SMTP send), `bulk_service.py` (campaign loop),
  `automation_service.py` (Playwright form detect/fill), `email_config.py` (2 account slots).
- Background work: FastAPI `BackgroundTasks` (`process_application`, campaign loops) —
  pages reflect progress through DB status polling and page reloads, not websockets.

## 2. Tech stack & build constraints

- Python / FastAPI (`main.py`, app title "Auto Job Application Agent", main.py:65).
- Templates: `templates/*.html` (Jinja), static: `static/style.css`, `static/app.js`.
- Font: **Manrope** (Google Fonts `@import` in style.css:7; setup.html:11 loads it directly;
  base.html:8–9 only preconnects). Fallback stack `'Manrope', 'Outfit', system-ui, sans-serif` (style.css:69).
- No CSS framework, no bundler, no TypeScript, no test suite found.
- Entry: `run.py` → uvicorn `127.0.0.1:8000`.
- Uncommitted/new files in working tree (as of inspection): `static/app.js`, `templates/base.html`,
  `templates/partials/`, `templates/resumes.html`, `email_config.py`, plus modified
  `main.py`, `models.py`, `schemas.py`, `static/style.css` and most templates.
  Only one commit exists: `bf0ca3d Initialize project…`.

## 3. Routing, guards, and context pipeline

- Every HTML page route calls `is_setup_complete(db)` (main.py:610) and redirects
  **307 → `/setup`** when the profile is missing. `/setup` itself redirects 307 → `/`
  when setup is already complete (main.py:616–617).
- Page routes (all `response_class=HTMLResponse`):

  | Route | Handler | Template | main.py |
  |---|---|---|---|
  | `GET /setup` | `setup_page` | `setup.html` | 614 |
  | `GET /` | `dashboard` | `dashboard.html` | 711 |
  | `GET /sent` | `sent_mails_page` | `sent_mails.html` | 916 |
  | `GET /apply` | `apply_page` | `apply.html` | 940 |
  | `GET /settings` | `settings_page` | `settings.html` | 974 |
  | `GET /drafts` | `drafts_page` | `drafts.html` | 1292 |
  | `GET /replies` | `replies_page` | `replies.html` | 1334 |
  | `GET /replies/{app_id}` | `reply_editor` | `reply_editor.html` | 1362 |
  | `GET /outreach` | (outreach page) | `outreach.html` | 2034 **and 2036 — duplicate decorator, harmless** |
  | `GET /resumes` | `resumes_page` | `resumes.html` | 2425 |

- Active-nav key is derived in the template: `nav_key = 'dashboard' if path == '/' else path.strip('/').split('/')[0]` (base.html:119).
- `active_page` is also passed per route ("dashboard", "apply", "drafts", "replies",
  "outreach", "resumes") but the sidebar highlight uses `nav_key` (base.html:135–158).
- Shared page context pieces: `recent_drafts` on `/apply` (main.py:958–969), `drafts` +
  `processing_apps` on `/drafts` (main.py:1320–1329; `blocked_apps` is queried at main.py:1312
  but **never passed to the template**), `emails` (limit 10) on `/replies` (main.py:1344),
  `campaigns` + `sent_today` on `/outreach` (main.py:2064–2073), `sent_emails` joined with
  `JobApplication` on `/sent` (main.py:926–935).

## 4. Global shell — sidebar

Source: `templates/base.html:124–177`.

- `<aside class="sidebar" id="sidebar">` fixed left, `--sidebar-w: 15.5rem` (style.css:34, 137+).
- **Brand**: `a.brand` → `#i-target` icon in `.brand-mark`, `.brand-name` = "Command",
  `.brand-label` = "Career workspace" (base.html:125–131).
- **Nav label "Workspace"** then items (`.nav-item`, active class from `nav_key`):
  - Dashboard `/` — `#i-dashboard`
  - Drafts `/drafts` — `#i-document`, plus `<span class="nav-count">{{ nav_draft_count }}</span>` only when count > 0 (base.html:140)
  - Reply center `/replies` — `#i-mail`
  - Outreach `/outreach` — `#i-send`
  - Resumes `/resumes` — `#i-briefcase`
- **Nav label "Account"** (`.nav-label.nav-section`):
  - Sent history `/sent` — `#i-clock`
  - Settings `/settings` — `#i-settings`
- **Weekly promo card** `.sidebar-promo`: `#i-sparkles` icon, title "Your weekly target",
  copy `{{ weekly_done }} of 15 applications sent` — the goal is **hard-coded `{% set weekly_goal = 15 %}`** (base.html:120–122), progress `.progress-track` width = pct (floored, capped 100),
  text button "Review drafts" → `/drafts` (base.html:161–167).
- **Profile card** `a.profile-card` → `/settings`: `.avatar` = `initials` (first 2 chars of
  display name, main.py:115), `strong` = `display_name` (fallback "Candidate"), small =
  "Personal workspace", trailing `#i-more` (base.html:169–176).
- Mobile: `.sidebar-scrim#sidebarScrim`; toggle `#menuToggle` adds/removes `body.nav-open`
  (app.js:527–541); at ≤760px sidebar is off-canvas `translateX(-100%)` (style.css:2783–2796).

## 5. Global shell — topbar

Source: `templates/base.html:181–218`.

- `<header class="topbar">` inside `<section class="workspace">`; content area `<div class="content">` holds `{% block content %}`.
- Left: mobile `#menuToggle` icon button (`#i-menu`).
- Search: `.search-box` with `#i-search`, `<input id="globalSearch" type="search"
  placeholder="Search companies, roles..." aria-label="Search this page">`, `<span class="shortcut">Ctrl K</span>`
  (hidden ≤760px, style.css:2814).
- `.topbar-actions`:
  1. **Account switcher** `#accountSwitcher` — see §9.
  2. **Sync button** `.sync-button[data-sync]` with `#i-refresh` + `<span>Sync</span>` — see §11.
  3. **Primary CTA** `a.primary-button[href=/apply]` with `#i-plus` + "Add application"
     (inline styles `padding:.68rem 1rem;font-size:.7rem;font-weight:700`; at ≤480px the label
     collapses to icon-only via `font-size:0`, style.css:2932–2940).

## 6. Global overlays: loading, status, confirm, prompt, connect-account

All defined once in `base.html` and driven by `app.js`.

- **Loading overlay** `.process-overlay#loadingOverlay` (hidden) → `.process-modal` with
  `.spinner`, `#loadingTitle` ("Working…"), `#loadingText` ("One moment.") (base.html:221–227;
  show/hide app.js:63–74; styles style.css:2595–2656). It is explicitly **excluded from
  Escape-to-close** (app.js:610–613).
- **Status dialog** `.modal#statusModal` — centered, `×` close (`[data-close-modal]`),
  `#statusIconBox` (`.modal-icon.success`/`.danger`, swaps `#i-check`/`#i-trash`),
  `#statusTitle`, `#statusMessage`, full-width "Got it" button (base.html:230–240).
  API: `ui.showStatus(title, message, success)` (app.js:76–93); falls back to a toast if the
  modal is absent (app.js:78–80).
- **Confirm dialog** `.modal#confirmModal` — `.modal-icon.danger` + `#i-trash`,
  `#confirmTitle`, `#confirmMessage`, `.modal-actions.stack-actions` with
  `[data-confirm-no]` "Cancel" and `[data-confirm-yes]` "Confirm"
  (base.html:243–255). `ui.confirm({title, message, confirmText, cancelText})` → Promise<boolean>
  (app.js:107–132).
- **Prompt dialog** `.modal#promptModal` — `#promptTitle` (default "Tell the assistant what to
  change"), `#promptMessage`, label "Instructions", `<textarea id="promptInputField" rows="4">`
  with placeholder "Make it warmer, mention Python automation, keep it concise...", buttons
  Cancel / "Apply" (base.html:258–270). `ui.prompt({title, message, value, placeholder,
  confirmText})` → Promise<string|null>; **Enter (or Cmd/Ctrl+Enter) confirms**
  (app.js:134–167, onKey app.js:158–160).
- **Connect account modal** `.modal#connectAccountModal` — violet mail icon, heading
  "Connect a sending account", copy about app passwords, `#accountSlots` list, `#connectEmail`,
  `#connectPassword` with eye toggle (`[data-toggle-secret]`), `.form-help` text about Google
  App passwords, Cancel / `#btnConnectAccount` (base.html:273–305).
- **Modal dismissal**: click on the modal backdrop or `[data-close-modal]` closes; Escape
  closes every `.modal.active` and non-hidden `.process-overlay` (except `#loadingOverlay`),
  and closes the account menu (app.js:593–619).

## 7. Shared JS behaviour layer (`window.ui`)

Source: `static/app.js` (663 lines). Exported API (app.js:623–646):

| Helper | Purpose | Line |
|---|---|---|
| `qs/qsa/on` | DOM query / binding (no-op safe) | 15–25 |
| `icon(name,size)` | `<svg class="icon"><use href="#i-…">` builder | 27–30 |
| `escapeHtml` | HTML entity escaping | 32–39 |
| `toast(msg,{error,duration})` | see §8 | 45–59 |
| `showLoading/hideLoading` | loading overlay | 63–74 |
| `showStatus/closeStatusModal` | status dialog | 76–93 |
| `openModal/closeModal` | `.active` class toggles by id | 95–103 |
| `confirm` / `prompt` | promise dialogs | 107–167 |
| `request(url,opts)` | fetch → JSON; on !ok throws `Error(data.detail)` with `.status`/`.data` | 171–186 |
| `postJson(url,payload)` | JSON POST wrapper | 188–194 |
| `profileSections`, `buildProfileSummary`, `parseProfileSummary`, `buildProfilePrompt`, `collectProfileValues`, `applyProfileValues` | 2-way profile summary block (Settings) | 202–341 |

Legacy globals for older inline scripts: `showLoading`, `hideLoading`, `showStatus`,
`closeModal` (aliased to closeStatusModal), `notify` (alias of toast) — app.js:649–653.

Profile summary block: 11 labelled sections — Full Name, Email, Phone, GitHub, LinkedIn,
Portfolio, Skills, Experience, Projects, Bio, Drafting Instructions (app.js:202–214);
stub values ("N/A", "not provided"…) are ignored when parsing (app.js:222–231); links are
normalized (https:// prefix, linkedin trailing slash) (app.js:233–251).

DOMContentLoaded boot order: mobile nav → search → sync → modal dismiss → connect account →
account switcher (app.js:655–662).

## 8. Toast feedback

- Host `<div id="toastHost">` at end of `base.html:307` (setup.html:40 has its own, with
  `aria-live="polite"`).
- Render: `<div class="toast[ error]"><span>✓|!</span>message</div>`; cleared after
  **2600 ms** default (app.js:45–59).
- Style: fixed bottom-right, surface-raised, green/red border accents, `toast-in` animation
  (style.css:2671–2711).

## 9. Account switcher

- Markup: `.account-switcher#accountSwitcher > button.account-trigger` with
  `.account-avatar#accountAvatar`, `.account-copy` ("Sending from" + `#accountLabel`
  "Loading."), chevron (base.html:194–203).
- Menu is **rebuilt in JS** (`renderAccountMenu`, app.js:345–415): label
  "Connected accounts", one button per slot (`data-slot`) showing avatar initial, email or
  "Not connected", sub-label "Active account"/"Gmail connected", `✓` check on active; footer
  button `#openConnectAccount` with plus icon + "Connect another account".
- Data: `GET /api/current-email` → `{emails, index}` (main.py:810–812). Failure sets label
  "Unavailable" (app.js:515–523).
- Slot switch: `POST /api/switch-email {index}` → toast "Now sending from …" → reload after
  700 ms (app.js:391–408).
- Connect modal flow: `GET /api/accounts` → connected slots + `free_slots`; button becomes
  disabled "No free slots" when full (app.js:432–466); submit `POST /api/accounts {email,
  password}` → toast "Connected …" → auto switch → reload (app.js:483–512). Validation errors
  come back as 400 `detail` (main.py:838–857). `DELETE /api/accounts/{slot}` exists
  (main.py:860–867) — **no UI reference found in templates**: `Backend capability — no
  confirmed current UI.`
- Empty/invalid values fall back to slots `['1','2']` (app.js:8–13).

## 10. Global search, shortcuts & sync

- `#globalSearch` filters any element carrying `data-search="…"` by hiding non-matches
  (`row.hidden`), app.js:543–572. If no `[data-search]` targets exist the whole
  `.search-box` is hidden (app.js:548–551).
- Pages that provide targets: dashboard rows (application_row.html:2), apply recent drafts
  (apply.html:87), drafts items (drafts.html:50), outreach campaigns (outreach.html:43),
  replies rows (replies.html:44), sent rows (sent_mails.html:37), resumes rows
  (resumes.html:101,117). Settings and setup have none → search box hidden there.
- Shortcuts: **Ctrl/Cmd+K** focuses+selects search; **/** focuses it when not typing
  (app.js:561–571).
- **Sync**: any `[data-sync]` button → disable, `showLoading("Scanning Gmail and refreshing
  your workspace...", "Syncing")`, `POST /sync/` → reload after 500 ms; failure →
  `showStatus("Sync failed", message, false)` (app.js:574–591). Backend simply runs
  `email_service.monitor_inbox()` (main.py:801–807). `data-sync` appears on topbar (base.html:205)
  and Reply Center "Refresh inbox" buttons (replies.html:13, 74).

## 11. Design tokens

Source: `static/style.css:13–50` (`:root`), dark theme:

`--bg:#0a1020`, `--surface:#111a2d`, `--surface-raised:#162238`, `--surface-soft:#1b2940`,
`--border:rgba(157,176,211,.13)`, `--border-strong:rgba(157,176,211,.2)`,
`--text:#f7f8fc`, `--text-muted:#8f9bb3`, `--text-soft:#bac3d5`,
`--violet:#6d5dfc`, `--violet-light:#8c7eff`, `--blue:#3b82f6`, `--orange:#ff9d2e`,
`--green:#20c997`, `--cyan:#34d4e8`, `--danger:#f87171`,
`--radius-sm:.65rem`, `--radius-md:.9rem`, `--radius-lg:1.25rem`,
`--shadow:0 1.5rem 4rem rgba(0,0,0,.22)`, `--sidebar-w:15.5rem`
plus legacy aliases (`--primary`, `--card-bg`, `--success*`, `--warning*`, `--danger*`, `--info*`)
(style.css:36–49).

Body background: radial violet glow over `--bg` (`.app-shell`, style.css:130–135).
Scrollbar: 10px, rounded thumb rgba(157,176,211,…) (style.css:110–124).

CSS section map (line numbers): 1 Tokens 10 · 2 Reset/base 53 · 3 Shell 127 ·
4 Buttons & controls 601 · 5 Headings & cards 735 · 6 Stat cards 837 · 7 Dashboard grid 989 ·
8 Inner pages (draft studio / launch / compose) 1308 · 9 Forms 1873 · 10 Lists/tables/tabs 2117 ·
10 Conversation/chat 2393 · 11 Modals/overlays/toasts 2445 · 12 Responsive 2751 ·
Settings 2959 · Onboarding 3113 · Utilities 3206.

## 12. Iconography

Sprite ids (base.html:15–117): `i-target, i-dashboard, i-document, i-mail, i-send, i-briefcase,
i-clock, i-user, i-search, i-plus, i-refresh, i-menu, i-chevron, i-more, i-sparkles, i-arrow,
i-trash, i-archive, i-upload, i-link, i-check, i-settings, i-chart, i-inbox, i-eye, i-file`
(26 symbols). Stroke styling on `svg.icon`: `stroke-width:1.8`, round caps, default 1.125rem
(style.css:99–108). Setup page sprite: `i-file, i-upload, i-sparkles, i-check, i-arrow`
(setup.html:15–38).

## 13. Buttons & controls

(style.css §4 at line 601; usages across templates)
- `.btn` family: `.btn-primary` (violet gradient), `.btn-secondary` (ghost/outline),
  `.btn-danger`, `.btn-sm`.
- Sizes/variants used: `primary-button` (topbar CTA), `period-button`, `sync-button`,
  `text-button`, `view-all`, `insight-button`, `filter-button`, `icon-button`.
- `.step-indicator` on Apply: `<span class="done">1</span><i></i><span>2</span><i></i><span>3</span>`
  (apply.html:15–17) — a **static** 3-step decoration; no step state machine exists in code.
- Busy conventions observed: button `disabled` + replaced inner text
  ("Starting…", "Working…", "Saving…", "Uploading…", "Loading…", "Connecting…") then restored.

## 14. Cards, headings & layout primitives

- Page headers: `.page-heading` (dashboard, date eyebrow + greeting) and `.inner-page-heading`
  (all other pages: `.eyebrow`, `.title[role=heading][aria-level=1]`, `<p>` subtitle, right-side action).
- `.stats-grid` / `.stat-card` (+ `.featured`, `.stat-top`, `.stat-icon.violet|orange|blue|green|cyan`,
  `.stat-value`, `.stat-label`, `.stat-note`, `.trend[.positive]`, `.sparkline`, `.stat-link`) —
  dashboard.html:25–73.
- `.stat-strip` + `.mini-stat` — replies.html:18–35, outreach.html:20–37, sent_mails.html:18–31.
- `.card`, `.card-header`, `.section-title`, `.quick-start-card`, `.instruction-card`,
  `.source-grid`, `.launch-grid`/`.launch-main`, `.recent-drafts` (aside),
  `.draft-layout` (list + `.compose-card`), `.dashboard-grid`, `.applications-card`,
  `.insights-card`, `.prompt-box`, `.campaign-card`, `.stack`.
- `.empty-state` (inline, icon + muted text) and `.empty-workspace` (centered hero with
  `.empty-icon` + title + copy + CTA) — see §19.
- `.email-body`, `.email-meta` (modal email display), `.chat-container` + `.message.received|sent`.

## 15. Status pills, tones & campaign colors

- Application status pill: `<span class="status-pill status-{{status}}"><span></span>
  {{ status|replace('_',' ') }}</span>` (application_row.html:13, reply_editor.html:12,
  sent_mails.html:43, replies.html:52–55).
- `models.py` `ApplicationStatus`: `draft, submitted, blocked, responded, rejected,
  shortlisted, positive_response, awaiting_response, ocr_uncertain` — plus runtime values
  `processing` (main.py:2402) and `shortlisted` set on send (main.py:1550).
- Additional pill classes styled in CSS: `status-active`, `status-completed` (green),
  `status-paused`, `status-awaiting_response` (orange), `status-rejected`, `status-error` (red)
  (style.css:3224–3240).
- Company/avatar logo tones: `violet, blue, coral, green` (`APPLICATION_TONES`, main.py:870;
  per-row tone in `application_row_payload`, main.py:873–885); cyan variants exist in CSS
  (style.css:3214–3222).
- Outreach campaign card: status tone map `active→green, paused→orange, completed→violet,
  error→coral` (outreach.html:6); progress bar background varies by status (outreach.html:61–63);
  status pill reuses application pill classes via mapping (outreach.html:66).

## 16. Forms & inputs

(style.css §9 line 1873)
- `.form-label`, `.form-help`, `.form-note.ok|err`, `.form-row` (2-col), `.field-block`,
  `.row-between`, `.row`, `.check-row` (checkbox with strong/small copy), `.key-field`.
- `.input-with-action` + `.input-action` eye toggle for secrets (style.css:3039–3068;
  used settings.html:120–147, base.html:287–294).
- `.file-picker` (dashed, file icon + name + "Upload new") — settings resume tab
  (style.css:3070–3111).
- `.drop-zone` (onboarding drag & drop; `.dragging` state) style.css:3165–3198.
- `.paste-zone` for poster paste (apply.html:116–119).
- `.prompt-copy-text` (click-to-copy block) + `.prompt-help` (`.ok`/`.err`)
  — resumes.html:21–37, settings.html:77–82; styles style.css:3310–3316.

## 17. Lists, tables & pagination

- `.table-head` (4 cols: "Company & role", "Status", "Last activity", spacer) +
  `.application-row` grid: `.company-cell` (logo + strong/small), status pill, `<time>`,
  `.row-actions` icon buttons `js-view-source` / `js-view-email` / `js-delete-app`
  (dashboard.html:87–92, application_row.html:1–29). Status pill column and time are
  hidden/reflowed ≤760px (style.css:2849–2870).
- **Paged "Load more"**: first 12 rows server-rendered (`RECENT_APPLICATIONS_PAGE = 12`,
  main.py:723); button `#btnLoadMore[data-offset]` fetches
  `GET /api/applications?limit=12&offset=N` returning `{total, offset, limit, count, has_more, html}`
  (main.py:888–912); appended rows are re-bound; counter `Showing X of Y`; footer removed when
  exhausted (dashboard.html:282–319).
- `.mail-row` (replies + sent lists), `.draft-row` (apply recent + resumes gallery),
  `.draft-item` (draft studio list, `.selected` state), `.list-rows`.
- `.list-footer` (style.css:3377–3384).
- Campaign details table inside modal: `.table-container > table` thead
  Recipient / Company / Status / Sent at (outreach.html:158–170), client-rendered with a
  **200-row display limit** + note row (outreach.html:284–290).

## 18. Empty states

| Page | Element | Copy (abridged) | Ref |
|---|---|---|---|
| Dashboard (no apps) | `.empty-state` + `#i-inbox` | "No applications yet." + "Add your first application" CTA → /apply | dashboard.html:98–103 |
| Apply (no drafts) | `.empty-state` | "Your drafts will appear here once you launch an application." | apply.html:99–102 |
| Drafts (none) | `.empty-workspace` + `#i-document` | "No drafts waiting" + "Launch an application" → /apply | drafts.html:109–114 |
| Replies (empty) | `.empty-workspace` + `#i-inbox` | "Your inbox is empty" + "Refresh inbox" `[data-sync]` | replies.html:70–77 |
| Reply editor (no msgs) | `.empty-state` | "No messages recorded for this application yet." | reply_editor.html:38 |
| Outreach (none) | `.empty-workspace` + `#i-send` | "No campaigns yet" + "Start outreach" opens campaign modal | outreach.html:106–113 |
| Resumes (none) | `.empty-state` | "No role-specific resumes yet…" | resumes.html:131–134 |
| Sent (none) | `.empty-workspace` + `#i-send` | "No sent history yet" + "Review pending drafts" → /drafts | sent_mails.html:58–65 |

## 19. Responsive behavior

(style.css §12 line 2751)
- **≤1120px**: stats → 2 cols; dashboard → 1 col; `.insights-card` hidden; account trigger
  collapses to avatar-only; `.draft-layout`/`.launch-grid` → 1 col (style.css:2754–2781).
- **≤760px**: sidebar off-canvas (nav-open), workspace margin 0, topbar 4rem, mobile menu
  button shown, shortcut + sync label hidden, account switcher hidden, content padding
  `.1.4rem 1rem 2rem`, page headings stack, `.period-button` hidden, stats 2-up, table head
  hidden, application-row 2-col with actions on their own row, `.recent-drafts` aside hidden,
  source-grid 1-col, compose footer stacks, `.resume-grid` 1-col (style.css:2783–2921).
- **≤480px**: stats 1-col; topbar CTA icon-only; `.title` 1.55rem; list-footer stacks
  (style.css:2923–2945, 3390–3394).
- **≤900px**: onboarding grid 1-col (style.css:3200–3204).
- `prefers-reduced-motion: reduce` kills transitions/animations (style.css:2947–2957).

## 20. Page: Setup (`/setup`) — standalone

Source: `templates/setup.html` (does **not** extend base.html; `body.onboarding`, loads
`style.css?v=3` + Manrope directly).

- Hero: `.brand-mark` "C", eyebrow "Welcome to Command", h1 "Let's build your profile",
  sub copy (setup.html:42–48).
- Left card: "AI resume import" — `.drop-zone#dropZone` (drag & drop or click, PDF only),
  hidden `#fileInput`; while parsing shows `#loadingContainer` with spinner,
  `#statusMessage` ("Extracting resume text…" → "Structuring details using AI…") and note
  "This can take up to 20 seconds." (setup.html:52–81).
- Right card: form `#setupForm` — Full name*, Email*, Phone, "Portfolio & social links"
  (`placeholder="LinkedIn: … | GitHub: …"`), Key skills*, Experience summary*, Key projects,
  "Drafting instructions / persona"; submit `#submitBtn` "Save profile & open dashboard"
  (setup.html:84–132).
- JS: `POST /setup/parse-resume` (multipart) fills fields from JSON
  `{full_name,email,phone,portfolio_links,skills,experience,projects}` (setup.html:181–210);
  validation toast "Fill in your name, email, skills, and experience to continue.";
  `POST /setup/save` JSON then redirect `/` (setup.html:212–247).

**Reconstruction checklist — Setup:** standalone document; onboarding background gradients
(style.css:3117–3125); two-column `.onboarding-grid`; drop-zone with `.dragging` hover;
inline static loading block (position:static override, setup.html:76); required-field
client validation; PDF-only guard; toast errors; "Saving profile…" busy state; redirect to `/`.

## 21. Page: Dashboard (`/`)

Route main.py:711–797. Only `is_manual == True` applications are listed (main.py:721).

- Header: eyebrow = uppercase `now.strftime('%A, %B %d')`; title = time-based greeting
  ("Good morning/afternoon/evening, {first_name}") (dashboard.html:9–17); right
  `a.period-button[href=/sent]` "Last 30 days" + chevron.
- 4 stat cards: Total applications (+ "{weekly} this week" trend + 8-bucket sparkline),
  Awaiting response (pct of total, "{weekly_updated} updated this week" note),
  Drafts ready (`nav_draft_count`, link "Review drafts"), Success rate
  (`positive/total %`, "{n} shortlisted" trend, conditional note copy) (dashboard.html:25–73).
- Applications card: header "Recent applications" / "Your latest outreach and activity" +
  `view-all` "View all {total}" → `/sent`; `.table-head`; `#applicationList` rows from
  `partials/application_row.html`; optional `#loadMoreFooter` (see §17).
- Row actions: view source modal (`.js-view-source` → `GET /api/applications/{id}/source`
  → `#viewerModal` "Original job details"), view last email (`.js-view-email` →
  `GET /api/applications/{id}/last-email`), delete (`.js-delete-app` → `ui.confirm`
  "Delete this application?" → `DELETE /applications/{id}` → row fade-out 250 ms + toast
  "Application deleted") (dashboard.html:200–265).
- `#viewerModal` with `#viewerTitle`, `#viewerContent` (`.email-body`), Close (dashboard.html:170–179).
- Insights aside: "Smart insights / Updated just now", conic-gradient ring showing
  `{weekly_applications} this week`, conditional headline ("You're building momentum" ≥5 /
  "You're off to a good start" >0 / "Time to launch your first one"), copy, three
  `.insight-metric` rows (Applications / Shortlisted / Drafts waiting), CTA
  "Explore replies" → `/replies` (dashboard.html:118–166).

**Reconstruction checklist — Dashboard:** greeting logic + date eyebrow; 4-card stats grid
with sparkline percentages relative to peak; paged list with server-rendered partial and
client "load more"; viewer modal with Loading… state; confirm-before-delete with fade-out;
insights ring gradient built inline from `success_rate`; empty state with CTA.

## 22. Page: Apply (`/apply`) — "Launch an application"

Route main.py:940–970 (context: `recent_drafts` joined pairs, `emails`, `user`).

- Heading block: eyebrow "AI application assistant", title "Launch an application", subtitle
  "Turn job details into a thoughtful, tailored application.", `.step-indicator` (apply.html:8–18).
- `.launch-grid` → `.launch-main`:
  1. `.quick-start-card`: sparkles icon, "Quick start / Paste job details", copy, `<textarea
     id="jobText">` placeholder "Paste job details, requirements, and contact information here...",
     `.check-row` `#suggestResumeChange` — label "Match the best resume" with inline link to
     `/resumes`, `#btnProcess` "Process & write draft" (apply.html:22–45).
  2. `.instruction-card`: "One-time instructions / Optional guidance used only for this draft"
     + `#applicationInstructions` input (apply.html:47–54).
  3. `.source-grid` 3 buttons: "Paste a job poster" (orange, "Click, then paste a screenshot"),
     "Upload a poster" (green, "Choose a JPG or PNG file"), "Start with a link" (blue,
     "Import job from a public URL") (apply.html:56–77).
- `.recent-drafts` aside: "Recent drafts / Continue where you left off", up to **6** rows
  linking `/drafts` with alternating violet/blue logo initials; "View all drafts" button;
  or `.empty-state` (apply.html:80–104).
- **Paste flow**: `#posterPreviewModal` with paste zone (`#pasteArea`, `#pasteHint`,
  `#pastedPreview` img) → reads clipboard image → `POST /applications/poster/paste/`
  (JSON `{image, instructions}`) (apply.html:110–124, 235–269).
- **Upload flow**: hidden `#posterFile[accept=image/png,image/jpeg]` → `POST /applications/poster/`
  (multipart `file`, `instructions`) (apply.html:109, 273–305).
- **Link flow**: JS-built modal (append to body, apply.html:309–322) "Import from a link",
  `#jobUrlField`, button "Initialize agent" →
  `POST /applications/job/?job_url=…[&draft_instructions=…]` (apply.html:333–356).
- **Common success path** `handleApplicationStarted`: showLoading
  "Reading job details and writing the email draft…" / "Working your magic" → poll
  `GET /applications/{id}/draft/` up to **24 attempts × 2500 ms** → "Draft created. Opening
  the draft studio…" → redirect `/drafts` (apply.html:138–155).
- **OCR recovery**: any 401 → `ui.prompt` "OCR token needed" → `POST /user/hf_token/`
  → retry (apply.html:157–182). Other failures → `showStatus("Something went wrong", detail, false)`.
- Empty-text guard → status dialog "Job details required" (apply.html:188–192).

**Reconstruction checklist — Apply:** exact card order and copy; three intake modes with
their modals; instructions input shared by all modes (sent as `instructions` /
`draft_instructions`); loading overlay copy per mode; polling → redirect; 401 HF-token
prompt recovery; recent-drafts aside capped at 6 with alternating tones.

## 23. Page: Draft studio (`/drafts`)

Route main.py:1292–1330 (`drafts` = Draft⋈JobApplication where `draft_type=="email"`,
desc; `processing_apps` = status `"processing"`).

- Heading: eyebrow "Application workspace", title "Draft studio", subtitle; right
  `a.btn.btn-primary[href=/apply]` "New draft".
- **Processing banner** `#processingBanner` (only when apps processing): `.spinner.sm`,
  "AI drafting in progress / Your workspace refreshes automatically once every draft is
  ready.", `.tag-row` of `.tag` company names; page **auto-reloads every 3000 ms** while
  present (drafts.html:18–31, 122–124).
- When drafts exist → `.draft-layout`:
  - **List card**: header "Your drafts" + "{n} application(s) ready to review" + `.filter-button`
    "Recent" (decorative, no handler); `#draftList` with up to **50** `.draft-item` buttons
    (first is `.selected`): tone logo, company/role/contact, date `'%b %d'` + chevron;
    overflow link "Showing 50 of {n} — see all activity" → `/sent` (drafts.html:33–70).
  - **Compose card** `#editorCard`: `.compose-head` (`#editorLogo`, `#editorCompany`,
    `#editorRole`, `.ai-badge` "AI draft generated"); `.compose-fields` To/CC/Subject inputs;
    `.email-editor#fieldBody` textarea; `.compose-footer` — left: document icon
    "Resume attached automatically" + hidden `.suggestion-pill#suggestionPill` ("Alternative
    resume available"), right: `#btnDelete` "Delete", `#btnRegenerate` "Regenerate",
    `#btnSend` "Send application" (drafts.html:72–106).
- Empty → `.empty-workspace` "No drafts waiting" (drafts.html:109–114).
- JS behaviour (drafts.html:120–309):
  - `loadDraft` → `GET /api/drafts/{id}` fills fields; disables everything while loading;
    suggestion pill from `has_suggestion`.
  - Regenerate → `ui.prompt` "Regenerate with AI" (placeholder "Make it more formal,
    highlight my Python automation experience…") → `POST /drafts/regenerate/{id} {instructions}`
    → updates subject/body + toast "Draft regenerated".
  - Delete → `ui.confirm` "Discard this draft?" ("…application record itself stays in your
    dashboard.") → `DELETE /drafts/{id}` → remove row, select next or reload; toast "Draft discarded".
  - Send → validates recipient (status dialog "Missing info"), builds
    `{recipient, subject, content, cc?:[]}`; if `has_suggestion`, first-time confirm dialog
    "Send a different resume?" (confirm "Send this resume" / cancel "Use primary") based on
    `GET /api/applications/{id}/suggestion`, then adds `resume_id` →
    `POST /emails/send/{draftId}` → row fades (0.3 opacity, removed 700 ms) → status dialog
    "Application sent" / on error "Delivery failed".
  - On load: first (selected) draft auto-opens (drafts.html:307–308).

**Reconstruction checklist — Drafts:** two-column list/editor; 3 s auto-reload banner;
50-item cap; field-disabled busy states; four distinct dialog flows (prompt, confirm×2,
status) with their exact copy; suggestion-pill resume swap; empty state.

## 24. Page: Reply center (`/replies`)

Route main.py:1334–1358 — latest **10** `EmailEvent`s, `now` passed.

- Heading: eyebrow "Reply center", title "Inbox zero starts here", subtitle; right
  secondary "Refresh inbox" button `[data-sync]` (replies.html:6–16).
- `.stat-strip`: Recent conversations / Shortlisted (`classification=='positive'`) /
  Job related (`neutral`) / Unlinked (`application_id is none`) (replies.html:18–35).
- Rows: `a.mail-row[href=/replies/{id} or #]` with sender (angle-bracket stripped), subject,
  snippet[:120] with ellipsis, optional pill "Shortlisted"/"Job related", right-aligned time
  (today → `%I:%M %p`, else `%b %d`) (replies.html:37–68).
- Unlinked rows intercepted: status dialog "Not linked to an application" (replies.html:84–90).
- Empty state offers Refresh (replies.html:70–77).

## 25. Page: Reply editor (`/replies/{app_id}`)

Route main.py:1362–1412 — merges `EmailEvent` (type received) + `SentEmail` (type sent,
sender "ME") sorted by time; 404 if app missing.

- Heading: eyebrow "Conversation", title = company + inline status pill, subtitle =
  "role · contact email"; right `a.period-button[href=/replies]` with rotated chevron
  "Back to reply center" (reply_editor.html:6–20).
- Left card: "Conversation history / Started {date}"; `#chatHistory` with
  `.message.received|sent` (meta `sender · %b %d, %H:%M`, content); auto-scrolls to bottom
  (reply_editor.html:22–41, 95–96).
- Right column:
  - `#replyDraftArea` (hidden until generated): compose card "AI drafted reply / Review,
    refine, then send", `.ai-badge` "Draft", To (`#replyRecipient`, prefilled contact email),
    Subject (`#replySubject`, placeholder "RE: Job Application"), `#replyContent` textarea
    (min-height 15rem), footer note "Sending from your active account" + `#btnDiscardDraft`
    "Discard" and `#btnSendReply` "Send reply" (reply_editor.html:44–70).
  - `#promptBar` `.instruction-card` with `#promptInput` placeholder "Ask AI to draft a reply
    (e.g. 'Confirm availability for Tuesday at 3pm')" + `#btnGenerate` "Draft with AI"
    (reply_editor.html:72–78).
- JS: generate → `POST /replies/generate {app_id, instructions}` (loading "AI is reading the
  history and drafting your reply…" / "Writing reply") → show draft area + scroll + toast
  "Reply drafted". Discard hides/clears. Send validates recipient ("Missing recipient") and
  body ("Nothing to send") → `POST /emails/send/direct {app_id, recipient, subject, content}`
  → status "Reply sent" → redirect `/replies` after 1800 ms; failure "Delivery failed"
  (reply_editor.html:98–156).

**Reconstruction checklist — Reply editor:** chat-vs-compose split; draft area hidden by
default; Discard resets visibility; loading/status copy exactly as above; 1800 ms redirect.

## 26. Page: Outreach (`/outreach`)

Route (decorated twice, main.py:2034 & 2036) — context `campaigns`, `user`, `sent_today`.

- Heading: eyebrow "Outreach", title "Build meaningful connections", subtitle; right
  primary button `[data-open-campaign]` "New campaign" (outreach.html:8–18).
- `.stat-strip`: Sent today / Total campaigns / Running now (status active) / Paused (outreach.html:20–37).
- Campaign cards `.campaign-card#campaign-{id}[data-status][data-search]`:
  name, "Created {Mon DD, YYYY}", right counter `sent / total` + "emails sent",
  `.progress-track` (gradient per status), status pill + "{pct}% completed", action row
  (conditional):
  - `Retry` when `total_count==0 && status=='completed'` → `POST /campaigns/{id}/retry`
    (with optional header-row prompt dialog)
  - `Retry failed` when `completed && sent<total` → `POST /campaigns/{id}/retry_failed`
  - `Pause` (active) → `POST /campaigns/{id}/pause`; `Resume` (paused) → `POST /campaigns/{id}/resume`
  - `Sheet` external link to `c.sheet_url`
  - `Details` opens `#detailsModal`
  (outreach.html:39–104)
- **New campaign modal** `#newCampaignModal`: warning about publishing the sheet
  (File > Share > Publish to web > CSV); fields `#cName`, `#cUrl`, `#cHeader` (number, default 1),
  `#cContext1` "Target role / vacancy", `#cContext2` "Additional instructions (optional)",
  `#cDailyLimit` (optional, min 1); buttons Cancel / `#btnStartCampaign` "Start campaign" →
  `POST /campaigns/start` (missing name/url → status "Missing details") → reload (outreach.html:117–150, 191–224).
- **Details modal** `#detailsModal` (width `min(48rem,100%)`): loading line, table
  Recipient/Company/Status/Sent at rendered from `GET /campaigns/{id}/items`; statuses colored
  sent=green / error=orange / pending=muted; error_msg shown in red; 200-row cap note
  (outreach.html:152–172, 264–315).
- **Live polling**: every **5000 ms** fetch `GET /campaigns/{id}` for `.campaign-card[data-status=active|paused]`,
  update `#sent-{id}`, `#total-{id}`, `#prog-{id}`, `#pct-{id}`; **full reload when status
  changes** (outreach.html:317–346).
- Empty state `.empty-workspace` "No campaigns yet" with `[data-open-campaign]` CTA.

**Reconstruction checklist — Outreach:** stat strip; per-status bar gradients and pill
mapping; conditional action buttons incl. header-row retry prompt; two modals; 5 s polling
with reload-on-status-change; 200-row details cap.

## 27. Page: Resumes (`/resumes`)

Route main.py:2425–2434 (`resumes` ordered by `created_at desc`).

- Heading: eyebrow "Resumes", title "Your resume library", subtitle; right `[data-open-upload]`
  "Add resume" (scrolls/focuses the role input instead of opening a modal, resumes.html:252–255).
- `.prompt-box` "How to generate a resume summary" — copy-paste prompt block `#summaryPrompt`
  (10 labelled lines + code-box instruction, resumes.html:18–38); click copies via
  `navigator.clipboard`, hint switches `.ok`/`.err`.
- `.launch-grid` main column:
  1. **Primary resume card**: filename from `user.resume_path.split('\\')[-1]` (Windows-path
     split), "No primary resume uploaded yet." fallback; button "Manage in settings" → `/settings`
     (resumes.html:42–59).
  2. **Add role-specific resume card**: `#newResumeRole` (placeholder "e.g. AI Engineer"),
     `#newResumeFile` (PDF), help about automatic "(1), (2)" filename suffix,
     `#newResumeSummary` textarea, `#btnUploadResume` "Upload resume" + hidden `#uploadStatus`
     `.form-note.ok|err` (resumes.html:61–92). Client checks: role required ("Add a target role
     first."), file required ("Choose a PDF file first."); success → "Resume uploaded. Refreshing…"
     → reload after 900 ms (resumes.html:281–308).
- Aside `.recent-drafts` "Resume gallery / {n} in your library":
  - Primary row `.draft-row.primary-resume` with green logo, `.badge-primary` "Primary",
    role + "· summary added", single edit action `[data-edit-primary]` (resumes.html:99–114).
  - Role-specific rows with `[data-edit]` (document icon) and `[data-remove]` (trash icon)
    actions (resumes.html:116–129); empty state otherwise.
- Modals: `#primaryModal` (file readonly, target role, summary, "Save changes" →
  `POST /user/update/ {resume_role, resume_summary}` → reload); `#editModal` (readonly name
  with help "Rename by re-uploading the file.", role, summary → `PUT /api/resumes/{id}` →
  reload); `#deleteModal` (danger, "Any pending suggestion using it will fall back to your
  primary resume." → `DELETE /api/resumes/{id}` → remove row + toast "{name} deleted")
  (resumes.html:140–201, 220–378).
- Hidden `#resumeData` mirrors each resume as `data-id/name/role/summary` for JS (resumes.html:203–208).
- Backend validation: role uniqueness incl. primary resume → 400 with exact conflict message
  (main.py:2447–2449, 2496–2509); filename de-dup `(1)` suffix (main.py:2458–2462).

**Reconstruction checklist — Resumes:** prompt-box with copy hint; two main cards; gallery
aside with primary badge styling (`.primary-resume`, `.badge-primary`, style.css:3336–3353);
three modals; hidden data island; upload status notes; 900 ms post-upload reload.

## 28. Page: Sent history (`/sent`)

Route main.py:916–936 (all `SentEmail` outer-joined with `JobApplication`, desc).

- Heading: eyebrow "Sent history", title "Everything you've delivered", subtitle; right
  primary "Add application" → `/apply` (sent_mails.html:6–16).
- `.stat-strip` (3 mini stats): Emails delivered / Confirmed sent (status=='sent', green) /
  "Shown below" (capped list length) (sent_mails.html:18–31).
- List shows only the first **60** (`{% set recent = sent_emails[:60] %}`); note line when
  total exceeds 60 (sent_mails.html:6, 52–56).
- Rows: `.mail-row` with logo initials (company or recipient), subject, "recipient · company",
  a pill always styled `status-positive_response` showing `{{ email.status or 'sent' }}`,
  icon button `data-email` → modal (sent_mails.html:33–50).
- Modal `#emailModal`: title "Loading…" → subject; `.email-meta` To / Sent; `#emailModalBody`
  (`.email-body`, min-height 14rem) from `GET /api/sent-emails/{id}`; failure title
  "Unavailable" (sent_mails.html:69–116).
- Empty state → "Review pending drafts" → `/drafts`.

## 29. Page: Settings (`/settings`)

Route main.py:974–997 — creates a default user (`full_name="Candidate Name"`) if none; link
fields fall back through `_parse_legacy_portfolio_links` (main.py:1000–1022).

- Heading: eyebrow "Settings", title "Your global configuration", subtitle "These details are
  injected into every draft, application, and reply the agent writes."; right primary
  `#btnSaveSettings` "Save changes" (settings.html:6–16); duplicate bottom `#btnSaveSettingsBottom`
  with `#saveStatus` note (settings.html:184–187).
- **Tabs** `.settings-tabs[role=tablist]`: "Identity & contact" | "Background" |
  "AI configuration" | "Resume"; active tab gradient style (settings.html:18–23; style.css:2963–3008).
- **Panel profile**: `.panel-title` (user icon + "Used to sign off outgoing applications and
  emails"); rows: Full name, Email, Phone, GitHub, LinkedIn, Portfolio; textarea "Core skills"
  (settings.html:27–68).
- **Panel background**: prompt-box "How to generate your profile summary" (`#profilePrompt`
  dynamic via `ui.buildProfilePrompt`, `#profilePromptHint`); `.field-block` Profile summary
  `#profileSummary` (rows=12) with **Rebuild** and **Apply to fields** buttons and 2-way sync
  text (settings.html:71–109); Experience, Projects, "Standard answers & bio" textareas.
  Any field input rebuilds the summary; Apply reports "Applied N section(s)…" or
  "Nothing new to apply…" (settings.html:245–284).
- **Panel AI**: password inputs with eye toggles — Groq key (help "Primary drafting model."),
  OpenRouter key ("Used automatically when Groq is unavailable."), Hugging Face token
  ("Optional. Raises OCR limits…"); textarea "Custom drafting instructions" `#systemPrompt`
  (settings.html:112–153).
- **Panel resume**: `.file-picker` showing filename or "No file uploaded", hidden `#resumeUpload`,
  `#btnPickResume` "Upload new" → `POST /user/resume/` (FormData) → updates name + toast
  "Resume updated"; "Target role for this resume" `#resumeRole` (default 'AI Engineer');
  link "Manage role-specific resumes" → `/resumes` (settings.html:156–181, 353–381).
- **Save**: single payload `{full_name,email,phone,github_link,linkedin_link,portfolio_link,
  skills,experience,projects,standard_answers,groq_api_key,openrouter_api_key,hf_token,
  system_prompt[,resume_role][,profile_summary]}` → `POST /user/update/`; status
  "Saving configuration…" → "Settings saved." + toast; errors via `#saveStatus` `.err`
  (settings.html:307–351).

**Reconstruction checklist — Settings:** 4 tabs (aria-selected), all field ids/placeholders,
2-way summary block, dynamic AI prompt box with clipboard hint, eye-toggles, dual save
buttons with shared handler, save-status notes, resume file picker.

---

## 30. Route/API inventory, data states, and final reconstruction checklist

### 30.1 Full endpoint inventory (62 decorators; `main.py`)

**Pages:** `/setup` 614 · `/` 711 · `/sent` 916 · `/apply` 940 · `/settings` 974 ·
`/drafts` 1292 · `/replies` 1334 · `/replies/{app_id}` 1362 · `/outreach` 2034+2036 (dup) ·
`/resumes` 2425.

**Setup:** `POST /setup/parse-resume` 620 (Groq `llama-3.3-70b-versatile`, requires
`GROQ_API_KEY` env — main.py:632–634) · `POST /setup/save` 676.

**User:** `POST /user/update/` 1034 · `POST /user/resume/` 1062 · `POST /user/system_prompt/` 1126 ·
`POST /user/groq_api_key/` 1148 · `POST /user/hf_token/` 1168 · `POST /user/` 1712 · `GET /user/` 1728.

**Applications:** `POST /applications/text/` 1094 · `POST /applications/job/` 1744 ·
`POST /applications/poster/` 1762 · `POST /applications/poster/paste/` 2322 ·
`GET /applications/{id}/draft/` 1854 · `POST /applications/{id}/submit/` 1870 ·
`POST /applications/{id}/draft/toggle-star/` 1890 · `POST /applications/{id}/draft/toggle-favorite/` 1908 ·
`GET /applications/` 1926 · `GET /applications/poll-emails/` 1934 · `GET /stats/` 1944 ·
`DELETE /applications/{app_id}` 1996.

**Drafts/emails:** `POST /drafts/regenerate/{id}` 1188 · `DELETE /drafts/{id}` 1978 ·
`POST /emails/send/direct` 1480 · `POST /emails/send/{draft_id}` 1566.

**Accounts/sync:** `POST /sync/` 801 · `GET /api/current-email` 810 · `POST /api/switch-email` 815 ·
`GET /api/accounts` 829 · `POST /api/accounts` 838 · `DELETE /api/accounts/{slot}` 860.

**Read APIs used by UI:** `GET /api/applications` 888 (paged rows HTML) ·
`GET /api/applications/{id}/suggestion` 2520 · `GET /api/applications/{id}/source` 2569 ·
`GET /api/applications/{id}/last-email` 2581 · `GET /api/drafts/{id}` 2549 ·
`GET /api/sent-emails/{id}` 2534 · `GET /api/resumes/` 2436 · `POST /api/resumes/` 2440 ·
`PUT /api/resumes/{id}` 2479 · `DELETE /api/resumes/{id}` 2511.

**Campaigns:** `POST /campaigns/start` 2078 · `/retry` 2122 · `/pause` 2172 · `/resume` 2192 ·
`/retry_failed` 2228 · `GET /campaigns/{id}` 2256 · `GET /campaigns/{id}/items` 2282.

**No UI references found in any template** → `Backend capability — no confirmed current UI.`:
`POST /applications/{id}/draft/toggle-star/`, `POST /applications/{id}/draft/toggle-favorite/`,
`GET /applications/poll-emails/`, `GET /stats/`, `DELETE /api/accounts/{slot}`,
`POST /applications/{id}/submit/`, `GET /user/`, `POST /user/system_prompt/`,
`POST /user/groq_api_key/` (Settings saves these via `/user/update/` instead).
Also `career_ops_service.py` + `schemas.CareerOps*` + `add_career_ops_table.py` have **no routes**
→ `Backend capability — no confirmed current UI.` `automation_service` is used only inside
`process_application` (main.py:171, 391), never directly by a page.

### 30.2 Application state machine as surfaced to the UI

| Status | Set at | UI meaning |
|---|---|---|
| `processing` | poster/text/link intake (main.py:2402) | Drafts page shows `#processingBanner` with company tag; 3 s auto-reload |
| `draft` | drafting finished (main.py:579) | Draft appears in Draft studio list |
| `blocked` | CAPTCHA/profile errors (main.py:177, 215, 591) | Pill "blocked"; no dedicated UI screen — `notify_blocked`/`notify_user` post to an **external n8n webhook** (`utils.py:9–31`), no in-app surface |
| `submitted` | after send (main.py:1882) | — |
| `awaiting_response` | after send (main.py:1654); auto-created inbox apps (email_service.py:134) | Dashboard "Awaiting response" count; orange pill |
| `shortlisted` | on send path (main.py:1550) | Green-ish pill |
| `positive_response` | LLM inbox classification (email_service.py:123) | Dashboard success rate numerator; replies "Shortlisted" |
| `ocr_uncertain` | poster OCR low confidence (main.py:1796) | Pill "ocr uncertain" |
| `rejected`, `responded` | enum only (models.py) | No writer found in main.py — display-only if present |

Campaign item statuses: `pending → sent | error` (bulk_service.py:361–409); campaign
statuses: `active, paused, completed, error` (bulk_service.py:20–307). All campaigns are
force-paused on startup (main.py:69–83).

### 30.3 Timing/behavior constants to reproduce exactly

- Toast: 2600 ms · draft-processing reload: 3000 ms · campaign poll: 5000 ms ·
  apply draft poll: 24 × 2500 ms · post-connect/switch reload: 700 ms · sync reload: 500 ms ·
  resume-upload reload: 900 ms · reply-sent redirect: 1800 ms · sent-row removal: 700 ms ·
  delete-row fade: 250 ms · prompt-dialog focus delay: 40 ms · connect-modal focus: 60 ms.
- Caps: dashboard page 12 · drafts list 50 · apply recent drafts 6 · replies 10 ·
  sent list 60 · campaign details 200 · sparkline buckets 8 (main.py:760–767) ·
  weekly goal 15 (base.html:120).
- Search hides the box entirely when no `[data-search]` nodes exist (app.js:548–551).

### 30.4 Per-page reconstruction checklist (final pass)

For each of the 10 pages, the rebuilding agent must verify:

1. **Route + guard**: correct path, `is_setup_complete` 307 redirect, template name, context keys (§3).
2. **Shell**: extends `base.html` (except setup); correct `{% block title %}` strings
   ("{Page} - Command" / "Command - Career Workspace" default); sidebar `nav_key` highlight.
3. **Heading block**: exact eyebrow / title / subtitle copy and right-side action (per page §21–29).
4. **Body**: every card, list, table, pill, tone class and caps listed in the page section.
5. **Empty state**: matching element + copy + CTA from §18.
6. **Modals**: ids, field labels, placeholders, button labels, close affordances.
7. **JS wiring**: every fetch/POST from the endpoint tables with the exact loading/toast/status
   copy; busy-state conventions; reload timings from §30.3.
8. **Search**: `data-search` attribute content present on all list rows.
9. **Responsive**: classes behave under the §19 breakpoints (no new breakpoints).
10. **Assets**: sprite symbol ids exist (§12); only `style.css` + `app.js` (+ inline scripts);
    no frameworks, no build step.

### 30.5 Known ambiguities / not determinable

- `blocked_apps` queried for `/drafts` but never rendered — whether a blocked-apps UI ever
  existed: `Not determinable from inspected code.` (main.py:1312 vs 1320–1329).
- `.filter-button` "Recent" in Draft studio has no click handler — sorting behavior:
  `Not determinable from inspected code.` (drafts.html:41–43).
- `.step-indicator` on Apply never advances — intended step semantics: `Not determinable from inspected code.`
- The `/sent` "Last 30 days" link on Dashboard filters nothing — whether filtering once
  existed: `Not determinable from inspected code.` (dashboard.html:20–22).
- Visual rendering (colors, spacing) is described only from CSS; pixel-perfect screenshots
  were not captured in this pass.
- Whether `toggle-star`/`toggle-favorite`/`poll-emails`/`stats` are consumed by an external
  client (e.g. n8n, BrowserAutomationForLinkdin submodule): `Not determinable from inspected code.`
