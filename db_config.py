import os
import psycopg2
from psycopg2.extensions import ISOLATION_LEVEL_AUTOCOMMIT
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from dotenv import load_dotenv
import time

# Load environment variables
load_dotenv()

def setup_env():
    """Ensure .env exists and has initial values or captures them from terminal."""
    env_path = ".env"
    
    print("\n" + "="*50)
    print("       🔑 ENVIRONMENT & API CONFIGURATION 🔑       ")
    print("="*50)
    
    # Database Settings
    print("\n1. DATABASE SETTINGS")
    print("Database Credentials (press Enter for defaults):")
    db_user = input("   DB User [postgres]: ") or "postgres"
    db_pass = input("   DB Password [12345678]: ") or "12345678"
    db_host = input("   DB Host [localhost]: ") or "localhost"
    db_port = input("   DB Port [5432]: ") or "5432"
    db_name = input("   DB Name [Job_assistant]: ") or "Job_assistant"

    # API Keys & Email
    print("\n2. AI API KEYS")
    print("Groq is used for JD extraction and email drafting.")
    groq_api = input("   Groq API Key (gsk_...): ").strip()
    print("HuggingFace is used for OCR/Poster processing.")
    hf_token = input("   HF Token (hf_...): ").strip()
    
    print("\n3. EMAIL CONFIGURATION (For sending applications)")
    print("NOTE: For Gmail, you MUST use an 'App Password', not your regular login password.")
    print("Get one here: https://myaccount.google.com/apppasswords")
    email_addr = input("   Your Email Address: ").strip()
    email_pass = input("   Email App Password: ").strip()
    imap_srv = input("   IMAP Server [imap.gmail.com]: ").strip() or "imap.gmail.com"
    
    env_content = f"""# Database Configuration
DATABASE_URL=postgresql://{db_user}:{db_pass}@{db_host}:{db_port}/{db_name}
DB_NAME={db_name}
DB_USER={db_user}
DB_PASSWORD={db_pass}
DB_HOST={db_host}
DB_PORT={db_port}

# API Keys and Email
GROQ_API_KEY={groq_api}
HF_TOKEN={hf_token}
EMAIL={email_addr}
PASSWORD={email_pass}
IMAP_SERVER={imap_srv}
"""
    
    with open(env_path, "w") as f:
        f.write(env_content)
    
    print(f"\n✅ Created/Updated {env_path}")
    load_dotenv(override=True)

def create_database_if_not_exists():
    """Create the PostgreSQL database if it does not already exist."""
    print("\n--- Database Setup ---")
    print("Checking database existence...")
    
    db_name = os.getenv("DB_NAME")
    db_user = os.getenv("DB_USER")
    db_password = os.getenv("DB_PASSWORD")
    db_host = os.getenv("DB_HOST")
    db_port = os.getenv("DB_PORT")

    try:
        # Use default 'postgres' database to connect and check/create the target database
        conn = psycopg2.connect(
            dbname="postgres",
            user=db_user,
            password=db_password,
            host=db_host,
            port=db_port
        )
        conn.set_isolation_level(ISOLATION_LEVEL_AUTOCOMMIT)
        cur = conn.cursor()

        # Check if database exists
        cur.execute(f"SELECT 1 FROM pg_catalog.pg_database WHERE datname = %s", (db_name,))
        exists = cur.fetchone()

        if not exists:
            print(f"Database '{db_name}' does not exist. Creating...")
            cur.execute(f'CREATE DATABASE "{db_name}"')
            print(f"Database '{db_name}' created successfully.")
        else:
            print(f"Database '{db_name}' already exists.")

        cur.close()
        conn.close()
    except Exception as e:
        print(f"❌ Error checking/creating database: {e}")
        print("Please ensure PostgreSQL is running and your credentials are correct.")
        return False
    return True

def initialize_tables():
    """Create all tables and run any necessary modifications."""
    print("\n--- Table Initialization ---")
    print("Initializing tables via SQLAlchemy...")
    try:
        # Import Base and models here to ensure they are registered with metadata after env load
        from database import Base, engine
        import models
        
        # Create all tables defined in models.py
        Base.metadata.create_all(bind=engine)
        print("✅ All tables created successfully.")
        
        # Supplemental migrations
        try:
            from migrate_db import migrate
            print("Running supplemental migrations...")
            migrate()
        except ImportError:
            pass
            
        return True
    except Exception as e:
        print(f"❌ Error creating tables: {e}")
        return False

def create_directories():
    """Create necessary directories for the application."""
    print("\n--- Directory Setup ---")
    directories = ["templates", "static", "uploads", "posters", "screenshots"]
    for directory in directories:
        if not os.path.exists(directory):
            os.makedirs(directory)
            print(f"Created directory: {directory}")
        else:
            print(f"Directory exists: {directory}")

def configure_database():
    """Main function to configure all necessary things."""
    print("="*50)
    print("       🚀 AI JOB ASSISTANT: FULL SYSTEM SETUP 🚀       ")
    print("="*50)
    
    # Step 1: Dynamic Environment Setup
    setup_env()
    
    # Step 2: Directory Setup
    create_directories()
    
    # Step 3: Database Creation
    if create_database_if_not_exists():
        # Step 4: Wait for DB to be ready and initialize tables
        time.sleep(1)
        if initialize_tables():
            print("\n" + "="*50)
            print("🎉 SYSTEM SETUP COMPLETE! 🎉")
            print("="*50)
            
            run_now = input("\nWould you like to start the application now? (y/n): ").lower().strip()
            if run_now == 'y':
                print("\n🚀 Starting AI Job Assistant...")
                import subprocess
                import sys
                try:
                    # Run main.py and wait for it
                    subprocess.run([sys.executable, "main.py"])
                except KeyboardInterrupt:
                    print("\n👋 Application stopped.")
            else:
                print("\nNext steps:")
                print(" 1. Run 'python main.py' to start the application manually.")
                print(" 2. Open http://localhost:8000 in your browser.")
                print(" 3. Start applying to jobs!")
                print("\nPress Enter to exit...")
                input()
        else:
            print("\n❌ Setup failed during table initialization.")
    else:
        print("\n❌ Setup failed during database creation.")

if __name__ == "__main__":
    configure_database()
