import os
import re
import time
import json
import logging
from pathlib import Path
import requests

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


def strip_tags(html):
    clean = re.sub(r"<[^>]+>", " ", html)
    return re.sub(r"\s+", " ", clean)


def fetch_price():
    r = requests.get(URL, headers=HEADERS, timeout=30)
    r.raise_for_status()
    text = strip_tags(r.text)

    lowered = text.lower()
    anchors = [m.start() for m in re.finditer(r"vibe.{0,5}pass", lowered)]

    prices = []
    for m in re.finditer(r"(\d+)[\s]*(lei|lej|ron)", text, flags=re.IGNORECASE):
        val = float(m.group(1))
        if 50 < val < 2000:
            prices.append((val, m.start()))

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
        log.info("Telegram üzenet elküldve.")
    except Exception as e:
        log.error(f"Telegram hiba: {e}")


def check():
    state = load_state()
    prev_price = state.get("last_price")
    prev_below = state.get("was_below", False)

    try:
        price = fetch_price()
    except Exception as e:
        log.error(f"Oldal lekérési hiba: {e}")
        return

    if price is None:
        log.warning("Nem sikerült árat felismerni az oldalon.")
        return

    log.info(f"Vibe Pass ár: {price:.0f} lei | Küszöb: {TARGET_PRICE:.0f} lei")

    currently_below = price <= TARGET_PRICE

    # Ár leesett küszöb alá (átmenet: fölötte volt -> alatta van)
    if currently_below and not prev_below:
        msg = (f"🔥 <b>VIBE Pass ár riasztás!</b>\n\n"
               f"Az ár <b>{price:.0f} lei</b>-re csökkent!\n"
               f"Küszöb: {TARGET_PRICE:.0f} lei\n\n"
               f"👉 Vedd meg most: {URL}")
        send_telegram(msg)
        log.info("⬇️ Ár küszöb alá esett — értesítés elküldve!")

    # Ár visszament küszöb fölé (átmenet: alatta volt -> fölötte van)
    elif not currently_below and prev_below:
        msg = (f"📈 <b>VIBE Pass ár visszament!</b>\n\n"
               f"Az ár <b>{price:.0f} lei</b>-re emelkedett.\n"
               f"Küszöb: {TARGET_PRICE:.0f} lei\n\n"
               f"Folytatom a figyelést...")
        send_telegram(msg)
        log.info("⬆️ Ár küszöb fölé ment vissza — értesítés elküldve!")

    state["last_price"] = price
    state["was_below"] = currently_below
    save_state(state)


def main():
    log.info("VIBE Pass árfigyelő v6 elindult.")
    log.info(f"Küszöb: {TARGET_PRICE:.0f} lei | Ellenőrzés: {CHECK_INTERVAL}s")
    if not BOT_TOKEN or not CHAT_ID:
        log.error("HIBA: Hiányzó TELEGRAM_BOT_TOKEN vagy TELEGRAM_CHAT_ID!")
        return
    send_telegram(
        f"✅ <b>VIBE árfigyelő v6 elindult!</b>\n\n"
        f"Figyelt oldal: {URL}\n"
        f"Értesítési küszöb: {TARGET_PRICE:.0f} lei\n"
        f"Ellenőrzési időköz: {CHECK_INTERVAL} másodperc\n\n"
        f"Értesítesz ha az ár küszöb alá esik és ha visszamegy."
    )
    while True:
        try:
            check()
        except Exception as e:
            log.error(f"Váratlan hiba: {e}")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
