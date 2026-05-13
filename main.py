import os
import re
import time
import json
import logging
from pathlib import Path
import requests
from bs4 import BeautifulSoup

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s", datefmt="%Y-%m-%d %H:%M:%S")
log = logging.getLogger(__name__)

URL = "https://vibefestival.ro/hu/jegyek"
TARGET_PRICE = 249.50
REFERENCE_PRICE = 499.0
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "1800"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
STATE_FILE = Path("/tmp/vibe_state.json")
UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: return {}
    return {}

def save_state(state):
    STATE_FILE.write_text(json.dumps(state))

def fetch_price():
    r = requests.get(URL, headers={"User-Agent": UA}, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True))
    prices = []
    for m in re.finditer(r"(\d+[\.,]?\d*)\s*(?:lei|lej)", text, flags=re.IGNORECASE):
        val = float(m.group(1).replace(",", "."))
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
            msg = (f"🎉 <b>VIBE Pass ár riasztás!</b>\n\nAz ár <b>{price:.2f} lei</b>-re csökkent!\n"
                   f"Ez már 50% kedvezmény (eredeti ár: {REFERENCE_PRICE:.0f} lei).\n\n👉 Vedd meg most: {URL}")
            send_telegram(msg)
            log.info("Értesítés elküldve!")
            state["last_notified"] = price
            save_state(state)
    else:
        log.info(f"Még nem érte el a küszöböt.")

def main():
    log.info("VIBE Pass árfigyelő elindult.")
    if not BOT_TOKEN or not CHAT_ID:
        log.error("HIBA: Hiányzó TELEGRAM_BOT_TOKEN vagy TELEGRAM_CHAT_ID!")
        return
    send_telegram(f"✅ <b>VIBE árfigyelő elindult!</b>\n\nFigyelt oldal: {URL}\nKüszöb: {TARGET_PRICE:.2f} lei\nEllenőrzés: {CHECK_INTERVAL//60} percenként")
    while True:
        try:
            check()
        except Exception as e:
            log.error(f"Hiba: {e}")
        time.sleep(CHECK_INTERVAL)

if __name__ == "__main__":
    main()
