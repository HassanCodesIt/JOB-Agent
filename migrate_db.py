import os
from sqlalchemy import create_engine, text
from dotenv import load_dotenv

def migrate():
    load_dotenv()
    DATABASE_URL = os.getenv("DATABASE_URL")
    if not DATABASE_URL:
        print("DATABASE_URL not found in .env")
        return

    engine = create_engine(DATABASE_URL)
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
            
            # Table: job_applications
            conn.execute(text("ALTER TABLE job_applications ADD COLUMN IF NOT EXISTS poster_path VARCHAR;"))
            
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
