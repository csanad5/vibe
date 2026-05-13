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
TARGET_PRICE = float(os.getenv("TARGET_PRICE", "260"))
REFERENCE_PRICE = 449.0
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL_SECONDS", "60"))
BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")
CHAT_ID = os.getenv("TELEGRAM_CHAT_ID")
STATE_FILE = Path("/tmp/vibe_state.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "hu-HU,hu;q=0.9,en;q=0.8",
}


def load_state():
    if STATE_FILE.exists():
        try: return json.loads(STATE_FILE.read_text())
        except: return {}
    return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state))


def fetch_price():
    r = requests.get(URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    soup = BeautifulSoup(r.text, "html.parser")
    text = soup.get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)

    # Keressük a VIBE PASS közelében lévő árat
    lowered = text.lower()
    anchors = [m.start() for m in re.finditer(r"vibe.{0,5}pass", lowered)]

    prices = []
    for m in re.finditer(r"(\d+)[\s]*(lei|lej|ron)", text, flags=re.IGNORECASE):
        val = float(m.group(1))
        if 50 < val < 2000:
            prices.append((val, m.start()))

    # Ha nincs "lei/lej/ron" egység, próbáljuk csak a számokkal
    if not prices:
        for m in re.finditer(r"\b(\d{3,4})\b", text):
            val = float(m.group(1))
            if 50 < val < 2000:
                prices.append((val, m.start()))

    if anchors and prices:
        candidates = []
        for a in anchors:
            nearby = [(abs(pos - a), val) for val, pos in prices if abs(pos - a) <= 800]
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
    try:
        requests.post(api, json={"chat_id": CHAT_ID, "text": message, "parse_mode": "HTML"}, timeout=30)
    except Exception as e:
        log.error(f"Telegram hiba: {e}")


def check():
    state = load_state()
    try:
        price = fetch_price()
    except Exception as e:
        log.error(f"Oldal lekérési hiba: {e}")
        return

    if price is None:
        log.warning("Nem sikerült árat felismerni az oldalon.")
        return

    log.info(f"Vibe Pass ár: {price:.0f} lei | Küszöb: {TARGET_PRICE:.0f} lei")
    state["last_seen"] = price
    save_state(state)

    if price <= TARGET_PRICE:
        if state.get("last_notified") != price:
            msg = (f"🎉 <b>VIBE Pass ár riasztás!</b>\n\n"
                   f"Az ár <b>{price:.0f} lei</b>-re csökkent!\n"
                   f"Küszöb: {TARGET_PRICE:.0f} lei\n\n"
                   f"👉 Vedd meg most: {URL}")
            send_telegram(msg)
            log.info("Értesítés elküldve!")
            state["last_notified"] = price
            save_state(state)
    else:
        log.info("Még nem érte el a küszöböt.")


def main():
    log.info("VIBE Pass árfigyelő v4 elindult.")
    log.info(f"Küszöb: {TARGET_PRICE:.0f} lei | Ellenőrzés: {CHECK_INTERVAL}s")
    if not BOT_TOKEN or not CHAT_ID:
        log.error("HIBA: Hiányzó TELEGRAM_BOT_TOKEN vagy TELEGRAM_CHAT_ID!")
        return
    send_telegram(
        f"✅ <b>VIBE árfigyelő v4 elindult!</b>\n\n"
        f"Figyelt oldal: {URL}\n"
        f"Értesítési küszöb: {TARGET_PRICE:.0f} lei\n"
        f"Ellenőrzési időköz: {CHECK_INTERVAL} másodperc"
    )
    while True:
        try:
            check()
        except Exception as e:
            log.error(f"Váratlan hiba: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
