import datetime
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
HOTEL_NAME = "Staayz Premium Hotel"
PRICE_THRESHOLD = 1500.0

# Base clean URLs (without existing trailing '?')
CLEARTRIP_BASE = "https://www.cleartrip.com/hotels/details/hotel-staayz-premium-cyber-city-1352800"
GOIBIBO_BASE = "https://www.goibibo.com/hotels/staayz-premium-studio-apartments-hotel-in-gurgaon-5842278316889170225/"

SENDER_EMAIL = os.getenv("SENDER_EMAIL")
APP_PASSWORD = os.getenv("APP_PASSWORD")
RECEIVER_EMAIL = os.getenv("RECEIVER_EMAIL")


def get_next_week_workdays():
    """Calculates Monday through Friday dates starting next week (T+7)."""
    today = datetime.date.today()
    start_date = today + datetime.timedelta(days=7)

    while start_date.weekday() > 4:
        start_date += datetime.timedelta(days=1)

    workdays = []
    curr = start_date
    while len(workdays) < 5:
        if curr.weekday() < 5:
            check_in = curr.strftime("%Y-%m-%d")
            check_out = (curr + datetime.timedelta(days=1)).strftime("%Y-%m-%d")
            workdays.append((check_in, check_out))
        curr += datetime.timedelta(days=1)
    return workdays


def extract_price_from_content(html_content):
    matches = re.findall(r"(?:₹|Rs\.?|INR)\s?([0-9,]+)", html_content)
    valid_prices = []
    for m in matches:
        clean = m.replace(",", "")
        if clean.isdigit():
            val = float(clean)
            if 300 <= val <= 25000:
                valid_prices.append(val)
    return min(valid_prices) if valid_prices else None


def fetch_cleartrip_price(page, check_in, check_out):
    url = f"{CLEARTRIP_BASE}?chk_in={check_in}&chk_out={check_out}&adults=1&num_rooms=1"
    try:
        page.goto(url, wait_until="load", timeout=45000)
        page.wait_for_timeout(4000)
        return extract_price_from_content(page.content())
    except Exception as e:
        print(f"Cleartrip error ({check_in}): {e}")
        return None


def fetch_goibibo_price(page, check_in, check_out):
    cin_compact = check_in.replace("-", "")
    cout_compact = check_out.replace("-", "")
    # Properly formatted Goibibo search query
    url = f"{GOIBIBO_BASE}/?checkin={cin_compact}&checkout={cout_compact}&roomString=1-2-&searchText=Staayz%20Premium%20Hotel%20&locusId=CTGGN&locusType=city&cityCode=CTGGN&cc=IN&uCurrency=INR"
    try:
        page.goto(url, wait_until="load", timeout=45000)
        page.wait_for_timeout(4000)
        return extract_price_from_content(page.content())
    except Exception as e:
        print(f"Goibibo error ({check_in}): {e}")
        return None


def send_email_alert(alerts):
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚨 {HOTEL_NAME} Price Alert: Rates Below ₹{int(PRICE_THRESHOLD)}!"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL

    body_lines = [f"<h3>Price Alert for {HOTEL_NAME}</h3><ul>"]
    for alert in alerts:
        body_lines.append(
            f"<li><b>Dates:</b> {alert['check_in']} to {alert['check_out']}<br>"
            f"<b>Rate:</b> ₹{int(alert['best_price'])} on <i>{alert['platform']}</i></li><br>"
        )
    body_lines.append("</ul><p>Visit the site to book before rates change.</p>")

    msg.attach(MIMEText("".join(body_lines), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())


def main():
    workdays = get_next_week_workdays()
    price_drops = []

    with sync_playwright() as p:
        # Launch Firefox which bypasses standard Chromium HTTP/2 protocol blocks
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0"
        )
        page = context.new_page()

        for check_in, check_out in workdays:
            platform_prices = {}

            # Cleartrip
            ct_price = fetch_cleartrip_price(page, check_in, check_out)
            if ct_price:
                platform_prices["Cleartrip"] = ct_price

            # Goibibo
            gb_price = fetch_goibibo_price(page, check_in, check_out)
            if gb_price:
                platform_prices["Goibibo"] = gb_price

            print(f"[{check_in} -> {check_out}] Scraped rates: {platform_prices}")

            if platform_prices:
                best_platform = min(platform_prices, key=platform_prices.get)
                best_price = platform_prices[best_platform]
                if best_price <= PRICE_THRESHOLD:
                    price_drops.append({
                        "check_in": check_in,
                        "check_out": check_out,
                        "platform": best_platform,
                        "best_price": best_price,
                    })

        browser.close()

    if price_drops:
        print(f"Triggering alert for {len(price_drops)} dates...")
        send_email_alert(price_drops)
    else:
        print("No rates met the price threshold.")


if __name__ == "__main__":
    main()
