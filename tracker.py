import datetime
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
HOTEL_NAME = "SStaayz Premium Hotel & Studio Apartments"  # Explicit Hotel Name for alerts
PRICE_THRESHOLD = 1500.0             # Alert when price <= ₹1000

# Direct URLs / Property links for your hotel on each platform
CLEARTRIP_HOTEL_URL = "https://www.cleartrip.com/hotels/details/staayz-premium-hotel-&-studio-apartments-1352800?c=020926%7C040926&r=2%2C0"
GOIBIBO_HOTEL_URL = "https://www.goibibo.com/hotels/hotel-details/?checkin=20260831&checkout=20260902&roomString=1-2-0&searchText=Staayz%20Premium%20Hotel%20&%20Studio%20Apartments&locusId=CTGGN&locusType=city&cityCode=CTGGN&cc=IN&_uCurrency=INR&vcid=CTGGN&giHotelId=5842278316889170225&mmtId=201603191309599815&sType=city#rooms"

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


def extract_price_from_content(html_content):
    """Regex helper to extract the lowest realistic rupee amount from page HTML."""
    matches = re.findall(r"(?:₹|Rs\.?|INR)\s?([0-9,]+)", html_content)
    valid_prices = []
    for m in matches:
        clean_num = m.replace(",", "")
        if clean_num.isdigit():
            val = float(clean_num)
            if 300 <= val <= 20000:  # Ignore unrelated counts or outliers
                valid_prices.append(val)
    return min(valid_prices) if valid_prices else None


def fetch_cleartrip_price(page, check_in, check_out):
    """Navigates Cleartrip and extracts room rate."""
    url = f"{CLEARTRIP_HOTEL_URL}?chk_in={check_in}&chk_out={check_out}&adults=1&num_rooms=1"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        return extract_price_from_content(page.content())
    except Exception as e:
        print(f"Cleartrip fetch error ({check_in}): {e}")
        return None


def fetch_goibibo_price(page, check_in, check_out):
    """Navigates Goibibo and extracts room rate."""
    cin_compact = check_in.replace("-", "")
    cout_compact = check_out.replace("-", "")
    url = f"{GOIBIBO_HOTEL_URL}?ci={cin_compact}&co={cout_compact}&r=1-1-0"
    try:
        page.goto(url, wait_until="domcontentloaded", timeout=60000)
        page.wait_for_timeout(3000)
        return extract_price_from_content(page.content())
    except Exception as e:
        print(f"Goibibo fetch error ({check_in}): {e}")
        return None


def send_email_alert(alerts):
    """Sends notification email via Gmail SMTP with hotel and platform details."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"🚨 {HOTEL_NAME} Price Drop: Deals Below ₹{int(PRICE_THRESHOLD)}!"
    msg["From"] = SENDER_EMAIL
    msg["To"] = RECEIVER_EMAIL

    body_lines = [f"<h3>Price Alert for {HOTEL_NAME}</h3><ul>"]
    for alert in alerts:
        body_lines.append(
            f"<li><b>Dates:</b> {alert['check_in']} to {alert['check_out']}<br>"
            f"<b>Lowest Rate:</b> ₹{int(alert['best_price'])} per day on <i>{alert['platform']}</i></li><br>"
        )
    body_lines.append(f"</ul><p>Check the platform app/website to book before prices change!</p>")

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
            platform_prices = {}

            # 1. Fetch Cleartrip
            ct_price = fetch_cleartrip_price(page, check_in, check_out)
            if ct_price is not None:
                platform_prices["Cleartrip"] = ct_price

            # 2. Fetch Goibibo
            gb_price = fetch_goibibo_price(page, check_in, check_out)
            if gb_price is not None:
                platform_prices["Goibibo"] = gb_price

            print(f"[{check_in} -> {check_out}] Scraped rates: {platform_prices}")

            # 3. Find lowest price across platforms and check threshold
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
        print(f"Triggering email alert for {len(price_drops)} dates...")
        send_email_alert(price_drops)
    else:
        print("No dates met the price threshold across either platform.")


if __name__ == "__main__":
    main()
