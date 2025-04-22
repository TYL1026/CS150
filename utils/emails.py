#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Email notification module for CS Advising Bot.
Handles sending email notifications to human advisors.
"""

import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from dotenv import load_dotenv
import os

# Load environment variables from .env file
load_dotenv()
SMTP_SERVER = os.environ.get("SMTP_SERVER", "smtp.gmail.com")  # Default to Gmail
SMTP_PORT = int(os.environ.get("SMTP_PORT", "587"))  # Default to TLS port
EMAIL_USER = os.environ.get("EMAIL_USER")
EMAIL_PASSWORD = os.environ.get("EMAIL_PASSWORD")
ADVISOR_EMAIL = os.environ.get("ADVISOR_EMAIL")

# Set up logging
logger = logging.getLogger(__name__)


def send_notification_email(student_username, student_question, llm_answer, is_initial_escalation):
    if not all([EMAIL_USER, EMAIL_PASSWORD, ADVISOR_EMAIL]):
        logger.warning("Email credentials not configured. Skipping email notification.")
        return
    
    try:
        msg = MIMEMultipart()
        msg['From'] = EMAIL_USER
        msg['To'] = ADVISOR_EMAIL
        
        if is_initial_escalation:
            msg['Subject'] = f"🚨 ALERT: New CS Advising Escalation from {student_username}"
            body = f"""
            <html>
            <body>
                <h2>New Escalation Alert</h2>
                <p>Student <b>{student_username}</b> has requested help that requires your attention.</p>
                <h3>Student question:</h3>
                <p>{student_question}</p>
                <h3>AI-Generated Response:</h3>
                <p>{llm_answer}</p>
                <p>Please log in to RocketChat to respond to this message.</p>
                <hr>
                <p><i>This is an automated message from the Tufts CS Advising Bot.</i></p>
            </body>
            </html>
            """
        # else:
        #     msg['Subject'] = f"💬 New Thread Message from {student_username}"
        #     body = f"""
        #     <html>
        #     <body>
        #         <h2>New Message in Existing Thread</h2>
        #         <p>Student <b>{student_username}</b> has sent a new message in an active thread.</p>
        #         <h3>Message Content:</h3>
        #         <p>{message_text}</p>
        #         <p>Please log in to RocketChat to continue the conversation.</p>
        #         <hr>
        #         <p><i>This is an automated message from the Tufts CS Advising Bot.</i></p>
        #     </body>
        #     </html>
        #     """
        
        msg.attach(MIMEText(body, 'html'))
        
        # Connect to server and send
        server = smtplib.SMTP(SMTP_SERVER, SMTP_PORT)
        server.starttls()
        server.login(EMAIL_USER, EMAIL_PASSWORD)
        server.send_message(msg)
        server.quit()
        
        logger.info(f"Email notification sent to advisor for message from {student_username}")
        
    except Exception as e:
        logger.error(f"Failed to send email notification: {str(e)}")
