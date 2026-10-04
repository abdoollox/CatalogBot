"""Patronus (egasi, 2026-10-04): testni ilova o'tkazadi, natija shu yerda saqlanadi.

Qoidalar: faqat saralangan o'quvchiga, FAQAT BIR MARTA (qayta topshirib bo'lmaydi), bepul.
15 ta Patronus - asardagi qahramonlarniki. Natija `users.patronus` ustunida.

API: /api/patronus
  {}            -> {ok, code, at}            hozirgi Patronus (yo'q bo'lsa code = null)
  {code: "stag"} -> birinchi marta yozadi; allaqachon bor bo'lsa O'SHANI qaytaradi (o'zgarmaydi)
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import sqlite3
import time

from aiohttp import web

DB_PATH = os.getenv("HP_DB_PATH", "/data/hp.db")
_cfg = {}

KODLAR = ("stag", "doe", "otter", "dog", "horse", "hare", "swan", "phoenix",
          "cat", "lynx", "weasel", "wolf", "goat", "fox", "boar")


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _init():
    conn = _db()
    try:
        cols = {r[1] for r in conn.execute("PRAGMA table_info(users)")}
        if cols and "patronus" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN patronus TEXT")
        if cols and "patronus_at" not in cols:
            conn.execute("ALTER TABLE users ADD COLUMN patronus_at TEXT")
        conn.commit()
    finally:
        conn.close()


def _get(uid):
    conn = _db()
    try:
        r = conn.execute("SELECT house, patronus, patronus_at FROM users WHERE user_id=?", (int(uid),)).fetchone()
        return (r["house"], r["patronus"], r["patronus_at"]) if r else (None, None, None)
    finally:
        conn.close()


def _set(uid, code):
    """(holat, kod, vaqt): "ok" - yozildi, "bor" - avval olingan, "uy" - saralanmagan."""
    conn = _db()
    try:
        r = conn.execute("SELECT house, patronus, patronus_at FROM users WHERE user_id=?", (int(uid),)).fetchone()
        if not r or not r["house"]:
            return "uy", None, None
        if r["patronus"]:
            return "bor", r["patronus"], r["patronus_at"]
        hozir = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        # Shart so'rovning o'zida: ikki marta bosilsa ham birinchisi qoladi
        cur = conn.execute("UPDATE users SET patronus=?, patronus_at=? WHERE user_id=? AND patronus IS NULL",
                           (code, hozir, int(uid)))
        conn.commit()
        if cur.rowcount < 1:
            r = conn.execute("SELECT patronus, patronus_at FROM users WHERE user_id=?", (int(uid),)).fetchone()
            return "bor", r["patronus"], r["patronus_at"]
        return "ok", code, hozir
    finally:
        conn.close()


async def api_patronus(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    body = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            return cors(web.json_response({"ok": False, "error": "bad_json"}, status=400))
    user = _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", "")
                                    or str(body.get("initData", "")))
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
    uid = int(user["id"])
    code = body.get("code")
    if code is None:
        _, kod, vaqt = await asyncio.to_thread(_get, uid)
        return cors(web.json_response({"ok": True, "code": kod, "at": vaqt}))
    if code not in KODLAR:
        return cors(web.json_response({"ok": False, "error": "unknown"}, status=400))
    holat, kod, vaqt = await asyncio.to_thread(_set, uid, code)
    if holat == "uy":
        return cors(web.json_response({"ok": False, "error": "no_house"}, status=409))
    if holat == "ok" and _cfg.get("log"):
        try:
            await _cfg["log"](user, "patronus_" + kod)
        except Exception as e:
            logging.error("Patronus logi yozilmadi: %s", e)
    return cors(web.json_response({"ok": True, "code": kod, "at": vaqt, "new": holat == "ok"}))


# ---------------------------------------------------------------- ulashish rasmi
# Fakultet rasmi (hpuy.py) namunasida: 1080x1920, Stories yoki chatga. Patronus BAZADAN olinadi.

HERE = os.path.dirname(os.path.abspath(__file__))
ART_DIR = os.path.join(HERE, "img", "patronus")
OUT_DIR = os.getenv("HP_PATRONUS_DIR", "/data/patronus")
try:
    with open(os.path.join(HERE, "patronus_matn.json"), encoding="utf-8") as _f:
        MATN = json.load(_f)
except Exception:
    MATN = {}

W, H = 1080, 1920
BG = (10, 13, 20)
TEXT = (238, 241, 245)
DIM = (152, 162, 179)
GOLD = (231, 193, 112)
KUMUSH = (190, 220, 255)
SH_TX = {
    "uz": {"top": "XOGVARTS · PATRONUS", "said": "Ekspekto Patronum!", "anon": "Mening Patronusim", "kim": "%sning Patronusi",
           "foot1": "Sizning Patronusingiz qaysi?", "foot2": "t.me/garripotterkinobot",
           "matn": "Mening Patronusim — %s!", "tugma": "Patronusimni bilaman"},
    "ru": {"top": "ХОГВАРТС · ПАТРОНУС", "said": "Экспекто Патронум!", "anon": "Мой Патронус", "kim": "%s · мой Патронус",
           "foot1": "А какой Патронус у вас?", "foot2": "t.me/garripotterkinobot",
           "matn": "Мой Патронус — %s!", "tugma": "Узнать своего Патронуса"},
    "en": {"top": "HOGWARTS · PATRONUS", "said": "Expecto Patronum!", "anon": "My Patronus", "kim": "%s's Patronus",
           "foot1": "What is your Patronus?", "foot2": "t.me/garripotterkinobot",
           "matn": "My Patronus is the %s!", "tugma": "Find my Patronus"},
}


def render(name, lang, code, path):
    from PIL import Image, ImageDraw, ImageFilter
    import hpxat
    t = SH_TX.get(lang) or SH_TX["uz"]
    m = MATN[code]
    im = Image.new("RGB", (W, H), BG)
    glow = Image.new("RGB", (W, H), BG)
    ImageDraw.Draw(glow).ellipse([-150, 80, W + 150, 1180], fill=(40, 70, 120))
    glow = glow.filter(ImageFilter.GaussianBlur(200))
    im = Image.blend(im, glow, 0.9)
    d = ImageDraw.Draw(im)

    def center(text, font, y, fill):
        d.text(((W - d.textlength(text, font=font)) / 2, y), text, font=font, fill=fill)

    def fit(text, path_, size, weight, width):
        while size > 40:
            f = hpxat._font(path_, size, weight)
            if d.textlength(text, font=f) <= width:
                return f
            size -= 6
        return hpxat._font(path_, size, weight)

    hpxat._spaced(d, t["top"], hpxat._font(hpxat.FONT_MAIN, 30, 600), W / 2, 150, gap=7, fill=GOLD)

    # Patronus: doira ichida, kumush-ko'k halqa
    D = 700
    art = Image.open(os.path.join(ART_DIR, code + ".jpg")).convert("RGB").resize((D, D), Image.LANCZOS)
    mask = Image.new("L", (D * 2, D * 2), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, D * 2 - 1, D * 2 - 1], fill=255)
    mask = mask.resize((D, D), Image.LANCZOS)
    ax, ay = (W - D) // 2, 230
    d.ellipse([ax - 10, ay - 10, ax + D + 9, ay + D + 9], outline=(90, 130, 190), width=3)
    d.ellipse([ax - 4, ay - 4, ax + D + 3, ay + D + 3], outline=KUMUSH, width=4)
    im.paste(art, (ax, ay), mask)
    d = ImageDraw.Draw(im)

    y = ay + D + 70
    center(t["said"], hpxat._font(hpxat.FONT_ITALIC, 48, 500), y, DIM)
    y += 96
    kim = (t["kim"] % name) if name else t["anon"]
    center(kim, fit(kim, hpxat.FONT_MAIN, 70, 500, W - 160), y, TEXT)
    y += 100
    nom = m.get(lang) or m["uz"]
    center(nom, fit(nom, hpxat.FONT_MAIN, 180, 600, W - 120), y, KUMUSH)
    y += 230
    d.line([(W / 2 - 60, y), (W / 2 + 60, y)], fill=KUMUSH, width=3)
    y += 40
    f_note = hpxat._font(hpxat.FONT_ITALIC, 42, 500)
    for line in hpxat._wrap(d, m.get("n_" + lang) or m["n_uz"], f_note, W - 220)[:3]:
        center(line, f_note, y, TEXT)
        y += 56

    center(t["foot1"], hpxat._font(hpxat.FONT_MAIN, 40, 600), H - 250, GOLD)
    center(t["foot2"], hpxat._font(hpxat.FONT_MAIN, 30, 500), H - 190, DIM)
    tmp = path + ".tmp"
    im.save(tmp, "JPEG", quality=88, optimize=True, progressive=True)
    os.replace(tmp, path)
    return path


def path_of(token):
    return os.path.join(OUT_DIR, token + ".jpg")


def ensure(user_id, name, lang, code):
    """Rasmni (kerak bo'lsa) yasaydi, tokenini qaytaradi. Sinxron - to_thread ichida chaqiring."""
    import hpxat
    if code not in MATN:
        raise ValueError("patronus")
    lang = lang if lang in SH_TX else "uz"
    name = hpxat.clean_name(name)
    os.makedirs(OUT_DIR, exist_ok=True)
    token = hashlib.sha1(("pt|%s|%s|%s|%s" % (user_id, name or "", lang, code)).encode("utf-8")).hexdigest()[:20]
    if not os.path.exists(path_of(token)):
        render(name, lang, code, path_of(token))
    return token


_tez = {}


async def api_share(request):
    """Patronus rasmini yasaydi va manzilini qaytaradi (Stories yoki chatga ulashish uchun)."""
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
    hozir = time.time()
    if hozir - _tez.get(uid, 0) < 3:
        return cors(web.json_response({"ok": False, "error": "tez"}, status=429))
    _tez[uid] = hozir
    lang = str(body.get("lang", "uz"))
    lang = lang if lang in SH_TX else "uz"
    _, code, _ = await asyncio.to_thread(_get, uid)
    if code not in MATN:
        return cors(web.json_response({"ok": False, "error": "no_patronus"}))
    try:
        token = await asyncio.to_thread(ensure, uid, user.get("first_name"), lang, code)
    except Exception as e:
        logging.error("Patronus rasmini yasashda xato: %s", e)
        return cors(web.json_response({"ok": False, "error": "server"}, status=500))
    url = "%s/api/patronus/img/%s.jpg" % (_cfg.get("public_base", ""), token)
    share_id = None
    if uid > 0 and _cfg.get("share"):
        try:
            share_id = await _cfg["share"](uid, lang, url, SH_TX[lang]["matn"] % MATN[code][lang], SH_TX[lang]["tugma"])
        except Exception as e:
            logging.error("Patronus ulashish xabari tayyorlanmadi: %s", e)
    return cors(web.json_response({"ok": True, "url": url, "share_id": share_id, "code": code}))


async def api_file(request):
    token = request.match_info.get("token", "")
    if not re.fullmatch(r"[0-9a-f]{20}", token) or not os.path.exists(path_of(token)):
        return web.Response(status=404, text="yoq")
    return web.FileResponse(path_of(token), headers={"Cache-Control": "public, max-age=604800",
                                                     "Access-Control-Allow-Origin": "*"})


def register(app, cfg):
    """cfg: verify_init_data, cors, log, public_base, share (ulashish xabari tayyorlovchi)."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/patronus", api_patronus)
    app.router.add_route("*", "/api/patronus/share", api_share)
    app.router.add_get("/api/patronus/img/{token}.jpg", api_file)
    logging.info("Patronus: %d xil", len(KODLAR))
