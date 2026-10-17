# -*- coding: utf-8 -*-
"""Ilova ichidagi pleyer - film Telegram'dan server orqali OQIM bilan (egasi, 2026-10-17).

Maqsad: bitta film - ichida til (uz/ru/en), dublyaj (MY5 TV / ZO'R TV) va sifat
(Full HD / HD / SD) tugma bilan almashadi; odam 16 ta faylni yuklab olmaydi.
G'oya TelePlay ilovasidan olingan: fayllar Telegram'da qoladi (baza guruhida,
hpfilms.py jadvali), server ularni SAQLAMAYDI - Telegram'dan bo'lakma-bo'lak olib,
shu zahoti pleyerga uzatadi ("ko'prik").

NEGA ALOHIDA ULANISH: Bot API (aiogram) 20 MB dan katta faylni bermaydi. Shuning
uchun bot Telegram'ga ikkinchi marta - MTProto orqali (Telethon kutubxonasi) - O'SHA
bot tokeni bilan ulanadi. Buning uchun Telegram "ilova kaliti" kerak (api_id va
api_hash, my.telegram.org dan). Repolar ochiq - kalit kodga yozilmaydi: admin uni
botning shaxsiy chatida beradi va u /data/pleyer.json da turadi:

    /pleyer                         - holat (ulanish, rejim, trafik)
    /pleyer kalit 1234567 abcdef... - ilova kalitini saqlash (xabar darhol o'chiriladi)
    /pleyer sinov                   - pleyer FAQAT adminlarga (boshlang'ich holat)
    /pleyer ochiq                   - hammaga

Ilova uchun:
    POST /api/pleyer {film}         - shu filmning hamma nusxalari + imzoli kalit
    GET  /api/pleyer/v/<nusxa>?k=   - video oqimi (Range bilan; <video> sarlavha yubora olmaydi -
                                      imzo manzilda, faqat raqam/muddat/imzo, 6 soat)

TRAFIK: har tomosha serverdan o'tadi - kunlik hisob /data/pleyer_stat.json da (/pleyer ko'rsatadi).
"""

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import struct
import time

from aiohttp import web
from aiogram import types
from aiogram.filters import Command

import hpfilms

STORE = "/data/pleyer.json"
STAT = "/data/pleyer_stat.json"
META = "/data/pleyer_meta.json"     # har nusxaning video turi (fayl ichidan bir marta o'qiladi)
SESSION = "/data/pleyer"          # Telethon o'zi ".session" qo'shadi
KEY_TTL = 6 * 3600
REQ = 512 * 1024                  # Telegram'dan bir so'rovda olinadigan bo'lak (eng ko'pi 512 KB)
MSG_TTL = 20 * 60                 # xabar (fayl havolasi) shuncha vaqt eslab qolinadi
STAT_KUN = 30                     # statistika necha kun saqlanadi

_cfg = {}
_data = {"api_id": 0, "api_hash": "", "ochiq": False}
_client = None
_client_lock = asyncio.Lock()
_client_err = ""                  # oxirgi ulanish xatosi (holatda ko'rsatiladi)
_peer = None
_msgs = {}                        # mid -> (xabar, vaqt)
_stat = {}                        # "2026-10-17" -> {"b": bayt, "n": tomosha, "u": [odamlar]}
_stat_dirty = False
_ochiq_oqim = 0                   # hozir uzatilayotgan oqimlar soni
_meta = {}                        # nusxa -> {"s": hajm, "c": video turi, "p": almashtiriladigan joy}
_meta_locks = {}


# --- SAQLASH ---

def load():
    global _data, _stat
    try:
        with open(STORE, encoding="utf-8") as f:
            d = json.load(f)
        for k, v in (("api_id", 0), ("api_hash", ""), ("ochiq", False)):
            d.setdefault(k, v)
        _data = d
    except FileNotFoundError:
        pass
    except Exception as e:
        logging.error("pleyer.json o'qilmadi: %s", e)
    try:
        with open(STAT, encoding="utf-8") as f:
            _stat = json.load(f)
    except Exception:
        _stat = {}
    try:
        with open(META, encoding="utf-8") as f:
            _meta.update(json.load(f))
    except Exception:
        pass


def _save():
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_data, f)
    os.replace(tmp, STORE)


def _stat_save():
    global _stat_dirty
    if not _stat_dirty:
        return
    for k in sorted(_stat)[:-STAT_KUN]:
        _stat.pop(k, None)
    tmp = STAT + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_stat, f)
        os.replace(tmp, STAT)
        _stat_dirty = False
    except Exception as e:
        logging.warning("pleyer_stat yozilmadi: %s", e)


def _kun(now=None):
    # Toshkent vaqti (UTC+5) - kun yarim tunda almashadi
    return time.strftime("%Y-%m-%d", time.gmtime((now or time.time()) + 5 * 3600))


def _stat_add(uid=None, nusxa=None, bayt=0):
    global _stat_dirty
    k = _stat.setdefault(_kun(), {"b": 0, "n": 0, "u": []})
    k["b"] += int(bayt)
    if nusxa is not None:
        k["n"] += 1
        if uid is not None and uid not in k["u"]:
            k["u"].append(uid)
    _stat_dirty = True


def ready():
    return bool(_data.get("api_id") and _data.get("api_hash"))


def allowed(uid):
    """Kim pleyerni ko'radi: rejim ochiq bo'lsa hamma, aks holda adminlar (sinov o'quvchisi ham)."""
    if _data.get("ochiq"):
        return True
    try:
        return abs(int(uid)) in _cfg.get("admin_ids", ())
    except Exception:
        return False


# --- IMZOLI KALIT ---

def _secret():
    return hashlib.sha256(b"hp-pleyer|" + (_cfg.get("token") or "").encode()).digest()


def make_key(user_id, now=None):
    exp = int((now or time.time()) + KEY_TTL)
    body = "%d.%d" % (int(user_id), exp)
    sig = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:24]
    return "%s.%s" % (body, sig)


def check_key(key, now=None):
    try:
        uid, exp, sig = str(key).split(".")
        body = "%s.%s" % (uid, exp)
        good = hmac.new(_secret(), body.encode(), hashlib.sha256).hexdigest()[:24]
        if not hmac.compare_digest(good, sig) or int(exp) < (now or time.time()):
            return None
        return int(uid)
    except Exception:
        return None


# --- NUSXALAR (hpfilms jadvalidan) ---

_NUSXA = re.compile(r"^([a-z]+\d+)_(uz|ru|en)(?:~([a-z0-9]+))?(?:@([a-z]+))?$")


def _mime(name):
    n = (name or "").lower()
    if n.endswith(".mkv"):
        return "video/x-matroska"
    if n.endswith(".webm"):
        return "video/webm"
    return "video/mp4"


def nusxa(vkey):
    """Jadvaldagi bitta nusxa: {mid, size, mime} yoki None."""
    if not _NUSXA.match(vkey or "") or not hpfilms._data.get("group"):
        return None
    it = hpfilms._data["map"].get(vkey)
    if not it or not it.get("mid"):
        return None
    return {"mid": int(it["mid"]), "size": int(it.get("size") or 0), "mime": _mime(it.get("name")),
            "dur": int(it.get("dur") or 0)}


def versions(film):
    """Filmning hamma nusxalari - pleyerdagi tugmalar uchun."""
    out = []
    for lang in hpfilms.LANGS:
        for dub in (hpfilms.DUBS if lang == "uz" else (None,)):
            for q in hpfilms.QUALITIES:
                k = hpfilms._mkey(film, lang, q, dub)
                it = nusxa(k)
                if it:
                    v = {"v": k, "lang": lang, "dub": dub or "", "q": q,
                         "size": it["size"], "dur": it["dur"], "mime": it["mime"]}
                    m = _meta.get(k)
                    if m and m.get("s") == it["size"]:
                        v["codec"] = m.get("c", "")
                        v["p10"] = m.get("prof") == 110        # 10 bitli H.264 - Android brauzeri o'ynatmaydi
                    out.append(v)
    return out


# --- TELEGRAM BILAN IKKINCHI ULANISH (MTProto) ---

async def _get_client():
    """Telethon mijozi - birinchi kerak bo'lganda ulanadi. Kalit yo'q bo'lsa None."""
    global _client, _client_err, _peer
    if _client is not None and _client.is_connected():
        return _client
    if not ready():
        return None
    async with _client_lock:
        if _client is not None and _client.is_connected():
            return _client
        try:
            from telethon import TelegramClient
            c = TelegramClient(SESSION, int(_data["api_id"]), _data["api_hash"],
                               receive_updates=False,        # yangiliklarni aiogram oladi
                               device_model="HP pleyer", connection_retries=3)
            await c.start(bot_token=_cfg["token"])
            _client, _client_err, _peer = c, "", None
            logging.info("Pleyer: Telegram'ga ulandi")
            return c
        except Exception as e:
            _client_err = "%s: %s" % (type(e).__name__, str(e)[:160])
            logging.error("Pleyer: ulanmadi - %s", _client_err)
            return None


async def _reset_client():
    global _client, _peer
    c, _client, _peer = _client, None, None
    _msgs.clear()
    if c is not None:
        try:
            await c.disconnect()
        except Exception:
            pass


async def _message(c, mid, fresh=False):
    """Baza guruhidagi xabar (video fayli bilan). Bot guruh a'zosi - access_hash=0 yetadi."""
    global _peer
    hit = _msgs.get(mid)
    if hit and not fresh and time.time() - hit[1] < MSG_TTL:
        return hit[0]
    from telethon import functions, types as tt, utils
    if _peer is None:
        gid = int(hpfilms._data["group"])
        cid = -gid - 1000000000000 if gid < -1000000000000 else abs(gid)
        res = await c(functions.channels.GetChannelsRequest([tt.InputChannel(cid, 0)]))
        _peer = utils.get_input_peer(res.chats[0])
    msg = await c.get_messages(_peer, ids=mid)
    if msg is None or not msg.media or not getattr(msg.media, "document", None):
        return None
    _msgs[mid] = (msg, time.time())
    return msg


async def _chunks(item, start, end):
    """Fayl baytlari [start, end] oralig'ida, bo'lakma-bo'lak (Telegram'dan)."""
    c = await _get_client()
    if c is None:
        raise RuntimeError("ulanish yo'q")
    for urinish in (0, 1):
        msg = await _message(c, item["mid"], fresh=bool(urinish))
        if msg is None:
            raise LookupError("xabar topilmadi")
        left = end - start + 1
        try:
            it = c.iter_download(msg.media.document, offset=start, request_size=REQ,
                                 file_size=item["size"] or None)
            try:
                async for chunk in it:
                    if left <= 0:
                        break
                    chunk = bytes(chunk[:left])
                    left -= len(chunk)
                    start += len(chunk)
                    yield chunk
            finally:
                try:
                    await it.close()        # boshqa markazdan olingan ulanish qaytariladi
                except Exception:
                    pass
            return
        except (ConnectionResetError, asyncio.CancelledError, GeneratorExit):
            raise
        except Exception as e:
            # Fayl havolasi eskirgan bo'lishi mumkin - xabarni yangidan olib bir marta qayta urinamiz
            if urinish or left <= 0:
                raise
            logging.warning("Pleyer: oqim uzildi (%s), qayta urinish", e)


# --- RANGE ---

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
    else:
        start = max(0, size - int(m.group(2)))
        end = size - 1
    end = min(end, size - 1)
    if start > end or start >= size:
        raise ValueError(header)
    return start, end


# --- MP4 ICHI: APPLE UCHUN HEVC BELGISI (2026-10-17) ---
# Egasining o'zbekcha HD/SD fayllari HEVC, lekin "hev1" belgisi bilan. Safari (iPhone, Mac Telegram)
# "hev1" ni o'ynatmaydi, xuddi shu fayl "hvc1" belgisi bilan o'ynaydi (WebKit'da sinab ko'rildi;
# fayldagi hvcC da VPS/SPS/PPS bor). `ffmpeg -c copy -tag:v hvc1` ham AYNAN shu 4 baytni almashtiradi.
# Shuning uchun server fayl ichidagi video turini bir marta o'qiydi (yuqori qutilar -> moov -> stsd)
# va uzatishda o'sha 4 baytni "hvc1" ga almashtiradi. Hajm o'zgarmaydi, Telegram'dagi fayl o'zgarmaydi.
# 10 bitli H.264 (profil 110) ni almashtirib bo'lmaydi - u faqat belgilanadi (p10).

MOOV_OQ = 256 * 1024              # moov boshidan shuncha o'qiladi (stsd shu yerda turadi)
_VIDEO = (b"avc1", b"avc3", b"hev1", b"hvc1", b"av01", b"vp09", b"mp4v")


async def _read(item, off, n):
    end = min(item["size"] - 1, off + n - 1)
    if off > end:
        return b""
    buf = bytearray()
    gen = _chunks(item, off, end)
    try:
        async for ch in gen:
            buf += ch
    finally:
        await gen.aclose()
    return bytes(buf)


def _stsd(d, base):
    """moov bo'lagidan video namunasi turi; hev1 bo'lsa uning fayldagi mutlaq joyi."""
    out = {"c": "", "p": None}
    i = 0
    while True:
        t = d.find(b"stsd", i)
        if t < 4 or t + 20 > len(d):
            return out
        typ = d[t + 16:t + 20]          # stsd: tur(4) + versiya(4) + soni(4) + yozuv o'lchami(4) + yozuv turi
        if typ in _VIDEO:
            out["c"] = typ.decode()
            if typ == b"hev1":
                out["p"] = base + t + 16
            elif typ in (b"avc1", b"avc3"):
                a = d.find(b"avcC", t, t + 600)
                if 0 < a and a + 6 <= len(d):
                    out["prof"] = d[a + 5]       # avcC: versiya, keyin profil (100 High, 110 High 10)
            return out
        i = t + 4


async def _taxlil(item):
    size = item["size"]
    off, buf_off, buf = 0, 0, b""
    for _ in range(16):                 # yuqori qutilar: ftyp, free, mdat, moov...
        if off + 8 > size:
            break
        if not (buf_off <= off and off + 16 <= buf_off + len(buf)):
            buf_off, buf = off, await _read(item, off, 65536)
        h = buf[off - buf_off:off - buf_off + 16]
        bsize, typ = struct.unpack(">I4s", h[:8])
        if bsize == 1:
            bsize = struct.unpack(">Q", h[8:16])[0]
        elif bsize == 0:
            bsize = size - off
        if typ == b"moov":
            return _stsd(await _read(item, off, min(bsize, MOOV_OQ)), off)
        if bsize < 8:
            break
        off += bsize
    return {"c": "", "p": None}


def _meta_save():
    tmp = META + ".tmp"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            json.dump(_meta, f)
        os.replace(tmp, META)
    except Exception as e:
        logging.warning("pleyer_meta yozilmadi: %s", e)


async def meta(vkey, item):
    """Nusxaning video turi - bir marta o'qiladi va eslab qolinadi (fayl almashsa - hajmidan bilinadi)."""
    m = _meta.get(vkey)
    if m and m.get("s") == item["size"]:
        return m
    lock = _meta_locks.setdefault(vkey, asyncio.Lock())
    async with lock:
        m = _meta.get(vkey)
        if m and m.get("s") == item["size"]:
            return m
        try:
            m = await asyncio.wait_for(_taxlil(item), 40)
        except Exception as e:
            logging.warning("Pleyer: %s ichi o'qilmadi: %s", vkey, e)
            return {"c": "", "p": None}            # eslab qolinmaydi - keyingi safar yana urinadi
        m["s"] = item["size"]
        _meta[vkey] = m
        _meta_save()
        logging.info("Pleyer: %s - %s%s", vkey, m.get("c") or "?", " (hvc1 ga almashtiriladi)" if m.get("p") else "")
        return m


def _yamoq(chunk, pos, p):
    """chunk fayldagi pos dan boshlanadi; p..p+3 baytlarni "hvc1" ga almashtiradi (qisman bo'lsa ham)."""
    if p is None or pos >= p + 4 or p >= pos + len(chunk):
        return chunk
    b = bytearray(chunk)
    for k in range(4):
        j = p + k - pos
        if 0 <= j < len(b):
            b[j] = b"hvc1"[k]
    return bytes(b)


async def _meta_fon(vs):
    for v in vs:
        it = nusxa(v["v"])
        if it and "codec" not in v:
            await meta(v["v"], it)


# --- ILOVA UCHUN ---

async def api_info(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    try:
        body = await request.json()
    except Exception:
        body = {}
    user = _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", "")
                                    or str(body.get("initData", "")))
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
    uid = int(user["id"])
    if not allowed(uid):
        return cors(web.json_response({"ok": False, "error": "yopiq"}))
    film = str(body.get("film") or "")[:12]
    if not ready():
        return cors(web.json_response({"ok": True, "ready": False, "versions": []}))
    vs = versions(film)
    if any("codec" not in v for v in vs):
        asyncio.get_event_loop().create_task(_meta_fon(vs))     # birinchi tomoshagacha tayyor tursin
    return cors(web.json_response({
        "ok": True, "ready": True, "versions": vs, "key": make_key(uid),
        "base": _cfg.get("public_base", "") + "/api/pleyer/v/",
    }))


async def api_video(request):
    global _ochiq_oqim
    base = {"Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Headers": "Range",
            "Access-Control-Expose-Headers": "Accept-Ranges, Content-Range, Content-Length"}
    if request.method == "OPTIONS":
        return web.Response(status=204, headers=base)
    uid = check_key(request.query.get("k", ""))
    if uid is None or not allowed(uid):
        return web.Response(status=403, text="key", headers=base)
    vkey = request.match_info.get("v", "")
    item = nusxa(vkey)
    if not item or not item["size"]:
        return web.Response(status=404, text="nusxa", headers=base)
    size = item["size"]
    try:
        rng = parse_range(request.headers.get("Range"), size)
    except ValueError:
        return web.Response(status=416, headers=dict(base, **{"Content-Range": "bytes */%d" % size}))

    head = dict(base, **{
        "Content-Type": item["mime"],
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=3600",
        "X-Accel-Buffering": "no",          # nginx oqimni o'zida to'plamasin
    })
    if request.method == "HEAD":
        return web.Response(status=200, headers=dict(head, **{"Content-Length": str(size)}))

    start, end = rng if rng else (0, size - 1)
    patch = (await meta(vkey, item)).get("p")
    # Tomosha boshlandi: fayl boshidan katta bo'lak so'ralganda (Safari avval 2 baytni sinaydi)
    if start == 0 and end - start > 1024:
        _stat_add(uid, vkey)

    resp = web.StreamResponse(status=206 if rng else 200, headers=head)
    if rng:
        resp.headers["Content-Range"] = "bytes %d-%d/%d" % (start, end, size)
    resp.content_length = end - start + 1
    await resp.prepare(request)
    _ochiq_oqim += 1
    yuborildi = 0
    gen = _chunks(item, start, end)
    try:
        async for chunk in gen:
            await resp.write(_yamoq(chunk, start + yuborildi, patch))
            yuborildi += len(chunk)
        await resp.write_eof()
    except (ConnectionResetError, asyncio.CancelledError):
        pass                       # tomoshabin o'tkazib yubordi yoki yopdi - odatiy hol
    except Exception as e:
        logging.warning("Pleyer: %s oqimi uzildi (%d bayt): %s", vkey, yuborildi, e)
    finally:
        _ochiq_oqim -= 1
        _stat_add(bayt=yuborildi)
        try:
            await gen.aclose()          # Telegram'dan olishni darhol to'xtatadi
        except Exception:
            pass
    return resp


# --- ADMIN ---

def _gb(b):
    return "%.2f GB" % (b / 1024 ** 3)


def holat_text():
    if not ready():
        ulanish = "ilova kaliti YO'Q — /pleyer kalit <api_id> <api_hash>"
    elif _client is not None and _client.is_connected():
        ulanish = "ulangan ✅"
    else:
        ulanish = "kalit bor, hali ulanmagan" + (" (xato: %s)" % _client_err if _client_err else "")
    rejim = "OCHIQ (hamma ko'radi)" if _data.get("ochiq") else "SINOV (faqat adminlar)"
    qator = []
    for k in sorted(_stat)[-7:][::-1]:
        s = _stat[k]
        qator.append("%s: %s, %d tomosha, %d kishi" % (k, _gb(s.get("b", 0)), s.get("n", 0), len(s.get("u", []))))
    jami = sum(s.get("b", 0) for s in _stat.values())
    return ("🎬 Pleyer (ilova ichida ko'rish)\nUlanish: %s\nRejim: %s\nHozir uzatilmoqda: %d ta oqim\n\n"
            "Trafik (oxirgi 7 kun):\n%s\nJami %d kunda: %s" % (
                ulanish, rejim, _ochiq_oqim, "\n".join(qator) or "—", len(_stat), _gb(jami)))


async def on_pleyer_command(message: types.Message):
    u = message.from_user
    if not u or u.id not in _cfg.get("admin_ids", ()) or message.chat.type != "private":
        return
    bolak = (message.text or "").split()
    sub = bolak[1].lower() if len(bolak) > 1 else ""
    if sub == "kalit":
        try:
            await message.delete()            # kalit chatda qolmasin
        except Exception:
            pass
        if len(bolak) != 4 or not bolak[2].isdigit() or not re.match(r"^[0-9a-f]{32}$", bolak[3].lower()):
            await message.answer("Yozilishi: /pleyer kalit <api_id> <api_hash>\n"
                                 "api_id — raqam, api_hash — 32 belgili qator (my.telegram.org).")
            return
        _data["api_id"], _data["api_hash"] = int(bolak[2]), bolak[3].lower()
        _save()
        await _reset_client()
        c = await _get_client()
        await message.answer(("Kalit saqlandi va Telegram'ga ulandi ✅" if c else
                              "Kalit saqlandi, lekin ulanmadi ❌\n%s" % _client_err) + "\n\n" + holat_text())
        return
    if sub in ("ochiq", "sinov"):
        _data["ochiq"] = sub == "ochiq"
        _save()
    await message.answer(holat_text() + "\n\nBuyruqlar: /pleyer kalit <api_id> <api_hash>  |  "
                                        "/pleyer sinov  |  /pleyer ochiq")


async def _stat_kuzatuvchi():
    while True:
        await asyncio.sleep(60)
        _stat_save()


# --- ULASH ---

def register(dp, bot, app, cfg):
    """cfg: admin_ids, token, verify_init_data, cors, public_base. hpfilms DAN KEYIN ulanadi."""
    _cfg.update(cfg)
    _cfg["bot"] = bot
    load()
    dp.message.register(on_pleyer_command, Command("pleyer"))
    app.router.add_route("*", "/api/pleyer", api_info)
    app.router.add_route("*", "/api/pleyer/v/{v}", api_video)
    asyncio.get_event_loop().create_task(_stat_kuzatuvchi())
    logging.info("Pleyer: kalit %s, rejim %s", "bor" if ready() else "yo'q",
                 "ochiq" if _data.get("ochiq") else "sinov")
