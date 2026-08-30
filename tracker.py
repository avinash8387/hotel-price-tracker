import datetime
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
PRICE_THRESHOLD = 1000.0  # Alert when price <= ₹1000
HOTEL_BASE_URL = "https://www.cleartrip.com/hotels"  # Replace with direct hotel page URL if available
HOTEL_NAME = "Staayz Premium Hotel & Studio Apartments"  # Replace with your exact target hotel name

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")


def get_next_week_workdays():
    """Calculates Monday through Friday dates starting next week (T+7)."""
    today = datetime.date.today()
    start_date = today + datetime.timedelta(days=7)

    # Shift to Monday if T+7 lands on Saturday or Sunday
    while start_date.weekday() > 4:  # 0=Mon, 4=Fri, 5=Sat, 6=Sun
        start_date += datetime.timedelta(days=1)

    workdays = []
    curr = start_date
    while len(workdays) < 5:
        if curr.weekday() < 5:  # Mon to Fri only
            check_in = curr.strftime("%Y-%m-%d")
            check_out = (curr + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            workdays.append((check_in, check_out))
        curr += datetime.timedelta(days=1)
    return workdays


def fetch_hotel_price(page, check_in, check_out):
    """Navigates Flipkart Hotels and extracts room rate."""
    # Example format for Flipkart Hotel search URL (or direct hotel link with query params)
    url = f"{HOTEL_BASE_URL}?checkin={check_in}&checkout={check_out}&rooms=1&adults=1"
    page.goto(url, wait_until="networkidle", timeout=60000)

    # Wait for price containers to render
    page.wait_for_timeout(3000)

    # Scrape visible price text containing rupee sign or price container
    content = page.content()

    # Regex to capture price patterns like ₹ 899, ₹899, or INR 899
    matches = re.findall(r"(?:₹|Rs\.?|INR)\s?([0-9,]+)", content)
    valid_prices = []
    for m in matches:
        clean_num = m.replace(",", "")
        if clean_num.isdigit():
            val = float(clean_num)
            if 300 <= val <= 20000:  # Ignore unrelated small numbers/outliers
                valid_prices.append(val)

    return min(valid_prices) if valid_prices else None


def send_email_alert(alerts):
    """Sends notification email via Gmail SMTP."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚨 Price Alert: Hotel Dropped Below ₹{int(PRICE_THRESHOLD)}!"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL

    body_lines = ["<h3>Flipkart Travel Hotel Price Alert</h3><ul>"]
    for alert in alerts:
        body_lines.append(
            f"<li><b>Dates:</b> {alert['check_in']} to {alert['check_out']} — "
            f"<b>Price:</b> ₹{int(alert['price'])} per day</li>"
        )
    body_lines.append("</ul><p>Book now on Flipkart Travel before prices fluctuate!</p>")

    msg.attach(MIMEText("".join(body_lines), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())


def main():
    workdays = get_next_week_workdays()
    price_drops = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()

        for check_in, check_out in workdays:
            try:
                price = fetch_hotel_price(page, check_in, check_out)
                print(f"[{check_in} -> {check_out}] Detected Price: ₹{price}")

                if price is not None and price <= PRICE_THRESHOLD:
                    price_drops.append(
                        {
                            "check_in": check_in,
                            "check_out": check_out,
                            "price": price,
                        }
                    )
            except Exception as e:
                print(f"Error fetching {check_in}: {e}")

        browser.close()

    if price_drops:
        print(f"Triggering email alert for {len(price_drops)} dates...")
        send_email_alert(price_drops)
    else:
        print("No dates met the price threshold.")


if __name__ == "__main__":
    main()
