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


# --- KUZATUV PANELI UCHUN O'QISH ---
# Panel (dashboard) butun jadvalni bir marta oladi va hisoblashni o'zi bajaradi.
#
# Kesh MATN ko'rinishida saqlanadi, qatorlar ro'yxati emas: 20 mingdan ortiq
# qator ro'yxat bo'lib ~25 MB joy egallaydi, tayyor CSV esa ~2 MB. Konteyner
# xotirasi 384 MB bilan chegaralangan, shuning uchun bu farq muhim.
#
# Muddati o'tgan keshda eski nusxa DARHOL beriladi va yangisi fonda olinadi:
# Sheets'dan 20 ming qatorni olish 10-15 soniya turadi, panel esa shuncha
# kutib turmasligi kerak.
CACHE_SECONDS = 120
# MUTLAQ yo'l va aynan /data: docker-compose faqat shu papkani hostga ulaydi
# (./data:/data). Nisbiy "data/..." konteynerning ICHIDAGI nusxaga yozilardi va
# konteyner qayta qurilganda yo'qolardi - hp.db ham shu sababdan /data/hp.db.
CACHE_FILE = os.getenv("SHEETS_CACHE", "/data/logs_cache.csv")
_cache = {"at": 0.0, "csv": None}
_read_lock = asyncio.Lock()


def _load_disk():
    """Oldingi nusxa. Bot qayta ishga tushganda panel darhol ishlasin."""
    try:
        with open(CACHE_FILE, encoding="utf-8") as f:
            return f.read()
    except FileNotFoundError:
        return None
    except Exception as e:
        logging.warning("Kesh faylini o'qib bo'lmadi: %s", e)
        return None


def _save_disk(text):
    # Avval vaqtinchalik faylga: yozish yarmida uzilsa eski nusxa buzilmasin.
    try:
        tmp = CACHE_FILE + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, CACHE_FILE)
    except Exception as e:
        logging.warning("Kesh faylini yozib bo'lmadi: %s", e)


def _to_csv(rows):
    import csv, io
    buf = io.StringIO()
    csv.writer(buf).writerows(rows)
    return buf.getvalue()


async def _refresh():
    """Jadvalni o'qib keshga yozadi. Xato bo'lsa eski nusxa qoladi."""
    global _ws
    async with _read_lock:
        if not _ws and _configured():
            await asyncio.to_thread(_connect)
        if not _ws:
            return _cache["csv"]
        try:
            rows = await asyncio.to_thread(_ws.get_all_values)
            _cache["csv"] = _to_csv(rows)
            _cache["at"] = time.time()
            await asyncio.to_thread(_save_disk, _cache["csv"])
        except Exception as e:
            logging.error("Sheetsni o'qishda xato: %s", e)
            _ws = None   # ulanish uzilgan bo'lishi mumkin - keyingi safar qaytadan
        return _cache["csv"]


async def read_csv():
    """Logs varag'ining CSV nusxasi (matn) yoki None."""
    if _cache["csv"] is None:
        disk = await asyncio.to_thread(_load_disk)
        if disk:
            _cache["csv"] = disk
            _cache["at"] = 0.0       # eskirgan: quyida fonda yangilanadi
    if _cache["csv"] is None:
        return await _refresh()      # birinchi ishga tushish - kutishdan boshqa chora yo'q
    if time.time() - _cache["at"] > CACHE_SECONDS and not _read_lock.locked():
        asyncio.create_task(_refresh())   # fonda yangilaymiz, javobni kuttirmaymiz
    return _cache["csv"]
