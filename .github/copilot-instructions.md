# Copilot instructions for AI Job assistant

## Architecture overview
- FastAPI app lives in [main.py](main.py#L1); it wires routes, templates, background tasks, and the end‑to‑end application pipeline.
- The core pipeline is `process_application()` in [main.py](main.py#L1): form detection (Playwright), LLM extraction + mapping (Groq), email draft creation, then DB updates.
- Services are separated into small modules:
  - Playwright form detection/fill: [automation_service.py](automation_service.py#L1)
  - LLM extraction/mapping/drafting/classification: [llm_service.py](llm_service.py#L1)
  - OCR via HuggingFace Router (OpenAI client): [ocr_service.py](ocr_service.py#L1)
  - IMAP inbox sync + classification: [email_service.py](email_service.py#L1)
  - Webhook notifications (n8n): [utils.py](utils.py#L1)

## Data model and flow
- SQLAlchemy models are in [models.py](models.py#L1); DB session/engine in [database.py](database.py#L1). Schemas mirror models in [schemas.py](schemas.py#L1).
- `JobApplication` drives most flows; related tables include `ApplicationForm`, `Draft`, `EmailEvent`, and `SentEmail`.
- `process_application()` updates status and drafts; it stores LLM form mappings as `Draft(draft_type="form_mapping")` and email drafts as `Draft(draft_type="email")`.

## UI and API
- Server-rendered pages use Jinja templates in [templates/](templates/). Static assets are in [static/](static/).
- Key routes are in [main.py](main.py#L1) (dashboard, apply, settings, and API endpoints for uploads, sync, drafts, and user settings).

## Environment and external dependencies
- Required env vars (via .env): `DATABASE_URL`, `GROQ_API_KEY`, `HF_TOKEN`, `EMAIL`, `PASSWORD`, `IMAP_SERVER`, `N8N_WEBHOOK_URL`.
- External integrations: Postgres (SQLAlchemy), Groq LLM, HuggingFace Router for OCR, IMAP mailbox, and optional n8n webhook.

## Local dev workflow
- Start the app with the Uvicorn entrypoint in [run.py](run.py#L1) (reload enabled).
- On Windows, the event loop policy is explicitly set in [main.py](main.py#L1) and [run.py](run.py#L1); keep this when adding async code.

## Project conventions
- LLM calls return JSON and are parsed defensively; see patterns in [llm_service.py](llm_service.py#L1).
- CC email extraction is supported end‑to‑end (OCR → LLM extraction → DB fields). Keep `cc_emails` as comma‑separated string in `JobApplication`/`SentEmail`.
- Notifications are side‑effectful webhooks; keep them in [utils.py](utils.py#L1) and call from workflow code, not route handlers.
