import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

import models

def migrate():
    load_dotenv()
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("DATABASE_URL not found in .env")
        return

    engine = create_engine(DATABASE_URL)

    # Make sure new tables (e.g. role_resumes) exist before columns reference them
    models.Base.metadata.create_all(bind=engine)

    with engine.connect() as conn:
        try:
            # Table: drafts
            conn.execute(text("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS subject VARCHAR;"))
            conn.execute(text("ALTER TABLE drafts ADD COLUMN IF NOT EXISTS is_favorite BOOLEAN DEFAULT FALSE;"))
            
            # Table: users
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS system_prompt TEXT;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS groq_api_key VARCHAR;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS hf_token VARCHAR;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS openrouter_api_key VARCHAR;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS resume_role VARCHAR;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS resume_summary TEXT;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS profile_summary TEXT;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS github_link VARCHAR;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS linkedin_link VARCHAR;"))
            conn.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS portfolio_link VARCHAR;"))
            
            # Table: job_applications
            conn.execute(text("ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS poster_path VARCHAR;"))
            conn.execute(text("ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS suggested_resume_id INTEGER REFERENCES role_resumes(id);"))
            conn.execute(text("ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS suggest_resume_change BOOLEAN DEFAULT FALSE;"))

            # Table: job_applications -> LinkedIn Job Finder linkage
            # (linkedin_jobs is created above by create_all, so the FK target exists.)
            conn.execute(text("ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS source VARCHAR;"))
            conn.execute(text("ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS linkedin_job_id INTEGER REFERENCES linkedin_jobs(id);"))

            # Table: linkedin_runs / linkedin_jobs / settings are new and created by create_all,
            # but guarantee the filter columns exist for databases created before them.
            conn.execute(text("ALTER TABLE linkedin_jobs ADD COLUMN IF NOT EXISTS filter_status VARCHAR DEFAULT 'pending';"))
            conn.execute(text("ALTER TABLE linkedin_jobs ADD COLUMN IF NOT EXISTS filter_batch VARCHAR;"))
            conn.execute(text("ALTER TABLE linkedin_jobs ADD COLUMN IF NOT EXISTS filter_model VARCHAR;"))
            conn.execute(text("ALTER TABLE linkedin_jobs ADD COLUMN IF NOT EXISTS filter_prompt_version INTEGER;"))
            conn.execute(text("ALTER TABLE linkedin_jobs ADD COLUMN IF NOT EXISTS filter_error TEXT;"))
            conn.execute(text("ALTER TABLE linkedin_jobs ADD COLUMN IF NOT EXISTS filtered_at TIMESTAMP;"))
            conn.execute(text("ALTER TABLE linkedin_jobs ADD COLUMN IF NOT EXISTS job_application_id INTEGER REFERENCES job_applications(id);"))
            conn.execute(text("ALTER TABLE linkedin_runs ADD COLUMN IF NOT EXISTS summary_json TEXT;"))

            # Table: email_events
            conn.execute(text("ALTER TABLE email_events ADD COLUMN IF NOT EXISTS application_id INTEGER;"))
            
            # Table: responses
            conn.execute(text("ALTER TABLE responses ADD COLUMN IF NOT EXISTS application_id INTEGER;"))
            
            conn.commit()
            print("Database migration successful: Added missing columns to all tables.")
        except Exception as e:
            print(f"Migration failed: {e}")

if __name__ == "__main__":
    migrate()
