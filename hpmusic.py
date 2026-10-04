# -*- coding: utf-8 -*-
"""Soundtrack kutubxonasi — filmlar musiqasi.

Fayllar yopiq GURUHDA (mavzularga bo'lingan "baza") turadi: barcha albomlar
BITTA mavzuda ("Soundtrack"), ketma-ket. Serverga ham, GitHub'ga ham musiqa
qo'yilmaydi: server fayllarni Telegramdan olib, tinglovchiga oqim bilan uzatadi.

Sozlash (bir marta, admin):
    1. Botni guruhga ADMIN qilib qo'shing (admin bot guruhdagi hamma xabarni ko'radi).
    2. Soundtrack mavzusida `/musiqa` deb yozing. Bot guruhni va mavzuni eslab
       qoladi va mavzudagi ESKI fayllarni o'qiydi. Telegram botga eski
       xabarlarni o'qishga ruxsat bermaydi, shuning uchun bot har xabarni
       adminning bot bilan shaxsiy chatiga nusxalab (forward) o'qiydi va
       darhol o'chiradi. Guruhga hech narsa yozilmaydi.

Qaysi albom — mavzu ichidagi TARTIBDAN:
    * "HP1 - Philosopher's Stone", "Azkaban", "#hp3" kabi sarlavha xabari
      (yoki trekning izohi) — shundan keyingi treklar o'sha albom;
    * sarlavha bo'lmasa: trek raqami qaytadan 1 ga tushsa yoki kompozitor
      almashsa — keyingi albom boshlandi;
    * bir nechta albom sanalgan xabar (mundarija) e'tiborga olinmaydi.
    `#hp1 tozala` — albomni bo'shatadi (keyin qayta yuklash uchun).
Yangi yuklangan fayllar xuddi shu qoida bilan o'zi ushlanadi, bot mavzuga hisobot yozadi.

Tinglash ikki yo'l bilan:
    * ilova ichida — `GET /api/music` ro'yxat + vaqtinchalik kalit beradi,
      `GET /api/music/a/<albom>/<n>?k=<kalit>` faylni oqim bilan uzatadi;
    * Telegramga — `POST /api/music/send` albomni yoki bitta trekni fayl
      raqami (file_id) bilan chatga yuboradi (filmlar kabi protect_content).

NARX (2026-10-04 dan): birinchi albom bepul, qolganlari galleonga bir marta ochiladi
(ALBUM_PRICE) va doim ochiq qoladi — `album_open()`, `POST /api/music/buy`.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import sqlite3
import time

import aiohttp
import types as _pytypes
from aiohttp import web
from aiogram import types
from aiogram.filters import Command
import emoji
import catalog
from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError,
                                TelegramNetworkError, TelegramRetryAfter)

STORE = "/data/music.json"   # MUTLAQ yo'l: faqat /data konteynerdan tashqarida yashaydi
# Mavzudagi har xabarning xom nusxasi (matn + audio ma'lumoti). Albomlar shundan
# qayta hisoblanadi (rebuild) — qoidani o'zgartirsak guruhni qayta o'qish shart emas.
RAW = "/data/music_raw.json"

ORDER = ["hp1", "hp2", "hp3", "hp4", "hp5", "hp6", "hp7", "hp8"]
ALBUMS = {
    "hp1": {"film": "hp1", "year": 2001, "composer": "John Williams"},
    "hp2": {"film": "hp2", "year": 2002, "composer": "John Williams"},
    "hp3": {"film": "hp3", "year": 2004, "composer": "John Williams"},
    "hp4": {"film": "hp4", "year": 2005, "composer": "Patrick Doyle"},
    "hp5": {"film": "hp5", "year": 2007, "composer": "Nicholas Hooper"},
    "hp6": {"film": "hp6", "year": 2009, "composer": "Nicholas Hooper"},
    "hp7": {"film": "hp7", "year": 2010, "composer": "Alexandre Desplat"},
    "hp8": {"film": "hp8", "year": 2011, "composer": "Alexandre Desplat"},
}
SURNAMES = {"williams": "John Williams", "doyle": "Patrick Doyle",
            "hooper": "Nicholas Hooper", "desplat": "Alexandre Desplat"}

# Sarlavhadagi kalit so'zlar (uz/ru/en). Ajal tuhfasi 1/2 raqamga qarab ajraladi.
TITLE_WORDS = [
    ("hp1", ("philosopher", "sorcerer", "философ", "hikmat")),
    ("hp2", ("chamber", "тайная", "maxfiy", "hujra")),
    ("hp3", ("azkaban", "prisoner", "азкабан", "узник")),
    ("hp4", ("goblet", "кубок", "alanga")),
    ("hp5", ("phoenix", "order of", "феникс", "орден", "feniks")),
    ("hp6", ("half-blood", "half blood", "prince", "полукров", "принц", "tilsim", "shahzoda", "shaxzoda")),
    ("hallows", ("hallows", "дары смерти", "ajal")),
]

KEY_TTL = 12 * 3600          # ilovadagi tinglash kaliti shuncha amal qiladi
PATH_TTL = 50 * 60           # Telegram fayl manzili ~1 soat yashaydi
SEND_GAP = 4                 # bir odam Telegramga yuborish orasidagi soniya
SEND_PACE = 0.5              # albom treklari orasidagi pauza (bitta chatga ~1 xabar/s)
REPORT_DELAY = 8             # oxirgi fayldan keyin hisobot kutish
SCAN_PACE = 0.35             # shaxsiy chatga nusxa oralig'i
NET_TRIES = 6                # tarmoq uzilsa shuncha qayta urinish
BOT_API_LIMIT = 20 * 1024 * 1024   # bot bundan katta faylni yuklab ololmaydi

_cfg = {}
# group/thread: baza guruhi va Soundtrack mavzusi; albums: {albom: [trek]};
# cur/prev_n: mavzudagi oxirgi bo'lim (yangi fayl qaysi albomga tushadi);
# skipped: albomi aniqlanmagan audiolar soni
_data = {"group": None, "thread": None, "albums": {}, "cur": None, "prev_n": None}
_paths = {}                  # file_id -> (file_path, vaqt)
_last_send = {}              # user_id -> vaqt
_report_task = None
_scan_task = None
_scan_errors = {}            # skanerda Telegram rad etgan sabablar -> soni
_raw = []                    # [{mid, x: matn, a: audio|None}] mid bo'yicha tartibda
_session = None
_lock = None                 # asyncio.Lock — ishga tushganda yaratiladi


# --- SAQLASH ---

def load():
    global _data
    try:
        with open(STORE, encoding="utf-8") as f:
            d = json.load(f)
        for k in ("topics", "names", "pending", "current"):
            d.pop(k, None)       # eski tuzilma qoldiqlari
        for k, v in (("group", None), ("thread", None), ("albums", {}), ("cur", None), ("prev_n", None)):
            d.setdefault(k, v)
        _data = d
    except FileNotFoundError:
        pass
    except Exception as e:
        logging.error("music.json o'qilmadi: %s", e)


def _save():
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


def load_raw():
    global _raw
    try:
        with open(RAW, encoding="utf-8") as f:
            _raw = json.load(f)
    except FileNotFoundError:
        _raw = []
    except Exception as e:
        logging.error("music_raw.json o'qilmadi: %s", e)
        _raw = []


def _save_raw():
    tmp = RAW + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_raw, f, ensure_ascii=False)
    os.replace(tmp, RAW)


def raw_item(mid, text, audio):
    a = None
    if audio is not None:
        a = {"p": audio.performer, "t": audio.title, "f": audio.file_name, "d": audio.duration,
             "s": audio.file_size, "m": audio.mime_type, "id": audio.file_id, "u": audio.file_unique_id}
    return {"mid": mid, "x": (text or "")[:1500], "a": a}


def _audio_obj(a):
    return _pytypes.SimpleNamespace(performer=a.get("p"), title=a.get("t"), file_name=a.get("f"),
                                 duration=a.get("d"), file_size=a.get("s"), mime_type=a.get("m"),
                                 file_id=a.get("id"), file_unique_id=a.get("u"))


def remember(item):
    """Xom nusxani mid bo'yicha qo'shadi/yangilaydi."""
    for i, x in enumerate(_raw):
        if x["mid"] == item["mid"]:
            _raw[i] = item
            return
    _raw.append(item)
    _raw.sort(key=lambda x: x["mid"])


def rebuild():
    """Albomlarni xom nusxalardan boshidan hisoblaydi."""
    _data["albums"], _data["cur"], _data["prev_n"] = {}, None, None
    _data["heads"], _data["hmid"] = {}, None
    for it in _raw:
        see(it["mid"], it.get("x") or "", _audio_obj(it["a"]) if it.get("a") else None)


def tracks(album):
    return _data["albums"].get(album, [])


# Narx (egasi, 2026-10-04): albom galleonga bir marta ochiladi va doim ochiq qoladi.
# Birinchi albom hammaga bepul (tatib ko'rish uchun). Galleon - hafta yakunidagi kubok
# mukofotidan (hpcup._galleon_mukofot) va Gringottsdagi boshlang'ich puldan.
ALBUM_PRICE = 30
FREE_ALBUMS = ("hp1",)
_owned = {}                  # user_id -> {albom} (bazadan bir marta o'qiladi)


def owned(user_id):
    uid = int(user_id)
    if uid not in _owned:
        conn = _db()
        try:
            _owned[uid] = {r[0] for r in conn.execute(
                "SELECT album FROM album_egasi WHERE user_id=?", (uid,))}
        except sqlite3.OperationalError:
            return set()                 # jadval hali yo'q (ishga tushish payti)
        finally:
            conn.close()
    return _owned[uid]


def album_open(user_id, album):
    """Albom shu odamga ochiqmi: bepul albom yoki sotib olingan."""
    if album not in ALBUMS:
        return False
    if album in FREE_ALBUMS or user_id is None:
        return album in FREE_ALBUMS
    # Sinov o'quvchisiga ham qulf (egasi, 2026-10-04): u oddiy odam ko'rganini ko'rishi kerak
    return album in owned(user_id)


def _galleons(uid):
    conn = _db()
    try:
        r = conn.execute("SELECT galleons FROM users WHERE user_id=?", (int(uid),)).fetchone()
        return int(r[0] or 0) if r else 0
    except sqlite3.OperationalError:
        return 0
    finally:
        conn.close()


def _buy(uid, album):
    """Albomni galleonga ochadi. (holat, qoldiq): "ok" | "bor" | "pul"."""
    uid = int(uid)
    conn = _db()
    try:
        if conn.execute("SELECT 1 FROM album_egasi WHERE user_id=? AND album=?", (uid, album)).fetchone():
            return "bor", _galleons(uid)
        # Bitta so'rovda tekshirib yechamiz: ikki marta bosilsa ham pul ikki marta ketmaydi
        cur = conn.execute("UPDATE users SET galleons = galleons - ? WHERE user_id = ? AND galleons >= ?",
                           (ALBUM_PRICE, uid, ALBUM_PRICE))
        if cur.rowcount < 1:
            conn.rollback()
            return "pul", _galleons(uid)
        conn.execute("INSERT INTO album_egasi (user_id, album, narx, vaqt) VALUES (?,?,?,?)",
                     (uid, album, ALBUM_PRICE, int(time.time())))
        conn.commit()
        _owned.setdefault(uid, set()).add(album)
        r = conn.execute("SELECT galleons FROM users WHERE user_id=?", (uid,)).fetchone()
        return "ok", int(r[0] or 0)
    finally:
        conn.close()


async def api_buy(request):
    """Ilova: albomni galleonga ochish. {album} -> {ok, gal} yoki {error: "pul", gal, price}."""
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    try:
        body = await request.json()
    except Exception:
        return cors(web.json_response({"ok": False, "error": "bad_json"}, status=400))
    user = _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", "")
                                    or str(body.get("initData", "")))
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
    uid = int(user["id"])
    album = str(body.get("album", ""))
    if album not in ALBUMS or not tracks(album):
        return cors(web.json_response({"ok": False, "error": "unknown"}, status=404))
    if album_open(uid, album):
        return cors(web.json_response({"ok": True, "gal": await asyncio.to_thread(_galleons, uid)}))
    holat, gal = await asyncio.to_thread(_buy, uid, album)
    if holat == "pul":
        return cors(web.json_response({"ok": False, "error": "pul", "gal": gal, "price": ALBUM_PRICE}))
    if holat == "ok" and _cfg.get("log"):
        try:
            await _cfg["log"](user, "buy_ost_" + album)
        except Exception as e:
            logging.error("Albom xaridi logi yozilmadi: %s", e)
    return cors(web.json_response({"ok": True, "gal": gal}))


# --- MATNDAN ALBOM ---

def title_album(text):
    """Bitta qatordan albomni topadi ("HP3 - Prisoner of Azkaban"), topolmasa None."""
    n = (text or "").lower().replace("’", "'").strip()
    n = re.sub(r"^[\s\W_]+", "", n)          # "├── ", "🎬 ", "#" kabi boshlanishlar
    m = re.match(r"^(?:hp\s*)?([1-8])(?!\d)", n) or re.search(r"\bhp\s*([1-8])\b", n)
    if m:
        return "hp" + m.group(1)
    for album, words in TITLE_WORDS:
        if any(w in n for w in words):
            if album != "hallows":
                return album
            two = re.search(r"(part|часть|qism)\s*(2|ii)\b|\b(2|ii)\b|2\s*-\s*(qism|часть)", n)
            return "hp8" if two else "hp7"
    return None


def header_album(text):
    """Sarlavha xabari bo'lsa albomni qaytaradi — FAQAT birinchi qatoridan.

    Guruhdagi sarlavha: "🎼 Harry Potter and the Philosopher's Stone / Composer / 1. Prologue / ...".
    Keyingi qatorlardagi "1. Prologue", "2. ..." ni film raqami deb o'qib bo'lmaydi.
    Mundarijaning birinchi qatori ("FILM SOUNDTRACKS") albom emas — e'tiborga olinmaydi.
    """
    for line in (text or "").splitlines():
        if line.strip():
            return title_album(line)
    return None


def composer_of(audio):
    p = " ".join([(audio.performer or ""), (audio.title or ""), (audio.file_name or "")]).lower()
    for s, full in SURNAMES.items():
        if s in p:
            return full
    return None


# --- TREKLAR ---

_NUM = re.compile(r"^\s*(?:cd\s*\d+\s*[-_.]\s*)?(\d{1,3})(?!\d)\s*[-_.)\]]*\s*", re.I)
_CLEAR = re.compile(r"#(hp[1-8])\s+(tozala|clear)\b", re.I)


def _track_num(*names):
    for name in names:
        m = _NUM.match(name or "")
        if m:
            return int(m.group(1))
    return None


def _clean_title(audio):
    if audio.title:
        t = audio.title
    else:
        t = os.path.splitext(audio.file_name or "")[0]
        # "Alexandre Desplat - Showdown" -> "Showdown"
        if audio.performer and t.lower().startswith(audio.performer.lower()):
            t = t[len(audio.performer):].lstrip(" -–—_")
    t = _NUM.sub("", t, count=1) if _NUM.match(t) else t
    return (t.replace("_", " ").strip() or "Track")[:120]


def _sort(lst):
    lst.sort(key=lambda x: x["mid"])


def _drop(fuid):
    for lst in _data["albums"].values():
        lst[:] = [x for x in lst if x["fuid"] != fuid]


def _next_album(cur, composer=None):
    """cur dan keyingi albom; kompozitor berilsa — shu kompozitorning keyingisi."""
    start = ORDER.index(cur) + 1 if cur in ORDER else 0
    for a in ORDER[start:]:
        if not composer or ALBUMS[a]["composer"] == composer:
            return a
    return None


def place(message_id, audio):
    """Trekni mavzudagi tartib bo'yicha albomga qo'yadi. Albomni (yoki None) qaytaradi."""
    # Shu fayl allaqachon bor (qayta yuklangan) — o'z albomida yangilanadi, tartib buzilmaydi
    for album, lst in _data["albums"].items():
        for i, x in enumerate(lst):
            if x["fuid"] == audio.file_unique_id:
                lst[i] = dict(x, mid=message_id, fid=audio.file_id)
                _sort(lst)
                return album
    comp = composer_of(audio)
    n = _track_num(audio.file_name, audio.title)
    cur = _data.get("cur")
    if cur is None:
        cur = _next_album(None, comp) or "hp1"
    else:
        prev = _data.get("prev_n")
        if comp and ALBUMS[cur]["composer"] != comp:
            cur = _next_album(cur, comp)          # kompozitor almashdi
        elif n is not None and prev is not None and n <= prev:
            cur = _next_album(cur)                # raqam qaytadan boshlandi
    if not cur:
        return None
    _data["cur"], _data["prev_n"] = cur, n
    # albomning birinchi treki: undan oldingi sarlavha xabari — muqova manbasi
    hm = _data.get("hmid")
    if hm and hm[0] == cur:
        _data.setdefault("heads", {}).setdefault(cur, hm[1])
    _drop(audio.file_unique_id)
    _data["albums"].setdefault(cur, []).append({
        "mid": message_id,
        "fid": audio.file_id,
        "fuid": audio.file_unique_id,
        "n": n,
        "t": _clean_title(audio),
        "d": int(audio.duration or 0),
        "s": int(audio.file_size or 0),
        "mime": audio.mime_type or "audio/mpeg",
    })
    _sort(_data["albums"][cur])
    return cur


def see(message_id, text, audio):
    """Mavzudagi bitta xabarni hisobga oladi (skaner ham, jonli ham shu yo'ldan)."""
    clear = _CLEAR.search(text or "")
    if clear:
        album = clear.group(1).lower()
        _data["albums"][album] = []
        _data["cur"], _data["prev_n"] = album, None
    else:
        album = header_album(text)
        if album:
            _data["cur"], _data["prev_n"] = album, None
            _data["hmid"] = [album, message_id]
    if audio is not None:
        return place(message_id, audio)
    return None


def _fmt_dur(sec):
    h, m = divmod(sec // 60, 60)
    return ("%d:%02d:%02d" % (h, m, sec % 60)) if h else ("%d:%02d" % (m, sec % 60))


def summary_text():
    qator = []
    for key in ORDER:
        lst = tracks(key)
        if lst:
            qator.append("✅ %s — %d ta trek, %s (%s … %s)" % (
                key, len(lst), _fmt_dur(sum(x["d"] for x in lst)), lst[0]["t"], lst[-1]["t"]))
        else:
            qator.append("▫️ %s — yo'q" % key)
    return "\n".join(qator)


async def _say(text):
    kw = {}
    if _data.get("thread"):
        kw["message_thread_id"] = _data["thread"]
    await _tg(_cfg["bot"].send_message, _data["group"], text[:4000], disable_notification=True, **kw)


async def _report_later():
    try:
        await asyncio.sleep(REPORT_DELAY)
        await _say("\U0001f3b5 Soundtrack yangilandi:\n\n" + summary_text())
        if _missing_covers():
            _start_covers()
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error("Musiqa hisoboti yuborilmadi: %s", e)


def _schedule_report():
    global _report_task
    if _report_task and not _report_task.done():
        _report_task.cancel()
    _report_task = asyncio.create_task(_report_later())


async def _tg(fn, *a, **kw):
    """Telegram so'rovi: sekinla desa kutadi, tarmoq uzilsa qayta uradi."""
    for urinish in range(NET_TRIES):
        try:
            return await fn(*a, **kw)
        except TelegramRetryAfter as e:
            await asyncio.sleep(e.retry_after + 1)
        except TelegramNetworkError as e:
            if urinish == NET_TRIES - 1:
                raise
            logging.warning("Musiqa: tarmoq uzildi (%s-urinish): %s", urinish + 1, e)
            await asyncio.sleep(2 * (urinish + 1))
    return await fn(*a, **kw)


def _in_topic(message):
    if not _data.get("group") or message.chat.id != _data["group"]:
        return False
    th = message.message_thread_id if message.is_topic_message else None
    return th == _data.get("thread")


async def on_group_message(message: types.Message):
    text = message.text or message.caption or ""
    audio = message.audio
    if audio is None and message.document and (message.document.mime_type or "").startswith("audio/"):
        await _say("⚠️ %s hujjat (fayl) bo'lib tushdi. Uni musiqa sifatida qayta "
                   "yuboring." % (message.document.file_name or ""))
        return
    if audio is None and not header_album(text) and not _CLEAR.search(text):
        return
    async with _lock:
        item = raw_item(message.message_id, text, audio)
        is_new = not _raw or item["mid"] > _raw[-1]["mid"]
        remember(item)
        _save_raw()
        if is_new:
            album = see(message.message_id, text, audio)
        else:                     # tahrir yoki eski xabar — hammasini qayta hisoblaymiz
            rebuild()
            album = None
        _save()
    if audio is not None:
        logging.info("Musiqa: %s <- %s (%s)", album or "?", audio.file_name, message.message_id)
    _schedule_report()


# --- ESKI FAYLLARNI O'QISH ---

async def _peek(bot, chat, mid, inbox):
    """mid xabarini inbox (admin shaxsiy chati) ga nusxalab o'qiydi va o'chiradi."""
    try:
        m = await _tg(bot.forward_message, inbox, chat, mid, disable_notification=True)
    except TelegramBadRequest as e:
        why = str(e.message or e)[:80]       # yo'q, xizmat xabari va h.k.
        _scan_errors[why] = _scan_errors.get(why, 0) + 1
        return None
    try:
        await _tg(bot.delete_message, inbox, m.message_id)
    except Exception as e:
        logging.warning("Skaner nusxasi o'chmadi (%s): %s", m.message_id, e)
    return m


async def _inbox(bot, note=None):
    """Nusxalar boradigan admin chati: bot yoza oladigan birinchi admin."""
    for uid in sorted(_cfg.get("admin_ids", ())):
        try:
            m = await _tg(bot.send_message, uid, note or ("\U0001f3b5 Soundtrack mavzusini o'qiyapman — "
                          "bu yerda bir lahza xabarlar ko'rinib o'chadi."), disable_notification=True)
            return uid, m.message_id
        except (TelegramBadRequest, TelegramForbiddenError):
            continue
    return None, None


async def scan(chat, start, upto):
    """start..upto oralig'idagi xabarlarni tartib bilan o'qiydi. Topilgan audio sonini qaytaradi."""
    bot = _cfg["bot"]
    _scan_errors.clear()
    inbox, note = await _inbox(bot)
    if not inbox:
        raise RuntimeError("hech bir admin bot bilan shaxsiy chat ochmagan (/start bosing)")
    topildi = 0
    yigim = []
    for mid in range(start, upto):
        m = await _peek(bot, chat, mid, inbox)
        if m is not None:
            yigim.append(raw_item(mid, m.text or m.caption or "", m.audio))
            if m.audio:
                topildi += 1
        await asyncio.sleep(SCAN_PACE)
    async with _lock:
        global _raw
        # skanerdan keyin jonli kelganlar ham saqlanib qolsin
        keyin = [x for x in _raw if x["mid"] >= upto]
        _raw = sorted(yigim + keyin, key=lambda x: x["mid"])
        _save_raw()
        rebuild()
        _save()
    try:
        await bot.delete_message(inbox, note)
    except Exception:
        pass
    return topildi


async def _scan_job(chat, start, upto):
    global _scan_task
    try:
        n = await scan(chat, start, upto)
        _start_covers()
        joy = sum(len(v) for v in _data["albums"].values())
        izoh = "\n".join("  %s — %d" % (k, v) for k, v in sorted(_scan_errors.items(), key=lambda x: -x[1])[:4])
        logging.info("Musiqa skaneri: %d ta audio, %d joylandi, rad etilgan: %s", n, joy, _scan_errors)
        await _say("\U0001f3b5 O'qib chiqdim: %d ta audio, %d tasi albomlarga joylandi.\n\n%s%s" % (
            n, joy, summary_text(), ("\n\nO'tkazib yuborilgan xabarlar:\n" + izoh) if izoh else ""))
    except Exception as e:
        logging.error("Musiqa skaneri to'xtadi: %s", e)
        try:
            await _say("❌ O'qish to'xtadi: %s\nQayta /musiqa yozsangiz boshidan boshlaydi." % e)
        except Exception:
            pass
    finally:
        _scan_task = None


def _auto_scan():
    global _scan_task
    if _scan_task and not _scan_task.done():
        return
    th = _data.get("thread")
    logging.info("Soundtrack: xom nusxa yo'q — mavzuni o'zim qayta o'qiyman")
    _scan_task = asyncio.create_task(_scan_job(_data["group"], (th or 0) + 1, _data["up_to"]))


def _is_admin(message):
    u = message.from_user
    if u and u.id in _cfg.get("admin_ids", ()):
        return True
    # guruhga "anonim admin" bo'lib yozganlar
    return bool(message.sender_chat and message.sender_chat.id == message.chat.id)


async def on_music_command(message: types.Message):
    global _scan_task
    if not _is_admin(message):
        return
    if "muqova" in (message.text or "").lower():
        _start_covers(force=True)
        await message.reply("\U0001f5bc Albom muqovalarini qayta olyapman.")
        return
    if message.chat.type == "private":
        g = _data.get("group")
        await message.answer(("Guruh: %s, mavzu: %s\n\n%s" % (g, _data.get("thread"), summary_text())) if g else
                             "Guruh hali ulanmagan: botni guruhga admin qilib, Soundtrack mavzusida /musiqa yozing.")
        return
    if message.chat.type != "supergroup":
        await message.reply("Bu buyruq superguruhda ishlaydi.")
        return
    if _scan_task and not _scan_task.done():
        await message.reply("O'qish allaqachon ketmoqda.")
        return
    thread = message.message_thread_id if message.is_topic_message else None
    async with _lock:
        _data.update({"group": message.chat.id, "thread": thread, "up_to": message.message_id})
        _save()
    start = (thread or 0) + 1
    upto = message.message_id
    daq = max(1, round((upto - start) * (SCAN_PACE + 0.5) / 60))
    await message.reply("\U0001f50e Soundtrack mavzusini o'qiyapman (~%d daq). Guruhga hech narsa "
                        "yozilmaydi; bot bilan shaxsiy chatingizda xabarlar bir lahza ko'rinib o'chadi." % daq)
    _scan_task = asyncio.create_task(_scan_job(message.chat.id, start, upto))


# --- ALBOM MUQOVALARI ---
# Guruhdagi albom sarlavhasi (rasm + izoh) rasmidan; rasm bo'lmasa birinchi
# trek faylining ichidagi muqovadan. Serverda saqlanadi, ilova
# /api/music/cover/<albom>.jpg dan oladi. Yangi albom qo'shilsa o'zi olinadi.

COVER_DIR = "/data/ost"
_cover_task = None


def cover_path(album):
    return os.path.join(COVER_DIR, album + ".jpg")


def _best_photo(sizes, want=640):
    """Rasmning ~640px li o'lchami (katta bo'lsa ham, kichigi bo'lsa ham eng yaqini)."""
    if not sizes:
        return None
    big = [p for p in sizes if min(p.width, p.height) >= want]
    return (min(big, key=lambda p: p.width) if big else max(sizes, key=lambda p: p.width)).file_id


def _missing_covers():
    return [a for a in ORDER if tracks(a) and not os.path.exists(cover_path(a))]


async def fetch_covers(force=False):
    """Muqovasi yo'q albomlar uchun rasm oladi. Olinganlar sonini qaytaradi."""
    bot = _cfg["bot"]
    todo = [a for a in ORDER if tracks(a)] if force else _missing_covers()
    if not todo or not _data.get("group"):
        return 0
    inbox, note = await _inbox(bot, "\U0001f5bc Albom muqovalarini olyapman — bu yerda bir lahza "
                               "xabarlar ko'rinib o'chadi.")
    if not inbox:
        return 0
    os.makedirs(COVER_DIR, exist_ok=True)
    olindi = 0
    for album in todo:
        try:
            fid = None
            head = (_data.get("heads") or {}).get(album)
            if head:
                m = await _peek(bot, _data["group"], head, inbox)
                if m is not None and getattr(m, "photo", None):
                    fid = _best_photo(m.photo)
            if not fid:
                m = await _peek(bot, _data["group"], tracks(album)[0]["mid"], inbox)
                th = getattr(m.audio, "thumbnail", None) if m is not None and m.audio else None
                if th:
                    fid = th.file_id
            if not fid:
                logging.warning("Soundtrack: %s muqovasi topilmadi", album)
                continue
            tmp = cover_path(album) + ".tmp"
            await _tg(bot.download, fid, destination=tmp)
            os.replace(tmp, cover_path(album))
            olindi += 1
        except Exception as e:
            logging.error("Soundtrack: %s muqovasi olinmadi: %s", album, e)
        await asyncio.sleep(SCAN_PACE)
    try:
        await bot.delete_message(inbox, note)
    except Exception:
        pass
    logging.info("Soundtrack: %d ta muqova olindi", olindi)
    return olindi


async def _cover_job(force=False):
    global _cover_task
    try:
        await fetch_covers(force)
    except Exception as e:
        logging.error("Soundtrack muqovalari: %s", e)
    finally:
        _cover_task = None


def _start_covers(force=False):
    global _cover_task
    if _cover_task and not _cover_task.done():
        return
    _cover_task = asyncio.create_task(_cover_job(force))


def _cover_ver(album):
    try:
        return int(os.path.getmtime(cover_path(album)))
    except OSError:
        return None


async def api_cover(request):
    album = request.match_info.get("album", "")
    if album not in ALBUMS or not os.path.exists(cover_path(album)):
        return web.Response(status=404)
    return web.FileResponse(cover_path(album), headers={
        "Cache-Control": "public, max-age=2592000", "Access-Control-Allow-Origin": "*"})


# --- ILOVA UCHUN KALIT ---
# <audio> teg sarlavha yubora olmaydi, shuning uchun imzo manzilga qo'yiladi.
# Kalitda ism yoki initData YO'Q: faqat raqam, muddat va imzo.

def _secret():
    return hashlib.sha256(b"hp-music|" + (_cfg.get("token") or "").encode()).digest()


def make_key(user_id, now=None):
    exp = int((now or time.time()) + KEY_TTL)
    body = "%d.%d" % (int(user_id), exp)
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:24]
    return "%s.%s" % (body, sig)


def check_key(key, now=None):
    """To'g'ri kalit bo'lsa foydalanuvchi raqamini, aks holda None qaytaradi."""
    try:
        uid, exp, sig = str(key).split(".")
        body = "%s.%s" % (uid, exp)
        good = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:24]
        if not hmac.compare_digest(good, sig):
            return None
        if int(exp) < (now or time.time()):
            return None
        return int(uid)
    except Exception:
        return None


# --- OQIM (STREAM) ---

def _http():
    global _session
    if _session is None or _session.closed:
        _session = aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(
            total=None, connect=15, sock_read=60))
    return _session


async def _file_url(fid, fresh=False):
    hit = _paths.get(fid)
    if hit and not fresh and time.time() - hit[1] < PATH_TTL:
        path = hit[0]
    else:
        f = await _cfg["bot"].get_file(fid)
        path = f.file_path
        _paths[fid] = (path, time.time())
    return _cfg["file_base"] + path


_RANGE = re.compile(r"^bytes=(\d*)-(\d*)$")


def parse_range(header, size):
    """'bytes=a-b' -> (start, end) yoki None (butun fayl). Noto'g'ri bo'lsa ValueError."""
    if not header:
        return None
    m = _RANGE.match(header.strip())
    if not m or (not m.group(1) and not m.group(2)):
        raise ValueError(header)
    if m.group(1):
        start = int(m.group(1))
        end = int(m.group(2)) if m.group(2) else size - 1
    else:                      # "bytes=-500" — oxirgi 500 bayt
        start = max(0, size - int(m.group(2)))
        end = size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        raise ValueError(header)
    return start, end


async def api_stream(request):
    uid = check_key(request.query.get("k", ""))
    album = request.match_info.get("album", "")
    try:
        idx = int(request.match_info.get("n", "0")) - 1
    except ValueError:
        idx = -1
    if uid is None:
        return web.Response(status=403, text="key")
    lst = tracks(album)
    if not (0 <= idx < len(lst)) or not album_open(uid, album):
        return web.Response(status=404, text="track")
    tr = lst[idx]
    size = tr["s"]
    if size > BOT_API_LIMIT:
        return web.Response(status=413, text="big")

    try:
        rng = parse_range(request.headers.get("Range"), size) if size else None
    except ValueError:
        return web.Response(status=416, headers={"Content-Range": "bytes */%d" % size})

    # Fayl boshidan so'ralsa — tinglash boshlandi (o'rtasidan = o'tkazib yuborish, sanalmaydi)
    if request.method == "GET" and (rng is None or rng[0] == 0):
        await note_play(uid, tr["fuid"])

    base_headers = {
        "Content-Type": tr.get("mime") or "audio/mpeg",
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=86400",
        # nginx oqimni o'zida to'plamasin (diskka vaqtinchalik fayl yozmasin)
        "X-Accel-Buffering": "no",
    }

    if request.method == "HEAD":
        h = dict(base_headers)
        h["Content-Length"] = str(size)
        return web.Response(status=200, headers=h)

    up_headers = {}
    if rng:
        up_headers["Range"] = "bytes=%d-%d" % rng

    up = None
    for urinish in (0, 1):
        try:
            url = await _file_url(tr["fid"], fresh=bool(urinish))
            up = await _http().get(url, headers=up_headers)
        except Exception as e:
            logging.warning("Musiqa manbasi ochilmadi (%s/%s): %s", album, idx + 1, e)
            up = None
            continue
        if up.status in (200, 206):
            break
        up.release()
        up = None          # manzil eskirgan bo'lishi mumkin — yangisini so'raymiz
    if up is None:
        return web.Response(status=502, text="upstream")

    try:
        # Telegram diapazonni bajarmasa (200 qaytarsa) — o'zimiz kesamiz.
        skip = 0
        if rng:
            start, end = rng
            if up.status == 200:
                skip = start
            status = 206
            length = end - start + 1
            extra = {"Content-Range": "bytes %d-%d/%d" % (start, end, size)}
        else:
            status = 200
            length = size or None
            extra = {}

        resp = web.StreamResponse(status=status, headers=dict(base_headers, **extra))
        if length:
            resp.content_length = length
        await resp.prepare(request)

        left = length
        async for chunk in up.content.iter_chunked(64 * 1024):
            if skip:
                if len(chunk) <= skip:
                    skip -= len(chunk)
                    continue
                chunk = chunk[skip:]
                skip = 0
            if left is not None:
                if left <= 0:
                    break
                chunk = chunk[:left]
                left -= len(chunk)
            await resp.write(chunk)
        await resp.write_eof()
        return resp
    except (ConnectionResetError, asyncio.CancelledError):
        raise          # tinglovchi o'tkazib yubordi yoki yopdi — odatiy hol
    finally:
        up.release()


# --- LIKE'LAR ---
# Asosiy bazada (hp.db — har kungi zaxiraga tushadi). Trek fayl raqami (fuid)
# bo'yicha: albomlar qayta hisoblansa ham like'lar o'z trekida qoladi.
# Umumiy son faqat HAQIQIY odamlardan (user_id > 0); sinov o'quvchisi
# o'z like'ini ko'radi, lekin u hech kimning soniga qo'shilmaydi.

DB_PATH = os.getenv("HP_DB_PATH", "/data/hp.db")
LIKE_LIMIT = (30, 60)        # bir odam 60 soniyada 30 tadan ortiq bosa olmaydi
_likes = {}                  # fuid -> son
_like_hits = {}              # user_id -> [vaqtlar]


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


def _init_likes():
    conn = _db()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS music_likes ("
                     "fuid TEXT NOT NULL, user_id INTEGER NOT NULL, created_at INTEGER NOT NULL, "
                     "PRIMARY KEY (fuid, user_id))")
        # Ilovada tinglash: bir odam bitta trekni PLAY_GAP ichida qayta boshlasa — bitta tinglash
        conn.execute("CREATE TABLE IF NOT EXISTS music_plays ("
                     "fuid TEXT NOT NULL, user_id INTEGER NOT NULL, ts INTEGER NOT NULL)")
        conn.execute("CREATE INDEX IF NOT EXISTS music_plays_ts ON music_plays(ts)")
        # Galleonga ochilgan albomlar (bir marta sotiladi, doim ochiq)
        conn.execute("CREATE TABLE IF NOT EXISTS album_egasi ("
                     "user_id INTEGER NOT NULL, album TEXT NOT NULL, narx INTEGER NOT NULL, "
                     "vaqt INTEGER NOT NULL, PRIMARY KEY (user_id, album))")
        conn.commit()
        rows = conn.execute("SELECT fuid, COUNT(*) FROM music_likes WHERE user_id > 0 "
                            "GROUP BY fuid").fetchall()
    finally:
        conn.close()
    _likes.clear()
    _likes.update({f: n for f, n in rows})


def _my_likes(uid):
    conn = _db()
    try:
        return {r[0] for r in conn.execute("SELECT fuid FROM music_likes WHERE user_id = ?", (uid,))}
    finally:
        conn.close()


def _set_like(uid, fuid, on):
    """Like qo'yadi/oladi. O'zgargan bo'lsa True."""
    conn = _db()
    try:
        if on:
            cur = conn.execute("INSERT OR IGNORE INTO music_likes (fuid, user_id, created_at) "
                               "VALUES (?, ?, ?)", (fuid, uid, int(time.time())))
        else:
            cur = conn.execute("DELETE FROM music_likes WHERE fuid = ? AND user_id = ?", (fuid, uid))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


PLAY_GAP = 30 * 60
_play_seen = {}              # (user_id, fuid) -> oxirgi yozilgan vaqt


def _add_play(uid, fuid, ts):
    conn = _db()
    try:
        conn.execute("INSERT INTO music_plays (fuid, user_id, ts) VALUES (?, ?, ?)", (fuid, uid, ts))
        conn.commit()
    finally:
        conn.close()


async def note_play(uid, fuid):
    """Tinglash boshlandi (fayl boshidan so'raldi). Faqat haqiqiy odamlar."""
    if uid is None or uid <= 0:
        return
    now = int(time.time())
    key = (uid, fuid)
    if now - _play_seen.get(key, 0) < PLAY_GAP:
        return
    _play_seen[key] = now
    if len(_play_seen) > 20000:          # xotira o'smasin
        eski = now - PLAY_GAP
        for k in [k for k, v in _play_seen.items() if v < eski]:
            _play_seen.pop(k, None)
    try:
        await asyncio.to_thread(_add_play, uid, fuid, now)
    except Exception as e:
        logging.error("Tinglash yozilmadi: %s", e)


def _stat_rows():
    conn = _db()
    try:
        plays = conn.execute("SELECT fuid, user_id, ts FROM music_plays ORDER BY ts").fetchall()
        likes = conn.execute("SELECT fuid, user_id, created_at FROM music_likes WHERE user_id > 0 "
                             "ORDER BY created_at").fetchall()
    finally:
        conn.close()
    return plays, likes


async def api_stat(request):
    """Kuzatuv paneli uchun: albomlar/treklar, tinglashlar va like'lar (vaqti, kim)."""
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    if not _cfg.get("dash_ok", lambda r: False)(request):
        return cors(web.json_response({"ok": False, "error": "bad_token"}, status=403))
    where = {}
    albums = []
    for key in ORDER:
        lst = tracks(key)
        if not lst:
            continue
        for i, x in enumerate(lst):
            where[x["fuid"]] = (key, i + 1)
        albums.append({"id": key, "name": album_title(key, "uz"), "composer": ALBUMS[key]["composer"],
                       "year": ALBUMS[key]["year"], "tracks": [{"t": x["t"], "d": x["d"]} for x in lst]})
    try:
        plays, likes = await asyncio.to_thread(_stat_rows)
    except Exception as e:
        logging.error("Musiqa statistikasi o'qilmadi: %s", e)
        return cors(web.json_response({"ok": False, "error": "server"}, status=500))
    def pack(rows):
        out = []
        for fuid, uid, ts in rows:
            w = where.get(fuid)
            if w:
                out.append([ts, str(uid), w[0], w[1]])
        return out
    return cors(web.json_response({"ok": True, "albums": albums, "plays": pack(plays), "likes": pack(likes)}))


def _shown(fuid, uid, mine):
    """Ko'rinadigan son: sinov o'quvchisi o'z like'ini ham ko'rsin."""
    n = _likes.get(fuid, 0)
    return n + 1 if (mine and uid is not None and uid < 0) else n


# --- RO'YXAT VA TELEGRAMGA YUBORISH ---

def _public_list(uid=None, mine=frozenset()):
    out = {}
    for key in ORDER:
        lst = tracks(key)
        if not lst:
            continue
        out[key] = {
            "year": ALBUMS[key]["year"],
            "composer": ALBUMS[key]["composer"],
            "cv": _cover_ver(key),
            "open": album_open(uid, key),
            "tracks": [{"t": x["t"], "d": x["d"], "big": x["s"] > BOT_API_LIMIT,
                        "l": _shown(x["fuid"], uid, x["fuid"] in mine),
                        "me": x["fuid"] in mine} for x in lst],
        }
    return out


async def api_list(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    user = _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", ""))
    uid, mine = None, frozenset()
    if user:
        uid = int(user["id"])
        try:
            mine = await asyncio.to_thread(_my_likes, uid)
        except Exception as e:
            logging.error("Musiqa like'lari o'qilmadi: %s", e)
    body = {"ok": True, "albums": _public_list(uid, mine), "price": ALBUM_PRICE}
    if user:
        body["key"] = make_key(uid)
        body["gal"] = await asyncio.to_thread(_galleons, uid)
    return cors(web.json_response(body))


async def api_like(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    if request.method != "POST":
        return cors(web.json_response({"ok": False, "error": "method"}, status=405))
    try:
        body = await request.json()
    except Exception:
        return cors(web.json_response({"ok": False, "error": "bad_json"}, status=400))
    user = _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", "")
                                    or str(body.get("initData", "")))
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
    uid = int(user["id"])
    lst = tracks(str(body.get("album", "")))
    try:
        n = int(body.get("track"))
    except (TypeError, ValueError):
        n = 0
    if not (1 <= n <= len(lst)):
        return cors(web.json_response({"ok": False, "error": "unknown"}, status=404))
    fuid = lst[n - 1]["fuid"]

    now = time.time()
    hits = [t for t in _like_hits.get(uid, []) if now - t < LIKE_LIMIT[1]]
    if len(hits) >= LIKE_LIMIT[0]:
        return cors(web.json_response({"ok": False, "error": "slow"}))
    hits.append(now)
    _like_hits[uid] = hits

    on = bool(body.get("on"))
    try:
        changed = await asyncio.to_thread(_set_like, uid, fuid, on)
    except Exception as e:
        logging.error("Musiqa like'i yozilmadi: %s", e)
        return cors(web.json_response({"ok": False, "error": "server"}, status=500))
    if changed and uid > 0:
        _likes[fuid] = max(0, _likes.get(fuid, 0) + (1 if on else -1))
    return cors(web.json_response({"ok": True, "me": on, "l": _shown(fuid, uid, on)}))


async def api_send(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    if request.method != "POST":
        return cors(web.json_response({"ok": False, "error": "method"}, status=405))
    try:
        body = await request.json()
    except Exception:
        return cors(web.json_response({"ok": False, "error": "bad_json"}, status=400))

    user = _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", "")
                                    or str(body.get("initData", "")))
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
    uid = int(user["id"])
    album = str(body.get("album", ""))
    lst = tracks(album)
    if not lst:
        return cors(web.json_response({"ok": False, "error": "unknown"}, status=404))
    if not album_open(uid, album):
        return cors(web.json_response({"ok": False, "error": "locked"}))

    # Ilovada birinchi marta chalinganini statistikaga yozish (yuborish emas)
    if body.get("action") == "play":
        if uid > 0:
            await _cfg["log"](user, "music_play_" + album)
        return cors(web.json_response({"ok": True}))

    now = time.time()
    if now - _last_send.get(uid, 0) < SEND_GAP:
        return cors(web.json_response({"ok": False, "error": "slow"}))
    _last_send[uid] = now

    n = body.get("track")
    if n is not None:
        try:
            n = int(n)
        except (TypeError, ValueError):
            n = -1
        if not (1 <= n <= len(lst)):
            return cors(web.json_response({"ok": False, "error": "unknown"}, status=404))
        mids = [lst[n - 1]["mid"]]
    else:
        mids = [x["mid"] for x in lst]

    chat = _cfg["tg_chat_id"](uid)
    if await _cfg["is_subscribed"](chat) is False:
        return cors(web.json_response({"ok": False, "error": "not_subscribed"}))

    if _sending.get(uid):
        return cors(web.json_response({"ok": False, "error": "slow"}))
    bot = _cfg["bot"]
    # Fayl raqami (file_id) bilan, har trek ALOHIDA xabar (guruhlanmaydi), filmlar kabi himoyalangan.
    # Birinchisini shu yerda yuboramiz (bot bloklangan bo'lsa darhol bilinadi), qolganlari orqada.
    idx = [i for i, x in enumerate(lst) if x["mid"] in mids]
    lang = str(body.get("lang") or "")
    if lang not in CAP and _cfg.get("user_lang"):
        try:
            lang = await _cfg["user_lang"](chat) or "uz"
        except Exception:
            lang = "uz"
    try:
        await send_track(chat, album, idx[0], lang, caption=len(idx) == 1)
    except Exception as e:
        logging.error("Musiqa yuborilmadi (%s): %s", album, e)
        return cors(web.json_response({"ok": False, "error": "send_failed"}))
    if len(idx) > 1:
        _sending[uid] = True
        asyncio.create_task(_send_rest(uid, chat, album, idx[1:], lang))

    if uid > 0:
        await _cfg["log"](user, "music_%s%s" % (album, "_%d" % n if n else ""))
    return cors(web.json_response({"ok": True, "count": len(mids)}))


_sending = {}                # user_id -> albom hali yuborilmoqda

# Trek ostidagi yozuv (film kartasi uslubida). Custom emoji faqat bor belgilar
# uchun (yil, vaqt, tasdiq); musiqa belgisi to'plamda yo'q — oddiy emoji.
CAP = {
    "uz": {"kick": "Filmning asl musiqasi", "trek": "Trek", "komp": "Kompozitor", "yil": "Yil",
           "vaqt": "Davomiyligi", "like": "Yoqdi"},
    "ru": {"kick": "Оригинальный саундтрек", "trek": "Трек", "komp": "Композитор", "yil": "Год",
           "vaqt": "Длительность", "like": "Нравится"},
    "en": {"kick": "Original motion picture soundtrack", "trek": "Track", "komp": "Composer",
           "yil": "Year", "vaqt": "Duration", "like": "Likes"},
}
COMPOSER_NAME = {
    "John Williams": {"uz": "Jon Uilyams", "ru": "Джон Уильямс"},
    "Patrick Doyle": {"uz": "Patrik Doyl", "ru": "Патрик Дойл"},
    "Nicholas Hooper": {"uz": "Nikolas Xuper", "ru": "Николас Хупер"},
    "Alexandre Desplat": {"uz": "Aleksandr Despla", "ru": "Александр Деспла"},
}
APP_LINK = "https://t.me/garripotterkinobot/catalog?startapp=ost_%s"


def album_title(album, lang):
    """"Garri Potter va Hikmatlar Toshi" — katalogdagi film nomidan (raqam va teglarsiz)."""
    try:
        cap = catalog.FILMS[ALBUMS[album]["film"]][lang]["caption"]
    except KeyError:
        return album
    cap = re.sub(r"<[^>]+>", "", cap)
    return re.sub(r"^\s*\d+\.\s*", "", cap).strip()


def track_caption(album, i, lang):
    """i — 0 dan boshlanadigan trek tartibi."""
    lang = lang if lang in CAP else "uz"
    c, lst = CAP[lang], tracks(album)
    tr = lst[i]
    comp = ALBUMS[album]["composer"]
    comp = COMPOSER_NAME.get(comp, {}).get(lang, comp)
    esc = lambda x: x.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    lines = [
        "<b>%s</b>" % esc(album_title(album, lang)),
        "<i>%s</i>" % c["kick"],
        "— — — — — — — — — —",
        "\U0001f3bc %s: %d / %d" % (c["trek"], i + 1, len(lst)),
        "\U0001f464 %s: %s" % (c["komp"], esc(comp)),
        "%s %s: %s" % (emoji.tag("yil"), c["yil"], ALBUMS[album]["year"]),
    ]
    if tr["d"]:
        lines.append("%s %s: %s" % (emoji.tag("vaqt"), c["vaqt"], _fmt_dur(tr["d"])))
    likes = _likes.get(tr["fuid"], 0)
    if likes:
        lines.append("\u2764\ufe0f %s: %d" % (c["like"], likes))
    brand = _cfg.get("brand", lambda l: "GARRI POTTER KOLLEKSIYA")(lang)
    lines += ["", '%s <b><a href="%s">%s</a></b>' % (emoji.tag("tasdiq"), APP_LINK % album, brand)]
    return "\n".join(lines)


async def send_track(chat, album, i, lang, caption=True):
    """Trekni yuboradi. Yozuv faqat BITTA trek so'ralganda (foydalanuvchi qarori:
    butun albom yozuvsiz keladi — 20 ta bir xil matn chatni to'ldirib yuboradi).
    Custom emoji rad etilsa — oddiy belgilar bilan."""
    bot = _cfg["bot"]
    fid = tracks(album)[i]["fid"]
    if not caption:
        return await _tg(bot.send_audio, chat, fid, protect_content=True)
    cap = track_caption(album, i, lang)
    try:
        return await _tg(bot.send_audio, chat, fid, caption=cap, parse_mode="HTML", protect_content=True)
    except TelegramBadRequest as e:
        logging.warning("Trek yozuvi custom emoji bilan o'tmadi (%s): %s", chat, e)
        return await _tg(bot.send_audio, chat, fid, caption=emoji.strip_tags(cap), parse_mode="HTML",
                         protect_content=True)


async def _send_rest(uid, chat, album, idx, lang):
    try:
        for i in idx:
            await asyncio.sleep(SEND_PACE)
            await send_track(chat, album, i, lang, caption=False)
    except Exception as e:
        logging.error("Albom oxirigacha yuborilmadi (%s -> %s): %s", album, chat, e)
    finally:
        _sending.pop(uid, None)


# --- ULASH ---

def register(dp, bot, app, cfg):
    """cfg: token, admin_ids, verify_init_data, cors, is_subscribed,
    tg_chat_id, log (async (user_dict, payload))."""
    global _lock
    _cfg.update(cfg)
    _cfg["bot"] = bot
    _cfg.setdefault("file_base", "https://api.telegram.org/file/bot%s/" % cfg["token"])
    _lock = asyncio.Lock()
    load()
    load_raw()
    try:
        _init_likes()
    except Exception as e:
        logging.error("Musiqa like jadvali ochilmadi: %s", e)
    if _raw:
        rebuild()                 # qoida o'zgargan bo'lsa ham albomlar yangi qoida bilan
        _save()
    elif _data.get("group"):
        if not _data.get("up_to"):
            # eski yozuvda chegara yo'q: ma'lum oxirgi trekdan keyin yana 40 ta xabar
            mids = [x["mid"] for lst in _data["albums"].values() for x in lst]
            _data["up_to"] = (max(mids) + 40) if mids else None
        if _data.get("up_to"):
            asyncio.get_event_loop().call_later(30, _auto_scan)
    dp.message.register(on_music_command, Command("musiqa"))
    dp.message.register(on_group_message, _in_topic)
    app.router.add_route("*", "/api/music", api_list)
    app.router.add_route("*", "/api/music/send", api_send)
    app.router.add_route("*", "/api/music/like", api_like)
    app.router.add_route("*", "/api/music/buy", api_buy)
    app.router.add_route("*", "/api/musiqa", api_stat)       # kuzatuv paneli (X-Dash-Token)
    app.router.add_get("/api/music/a/{album}/{n}", api_stream)
    app.router.add_get("/api/music/cover/{album}.jpg", api_cover)
    if _raw and _data.get("group") and _missing_covers():
        asyncio.get_event_loop().call_later(40, _start_covers)
    logging.info("Soundtrack: %d ta albom tayyor", len(_public_list()))
