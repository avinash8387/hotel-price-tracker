import datetime
import os
import re
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from playwright.sync_api import sync_playwright

# --- CONFIGURATION ---
HOTEL_NAME = "Staayz Premium Hotel"
PRICE_THRESHOLD = 1500.0  # Alert when price <= ₹1500

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


def clean_price_string(price_str):
    """Extracts exact integer value from a price text block (e.g. '₹ 1,093' -> 1093.0)."""
    if not price_str:
        return None
    cleaned = re.sub(r"[^\d]", "", price_str)
    return float(cleaned) if cleaned.isdigit() else None


def fetch_goibibo_price(page, check_in, check_out):
    """Targets Goibibo's exact primary room rate element."""
    cin_compact = check_in.replace("-", "")
    cout_compact = check_out.replace("-", "")
    url = (
        f"{GOIBIBO_BASE}/?checkin={cin_compact}&checkout={cout_compact}"
        f"&roomString=1-2-&searchText=Staayz%20Premium%20Hotel%20"
        f"&locusId=CTGGN&locusType=city&cityCode=CTGGN&cc=IN&uCurrency=INR"
    )

    try:
        page.goto(url, wait_until="load", timeout=60000)

        # Primary Goibibo price selectors: Room rate badge next to 'Per Night'
        selectors = [
            "span[class*='PriceWrapper']",
            "div[class*='dwebCommonstyles__FlexDiv'] h4",
            "p[class*='PriceCard']",
            "div[data-testid='hotel-price-block']",
            "span:has-text('₹'):not(:has-text('off')):not(:has-text('Get'))",
        ]

        # Locate the price element that specifically sits above 'Per Night'
        for sel in selectors:
            elements = page.query_selector_all(sel)
            for el in elements:
                text = el.inner_text().strip()
                if "₹" in text and not any(
                    x in text.lower() for x in ["off", "save", "cashback", "coupon"]
                ):
                    val = clean_price_string(text)
                    if val and 600 <= val <= 25000:
                        return val

        # Fallback: Locate elements containing the per-night price structure
        body = page.inner_text("body")
        matches = re.findall(r"₹\s*([0-9,]+)\s*(?:\n|\+)?.*?(?:Per Night|taxes)", body, re.IGNORECASE)
        if matches:
            return clean_price_string(matches[0])

    except Exception as e:
        print(f"Goibibo fetch error ({check_in}): {e}")
    return None


def fetch_cleartrip_price(page, check_in, check_out):
    """Targets Cleartrip's primary room rate container."""
    url = f"{CLEARTRIP_BASE}?chk_in={check_in}&chk_out={check_out}&adults=1&num_rooms=1"
    try:
        page.goto(url, wait_until="load", timeout=60000)
        page.wait_for_timeout(3000)

        # Search for primary bold room rate
        selectors = [
            "h2:has-text('₹')",
            "h3:has-text('₹')",
            "span[class*='price']",
            "div[class*='room-price']",
        ]

        for sel in selectors:
            elements = page.query_selector_all(sel)
            for el in elements:
                text = el.inner_text().strip()
                if "₹" in text and "off" not in text.lower():
                    val = clean_price_string(text)
                    if val and 600 <= val <= 25000:
                        return val

        body = page.inner_text("body")
        matches = re.findall(r"₹\s*([0-9,]+)\s*(?:/night|per night|\+)", body, re.IGNORECASE)
        if matches:
            return clean_price_string(matches[0])

    except Exception as e:
        print(f"Cleartrip fetch error ({check_in}): {e}")
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
            f"<b>Actual Rate:</b> ₹{int(alert['best_price'])} per night on <i>{alert['platform']}</i></li><br>"
        )
    body_lines.append("</ul><p>Visit the booking website to confirm the rate.</p>")

    msg.attach(MIMEText("".join(body_lines), "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(SENDER_EMAIL, APP_PASSWORD)
        server.sendmail(SENDER_EMAIL, RECEIVER_EMAIL, msg.as_string())


def main():
    workdays = get_next_week_workdays()
    price_drops = []

    with sync_playwright() as p:
        browser = p.firefox.launch(headless=True)
        context = browser.new_context(
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) Gecko/20100101 Firefox/124.0",
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()

        for check_in, check_out in workdays:
            platform_prices = {}

            gb_price = fetch_goibibo_price(page, check_in, check_out)
            if gb_price:
                platform_prices["Goibibo"] = gb_price

            ct_price = fetch_cleartrip_price(page, check_in, check_out)
            if ct_price:
                platform_prices["Cleartrip"] = ct_price

            print(f"[{check_in} -> {check_out}] Exact Rates Extracted: {platform_prices}")

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
        print(f"Sending email notification for {len(price_drops)} valid deals...")
        send_email_alert(price_drops)
    else:
        print(f"No rates found below threshold (₹{PRICE_THRESHOLD}).")


if __name__ == "__main__":
    main()
