# -*- coding: utf-8 -*-
"""Soundtrack kutubxonasi — filmlar musiqasi.

Fayllar filmlar kabi YOPIQ kanalda (DB_CHANNEL_ID) turadi. Serverga ham,
GitHub'ga ham qo'yilmaydi: server ularni Telegramdan olib, tinglovchiga
oqim bilan uzatib turadi xolos (serverda joy va xotira juda kam).

Albom qanday qo'shiladi (admin uchun, qo'lda raqam yozish shart emas):

    1. Yopiq kanalga `#hp1` deb yozing (qaysi albom ekanini bildiradi).
    2. O'sha albomning audio fayllarini kanalga tashlang.
    3. Bot ularni o'zi ushlab, `/data/music.json` ga yozadi va bir necha
       soniyadan keyin kanalga "hp1: 19 ta trek" deb hisobot beradi.

    `#hp1 tozala` — albomni bo'shatadi (xato fayl tushsa qaytadan yuklash uchun).

Trek tartibi fayl nomidagi yoki sarlavhadagi boshlang'ich raqamdan olinadi
("03 - Harry's Wondrous World.mp3"); raqam bo'lmasa — kanaldagi tartib.

Tinglash ikki yo'l bilan:
    * ilova ichida — `GET /api/music` ro'yxat + vaqtinchalik kalit beradi,
      `GET /api/music/a/<albom>/<n>?k=<kalit>` faylni oqim bilan uzatadi;
    * Telegramga — `POST /api/music/send` albomni yoki bitta trekni chatga
      nusxalaydi (filmlar kabi protect_content bilan).

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
from aiohttp import web
from aiogram import F, types

STORE = "/data/music.json"   # MUTLAQ yo'l: faqat /data konteynerdan tashqarida yashaydi

# Albomlar tartibi va ma'lumoti. Nomlar ilovada catalog'dagi film nomidan olinadi.
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

KEY_TTL = 12 * 3600          # ilovadagi tinglash kaliti shuncha amal qiladi
PATH_TTL = 50 * 60           # Telegram fayl manzili ~1 soat yashaydi
SEND_GAP = 4                 # bir odam Telegramga yuborish orasidagi soniya
REPORT_DELAY = 8             # oxirgi fayldan keyin hisobot kutish
BOT_API_LIMIT = 20 * 1024 * 1024   # bot bundan katta faylni yuklab ololmaydi

_cfg = {}
_data = {"albums": {}, "current": None}
_paths = {}                  # file_id -> (file_path, vaqt)
_last_send = {}              # user_id -> vaqt
_report_tasks = {}           # albom -> asyncio.Task
_session = None
_lock = None                 # asyncio.Lock — ishga tushganda yaratiladi


# --- SAQLASH ---

def load():
    global _data
    try:
        with open(STORE, encoding="utf-8") as f:
            d = json.load(f)
        d.setdefault("albums", {})
        d.setdefault("current", None)
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


def tracks(album):
    return _data["albums"].get(album, [])


def album_open(user_id, album):
    """Albom shu odamga ochiqmi. HOZIRCHA hammaga bepul.

    Galleon tizimi tayyor bo'lganda shu yerda sotib olinganini tekshiramiz
    (butun albom bir marta sotiladi, trek alohida emas).
    """
    return album in ALBUMS


# --- KANALDAN FAYLLARNI USHLASH ---

_NUM = re.compile(r"^\s*(?:cd\s*\d+\s*[-_.]\s*)?(\d{1,3})(?!\d)\s*[-_.)\]]*\s*", re.I)
_MARK = re.compile(r"^\s*#(hp[1-8])\b\s*(tozala|clear)?", re.I)


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
    t = _NUM.sub("", t, count=1) if _NUM.match(t) else t
    return (t.replace("_", " ").strip() or "Track")[:120]


def _sort(album):
    lst = _data["albums"].get(album, [])
    lst.sort(key=lambda x: (x.get("n") if x.get("n") is not None else 10 ** 6, x["mid"]))


def add_audio(album, message_id, audio):
    """Albomga trek qo'shadi. Xuddi shu fayl qayta tushsa — yangilanadi."""
    lst = _data["albums"].setdefault(album, [])
    lst[:] = [x for x in lst if x["fuid"] != audio.file_unique_id]
    lst.append({
        "mid": message_id,
        "fid": audio.file_id,
        "fuid": audio.file_unique_id,
        "n": _track_num(audio.file_name, audio.title),
        "t": _clean_title(audio),
        "d": int(audio.duration or 0),
        "s": int(audio.file_size or 0),
        "mime": audio.mime_type or "audio/mpeg",
    })
    _sort(album)


def _fmt_dur(sec):
    h, m = divmod(sec // 60, 60)
    return ("%d:%02d:%02d" % (h, m, sec % 60)) if h else ("%d:%02d" % (m, sec % 60))


def _report_text(album):
    lst = tracks(album)
    jami = sum(x["d"] for x in lst)
    katta = [x for x in lst if x["s"] > BOT_API_LIMIT]
    qator = ["✅ %s: %d ta trek, %s" % (album, len(lst), _fmt_dur(jami))]
    for i, x in enumerate(lst, 1):
        qator.append("%d. %s (%s)" % (i, x["t"], _fmt_dur(x["d"])))
    if katta:
        qator.append("")
        qator.append("⚠️ 20 MB dan katta %d ta fayl ilovada chalinmaydi "
                     "(faqat Telegramga yuboriladi)." % len(katta))
    return "\n".join(qator)[:4000]


async def _report_later(album):
    try:
        await asyncio.sleep(REPORT_DELAY)
        await _cfg["bot"].send_message(_cfg["db_channel_id"], _report_text(album))
    except asyncio.CancelledError:
        pass
    except Exception as e:
        logging.error("Musiqa hisoboti yuborilmadi: %s", e)


def _schedule_report(album):
    old = _report_tasks.get(album)
    if old and not old.done():
        old.cancel()
    _report_tasks[album] = asyncio.create_task(_report_later(album))


async def on_channel_post(message: types.Message):
    if message.chat.id != _cfg["db_channel_id"]:
        return
    bot = _cfg["bot"]

    text = message.text or message.caption or ""
    mark = _MARK.match(text)
    if mark:
        album = mark.group(1).lower()
        async with _lock:
            _data["current"] = album
            if mark.group(2):
                _data["albums"][album] = []
            _save()
        izoh = ("\U0001f5d1 %s tozalandi. " % album) if mark.group(2) else ""
        await bot.send_message(message.chat.id, "\U0001f3b5 %sEndi yuborilgan audio fayllar "
                               "%s albomiga yoziladi." % (izoh, album))
        # Albom belgisi bilan birga fayl ham kelgan bo'lishi mumkin (izohli audio)
        if not message.audio:
            return

    audio = message.audio
    if not audio:
        doc = message.document
        if doc and (doc.mime_type or "").startswith("audio/"):
            await bot.send_message(message.chat.id, "\u26a0\ufe0f %s hujjat (fayl) bo'lib "
                                   "tushdi. Uni musiqa sifatida qayta yuboring." % (doc.file_name or ""))
        return
    async with _lock:
        album = _data.get("current")
        if not album:
            await bot.send_message(message.chat.id, "⚠️ Qaysi albom? Avval "
                                   "#hp1 … #hp8 deb yozing, keyin fayllarni qayta tashlang.")
            return
        add_audio(album, message.message_id, audio)
        _save()
    logging.info("Musiqa: %s <- %s (%s)", album, audio.file_name, message.message_id)
    _schedule_report(album)


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
    for key in ALBUMS:
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
        # copyMessages bir so'rovda 100 tagacha, tartibni saqlaydi
        for i in range(0, len(mids), 100):
            await bot.copy_messages(chat_id=chat, from_chat_id=_cfg["db_channel_id"],
                                    message_ids=mids[i:i + 100], protect_content=True)
    except Exception as e:
        logging.error("Musiqa yuborilmadi (%s): %s", album, e)
        return cors(web.json_response({"ok": False, "error": "send_failed"}))

    if uid > 0:
        await _cfg["log"](user, "music_%s%s" % (album, "_%d" % n if n else ""))
    return cors(web.json_response({"ok": True, "count": len(mids)}))


# --- ULASH ---

def register(dp, bot, app, cfg):
    """cfg: token, db_channel_id, verify_init_data, cors, is_subscribed,
    tg_chat_id, log (async (user_dict, payload))."""
    _cfg.update(cfg)
    _cfg["bot"] = bot
    _cfg.setdefault("file_base", "https://api.telegram.org/file/bot%s/" % cfg["token"])
    global _lock
    _lock = asyncio.Lock()
    load()
    dp.channel_post.register(on_channel_post, F.chat.id == cfg["db_channel_id"])
    app.router.add_route("*", "/api/music", api_list)
    app.router.add_route("*", "/api/music/send", api_send)
    app.router.add_get("/api/music/a/{album}/{n}", api_stream)
    logging.info("Soundtrack: %d ta albom tayyor", len(_public_list()))
