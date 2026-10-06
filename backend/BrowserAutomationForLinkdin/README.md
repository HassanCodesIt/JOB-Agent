# LinkedIn Job Post Collector

Searches LinkedIn **Posts** for AI/ML job openings and prints, in the terminal, only
the posts that pass all five collection criteria:

1. they match a target role (including spelling variations),
2. they look like a real job opportunity (not announcements or celebrations),
3. they contain meaningful job-description information,
4. they contain **at least one e-mail address**,
5. they are not duplicates of an already collected post.

The script attaches to a Chrome window **you** start and are already logged into, so it
never asks for credentials, never logs you out, and never closes your browser or tab.

---

## Quick start (one command)

```bash
pip install -r requirements.txt
python run.py --launch-chrome
```

`run.py` checks the Python version and dependencies, starts Chrome with remote debugging
(if it is not already listening), logs into nothing itself, and then runs `main.py`.

If you prefer to start Chrome yourself (you only have to do this once per session):

```bash
# Windows
chrome.exe --remote-debugging-port=9222 --user-data-dir="C:\chrome-linkedin-profile"

# macOS
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-linkedin-profile"

# Linux
google-chrome --remote-debugging-port=9222 --user-data-dir="$HOME/chrome-linkedin-profile"
```

Log into LinkedIn in that window, keep it open, then:

```bash
python run.py
```

---

## Usage

```bash
python run.py                                     # all 7 roles, default limits
python run.py --roles "LLM Engineer,AI Developer" # only these roles
python run.py --max-scrolls 2 --max-jds 3         # small smoke-test run
python run.py --dry-run                           # offline run on tests/fixtures/*.txt
python main.py --help                             # full flag list
```

`run.py` accepts `--install`, `--launch-chrome`, `--no-chrome-check`, `--profile` and
forwards everything else to `main.py`.

| Flag | Default | Meaning |
| --- | --- | --- |
| `--roles` | 7 roles (see below) | comma separated target roles |
| `--cdp-url` | `http://localhost:9222` | Chrome DevTools endpoint |
| `--max-scrolls` | `10` | scroll steps per role search |
| `--max-posts` | `100` | hard cap on posts processed |
| `--max-jds` | `30` | hard cap on collected job descriptions |
| `--min-jd-signals` | `2` | JD sections a post must contain |
| `--action-delay` | `1.0-2.5` | random delay between UI actions |
| `--page-load-delay` | `2.5-4.5` | random delay after page loads |
| `--config` | `./config.yaml` | YAML overrides |
| `--dry-run [path]` | `tests/fixtures` | run the decision pipeline offline |
| `--color` / `--no-color` | plain | ANSI colours in the output |
| `-v` / `-q` | - | verbose / quiet logging |

Default target roles: Generative AI Engineer, AI Developer, LLM Engineer,
Applied AI Engineer, Machine Learning Developer, AI Agent Engineer,
AI Application Developer.

---

## Output

```text
============================================================
MATCH #01
============================================================
TARGET ROLE: AI Developer
MATCHED ROLE VARIATIONS: ai engineer
AUTHOR: Priya Raghavan
COMPANY: Northwind Labs
LOCATION: Bengaluru
EXPERIENCE: 3-5 years
EMPLOYMENT TYPE: Full-Time
SALARY: 25-35 LPA
EMAIL: hr@northwindlabs.com
SKILLS:
  - Python
  - PyTorch
RESPONSIBILITIES:
  - Build and ship generative AI features
QUALIFICATIONS:
  - Strong understanding of machine learning
JOB DESCRIPTION:
Northwind Labs is hiring an AI Engineer ...
APPLICATION INSTRUCTIONS:
  - send your resume to hr@northwindlabs.com
LINKEDIN POST: https://www.linkedin.com/feed/update/urn:li:activity:7123.../
MATCH REASONS:
  - Target role matched: AI Developer
  - Role variations found: ai engineer
  - Job signals: hiring, Full-time, Apply, send your resume
  - Job description sections found (8): Responsibilities, Requirements, ...
  - Email address found: hr@northwindlabs.com
============================================================
```

Anything that cannot be determined is printed as `Not specified` - nothing is invented.

The run ends with a summary that reconciles with the blocks printed above:

```text
============================================================
COLLECTION COMPLETE
============================================================
Target Roles Searched: N
Role Searches Skipped: N
Role Searches With Read Errors: N
Posts Processed: N
Potential Job Posts: N
Posts With Email: N
Valid Job Matches: N
Duplicates Removed: N
Posts Skipped (unreadable): N
Stop Reason: N

Final JDs Collected: N
============================================================
```

---

## Project layout

```text
main.py                  entry point / orchestration / CLI
run.py                   one-command launcher (deps + Chrome check)
config.py                Config dataclass, YAML + CLI loading
config.yaml              optional overrides
collector/
  browser.py             CDP attach, tab picking, randomised delays
  safety.py              CAPTCHA / verification / login-wall detection
  navigator.py           search box, submit, Posts filter (selectors as constants)
  scroller.py            scroll + load-wait loop, "see more" expansion
  post_reader.py         author / full text / permalink extraction
  role_matcher.py        role categories -> regex variations (+ AI-context guard)
  job_detector.py        positive / negative signals, JD section scoring
  email_extractor.py     permissive regex + obfuscation handling + denylists
  field_extractor.py     company, location, experience, skills, salary, ...
  dedupe.py              canonical URL key + normalised-text hash fallback
  pipeline.py            decide(): the five criteria, in order
  models.py              Post, RoleMatchResult, JobMatch, Stats
  printer.py             structured terminal blocks + summary
  logger.py              [INFO] / [WARNING] / [ERROR] helpers
tests/                   pytest unit tests + fixtures/ for the offline pipeline
```

## Tests

```bash
python -m pytest
```

No browser needed. `--dry-run` runs the same decision pipeline over
`tests/fixtures/*.txt`, which is the quickest way to see the output format.

## Politeness and safety rules enforced in code

- attaches to an existing browser only, never asks for or stores credentials;
- randomised delays between every action, moderate scroll distances;
- hard caps on scrolls / posts / JDs, and early exit when no new posts appear;
- a failed role search is retried once, then that role is skipped and counted;
- no CAPTCHA, proxy or fingerprint tricks - a verification screen stops the run
  safely and prints what to do;
- the browser, context, tab and login are never closed, not even on Ctrl+C
  (the summary is still printed).