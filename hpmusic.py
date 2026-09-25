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

NARX: HOZIRCHA BEPUL (galleon tizimi tayyor emas). Keyin butun albom
galleonga bir marta sotib olinadi — tekshiruv `album_open()` da bo'ladi.
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import time

import aiohttp
import types as _pytypes
from aiohttp import web
from aiogram import types
from aiogram.filters import Command
from aiogram.exceptions import (TelegramBadRequest, TelegramForbiddenError,
                                TelegramNetworkError, TelegramRetryAfter)
from aiogram.types import InputMediaAudio

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
    for it in _raw:
        see(it["mid"], it.get("x") or "", _audio_obj(it["a"]) if it.get("a") else None)


def tracks(album):
    return _data["albums"].get(album, [])


def album_open(user_id, album):
    """Albom shu odamga ochiqmi. HOZIRCHA hammaga bepul.

    Galleon tizimi tayyor bo'lganda shu yerda sotib olinganini tekshiramiz
    (butun albom bir marta sotiladi, trek alohida emas).
    """
    return album in ALBUMS


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


async def _inbox(bot):
    """Nusxalar boradigan admin chati: bot yoza oladigan birinchi admin."""
    for uid in sorted(_cfg.get("admin_ids", ())):
        try:
            m = await _tg(bot.send_message, uid, "\U0001f3b5 Soundtrack mavzusini o'qiyapman — "
                          "bu yerda bir lahza xabarlar ko'rinib o'chadi.", disable_notification=True)
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


# --- RO'YXAT VA TELEGRAMGA YUBORISH ---

def _public_list():
    out = {}
    for key in ORDER:
        lst = tracks(key)
        if not lst:
            continue
        out[key] = {
            "year": ALBUMS[key]["year"],
            "composer": ALBUMS[key]["composer"],
            "tracks": [{"t": x["t"], "d": x["d"], "big": x["s"] > BOT_API_LIMIT} for x in lst],
        }
    return out


async def api_list(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    user = _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", ""))
    body = {"ok": True, "albums": _public_list(), "price": 0}
    if user:
        body["key"] = make_key(user["id"])
    return cors(web.json_response(body))


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

    bot = _cfg["bot"]
    try:
        # fayl raqami (file_id) bilan: guruhda "nusxalashni taqiqlash" yoqilsa ham ishlaydi.
        # Albom 10 talik to'plamlarda (media group) — chatda bitta blok bo'lib turadi.
        items = [x for x in lst if x["mid"] in mids]
        if len(items) == 1:
            await _tg(bot.send_audio, chat, items[0]["fid"], protect_content=True)
        else:
            for i in range(0, len(items), 10):
                part = items[i:i + 10]
                if len(part) == 1:
                    await _tg(bot.send_audio, chat, part[0]["fid"], protect_content=True)
                else:
                    await _tg(bot.send_media_group, chat, [InputMediaAudio(media=x["fid"]) for x in part],
                              protect_content=True)
    except Exception as e:
        logging.error("Musiqa yuborilmadi (%s): %s", album, e)
        return cors(web.json_response({"ok": False, "error": "send_failed"}))

    if uid > 0:
        await _cfg["log"](user, "music_%s%s" % (album, "_%d" % n if n else ""))
    return cors(web.json_response({"ok": True, "count": len(mids)}))


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
    app.router.add_get("/api/music/a/{album}/{n}", api_stream)
    logging.info("Soundtrack: %d ta albom tayyor", len(_public_list()))
