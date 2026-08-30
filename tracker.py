import datetime  # For date math (T+7, weekday checks)
import os        # To read environment variables / GitHub Secrets
import re        # Regular expressions to parse rupee prices from raw HTML
import smtplib   # Standard library to send emails via SMTP
from email.mime.multipart import MIMEMultipart  # Containers for email formatting
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright  # Headless browser automation

PRICE_THRESHOLD = 1000.0  # Alert limit (₹1000)
HOTEL_BASE_URL = "https://www.cleartrip.com/hotels"  # Base endpoint/URL
HOTEL_NAME = "Staayz Premium Hotel & Studio Apartments"  # Reference hotel label

# Fetch secrets injected securely by GitHub Actions runner
SENDER_EMAIL = os.getenv("SENDER_EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")
