import os
import re
import time
import json
import logging
from pathlib import Path

from selenium import webdriver
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
import requests

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)

URL = "https://vibefestival.ro/hu/jegyek"
TARGET_PRICE = float(os.getenv("TARGET_PRICE", "260"))
REFERENCE_PRICE = 499.0
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
STATE_FILE = Path("/tmp/vibe_state.json")


def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def get_driver():
    options = Options()
    options.add_argument("--headless")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-gpu")
    options.add_argument("--window-size=1920,1080")
    options.add_argument("--user-agent=Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36")
    return webdriver.Chrome(options=options)


def fetch_price():
    driver = get_driver()
    try:
        driver.get(URL)
        WebDriverWait(driver, 15).until(
            EC.presence_of_element_located((By.TAG_NAME, "body"))
        )
        time.sleep(3)  # JS betöltésre várunk
        text = driver.find_element(By.TAG_NAME, "body").text
        text = re.sub(r"\s+", " ", text)

        prices = []
        for m in re.finditer(r"(\d+[\.,]?\d*)\s*(?:lei|lej)", text, flags=re.IGNORECASE):
            val = float(m.group(1).replace(",", "."))
            if 10 < val < 2000:
                prices.append((val, m.start()))

        lowered = text.lower()
        anchors = [m.start() for m in re.finditer(r"vibe\s*pass", lowered)]

        if anchors:
            candidates = []
            for a in anchors:
                nearby = [(abs(pos - a), val) for val, pos in prices if abs(pos - a) <= 600]
                candidates.extend(nearby)
            if candidates:
                candidates.sort(key=lambda x: (x[0], abs(x[1] - REFERENCE_PRICE)))
                return candidates[0][1]

        if prices:
            prices.sort(key=lambda x: abs(x[0] - REFERENCE_PRICE))
            return prices[0][0]

        return None
    finally:
        driver.quit()


def send_telegram(message):
    if not BOT_TOKEN or not CHAT_ID:
        log.warning("Telegram nincs beállítva!")
        return
    api = f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    requests.post(api, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=30)


def check():
    state = load_state()
    price = fetch_price()
    if price is None:
        log.warning("Nem sikerült árat felismerni.")
        return
    log.info(f"Vibe Pass ár: {price:.2f} lei | Küszöb: {TARGET_PRICE:.2f} lei")
    state["last_seen"] = price
    save_state(state)
    if price <= TARGET_PRICE:
        if state.get("last_notified") != price:
            msg = (f"🎉 <b>VIBE Pass ár riasztás!</b>\n\n"
                   f"Az ár <b>{price:.2f} lei</b>-re csökkent!\n"
                   f"Küszöb: {TARGET_PRICE:.2f} lei\n\n"
                   f"👉 Vedd meg most: {URL}")
            send_telegram(msg)
            log.info("Értesítés elküldve!")
            state["last_notified"] = price
            save_state(state)
    else:
        log.info("Még nem érte el a küszöböt.")


def main():
    log.info("VIBE Pass árfigyelő v2 (Selenium) elindult.")
    log.info(f"Küszöb: {TARGET_PRICE:.2f} lei | Ellenőrzés: {CHECK_INTERVAL}s")
    if not BOT_TOKEN or not CHAT_ID:
        log.error("HIBA: Hiányzó TELEGRAM_BOT_TOKEN vagy TELEGRAM_CHAT_ID!")
        return
    send_telegram(
        f"✅ <b>VIBE árfigyelő v2 elindult!</b>\n\n"
        f"Figyelt oldal: {URL}\n"
        f"Értesítési küszöb: {TARGET_PRICE:.2f} lei\n"
        f"Ellenőrzési időköz: {CHECK_INTERVAL} másodperc\n"
        f"Motor: Selenium Chrome (JS támogatással) ✅"
    )
    while True:
        try:
            check()
        except Exception as e:
            log.error(f"Hiba: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
