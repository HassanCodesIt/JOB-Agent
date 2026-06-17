# Auto Job Agent 🚀

Auto Job Agent is an AI-powered job application tracking and automated outreach system. It helps you scan job posters/links via OCR, generate personalized outreach/application emails using LLMs, and track recruiter replies directly in a unified command center.

---

## Key Features

1. **AI Job Poster Parsing (OCR)**: Upload or paste job posters/banners. The system extracts company name, role details, contact emails, CC addresses, and application links using the state-of-the-art `Qwen/Qwen3.6-27B:featherless-ai` model via the HuggingFace Router.
2. **First-Time Guided Setup**: Accessing the app for the first time redirects you to a profile configuration page. You can fill out your profile details manually or upload a PDF resume for instant AI-powered data extraction.
3. **Automated Application Drafts**: Instantly generates highly personalized cold emails or application messages using your skills, experience, and custom instructions.
4. **Smart Inbox Sync**: Syncs your Gmail inbox automatically, tracking recruiter responses and classifying replies (e.g., Shortlisted, Neutral, Rejections).
5. **Outreach Campaigns**: Launch bulk outreach campaigns by simply importing public Google Sheets.
6. **Interactive Editor**: Review drafts, request AI-driven refinements, add CCs, and send emails with your resume attached with a single click.

---

## Tech Stack

- **Backend**: FastAPI (Python 3.10+)
- **Database**: PostgreSQL (SQLAlchemy ORM)
- **OCR Engine**: Qwen 3.6 27B (via HuggingFace Router)
- **Drafting Engines**: Groq (Llama-3/similar) & OpenRouter (Backup)
- **Resume Extraction**: pdfminer.six (for text parsing) + LLM (for structuring data)
- **Browser Automation**: Playwright (for scraping/processing links)
- **Templating**: Jinja2 + CSS

---

## Prerequisites

Ensure you have the following installed on your machine:
1. **Python 3.10 or higher**: [Download Python](https://www.python.org/downloads/)
2. **PostgreSQL Database**: [Download PostgreSQL](https://www.postgresql.org/download/)
3. **Gmail Account with App Password**:
   - Enable **2-Step Verification** on your Google Account.
   - Go to your Google Account Settings > Security > **App passwords**.
   - Generate a new App Password for "Mail" (this gives you a 16-character code like `xxxx xxxx xxxx xxxx`).

---

## Setup & Installation

Follow these steps to run the application locally on your computer:

### Step 1: Clone or Copy the Repository
Navigate to the directory containing the project:
```bash
cd "AI Job assistant"
```

### Step 2: Create a Virtual Environment
Initialize a virtual environment to manage dependencies:
```bash
# On Windows
python -m venv venv
venv\Scripts\activate
```

### Step 3: Install Dependencies
Install all required libraries listed in `requirements.txt`:
```bash
pip install -r requirements.txt
```

### Step 4: Install Playwright Browsers
Playwright requires browser binaries to parse dynamic application pages:
```bash
playwright install
```

### Step 5: Configure the Environment Variables & Initialize Database
Create a file named `.env` in the root directory (you can copy `.env.example` to `.env` and edit it) or run the setup helper script:
```bash
python db_config.py
```
This script will prompt you for your database details and API keys in the terminal, check your PostgreSQL connection, create the database, and initialize all necessary tables automatically.

> [!WARNING]
> Do **not** use your standard Gmail password in the `PASSWORD` field. You must use a 16-character **Gmail App Password**.

---

## Running the Application

To run the application:

```bash
python run.py
```

Open your web browser and navigate to:
👉 **[http://localhost:8000](http://localhost:8000)**

On your first visit, you will be redirected to the **Profile Setup** page where you can manually enter your profile or upload a PDF resume for AI parsing.
