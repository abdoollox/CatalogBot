import os, json, asyncio, logging
import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = os.getenv("SHEET_ID", "")
KEY_PATH = os.getenv("GOOGLE_KEY_PATH", "google_key.json")
_ws = None

try:
    if os.path.exists(KEY_PATH) and SHEET_ID:
        scopes = ["https://www.googleapis.com/auth/spreadsheets",
                  "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(KEY_PATH, scopes=scopes)
        gc = gspread.authorize(creds)
        _ws = gc.open_by_key(SHEET_ID).worksheet("Logs")
        logging.info("Google Sheets ulandi!")
    else:
        logging.warning("Sheets sozlanmagan (kalit yoki SHEET_ID yo'q).")
except Exception as e:
    logging.error(f"Sheets ulanishida xato: {e}")

async def append_click(user_id, nickname, username, payload, timestamp):
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
