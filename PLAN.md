# PLAN.md

# AI Job Assistant — Native LinkedIn Job Finder Integration

## 0. Architecture Update (current direction — supersedes the UI constraint below)

Status: approved. This section is the authoritative architecture statement. The
original integration plan is preserved below as history; where it conflicts with
this section, this section wins.

### Final architecture

```
/
├── backend/     FastAPI app (main.py), linkedin_integration/, BrowserAutomationForLinkdin/,
│                templates/, tests/, venv/, .env, requirements.txt
├── frontend/    React 19 + Vite app (Figma Make source), built to frontend/dist
└── run.py       single entry point
```

- Frontend: React production build (`frontend/dist`) served by FastAPI on the
  same origin (no Vite dev server at runtime, no CORS).
- Backend: the existing FastAPI app unchanged (routes, services, business logic).
- Database: existing PostgreSQL via `database.py` (no new tables for the migration).
- LinkedIn automation: existing `BrowserAutomationForLinkdin` subprocess
  integration, six modes, JSON runs — unchanged.
- Startup: `python run.py` from the repository root starts backend + built
  frontend. No second server (no `pnpm dev` / `vite` / manual `uvicorn`).

### Superseded clauses

- Section 13: "The UI page can use regular server-rendered Jinja2 ... instead of
  introducing React/Vue" — **superseded**. The React frontend is the main UI;
  Jinja pages are retired progressively as React pages are wired up.
- Section 27: non-goal "A new frontend framework" — **superseded**.
- Everything else remains in force: backend/LinkedIn/database/URL-safety/filtering
  requirements, the six modes, and all workflow rules (Section 9 scope rules,
  including Draft & Apply restricted to filtered results unless deliberately
  changed later).

### Migration rules

- Connect the React frontend to existing endpoints; do not rewrite the backend
  and do not duplicate business logic in React.
- Mock/prototype-only frontend behavior (fake search runs, fake filtering, fake
  sends) is replaced page by page; mock data is removed as each page is wired.
- Figma "Stop Search" and "Needs Review" are not implemented: there is no
  backend cancellation, and status display uses only real filter states
  (`pending` / `accepted` / `rejected` / `error`).
- A small number of new JSON-only endpoints is allowed where the backend only
  has HTML pages (drafts list, inbox/conversations + thread, sent emails,
  campaigns, LinkedIn jobs JSON variant); existing endpoints are reused
  everywhere else.
- After each phase: run backend tests, build the frontend, verify pages and
  behavior, then report changes and discrepancies.

## 1. Objective

Make the existing `BrowserAutomationForLinkdin` application a **native LinkedIn Job Finder feature inside AI Job Assistant**.

The user experience should feel like one application:

- AI Job Assistant remains the main application.
- A new **LinkedIn Job Finder** section/page is added to it.
- The Dashboard gets a clear entry button for this feature.
- The existing LinkedIn scraper remains intact behind a separate process/module boundary so its Playwright/CDP lifecycle does not get mixed into FastAPI.
- Collected jobs are stored in AI Job Assistant's PostgreSQL database.
- The user manually starts LLM filtering.
- Relevant jobs are shown in a dedicated filtered-results area.
- Every relevant job can be sent into the existing AI Job Assistant drafting/sending workflow.
- LinkedIn post/job/apply/image links remain available as separate user-clickable actions.

This plan is for implementation only. **No implementation is performed in this phase.**

---

## 2. Final Decisions

### 2.1 Integration style

Use a **native product integration with a separate runtime process**.

From the user's point of view, LinkedIn Job Finder is a first-class AI Job Assistant feature.

Internally, the LinkedIn scraper remains isolated and is launched as a subprocess. Do not import its Playwright lifecycle directly into FastAPI request handling.

### 2.2 Scraper location

The user will place:

```text
AI Job Assistant/
└── BrowserAutomationForLinkdin/
```

The integration layer should treat that directory as the embedded LinkedIn automation module/application.

Do not copy the scraper's virtual environment into the AI Job Assistant project.

### 2.3 Existing scraper behavior

Preserve the existing scraper behavior, six run modes, JSON persistence, URL semantics, deduplication, continuation logic, failure handling, and existing tests.

The scraper's existing JSON run files remain the scraper-side source of truth. AI Job Assistant imports completed runs into its own database for UI, filtering, and application handoff.

### 2.4 Run execution model

Use a background subprocess rather than blocking the FastAPI server.

The browser automation process should:

1. Start using the AI Job Assistant Python environment.
2. Run from the `BrowserAutomationForLinkdin` working directory.
3. Attach to the already-open logged-in Chrome through the scraper's existing CDP mechanism.
4. Write its normal JSON run output exactly as it currently does.
5. Return its process exit code.
6. Let AI Job Assistant import the newly created run JSON after successful completion.

Only one LinkedIn scraping process should be active at a time in the first implementation, because the scraper is controlling one browser/CDP session and the application is single-user/local.

---

# 3. User Experience

## 3.1 Feature name

Use:

**LinkedIn Job Finder**

This is clearer than exposing implementation terms such as "automation", "scraper", or individual Python script names.

---

## 3.2 Dashboard entry

Add a prominent Dashboard action:

**Find Jobs on LinkedIn**

Clicking it opens the LinkedIn Job Finder page.

Do not expose script filenames anywhere in the user-facing interface.

---

## 3.3 LinkedIn Job Finder page layout

Recommended structure:

### Header

- Title: `LinkedIn Job Finder`
- Short description explaining that jobs are collected from the user's LinkedIn session and can later be filtered and drafted through AI Job Assistant.
- Current browser/session status indicator.

### Search & Automation panel

This is the main control area.

#### Job Role

Single-selection only.

Provide:

- Existing configured role presets from the scraper.
- A custom text input: `Enter a job role...`
- Only one role is active for a search at a time.

Examples should be loaded from the existing scraper configuration rather than invented separately in the new UI.

#### Sort By

Use a LinkedIn-like control such as:

- `Most relevant`
- `Most recent`

Only expose values that map to behavior the existing scraper actually supports.

#### Date Posted

Use a LinkedIn-like control.

At minimum, expose the existing scraper's supported date-filter behavior, including the existing `Past 24 hours` capability.

If the scraper supports additional date ranges, expose those through the same control. Do not silently invent unsupported scraper behavior.

#### Run mode buttons

Use friendly labels:

| UI label | Existing scraper behavior |
|---|---|
| **Standard Job Search** | Standard run |
| **Latest Jobs** | Latest run |
| **Jobs Posted in Last 24 Hours** | Date-posted-24h run |
| **Top Matches** | Top-match run |
| **Home Feed** | Feed run |
| **Continue Search** | Continuation run |

The UI should show these as clean cards/buttons, not filenames.

### Run status panel

After a run starts, show:

- Running / completed / failed
- Selected role
- Selected mode
- Selected filters
- Start time
- Current process state
- Collected count when available
- Error message when applicable

The page should remain usable while the scraper process runs.

Buttons that would start a conflicting second scraper run should be disabled while one is active.

---

# 4. Collected Jobs Area

Create a clearly separated section:

**Collected LinkedIn Jobs**

Every imported job gets a stable UI/database ID.

Each job card/row should show only useful information, for example:

- Job ID
- Role/title
- Company
- Location
- Experience
- Employment type
- Salary when available
- Email when available
- Short JD preview
- Application method
- Image indicator when relevant

Do not expose the entire raw scraper payload in the main row.

Use expandable details for longer JD content.

---

## 4.1 Link actions

Each job should have separate buttons/links where the source contains them.

### LinkedIn Post

**View LinkedIn Post**

Opens the collected `linkedin_post_url` so the user can go directly to the LinkedIn post.

### LinkedIn Job

**View Job**

Opens `job_url` when present.

### External Apply

**Open Apply Link**

Opens `apply_url` when present.

### Job image

For image-based job posts, provide:

**View Job Image**

when an image URL exists.

These links are presentation/navigation actions only. They must never be confused with the application's `application_url` used by AI Job Assistant's Playwright form detection.

---

# 5. Two Filtering Batches

Filtering must not remove jobs solely because they have no email.

Create two logical batches inside the LinkedIn Job Finder:

## Batch A — Jobs With Email

Jobs where a primary email is available.

These go through the LLM relevance filter when the user clicks the filtering action.

## Batch B — Jobs Without Email

Jobs with no email but one or more useful application paths, such as:

- External apply link
- LinkedIn job link
- Job image / image-based post
- Other scraper-recorded application method

These jobs must remain visible and must have their own filtering batch.

They must **not** be silently excluded from the email-job filtering step.

UI should make this separation obvious, for example:

```text
Collected Jobs
├── With Email
└── Without Email
    ├── Apply Link
    ├── LinkedIn Job
    └── Image Job Post
```

The exact visual layout can be tabs/cards rather than nested lists, as long as the categories are easy to understand and use.

---

# 6. Manual LLM Filtering

Filtering must be **user-triggered**, not automatic after every scrape.

Primary action:

**Filter Collected Jobs**

When clicked:

1. Import/confirm the current collected jobs in the DB.
2. Split them into the two batches above.
3. Run the LLM filter for the appropriate jobs.
4. Save each decision to the database.
5. Refresh the filtered-results area.

The UI should show a small progress state while filtering.

---

# 7. LLM Filtering Rules

## 7.1 Model

Use the Groq model:

```text
openai/gpt-oss-120b
```

The filtering model should be dedicated to relevance classification and should not generate explanations unless explicitly needed for debugging.

---

## 7.2 Default relevance criteria

Default prompt behavior:

```text
Accept fresher or entry-level roles only.
Accept roles requiring at most 1 year of experience.
Accept the JD when no experience requirement is mentioned.
Reject roles that clearly require more than 1 year of experience.
```

The exact prompt used by the system must be editable by the user.

---

## 7.3 Prompt settings

Add a **LinkedIn Filter Settings** section/page/panel.

Provide:

- Editable filtering prompt.
- Maximum allowed experience in years.
- Option to accept jobs where experience is not mentioned.
- Save/apply control.
- Preview of the final prompt that will be sent to the filtering model.

The structured controls should update the prompt used by filtering, while the editable prompt remains the final user-adjustable instruction.

Do not hard-code the fresher/1-year rules in a way that prevents later user customization.

---

# 8. Minimal-Token Filtering Design

Token usage is a first-class requirement.

## 8.1 Input minimization

Only the **JD text** should be sent to the filtering model.

Do not send as separate model input:

- LinkedIn post URL
- LinkedIn job URL
- External apply URL
- Image URL
- Email address
- Scraper run metadata
- Company field
- Location field
- Internal database IDs as semantic data

The JD should be locally cleaned before the LLM call:

- Normalize whitespace.
- Remove URLs from the text sent to the classifier.
- Remove obvious source/navigation boilerplate when it can be removed deterministically.
- Prefer the scraper's already-extracted `job_description` field when it is available.
- Fall back to cleaned `full_post` only when necessary.

The model must see the smallest useful text representation that still preserves the job requirements needed for classification.

A configurable maximum JD length should be enforced to prevent unexpectedly large prompts. Truncation must preserve the most useful JD content and should be implemented deterministically.

---

## 8.2 Batch requests instead of verbose per-JD calls

Do not make a large verbose LLM call for every JD if multiple JDs can be classified in a single request.

Use compact batches.

Example model input structure:

```text
System:
Classify each JD using the supplied criteria.
Return only one line per ID using ID:Y or ID:N.
No explanations.

User:
17
<JD text>

18
<JD text>

19
<JD text>
```

The actual implementation should keep the wrapper text as small as practical.

---

## 8.3 Minimal output

The requested output format must be:

```text
17:Y
18:N
19:Y
```

No explanations.

The requested maximum output token budget should be dynamically sized to the number of jobs in the batch rather than using a large fixed response budget.

Example strategy:

```text
max_output_tokens ~= small_constant × number_of_JDs
```

The implementation should use the smallest safe value that still reliably returns one decision per JD.

Temperature should be deterministic/low for classification.

---

## 8.4 Output parser

Use a strict canonical parser first:

```text
ID:Y
ID:N
```

For resilience, the parser may accept equivalent positive/negative tokens such as:

Positive:

- Y
- YES
- PASS
- KEEP
- RELEVANT

Negative:

- N
- NO
- REJECT
- SKIP
- IRRELEVANT

However, the prompt should always request the shortest canonical form: `ID:Y` or `ID:N`.

Never infer a decision from a long explanation when a deterministic classification token is absent. Mark that JD's filter result as an error/pending-retry state instead.

---

# 9. Filtered Results Area

Create a dedicated section:

**Filtered Jobs**

Show only accepted/relevant JDs in the normal actionable view.

Recommended organization:

```text
Filtered Jobs
├── With Email
└── Without Email
    ├── Apply Link
    ├── LinkedIn Job
    └── Image Job Post
```

Each filtered job should include:

- JD ID
- Role/title
- Company
- Experience
- Location
- Email when available
- JD preview
- `View LinkedIn Post`
- `View Job` when available
- `Open Apply Link` when available
- `View Job Image` when available
- **Draft & Apply**

Rejected decisions should remain represented by the saved database filter state, but rejected jobs must not occupy the main actionable filtered-results view.

---

# 10. Database Design

Do not overload `JobApplication` with all scraper-specific fields.

Add LinkedIn-specific persistence.

## 10.1 `LinkedInRun`

Suggested fields:

```text
id
scraper_run_number
mode
role
sort_by
date_posted
configuration_json
status
started_at
completed_at
exit_code
log_path
error_message
collected_count
filtered_count
created_at
```

This records each LinkedIn automation run and the UI configuration used.

---

## 10.2 `LinkedInJob`

Suggested fields:

```text
id
linkedin_run_id
linkedin_post_url
job_url
apply_url
image_url
company
role
location
experience
employment_type
salary
email
additional_emails
application_methods
application_instructions
job_description
full_post
skills
responsibilities
qualifications
has_image
image_based_job_post
match_reasons
filter_status
filter_batch
filter_model
filter_prompt_version
filtered_at
job_application_id
created_at
updated_at
```

### Important filter column

```text
filter_status
```

Suggested states:

```text
pending
accepted
rejected
error
```

Use an additional batch/source field to distinguish email and non-email filtering.

Do not make `linkedin_post_url` the AI Job Assistant `application_url`.

Do not make `job_url` the AI Job Assistant `application_url`.

Do not blindly place `lnkd.in`/external links into `application_url` without validation.

---

## 10.3 `JobApplication` linkage

Add a nullable foreign-key/reference column such as:

```text
linkedin_job_id
```

This lets the existing application record point back to the originating LinkedIn job without replacing the current application model.

A separate source indicator is recommended if it fits the current schema:

```text
source = linkedin_automation
```

Do not repurpose unrelated existing fields such as `is_manual` merely to identify LinkedIn jobs.

---

# 11. Importing Scraper Results

The integration should use the existing scraper JSON output rather than changing the scraper's core persistence mechanism.

## Flow

```text
LinkedIn UI
    ↓
AI Job Assistant integration service
    ↓
start scraper subprocess
    ↓
BrowserAutomationForLinkdin
    ↓
existing JSON run file
    ↓
AI Job Assistant import service
    ↓
PostgreSQL LinkedInRun + LinkedInJob
    ↓
LinkedIn Job Finder UI
```

Before launching a run, capture the current known run-file state.

After the subprocess exits successfully, identify the newly created run JSON deterministically.

Do not depend on stdout as the machine-readable contract.

Do not rewrite or migrate existing scraper run files.

---

# 12. Backend Integration Layer

Create a small dedicated integration layer in AI Job Assistant.

Recommended components:

```text
linkedin_integration/
├── runner.py
├── importer.py
├── filter_service.py
├── prompt_service.py
└── url_utils.py
```

Exact filenames can be adjusted to match the existing project style, but responsibilities should remain separated.

## `runner`

Responsibilities:

- Validate request/configuration.
- Build the correct existing scraper command.
- Launch subprocess.
- Store PID/process state.
- Capture stdout/stderr into an application log.
- Poll/track status.
- Detect completion/failure.
- Hand completed runs to importer.

## `importer`

Responsibilities:

- Find the correct completed scraper JSON.
- Parse the normalized `{run_info, summary, jobs}` payload.
- Insert/update `LinkedInRun`.
- Insert `LinkedInJob` rows.
- Preserve all scraper URL fields separately.
- Preserve image metadata and raw JD content.

## `filter_service`

Responsibilities:

- Split jobs into email/non-email batches.
- Clean JD input locally.
- Build minimal batch prompts.
- Call Groq using `openai/gpt-oss-120b`.
- Parse compact Y/N results.
- Update `filter_status`.
- Record model/prompt version/timestamp.
- Handle partial or malformed responses safely.

## `prompt_service`

Responsibilities:

- Load saved filter settings.
- Build the final prompt from user settings.
- Keep the prompt editable.
- Return a preview for the Settings UI.

## `url_utils`

Responsibilities:

- Validate/normalize URLs for display/navigation.
- Keep `linkedin_post_url`, `job_url`, and `apply_url` distinct.
- Never allow source post/job URLs to become `application_url` accidentally.

---

# 13. FastAPI Routes

Add a dedicated LinkedIn feature surface rather than scattering routes across unrelated handlers.

Recommended routes:

```text
GET  /linkedin-jobs
GET  /api/linkedin/runs
POST /api/linkedin/runs/start
GET  /api/linkedin/runs/{run_id}
POST /api/linkedin/filter
GET  /api/linkedin/jobs
GET  /api/linkedin/jobs/{job_id}
POST /api/linkedin/jobs/{job_id}/draft-apply
GET  /api/linkedin/filter-settings
POST /api/linkedin/filter-settings
```

The exact route naming can follow existing conventions.

The UI page can use regular server-rendered Jinja2 plus the existing vanilla JavaScript architecture instead of introducing React/Vue.

---

# 14. Normal AI Job Assistant Handoff

## 14.1 `Draft & Apply`

Clicking **Draft & Apply** on a filtered LinkedIn job should create an ordinary AI Job Assistant `JobApplication` using the existing application-processing pipeline.

Conceptually it must behave like:

```text
User copies JD
    ↓
AI Job Assistant /applications/text/
    ↓
process_application()
    ↓
Draft
    ↓
User reviews
    ↓
Send
```

The LinkedIn integration should reuse this flow instead of implementing a second email-drafting system.

---

## 14.2 Handoff data

The application created from a LinkedIn job should use the copied JD content as its normal text input.

Where available, prepopulate structured fields such as:

- company
- role
- contact email

The LinkedIn source metadata can be retained in the LinkedIn DB record and through a LinkedIn-job reference on `JobApplication`.

The LLM drafting process should continue using the existing AI Job Assistant profile/system prompt.

---

## 14.3 Email jobs

For a filtered job with an email:

- Create the JobApplication.
- Run the existing processing/drafting flow.
- Put the email into the draft recipient when available.
- Let the user review before sending.

Do not automatically send the application merely because the job passed filtering.

---

## 14.4 Jobs without email

For jobs without email:

- Keep them in their separate filtered batch.
- Permit `Draft & Apply` so the JD can still enter the normal AI Job Assistant workflow.
- Keep `Open Apply Link`, `View Job`, `View LinkedIn Post`, and image actions available.
- If no email recipient exists, the draft should still be possible.
- Sending should remain blocked until a valid recipient is provided, matching the existing send behavior.

The absence of email must not cause the job to disappear from the LinkedIn filtering workflow.

---

# 15. URL Safety / Field Separation

These fields must remain different everywhere:

```text
linkedin_post_url = LinkedIn post permalink
job_url           = LinkedIn job listing URL
apply_url         = external application link
application_url   = AI Job Assistant form-detection target
```

Rules:

1. `linkedin_post_url` is for viewing the LinkedIn post and retaining source identity.
2. `job_url` is for opening the LinkedIn job listing.
3. `apply_url` is for the user's external apply action when present.
4. `application_url` must not be populated from the LinkedIn post URL.
5. `application_url` must not be populated from the LinkedIn jobs URL.
6. An external apply URL may only become an AI Job Assistant form target after explicit validation of its semantics.
7. Filtering must never receive the URLs as separate LLM input data.

The integration must not claim that the existing scraper currently sends a wrong URL. This is a constraint that the new integration must enforce.

---

# 16. Environment / Groq Configuration

The user will copy the `BrowserAutomationForLinkdin` `.env` configuration into the AI Job Assistant environment.

Implementation requirements:

- Merge missing variables into the AI Job Assistant `.env` rather than blindly overwriting existing values.
- Preserve the AI Job Assistant's existing Groq configuration.
- Verify the actual variable name used by the LinkedIn automation before wiring it.
- Use the merged AI Job Assistant environment as the runtime source.
- Never display or log the API key.

Prefer one authoritative runtime configuration after the merge rather than maintaining two independent copies of the same Groq secret.

---

# 17. UI Settings

Add a LinkedIn-specific settings area for:

### Search settings

- Default role
- Preset roles
- Sort selection
- Date-posted selection
- Any other scraper-supported configurable search controls

### Filter settings

- Filter prompt
- Maximum experience threshold
- Whether unspecified experience is accepted
- Batch size, if necessary for token safety
- Maximum JD characters sent to the classifier, if exposed

The model name should be displayed as:

```text
Groq — openai/gpt-oss-120b
```

and treated as fixed unless a later product decision explicitly changes it.

---

# 18. Token-Control Rules

The filtering implementation should enforce these rules:

1. Never send URLs as separate fields.
2. Never send scraper metadata to the classifier.
3. Prefer the extracted JD over the full raw post.
4. Normalize/clean text before the request.
5. Use compact batches.
6. Use one compact Y/N decision per JD.
7. Use no explanations.
8. Dynamically size the output token limit to the number of JDs in the batch.
9. Use deterministic classification settings.
10. Retry only malformed/failed batches, not successful classifications.
11. Do not repeatedly re-filter jobs whose saved status already represents the current prompt version/configuration unless the user explicitly requests a re-filter.

This should keep both input and output usage very small.

---

# 19. Prompt Versioning

Because the user can modify the filter prompt, each filtering decision should remember which prompt version/settings produced it.

Store enough information to answer:

```text
Which model filtered this JD?
Which prompt/settings were active?
When was it filtered?
What was the final decision?
```

Do not store API secrets in the database.

---

# 20. Error Handling

## Scraper errors

If the scraper process fails:

- Mark the LinkedIn run as failed.
- Show a clear UI error.
- Keep previous successful runs/jobs untouched.
- Preserve the scraper's normal error/exit behavior.

## Browser/CDP errors

Show actionable status such as:

```text
LinkedIn browser connection could not be established.
Make sure your logged-in Chrome session is running with the required CDP setup.
```

Do not attempt to add LinkedIn password handling.

## Filter errors

If an LLM request fails:

- Keep the JD in the database.
- Do not mark it as accepted merely because the model failed.
- Use `error`/`pending` state.
- Allow the user to run filtering again.

If only part of a batch returns valid results, do not invent decisions for missing IDs.

## Draft handoff errors

If creating the JobApplication or starting the normal pipeline fails:

- Keep the LinkedIn job record.
- Show the failure on that job.
- Do not lose the JD or its links.

---

# 21. Security

The integration is local-first.

Requirements:

- Keep AI Job Assistant bound to its existing local interface unless the application already requires otherwise.
- Do not add LinkedIn credentials storage.
- Do not log Groq API keys.
- Escape raw `full_post` content in Jinja2-rendered HTML.
- Treat scraped LinkedIn text as untrusted user-generated/web-derived content.
- Validate all links before presenting actions.
- Do not let raw scraped text become executable HTML/JS.
- Keep subprocess arguments explicit; do not construct shell command strings with unescaped user input.

---

# 22. Dependency / Runtime Integration

The embedded scraper and AI Job Assistant must run from one supported Python environment.

Implementation steps:

1. Compare `BrowserAutomationForLinkdin` requirements with AI Job Assistant requirements.
2. Add only missing required packages to the AI Job Assistant environment.
3. Avoid copying the scraper's virtual environment.
4. Confirm Playwright is available to the Python executable used by the FastAPI app/subprocess.
5. Confirm browser/CDP prerequisites remain unchanged.
6. Run both existing applications' relevant startup checks before full integration testing.

Do not perform dependency upgrades unless required for compatibility.

---

# 23. UI Details

Use the existing AI Job Assistant design system and `base.html` shell.

The LinkedIn page should look like an existing feature of the application, not like an embedded developer tool.

Recommended visual hierarchy:

```text
LinkedIn Job Finder

[ Job Role ▼ ] [ Sort By ▼ ] [ Date Posted ▼ ]

[ Standard Job Search ] [ Latest Jobs ] [ Top Matches ]
[ Jobs Posted in Last 24 Hours ] [ Home Feed ] [ Continue Search ]

Run Status
────────────────────────────────

Collected Jobs
────────────────────────────────
[ With Email ] [ Without Email ]

[ Filter Collected Jobs ]

Filtered Jobs
────────────────────────────────
[ With Email ] [ Without Email ]

Job card
  Company / Role
  Experience / Location
  JD preview
  [ View LinkedIn Post ]
  [ View Job ] [ Open Apply Link ]
  [ Draft & Apply ]
```

The exact styling can be refined during implementation, but the information hierarchy should stay this clear.

---

# 24. No Script Names in UI

Never show:

```text
run.py
latest_run.py
date_posted_24h_run.py
top_match_run.py
feed_run.py
continue_run.py
```

Show only user-friendly concepts:

```text
Standard Job Search
Latest Jobs
Jobs Posted in Last 24 Hours
Top Matches
Home Feed
Continue Search
```

The backend may map these labels to the existing entry points internally.

---

# 25. Implementation Phases

## Phase 0 — Integration-safe baseline

- Confirm the embedded folder location.
- Verify existing scraper entry points.
- Verify current AI Job Assistant startup behavior.
- Compare dependency sets.
- Verify the merged `.env` configuration.
- Do not modify scraper behavior.

## Phase 1 — Database foundation

- Add `LinkedInRun`.
- Add `LinkedInJob`.
- Add `filter_status` and filtering metadata.
- Add `linkedin_job_id` linkage to `JobApplication`.
- Create a safe Postgres migration compatible with the project's existing migration approach.

## Phase 2 — Scraper runner integration

- Add the dedicated subprocess runner.
- Map friendly UI modes to existing scraper entry points.
- Pass the selected role/configuration through the scraper's supported CLI/config mechanism.
- Prevent blocking the FastAPI event loop.
- Persist process/run state.
- Import the completed JSON output.

## Phase 3 — LinkedIn Job Finder UI

- Add Dashboard entry.
- Add page route/template.
- Add search controls.
- Add six friendly run buttons.
- Add run status display.
- Add collected jobs area.
- Add source/application link actions.

## Phase 4 — Filtering engine

- Implement filter settings.
- Implement JD-only cleaning.
- Implement batch splitting.
- Implement minimal-token Groq classifier.
- Implement compact Y/N parser.
- Persist filter results.
- Render filtered results.

## Phase 5 — AI Job Assistant handoff

- Add `Draft & Apply` action.
- Create normal `JobApplication` records from filtered LinkedIn JDs.
- Reuse existing `process_application()` and drafting flow.
- Preserve recipient behavior for email/no-email jobs.
- Link the application back to the LinkedIn job record.

## Phase 6 — Quality / failure handling

- Add process locking/active-run protection.
- Add scraper error states.
- Add filter error states.
- Add retry behavior for failed filtering batches.
- Add safe link validation and URL separation checks.

## Phase 7 — Testing

Run the existing scraper test suite unchanged.

The existing LinkedIn automation test baseline must remain green.

Add targeted AI Job Assistant tests for:

- Friendly mode → correct entry point mapping.
- Role input handling.
- Date/sort mapping.
- Run process lifecycle.
- JSON import.
- Database persistence.
- Email/non-email batch separation.
- JD-only LLM payload.
- URL stripping from filter input.
- Prompt generation.
- Dynamic output-token calculation.
- `ID:Y` / `ID:N` parsing.
- Malformed model output handling.
- Filter result persistence.
- LinkedIn post link preservation.
- `application_url` safety.
- Draft & Apply handoff.
- No-email draft behavior.

## Phase 8 — End-to-end manual verification

Perform a real local test using the existing Chrome/CDP setup.

Verify each mode individually:

```text
Standard Job Search
Latest Jobs
Jobs Posted in Last 24 Hours
Top Matches
Home Feed
Continue Search
```

Verify the complete workflow:

```text
Dashboard
  ↓
LinkedIn Job Finder
  ↓
Select role
  ↓
Run search
  ↓
JSON created
  ↓
Jobs imported to DB
  ↓
Collected jobs displayed
  ↓
Filter Collected Jobs clicked
  ↓
Email batch + non-email batch filtered separately
  ↓
Accepted jobs displayed
  ↓
View LinkedIn Post / Job / Apply / Image
  ↓
Draft & Apply
  ↓
Existing AI Job Assistant processing
  ↓
Draft
  ↓
User review
  ↓
Send
```

---

# 26. Regression Constraints

The implementation must not break existing AI Job Assistant behavior.

It must also preserve the LinkedIn scraper's existing behavior.

Do not change:

- LinkedIn post URL requirement.
- Existing JSON job field names.
- Existing scraper qualification gates.
- Existing deduplication semantics.
- Existing continuation seeding semantics.
- Existing run-file numbering/persistence behavior.
- Existing six entry-point literals.
- Existing browser/navigation/sorting/date-filter mechanics unless explicitly required by a user-facing configuration that already maps to supported functionality.
- Existing email drafting/sending flow.
- Existing normal AI Job Assistant job intake behavior.

The LinkedIn feature is additive.

---

# 27. Important Non-Goals

Do not implement in this integration:

- LinkedIn username/password storage.
- A new authentication system for LinkedIn.
- A new email sender.
- A second LLM drafting pipeline.
- A new frontend framework.
- Automatic sending without user review.
- Automatic filtering immediately after every scrape.
- Replacing the scraper's JSON persistence.
- Merging Playwright browser objects into the FastAPI process.
- Turning LinkedIn post URLs into AI Job Assistant application URLs.

---

# 28. Definition of Done

The integration is complete when all of the following are true:

1. `BrowserAutomationForLinkdin` is physically inside AI Job Assistant.
2. The Dashboard contains a working **Find Jobs on LinkedIn** entry point.
3. The page is branded **LinkedIn Job Finder**.
4. All six current scraper modes are available using friendly labels.
5. The user can choose one role at a time and type a custom role.
6. Supported Sort By and Date Posted controls are configurable.
7. The scraper runs as a separate background subprocess.
8. Existing scraper JSON files continue to be written normally.
9. Completed runs are imported into PostgreSQL.
10. Collected jobs are displayed in the LinkedIn page.
11. Email and non-email jobs remain separate.
12. Non-email jobs are never discarded merely because email is absent.
13. The user manually clicks to start filtering.
14. Filtering uses Groq `openai/gpt-oss-120b`.
15. The filter prompt is editable in settings.
16. Default criteria are fresher/entry-level, maximum 1 year, and experience-unspecified accepted.
17. Only cleaned JD text is sent to the filter model.
18. Filter output is compact and machine-parseable as `ID:Y` / `ID:N`.
19. Output token budgets are kept deliberately minimal.
20. Filter status is saved in PostgreSQL.
21. Accepted jobs appear in a dedicated filtered-results area.
22. Every job retains a clickable LinkedIn post link.
23. Job/apply/image links are available in separate user actions when present.
24. `Draft & Apply` feeds the JD into the existing AI Job Assistant application pipeline.
25. No LinkedIn post/job URL is accidentally used as `application_url`.
26. Emailless jobs can still be drafted and manually completed/applied.
27. Existing scraper tests remain passing.
28. Existing AI Job Assistant functionality remains working.
29. Real end-to-end testing succeeds for all six run modes.

---

# 29. Final Architecture Summary

```text
                         AI JOB ASSISTANT
┌─────────────────────────────────────────────────────────────┐
│                                                             │
│ Dashboard                                                   │
│    │                                                        │
│    └── Find Jobs on LinkedIn                                │
│             │                                               │
│             ▼                                               │
│      LinkedIn Job Finder UI                                 │
│      ┌──────────────────────────────┐                       │
│      │ Role / Sort / Date           │                       │
│      │ Standard / Latest / 24h      │                       │
│      │ Top / Feed / Continue        │                       │
│      └──────────────┬───────────────┘                       │
│                     │                                       │
│                     ▼                                       │
│          LinkedIn Integration Runner                        │
│                     │                                       │
│             subprocess boundary                             │
│                     │                                       │
│                     ▼                                       │
│       BrowserAutomationForLinkdin                           │
│         Playwright + existing CDP flow                      │
│                     │                                       │
│                     ▼                                       │
│          Existing scraping JSON                             │
│                     │                                       │
│                     ▼                                       │
│              Import Service                                 │
│                     │                                       │
│                     ▼                                       │
│      PostgreSQL: LinkedInRun / LinkedInJob                  │
│                     │                                       │
│              ┌──────┴──────┐                                │
│              ▼             ▼                                │
│       With Email     Without Email                          │
│              │             │                                │
│              └──────┬──────┘                                │
│                     ▼                                       │
│             Manual Filter button                            │
│                     │                                       │
│                     ▼                                       │
│       Minimal JD-only Groq classifier                       │
│         openai/gpt-oss-120b                                │
│                     │                                       │
│                     ▼                                       │
│             Filtered Jobs                                   │
│               │        │                                    │
│               │        └── View Post / Job / Apply / Image  │
│               │                                             │
│               └── Draft & Apply                             │
│                           │                                 │
│                           ▼                                 │
│             Existing JobApplication                         │
│                           │                                 │
│                           ▼                                 │
│               Existing process_application()                │
│                           │                                 │
│                           ▼                                 │
│                    Draft Studio                              │
│                           │                                 │
│                           ▼                                 │
│                         Send                                  │
│                                                             │
└─────────────────────────────────────────────────────────────┘
```

The key design principle is:

> **Native in product experience, isolated in runtime execution, minimal in LLM usage, and fully connected to the existing AI Job Assistant application workflow.**
