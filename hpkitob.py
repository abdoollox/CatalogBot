# -*- coding: utf-8 -*-
"""Kitoblar (asosiy 7 ta kitob) - fayllar yopiq GURUHDAN, filmlar va serial kabi.

Maqsad (egasi, 2026-10-07): mexanizm hozirdan tayyor tursin - kitob faylini baza
guruhidagi mavzuga tashlashning o'zi yetarli bo'lsin. Kod o'zgartirish kerak emas.

Sozlash (bir marta, admin): guruhdagi kitoblar mavzusida
    /kitob            - shu mavzu kitoblar mavzusi (til fayl nomidan olinadi)
    /kitob en         - shu mavzudagi hamma fayl inglizcha (uz, ru ham shunday)
Shundan keyin mavzuga tashlangan har fayl (PDF, EPUB, FB2) o'zi taniladi:
    qaysi kitob - nomidan ("Chamber of Secrets", "Тайная комната", "2-kitob", "Book 2");
    til         - mavzu tilidan, bo'lmasa nomidan ("uz", "рус", "eng"; kirill harflari -> ru);
    format      - fayl kengaytmasidan.
Tanilmasa - adminning shaxsiy chatiga yoziladi, qo'lda bog'lash buyrug'i bilan.

Adminning bot bilan shaxsiy chatida:
    /kitob                    - holat
    /kitob sinov              - kitoblarni FAQAT adminlar ko'radi (boshlang'ich holat)
    /kitob ochiq              - hammaga ochiladi
    /kitobfayl kt2_en pdf 1234  - 2-kitob inglizcha PDF guruhdagi 1234-xabar
    /kitobfayl kt2_en pdf -     - bog'lanishni olib tashlash

ILOVADA O'QISH: PDF 20 MB dan kichik bo'lsa bot uni /data/kitob/ ga yuklab oladi va
ilovaga /api/books/f/... orqali beradi (bot bundan katta faylni Telegramdan ololmaydi).
Katta PDF faqat chatga yuboriladi - adminga aytiladi.

Narx: birinchi kitob bepul, qolganlari galleonga (albomlar kabi: bir marta, doim ochiq).
"""

import asyncio
import logging
import os
import re
import sqlite3
import time

import json

from aiohttp import web
from aiogram import types
from aiogram.filters import Command
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, WebAppInfo

import emoji

import hpfilms          # _topic_of
import hpmusic          # _tg, make_key/check_key, _galleons

STORE = "/data/kitob.json"     # MUTLAQ yo'l: faqat /data konteynerdan tashqarida yashaydi
FILE_DIR = "/data/kitob"       # ilovada o'qish uchun PDF nusxalari: kt1_en.pdf
DB_PATH = os.getenv("HP_DB_PATH", "/data/hp.db")
LANGS = ("uz", "ru", "en")
FORMATS = ("pdf", "epub", "fb2")
ORDER = ("kt1", "kt2", "kt3", "kt4", "kt5", "kt6", "kt7")
YEARS = {"kt1": 1997, "kt2": 1998, "kt3": 1999, "kt4": 2000, "kt5": 2003, "kt6": 2005, "kt7": 2007}
BOOK_PRICE = 3
FREE_BOOKS = ("kt1",)
SEND_GAP = 4
BOT_API_LIMIT = 20 * 1024 * 1024    # bot bundan katta faylni yuklab ololmaydi

_cfg = {}
# topics: {mavzu raqami: til yoki ""}; books: {"kt1_en": {"pdf": {...}}}
_data = {"group": None, "topics": {}, "books": {}, "ochiq": False}
_oxirgi = {}
_owned = {}


# --- SAQLASH ---

def load():
    global _data
    try:
        with open(STORE, encoding="utf-8") as f:
            d = json.load(f)
        for k, v in (("group", None), ("topics", {}), ("books", {}), ("ochiq", False)):
            d.setdefault(k, v)
        _data = d
    except FileNotFoundError:
        pass
    except Exception as e:
        logging.error("kitob.json o'qilmadi: %s", e)


def _save():
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_data, f, ensure_ascii=False)
    os.replace(tmp, STORE)


def _db():
    return sqlite3.connect(DB_PATH, timeout=10)


def _init():
    conn = _db()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS kitob_egasi ("
                     "user_id INTEGER NOT NULL, kitob TEXT NOT NULL, narx INTEGER NOT NULL, "
                     "vaqt INTEGER NOT NULL, PRIMARY KEY (user_id, kitob))")
        conn.commit()
    finally:
        conn.close()


# --- NOMDAN KITOB, TIL, FORMAT ---

# Tartib muhim: aniqroq so'zlar oldin. "prince" 6-kitob, "half blood" ham.
_SOZ = (
    ("kt7", r"deathly|hallows|дары\s+смерти|ajal\s+tuhfa|o'lim\s+tuhfa|olim\s+tuhfa"),
    ("kt6", r"half[\s-]*blood|prince|принц|полукровк|shahzoda|chala\s*qon"),
    ("kt5", r"phoenix|феникс|feniks|qaqnus|kaknus"),
    ("kt4", r"goblet|кубок\s+огня|olov\s+(?:jomi|kubogi)|otashli\s+jom"),
    ("kt3", r"azkaban|азкабан"),
    ("kt2", r"chamber|secrets|тайная\s+комната|maxfiy\s+xona|sirli\s+xona|sirlar\s+xonasi"),
    ("kt1", r"philosopher|sorcerer|stone|философск|камень|afsonaviy\s+tosh|falsafa\s+toshi|hikmatlar\s+toshi|sehrli\s+tosh"),
)
_SOZ = tuple((k, re.compile(rx)) for k, rx in _SOZ)
_RAQAM = (
    re.compile(r"(?:book|книга|kitob|part|том|year)\s*[#№]?\s*([1-7])\b"),
    re.compile(r"\b([1-7])\s*[-.]?\s*(?:kitob|книга|qism|том)"),
    re.compile(r"^\s*(?:hp|гп|gp)?\s*0?([1-7])\s*[-_. )]"),
    re.compile(r"\b(?:hp|гп|gp)\s*0?([1-7])\b"),
)
_TIL = (
    ("uz", re.compile(r"\b(?:uz|uzb|uzbek|o'zbek\w*|ozbek\w*)\b|узбек")),
    ("ru", re.compile(r"\b(?:ru|rus|russian|ruscha)\b|русск|рус\b")),
    ("en", re.compile(r"\b(?:en|eng|english|inglizcha|ingliz)\b|англ")),
)


def _norm(text):
    n = (text or "").lower().replace("’", "'").replace("`", "'").replace("ʻ", "'").replace("_", " ")
    return re.sub(r"\.(pdf|epub|fb2)\b", " ", n)


def book_of(text):
    """Matndan kitob kodi ("kt3") yoki None."""
    n = _norm(text)
    for k, rx in _SOZ:
        if rx.search(n):
            return k
    n = re.sub(r"\b(19|20)\d\d\b", " ", n)
    for rx in _RAQAM:
        m = rx.search(n)
        if m:
            return "kt" + m.group(1)
    return None


def lang_of(text):
    """Matndan til yoki None. Aniq belgi bo'lmasa: kirill harflari ko'p bo'lsa - ru."""
    n = _norm(text)
    for l, rx in _TIL:
        if rx.search(n):
            return l
    if len(re.findall(r"[а-яё]", n)) >= 4:
        return "ru"
    return None


def fmt_of(name, mime=""):
    m = re.search(r"\.(pdf|epub|fb2)$", (name or "").lower().strip())
    if m:
        return m.group(1)
    mime = (mime or "").lower()
    if "pdf" in mime:
        return "pdf"
    if "epub" in mime:
        return "epub"
    return None


_KEY = re.compile(r"^(kt[1-7])_(uz|ru|en)$")


def parse_key(k):
    m = _KEY.match((k or "").lower())
    return (m.group(1), m.group(2)) if m else None


def local_path(book, lang):
    return os.path.join(FILE_DIR, "%s_%s.pdf" % (book, lang))


def can_read(book, lang):
    it = (_data["books"].get("%s_%s" % (book, lang)) or {}).get("pdf")
    return bool(it and it.get("read") and os.path.isfile(local_path(book, lang)))


def source(book, lang, fmt):
    it = (_data["books"].get("%s_%s" % (book, lang)) or {}).get(fmt)
    if it and _data.get("group"):
        return _data["group"], int(it["mid"])
    return None


# --- EGALIK VA GALLEON ---

def owned(user_id):
    uid = int(user_id)
    if uid not in _owned:
        conn = _db()
        try:
            _owned[uid] = {r[0] for r in conn.execute(
                "SELECT kitob FROM kitob_egasi WHERE user_id=?", (uid,))}
        except sqlite3.OperationalError:
            return set()
        finally:
            conn.close()
    return _owned[uid]


def book_open(user_id, book):
    """Kitob shu odamga ochiqmi: bepul kitob yoki sotib olingan."""
    if book not in ORDER:
        return False
    if book in FREE_BOOKS:
        return True
    return user_id is not None and book in owned(user_id)


def _buy(uid, book):
    """Kitobni galleonga ochadi. (holat, qoldiq): "ok" | "bor" | "pul"."""
    uid = int(uid)
    conn = _db()
    try:
        if conn.execute("SELECT 1 FROM kitob_egasi WHERE user_id=? AND kitob=?", (uid, book)).fetchone():
            return "bor", hpmusic._galleons(uid)
        # Bitta so'rovda tekshirib yechamiz: ikki marta bosilsa ham pul ikki marta ketmaydi
        cur = conn.execute("UPDATE users SET galleons = galleons - ? WHERE user_id = ? AND galleons >= ?",
                           (BOOK_PRICE, uid, BOOK_PRICE))
        if cur.rowcount < 1:
            conn.rollback()
            return "pul", hpmusic._galleons(uid)
        conn.execute("INSERT INTO kitob_egasi (user_id, kitob, narx, vaqt) VALUES (?,?,?,?)",
                     (uid, book, BOOK_PRICE, int(time.time())))
        conn.commit()
        _owned.setdefault(uid, set()).add(book)
        r = conn.execute("SELECT galleons FROM users WHERE user_id=?", (uid,)).fetchone()
        return "ok", int(r[0] or 0)
    finally:
        conn.close()


# --- ILOVA UCHUN RO'YXAT ---

def _is_admin_id(uid):
    return uid is not None and int(uid) in _cfg.get("admin_ids", ())


def visible(uid=None):
    return bool(_data.get("ochiq")) or _is_admin_id(uid)


def public_list(uid=None):
    """[{id, year, open, files: {en: {pdf: {size, read}}}}] - faqat fayli bor kitoblar."""
    if not visible(uid):
        return []
    out = []
    for book in ORDER:
        files = {}
        for lang in LANGS:
            its = _data["books"].get("%s_%s" % (book, lang)) or {}
            f = {fmt: {"size": int(its[fmt].get("size") or 0),
                       "read": fmt == "pdf" and can_read(book, lang)}
                 for fmt in FORMATS if fmt in its}
            if f:
                files[lang] = f
        if files:
            out.append({"id": book, "year": YEARS[book], "free": book in FREE_BOOKS,
                        "open": book_open(uid, book), "files": files})
    return out


def table_text():
    qator = []
    for book in ORDER:
        bor = []
        for lang in LANGS:
            its = _data["books"].get("%s_%s" % (book, lang)) or {}
            for fmt in FORMATS:
                if fmt in its:
                    bor.append("%s·%s%s" % (lang, fmt, " (o'qish ✓)" if fmt == "pdf" and can_read(book, lang) else ""))
        qator.append("%s-kitob: %s" % (book[2], ", ".join(bor) or "—"))
    mavzu = ", ".join(sorted(v or "til nomdan" for v in _data["topics"].values())) or "yo'q"
    rejim = "OCHIQ (hamma ko'radi)" if _data.get("ochiq") else "SINOV (faqat adminlar ko'radi)"
    return "📚 Kitoblar\nRejim: %s\nMavzular: %s\n\n%s" % (rejim, mavzu, "\n".join(qator))


# --- ADMIN ---

async def _tell(text):
    bot = _cfg["bot"]
    for uid in sorted(_cfg.get("admin_ids", ())):
        try:
            await hpmusic._tg(bot.send_message, uid, text[:4000], disable_notification=True)
            return
        except Exception:
            continue


def _is_admin(message):
    u = message.from_user
    if u and u.id in _cfg.get("admin_ids", ()):
        return True
    return bool(message.sender_chat and message.sender_chat.id == message.chat.id)


async def on_kitob_command(message: types.Message):
    if not _is_admin(message):
        return
    bolak = (message.text or "").split()
    if message.chat.type == "private":
        if len(bolak) > 1 and bolak[1].lower() in ("ochiq", "sinov"):
            _data["ochiq"] = bolak[1].lower() == "ochiq"
            _save()
        await message.answer(table_text() + "\n\nMavzu qo'shish: guruhdagi kitoblar mavzusida /kitob "
                             "(yoki /kitob en).\nRejim: /kitob ochiq  |  /kitob sinov")
        return
    if message.chat.type != "supergroup":
        return
    lang = next((b.lower() for b in bolak[1:] if b.lower() in LANGS), "")
    try:
        await message.delete()             # guruhda buyruq izi qolmasin
    except Exception:
        pass
    thread = message.message_thread_id if message.is_topic_message else None
    _data["group"] = message.chat.id
    _data["topics"][str(thread)] = lang
    _save()
    await _tell("📚 Kitoblar mavzusi eslab qolindi (%s).\nEndi shu mavzuga tashlangan PDF, EPUB yoki FB2 fayl "
                "o'zi taniladi. Nomida kitob nomi yoki raqami bo'lsin: «Chamber of Secrets» yoki «2-kitob».\n"
                "Hozir rejim: %s." % ("til: " + lang if lang else "til fayl nomidan",
                                      "ochiq" if _data.get("ochiq") else "sinov (faqat adminlar ko'radi)"))


async def on_kitobfayl_command(message: types.Message):
    """Shaxsiy chatda: /kitobfayl kt2_en pdf 1234  yoki  /kitobfayl kt2_en pdf -"""
    if not _is_admin(message) or message.chat.type != "private":
        return
    bolak = (message.text or "").split()
    p = parse_key(bolak[1]) if len(bolak) > 1 else None
    fmt = bolak[2].lower() if len(bolak) > 2 else ""
    if not p or fmt not in FORMATS or len(bolak) < 4:
        await message.answer("Yozilishi: /kitobfayl kt2_en pdf 1234 (guruhdagi xabar raqami) "
                             "yoki /kitobfayl kt2_en pdf -")
        return
    k = "%s_%s" % p
    if bolak[3] == "-":
        (_data["books"].get(k) or {}).pop(fmt, None)
        if not _data["books"].get(k):
            _data["books"].pop(k, None)
        if fmt == "pdf":
            try:
                os.remove(local_path(*p))
            except OSError:
                pass
        _save()
        await message.answer("Olib tashlandi: %s %s\n\n%s" % (k, fmt, table_text()))
        return
    if not bolak[3].isdigit():
        await message.answer("Xabar raqami son bo'lishi kerak.")
        return
    _data["books"].setdefault(k, {})[fmt] = {"mid": int(bolak[3]), "name": "", "size": 0, "by": "qolda",
                                             "at": int(time.time())}
    _save()
    await message.answer("Bog'landi: %s %s ← %s-xabar\n(Qo'lda bog'langan fayl ilovada o'qilmaydi — "
                         "o'qish uchun faylni mavzuga qayta tashlang.)\n\n%s" % (k, fmt, bolak[3], table_text()))


def _in_topic(message):
    if not _data.get("group") or message.chat.id != _data["group"]:
        return False
    return hpfilms._topic_of(message) in _data["topics"]


def _in_topic_doc(message):
    return _in_topic(message) and getattr(message, "document", None) is not None


async def _fetch(fid, book, lang):
    """PDF ni ilovada o'qish uchun diskka oladi. Bo'lsa True."""
    try:
        os.makedirs(FILE_DIR, exist_ok=True)
        tmp = local_path(book, lang) + ".tmp"
        await _cfg["bot"].download(fid, destination=tmp)
        os.replace(tmp, local_path(book, lang))
        return True
    except Exception as e:
        logging.error("Kitob yuklab olinmadi (%s_%s): %s", book, lang, e)
        return False


async def on_group_doc(message: types.Message):
    """Kitoblar mavzusiga fayl tashlandi - kitob, til va format o'zi taniladi."""
    doc = message.document
    name = doc.file_name or ""
    cap = (message.caption or "")[:300]
    fmt = fmt_of(name, doc.mime_type or "")
    if not fmt:
        return                              # rasm yoki boshqa fayl - kitob emas
    matn = "%s\n%s" % (name, cap)
    book = book_of(matn)
    lang = _data["topics"].get(hpfilms._topic_of(message)) or lang_of(matn)
    mid = message.message_id
    if not book or not lang:
        await _tell("📚 Fayl tanilmadi: %d-xabar (%s)\n%s\nQo'lda: /kitobfayl %s_%s %s %d"
                    % (mid, name or cap[:60] or "nomsiz",
                       "Qaysi kitob ekani aniqlanmadi." if not book else "Tili aniqlanmadi.",
                       book or "kt1", lang or "en", fmt, mid))
        return
    k = "%s_%s" % (book, lang)
    old = (_data["books"].get(k) or {}).get(fmt)
    if old and old.get("by") == "qolda":
        await _tell("📚 %s-kitob (%s, %s) qo'lda bog'langan — %d-xabar o'tkazib yuborildi." % (book[2], lang, fmt, mid))
        return
    size = int(doc.file_size or 0)
    it = {"mid": mid, "name": name, "size": size, "fid": doc.file_id, "by": "nom",
          "at": (old or {}).get("at") or int(time.time()), "read": False}
    qoshimcha = ""
    if fmt == "pdf":
        if size and size > BOT_API_LIMIT:
            qoshimcha = ("\n⚠️ Fayl %d MB — ilovada O'QIB bo'lmaydi (chegara 20 MB), faqat chatga yuboriladi. "
                         "O'qish uchun yengilroq PDF tashlang." % round(size / 1048576))
        else:
            it["read"] = await _fetch(doc.file_id, book, lang)
            qoshimcha = "\nIlovada o'qish: %s" % ("tayyor ✓" if it["read"] else "yuklab olinmadi ⚠️")
    _data["books"].setdefault(k, {})[fmt] = it
    _save()
    await _tell("📚 %s-kitob (%s, %s) %s ← %d-xabar%s%s" % (
        book[2], lang, fmt.upper(), "yangilandi" if old else "bog'landi", mid, qoshimcha,
        "" if _data.get("ochiq") else "\nRejim: sinov — ilovada faqat adminlar ko'radi. Ochish: /kitob ochiq"))


# --- KARTA (chatga yuboriladigan fayl ostidagi yozuv) ---

NOM = {
    "uz": ("Garri Potter va afsonaviy tosh", "Garri Potter va maxfiy xona", "Garri Potter va Azkaban mahbusi",
           "Garri Potter va olov kubogi", "Garri Potter va Feniks ordeni", "Garri Potter va chala qonli shahzoda",
           "Garri Potter va ajal tuhfalari"),
    "ru": ("Гарри Поттер и философский камень", "Гарри Поттер и Тайная комната", "Гарри Поттер и узник Азкабана",
           "Гарри Поттер и Кубок огня", "Гарри Поттер и Орден Феникса", "Гарри Поттер и Принц-полукровка",
           "Гарри Поттер и Дары Смерти"),
    "en": ("Harry Potter and the Philosopher's Stone", "Harry Potter and the Chamber of Secrets",
           "Harry Potter and the Prisoner of Azkaban", "Harry Potter and the Goblet of Fire",
           "Harry Potter and the Order of the Phoenix", "Harry Potter and the Half-Blood Prince",
           "Harry Potter and the Deathly Hallows"),
}
KARTA = {
    "uz": {"ost": "%d-kitob", "yil": "Yil", "til": "Til", "format": "Format", "koll": "Kutubxona", "oqish": "Ilovada o'qish"},
    "ru": {"ost": "Книга %d", "yil": "Год", "til": "Язык", "format": "Формат", "koll": "Библиотека", "oqish": "Читать в приложении"},
    "en": {"ost": "Book %d", "yil": "Year", "til": "Language", "format": "Format", "koll": "Library", "oqish": "Read in the app"},
}
TILNOM = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}
APP_LINK = "https://t.me/garripotterkinobot/catalog?startapp=kitob"


def caption(book, lang, fmt, ui):
    """Karta odamning ILOVA tilida (ui), kitob tili alohida qatorda."""
    k = KARTA.get(ui) or KARTA["uz"]
    n = int(book[2])
    brand = _cfg["brand"](ui) if _cfg.get("brand") else "GARRI POTTER KOLLEKSIYA"
    lines = ["<b>%s</b>" % (NOM.get(ui) or NOM["uz"])[n - 1], k["ost"] % n, "— — — — — — — — — —",
             "%s %s: %s" % (emoji.tag("yil"), k["yil"], YEARS[book]),
             "%s %s: %s" % (emoji.tag("til"), k["til"], TILNOM[lang]),
             "%s %s: %s" % (emoji.tag("sifat"), k["format"], fmt.upper()),
             "", '%s <b><a href="%s">%s</a></b>' % (emoji.tag("tasdiq"), APP_LINK, brand)]
    return "\n".join(lines)


def keyboard(book, lang, ui):
    k = KARTA.get(ui) or KARTA["uz"]
    url = _cfg["webapp_url"](ui) if _cfg.get("webapp_url") else None
    if not url:
        return None
    qator = []
    if can_read(book, lang):
        qator.append(InlineKeyboardButton(text=k["oqish"], web_app=WebAppInfo(url=url + "&kitob=" + book)))
    qator.append(InlineKeyboardButton(text=k["koll"], web_app=WebAppInfo(url=url),
                                      icon_custom_emoji_id=emoji.icon("kolleksiya")))
    return InlineKeyboardMarkup(inline_keyboard=[qator])


# --- HTTP ---

def _auth(request, body=None):
    return _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", "")
                                    or str((body or {}).get("initData", "")))


async def api_list(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    user = _auth(request)
    uid = int(user["id"]) if user else None
    out = {"ok": True, "books": public_list(uid), "price": BOOK_PRICE,
           "test": not _data.get("ochiq") and _is_admin_id(uid)}
    if user:
        out["key"] = hpmusic.make_key(uid)
        out["gal"] = await asyncio.to_thread(hpmusic._galleons, uid)
    return cors(web.json_response(out))


async def _body(request):
    try:
        return await request.json()
    except Exception:
        return None


async def api_buy(request):
    """{book} -> {ok, gal} yoki {error: "pul", gal, price}."""
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    body = await _body(request)
    if body is None:
        return cors(web.json_response({"ok": False, "error": "bad_json"}, status=400))
    user = _auth(request, body)
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
    uid = int(user["id"])
    book = str(body.get("book", ""))
    if not visible(uid) or not any(b["id"] == book for b in public_list(uid)):
        return cors(web.json_response({"ok": False, "error": "unknown"}, status=404))
    if book_open(uid, book):
        return cors(web.json_response({"ok": True, "gal": await asyncio.to_thread(hpmusic._galleons, uid)}))
    holat, gal = await asyncio.to_thread(_buy, uid, book)
    if holat == "pul":
        return cors(web.json_response({"ok": False, "error": "pul", "gal": gal, "price": BOOK_PRICE}))
    if holat == "ok":
        await _log(user, "buy_book_" + book)
    return cors(web.json_response({"ok": True, "gal": gal}))


async def _log(user, payload):
    if int(user["id"]) > 0 and _cfg.get("log"):
        try:
            await _cfg["log"](user, payload)
        except Exception as e:
            logging.error("Kitob logi yozilmadi: %s", e)


async def api_send(request):
    """{book, lang, fmt, ui} - faylni chatga yuboradi. {action: "read"} - o'qish boshlanganini yozadi."""
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    body = await _body(request)
    if body is None:
        return cors(web.json_response({"ok": False, "error": "bad_json"}, status=400))
    user = _auth(request, body)
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
    uid = int(user["id"])
    book, lang, fmt = str(body.get("book", "")), str(body.get("lang", "")), str(body.get("fmt", "pdf"))
    ui = str(body.get("ui") or lang)
    if not visible(uid):
        return cors(web.json_response({"ok": False, "error": "not_ready"}))
    manba = source(book, lang, fmt) if (book in ORDER and lang in LANGS and fmt in FORMATS) else None
    if not manba:
        return cors(web.json_response({"ok": False, "error": "not_ready"}))
    if not book_open(uid, book):
        return cors(web.json_response({"ok": False, "error": "locked"}))
    if body.get("action") == "read":
        await _log(user, "read_%s_%s" % (book, lang))
        return cors(web.json_response({"ok": True}))
    hozir = time.time()
    if hozir - _oxirgi.get(uid, 0) < SEND_GAP:
        return cors(web.json_response({"ok": False, "error": "slow"}))
    _oxirgi[uid] = hozir
    chat = _cfg["tg_chat_id"](uid)
    if await _cfg["is_subscribed"](chat) is False:
        return cors(web.json_response({"ok": False, "error": "not_subscribed"}))
    matn = caption(book, lang, fmt, ui)
    kw = dict(chat_id=chat, from_chat_id=manba[0], message_id=manba[1], parse_mode="HTML",
              reply_markup=keyboard(book, lang, ui), protect_content=False)   # egasi, 2026-10-07: kitoblar himoyasiz
    try:
        try:
            sent = await _cfg["bot"].copy_message(caption=matn, **kw)
        except TelegramBadRequest as err:
            if "not found" in str(err).lower():
                raise
            logging.warning("Kitob custom emoji bilan yuborilmadi (%s): %s", chat, err)
            sent = await _cfg["bot"].copy_message(caption=emoji.strip_tags(matn), **kw)
    except Exception as err:
        logging.error("Kitob yuborilmadi (%s_%s %s): %s", book, lang, fmt, err)
        if "not found" in str(err).lower():
            await _tell("⚠️ Kitob yuborilmadi: %s_%s %s — guruhdagi xabar topilmadi." % (book, lang, fmt))
            return cors(web.json_response({"ok": False, "error": "film_missing"}))
        return cors(web.json_response({"ok": False, "error": "send_failed"}))
    await _log(user, "book_%s_%s_%s" % (book, lang, fmt))
    return cors(web.json_response({"ok": True, "message_id": sent.message_id}))


async def api_file(request):
    """Ilovadagi o'qish oynasi uchun PDF. Imzo manzilda (musiqadagi kabi kalit), bo'laklab o'qiladi."""
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        # pdf.js faylni bo'laklab so'raydi (Range) - brauzer avval ruxsat so'raydi
        r = cors(web.Response(status=204))
        r.headers["Access-Control-Allow-Headers"] = "Range"
        return r
    uid = hpmusic.check_key(request.query.get("k", ""))
    p = parse_key(request.match_info.get("key", ""))
    if uid is None:
        return cors(web.Response(status=403, text="key"))
    if not p or not visible(uid) or not can_read(*p) or not book_open(uid, p[0]):
        return cors(web.Response(status=404, text="book"))
    resp = web.FileResponse(local_path(*p), headers={
        "Content-Type": "application/pdf",
        "Cache-Control": "private, max-age=86400",
        "Access-Control-Expose-Headers": "Accept-Ranges, Content-Range, Content-Length",
    })
    return cors(resp)


# --- ULASH ---

def register(dp, bot, app, cfg):
    """cfg: admin_ids, verify_init_data, cors, is_subscribed, tg_chat_id, log, brand, webapp_url.
    hpmusic DAN KEYIN (kaliti shundan), hpfilms DAN OLDIN ulanadi."""
    _cfg.update(cfg)
    _cfg["bot"] = bot
    load()
    try:
        _init()
    except Exception as e:
        logging.error("Kitob jadvali ochilmadi: %s", e)
    dp.message.register(on_kitob_command, Command("kitob"))
    dp.message.register(on_kitobfayl_command, Command("kitobfayl"))
    dp.message.register(on_group_doc, _in_topic_doc)
    app.router.add_route("*", "/api/books", api_list)
    app.router.add_route("*", "/api/books/buy", api_buy)
    app.router.add_route("*", "/api/books/send", api_send)
    app.router.add_route("*", "/api/books/f/{key}.pdf", api_file)
    logging.info("Kitoblar: %d ta kitob-til, rejim %s", len(_data["books"]),
                 "ochiq" if _data.get("ochiq") else "sinov")
