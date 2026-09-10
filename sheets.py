import os, json, time, asyncio, logging
import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = os.getenv("SHEET_ID", "")
KEY_PATH = os.getenv("GOOGLE_KEY_PATH", "google_key.json")
_ws = None
_last_try = 0.0
RETRY_SECONDS = 300   # ulanish bo'lmasa, shuncha vaqtdan keyin qayta urinish


def _configured():
    return bool(SHEET_ID) and os.path.exists(KEY_PATH)


def _connect():
    """Jadvalga ulanadi. Ilgari bu faqat import paytida bir marta bo'lardi:
    ishga tushish lahzasida tarmoq uzilsa, Sheets keyingi qayta ishga
    tushishgacha butunlay o'chib qolardi (2026-09-10 da shunday bo'ldi)."""
    global _ws, _last_try
    _last_try = time.time()
    try:
        scopes = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(KEY_PATH, scopes=scopes)
        gc = gspread.authorize(creds)
        _ws = gc.open_by_key(SHEET_ID).worksheet("Logs")
        logging.info("Google Sheets ulandi!")
    except Exception as e:
        logging.error(f"Sheets ulanishida xato: {e}")


if _configured():
    _connect()
else:
    logging.warning("Sheets sozlanmagan (kalit yoki SHEET_ID yo'q).")

async def append_click(user_id, nickname, username, payload, timestamp):
    global _last_try
    if not _ws and _configured() and time.time() - _last_try > RETRY_SECONDS:
        # Vaqtni oldindan belgilaymiz: bir vaqtda kelgan boshqa yozuvlar
        # parallel ravishda yana ulanishga urinmasin.
        _last_try = time.time()
        await asyncio.to_thread(_connect)
    if not _ws:
        return
    try:
        await asyncio.to_thread(
            _ws.append_row,
            [str(user_id), nickname, username, payload, timestamp],
            value_input_option="USER_ENTERED"
        )
    except Exception as e:
        logging.error(f"Sheetsga yozishda xato: {e}")
