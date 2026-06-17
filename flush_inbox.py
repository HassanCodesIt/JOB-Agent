from database import SessionLocal
import models

def flush_inbox_cache():
    db = SessionLocal()
    try:
        print("Clearing inbox cache to fix timestamps and ordering...")
        # Delete only EmailEvents that were synced with the incorrect default timestamp
        # or just clear all EmailEvents since they'll be refetched by Deep Sync anyway
        db.query(models.EmailEvent).delete()
        db.commit()
        print("Done. Inbox cleared.")
    except Exception as e:
        print(f"Error flushing: {e}")
    finally:
        db.close()

if __name__ == "__main__":
    flush_inbox_cache()
