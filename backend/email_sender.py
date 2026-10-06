import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
import os
from dotenv import load_dotenv
from email_config import get_email_credentials

load_dotenv()

from email.mime.application import MIMEApplication

def send_email(to_email, subject, content, attachment_path=None, cc=None, bcc=None, sender_index=None):
    """
    Send an email with optional CC and BCC recipients.
    
    Args:
        to_email: Primary recipient email (string)
        subject: Email subject
        content: Email body content
        attachment_path: Optional file path to attach
        cc: Optional CC recipients (string or list of strings)
        bcc: Optional BCC recipients (string or list of strings)
        sender_index: Optional index (1 or 2) to override the active email
    """
    if sender_index:
        if sender_index == 1:
            GMAIL_USER, GMAIL_PASS = os.getenv("EMAIL"), os.getenv("PASSWORD")
        else:
            GMAIL_USER, GMAIL_PASS = os.getenv("EMAIL2"), os.getenv("PASSWORD2")
    else:
        GMAIL_USER, GMAIL_PASS = get_email_credentials()
        
    if not GMAIL_USER or not GMAIL_PASS:
        raise Exception("Email credentials not configured in .env")
    
    msg = MIMEMultipart()
    msg['From'] = GMAIL_USER
    msg['To'] = to_email
    msg['Subject'] = subject
    
    # Add CC header if provided
    if cc:
        if isinstance(cc, str):
            cc = [cc]
        msg['Cc'] = ', '.join(cc)
    
    # Note: BCC is not added to headers (that's the point of BCC!)
    
    msg.attach(MIMEText(content, 'plain'))

    if attachment_path and os.path.exists(attachment_path):
        try:
            with open(attachment_path, "rb") as f:
                part = MIMEApplication(f.read(), Name=os.path.basename(attachment_path))
            part['Content-Disposition'] = f'attachment; filename="{os.path.basename(attachment_path)}"'
            msg.attach(part)
        except Exception as e:
            print(f"Failed to attach file: {e}")

    try:
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(GMAIL_USER, GMAIL_PASS)
        text = msg.as_string()
        
        # Build complete recipient list for actual sending
        all_recipients = [to_email]
        if cc:
            if isinstance(cc, str):
                all_recipients.append(cc)
            else:
                all_recipients.extend(cc)
        if bcc:
            if isinstance(bcc, str):
                all_recipients.append(bcc)
            else:
                all_recipients.extend(bcc)
        
        server.sendmail(GMAIL_USER, all_recipients, text)
        server.quit()
        return True
    except Exception as e:
        print(f"Failed to send email: {e}")
        return False
