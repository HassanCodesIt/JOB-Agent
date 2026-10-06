
import requests
import csv
import io
import json
import asyncio
import datetime
from sqlalchemy.orm import Session
from database import SessionLocal
import models
from llm_service import llm_service
from email_sender import send_email

class BulkService:
    def pause_all_active_campaigns(self, db: Session):
        """
        Pauses all campaigns that are currently 'active'.
        Used on startup to ensure no unexpected sending after a restart.
        """
        active_campaigns = db.query(models.Campaign).filter(models.Campaign.status == "active").all()
        for campaign in active_campaigns:
            campaign.status = "paused"
        db.commit()
        if active_campaigns:
            print(f"INFO: Automatically paused {len(active_campaigns)} active campaigns on startup.")

    def fetch_sheet_data(self, sheet_url: str, header_row_index: int = 1):
        """
        Fetches Google Sheet data as CSV.
        Assumes the URL is a standard Google Sheet URL.
        Converts it to an export URL.
        """
        # Robustly extract Sheet ID to handle /edit, /htmlview, etc.
        import re
        match = re.search(r"/d/([a-zA-Z0-9-_]+)", sheet_url)
        if match:
            sheet_id = match.group(1)
            csv_url = f"https://docs.google.com/spreadsheets/d/{sheet_id}/export?format=csv"
        else:
            # Fallback for non-standard URLs (though unlikely to work if not public CSV)
            csv_url = sheet_url
            
        # Handle specific User/GID params if necessary? 
        # Usually just the ID is enough for the first sheet. 
        # If user wants a specific tab, they might need gid.
        if "gid=" in sheet_url:
            gid_match = re.search(r"gid=([0-9]+)", sheet_url)
            if gid_match:
                csv_url += f"&gid={gid_match.group(1)}"

        # Fetching CSV data
        try:
            response = requests.get(csv_url, headers={'User-Agent': 'Mozilla/5.0'})
            response.raise_for_status()
            
            # Parse CSV
            content = response.content.decode('utf-8')
            # Content loaded successfully
            
            reader = csv.reader(io.StringIO(content))
            rows = list(reader)
            
            if len(rows) < header_row_index:
                raise ValueError("Header row index is out of bounds")
            
            # 0-indexed adjustment
            header = rows[header_row_index - 1]
            data_rows = rows[header_row_index:]
            
            # Header row identified
            
            return header, data_rows
        except Exception as e:
            print(f"ERROR: Failed to fetch sheet: {e}")
            return None, None

    async def create_campaign(self, db: Session, name: str, sheet_url: str, header_row: int, context1: str, context2: str, daily_limit: int = None):
        header, data_rows = self.fetch_sheet_data(sheet_url, header_row)
        
        if not header:
            raise ValueError("Could not fetch valid data from the sheet. Check logs for details.")
            
        # Create Campaign
        campaign = models.Campaign(
            name=name,
            sheet_url=sheet_url,
            header_row=header_row,
            status="active",
            total_count=len(data_rows),
            sent_count=0,
            prompt_context_1=context1,
            prompt_context_2=context2,
            daily_limit=daily_limit
        )
        db.add(campaign)
        db.commit()
        db.refresh(campaign)
        
        # Create Items
        # Try to identify email column smartly
        email_idx = -1
        name_idx = -1
        company_idx = -1
        
        for i, col in enumerate(header):
            col_lower = col.lower()
            if "email" in col_lower: email_idx = i
            if "name" in col_lower and "company" not in col_lower: name_idx = i
            if "company" in col_lower or "organization" in col_lower: company_idx = i
        
        print(f"DEBUG: Column Mapping - Email: {email_idx}, Name: {name_idx}, Company: {company_idx}")
        
        items = []
        for row in data_rows:
            # Skip empty rows or rows without enough columns
            if not row or (email_idx >= 0 and len(row) <= email_idx):
                continue
                
            email = row[email_idx] if email_idx >= 0 else ""
            name = row[name_idx] if name_idx >= 0 else ""
            company = row[company_idx] if company_idx >= 0 else ""
            
            # Determine mapping for LLM: create a dict of Header: Value
            row_dict = {}
            for i, val in enumerate(row):
                if i < len(header):
                    row_dict[header[i]] = val
            
            # Simple validation: need at least an email
            if "@" in email:
                item = models.CampaignItem(
                    campaign_id=campaign.id,
                    row_data=json.dumps(row_dict),
                    recipient_email=email.strip(),
                    recipient_name=name.strip(),
                    company=company.strip(),
                    status="pending"
                )
                items.append(item)
        
        print(f"DEBUG: Parsed {len(items)} items.")
        
        db.add_all(items)
        db.commit()
        
        # Update total count to actual valid items
        campaign.total_count = len(items)
        db.commit()
        
        if len(items) == 0:
            # Cleanup and Error
            db.delete(campaign)
            db.commit()
            raise ValueError(f"No valid recipients. Found headers: {header}. Detected Email Col: {email_idx}")
            
        return campaign.id

    async def retry_campaign(self, db: Session, campaign_id: int, new_header_row: int = None):
        """
        Retries fetching items. Allows changing the header row index if the user provided one.
        """
        campaign = db.query(models.Campaign).get(campaign_id)
        if not campaign:
            raise ValueError("Campaign not found")

        # Update header row if provided
        if new_header_row:
            campaign.header_row = new_header_row
            db.commit()
            
        print(f"DEBUG: Retrying campaign {campaign_id} with url {campaign.sheet_url} using Header Row {campaign.header_row}")
        
        # Fetch Data Again
        header, data_rows = self.fetch_sheet_data(campaign.sheet_url, campaign.header_row)
        if not header:
             raise ValueError("Could not fetch valid data from the sheet. Check logs.")
             
        # Cleanup existing items (if any, though likely 0 if we are retrying)
        db.query(models.CampaignItem).filter(models.CampaignItem.campaign_id == campaign_id).delete()
        db.commit()
        
        # Re-populate Items
        email_idx = -1
        name_idx = -1
        company_idx = -1
        
        for i, col in enumerate(header):
            col_lower = col.lower()
            if "email" in col_lower: email_idx = i
            if "name" in col_lower and "company" not in col_lower: name_idx = i
            if "company" in col_lower or "organization" in col_lower: company_idx = i
            
        print(f"DEBUG: Retry Mapping - Email: {email_idx}, Name: {name_idx}, Company: {company_idx}")
            
        items = []
        for row in data_rows:
            if not row or (email_idx >= 0 and len(row) <= email_idx): continue
            
            email = row[email_idx] if email_idx >= 0 else ""
            name = row[name_idx] if name_idx >= 0 else ""
            company = row[company_idx] if company_idx >= 0 else ""
            
            row_dict = {}
            for i, val in enumerate(row):
                if i < len(header): row_dict[header[i]] = val
            
            if "@" in email:
                item = models.CampaignItem(
                    campaign_id=campaign.id,
                    row_data=json.dumps(row_dict),
                    recipient_email=email.strip(),
                    recipient_name=name.strip(),
                    company=company.strip(),
                    status="pending"
                )
                items.append(item)
        
        print(f"DEBUG: Retry parsed {len(items)} items.")
        
        if len(items) == 0:
            raise ValueError("Still no valid recipients found. Please check sheet format.")
            
        db.add_all(items)
        db.commit() # Commit items first
        
        # Reset Campaign Status
        # Important: Refresh campaign object to ensure we are editing the attached session object
        campaign = db.query(models.Campaign).get(campaign_id)
        campaign.total_count = len(items)
        campaign.sent_count = 0
        campaign.status = "active"
        
        db.commit()
        return True

    async def retry_failed_items(self, db: Session, campaign_id: int):
        """
        Resets all items with status 'error' back to 'pending' and sets campaign to 'active'.
        """
        campaign = db.query(models.Campaign).get(campaign_id)
        if not campaign:
            raise ValueError("Campaign not found")

        # Reset failed items to pending
        failed_items = db.query(models.CampaignItem).filter(
            models.CampaignItem.campaign_id == campaign_id,
            models.CampaignItem.status == "error"
        ).all()
        
        for item in failed_items:
            item.status = "pending"
            item.error_msg = None
            
        campaign.status = "active"
        db.commit()
        return len(failed_items)

    async def run_campaign_loop(self, campaign_id: int):
        # Campaign loop started
        
        # Lock in the sender index so switching email in UI doesn't affect active campaign
        from email_config import get_active_index
        campaign_sender_index = get_active_index()
        
        # New database session for the background task
        db = SessionLocal()
        try:
            while True:
                # Check status
                campaign = db.query(models.Campaign).get(campaign_id)
                if not campaign:
                    print("Campaign not found, stopping.")
                    break
                
                if campaign.status == "paused":
                    # Campaign paused, waiting
                    await asyncio.sleep(5)
                    continue
                
                if campaign.status in ["completed", "error"]:
                    print(f"Campaign {campaign_id} ended with status {campaign.status}")
                    break
                
                # Check daily limit
                if campaign.daily_limit:
                    # Count emails sent today (UTC)
                    today_start = datetime.datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
                    sent_today = db.query(models.CampaignItem).filter(
                        models.CampaignItem.campaign_id == campaign_id,
                        models.CampaignItem.status == "sent",
                        models.CampaignItem.sent_at >= today_start
                    ).count()
                    
                    if sent_today >= campaign.daily_limit:
                        print(f"Daily limit ({campaign.daily_limit}) reached for campaign {campaign_id}. Sent today: {sent_today}. Waiting until tomorrow...")
                        await asyncio.sleep(300)  # Sleep for 5 minutes and check again
                        continue
                
                # Fetch next pending item
                item = db.query(models.CampaignItem).filter(
                    models.CampaignItem.campaign_id == campaign_id,
                    models.CampaignItem.status == "pending"
                ).first()
                
                if not item:
                    # All items processed, marking campaign complete
                    campaign.status = "completed"
                    db.commit()
                    break
                
                # Process Item
                try:
                    # Processing email silently
                    
                    # 1. Draft Email with LLM
                    # Get user profile
                    user = db.query(models.User).first()
                    groq_key = user.groq_api_key if user else None
                    
                    user_profile = {
                        "full_name": user.full_name if user else "Candidate",
                        "email": user.email if user else "",
                        "phone": user.phone if user else "",
                        "resume_path": user.resume_path if user else None
                    }

                    # Construct context from row data + user prompts
                    row_data = json.loads(item.row_data)
                    
                    # Map Campaign Context to Job Details
                    # prompt_context_1 -> Target Role
                    # prompt_context_2 -> Additional Instructions
                    
                    target_role = campaign.prompt_context_1 or "Open Position"
                    additional_instructions = campaign.prompt_context_2 or ""
                    
                    # Build additional context from row data (without mentioning "sheet")
                    recipient_context = f"Writing to {item.recipient_name or 'Hiring Manager'}"
                    if item.company:
                        recipient_context += f" at {item.company}"
                    
                    job_details = {
                        "company": item.company or "the organization",
                        "role": target_role,
                        "text": f"{recipient_context}. Position: {target_role}. {json.dumps(row_data, indent=2)}",
                        "contact_email": item.recipient_email
                    }
                    
                    # Call LLM using the standard drafting method
                    llm_response = llm_service.generate_email_draft(
                        user_profile, 
                        job_details, 
                        custom_system_prompt=user.system_prompt if user else None,
                        api_key=groq_key,
                        instructions=additional_instructions
                    )
                    
                    # Validation: Ensure we have content before sending
                    if not llm_response or "error" in llm_response:
                        error_detail = llm_response.get("detail") if llm_response else "Unknown error"
                        item.status = "error"
                        item.error_msg = f"AI Generation Failed: {error_detail}"
                        db.commit()
                        continue

                    subject = llm_response.get("subject", "").strip()
                    body = llm_response.get("body", "").strip()

                    if not subject or not body:
                        item.status = "error"
                        item.error_msg = "AI generated empty subject or body"
                        db.commit()
                        continue

                    # Send Email
                    # Allow a small pause to avoid spam flags
                    await asyncio.sleep(2) 
                    
                    success = send_email(
                        item.recipient_email, 
                        subject, 
                        body, 
                        attachment_path=user_profile['resume_path'],
                        sender_index=campaign_sender_index
                    )
                    
                    if success:
                        item.status = "sent"
                        item.sent_at = datetime.datetime.utcnow()
                        campaign.sent_count += 1
                        
                        # Add to SentEmail log too for visibility in Reply Center
                        sent_log = models.SentEmail(
                            recipient_email=item.recipient_email,
                            subject=subject,
                            body=body,
                            status="sent"
                        )
                        db.add(sent_log)
                        
                    else:
                        item.status = "error"
                        item.error_msg = "SMTP send failed"
                        
                    db.commit()
                    
                except Exception as e:
                    print(f"Error processing item {item.id}: {e}")
                    item.status = "error"
                    item.error_msg = str(e)
                    db.commit()
                
                # Sleep between emails (Increased to 30s to avoid rate limits)
                await asyncio.sleep(30) 
                
        finally:
            db.close()

bulk_service = BulkService()
