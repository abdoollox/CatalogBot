"""Tayoqchani ulashish rasmi (egasi, 2026-10-05) - Patronus rasmi (hppatronus.py) namunasida.

Tayoqcha ilovada tanlanadi va o'sha yerda saqlanadi (serverda faqat olingan vaqti bor), shuning uchun
yog'och / o'zak / egiluvchanlik so'rovda keladi va ruxsat etilgan ro'yxat bilan tekshiriladi.
API: POST /api/tayoqcha/share {lang, wood, core, flex} -> {ok, url, share_id};  GET /api/tayoqcha/img/<token>.jpg
"""

import asyncio
import hashlib
import json
import logging
import os
import re
import time

from aiohttp import web

_cfg = {}
HERE = os.path.dirname(os.path.abspath(__file__))
ART_DIR = os.path.join(HERE, "img", "tayoqcha")
OUT_DIR = os.getenv("HP_TAYOQ_DIR", "/data/tayoqcha")
try:
    with open(os.path.join(HERE, "tayoqcha_matn.json"), encoding="utf-8") as _f:
        MATN = json.load(_f)
except Exception:
    MATN = {"woods": {}, "cores": {}, "flex": {}}

W, H = 1080, 1920
BG = (12, 13, 20)
TEXT = (238, 241, 245)
DIM = (152, 162, 179)
GOLD = (231, 193, 112)
TX = {
    "uz": {"top": "OLIVANDER DO'KONI · 382-YILDAN", "said": "Tayoqcha sehrgarni tanlaydi", "anon": "Mening tayoqcham",
           "kim": "%sning tayoqchasi", "inch": "dyuym", "foot1": "Sizni qaysi tayoqcha tanlaydi?", "foot2": "t.me/garripotterkinobot",
           "matn": "Meni %s tayoqchasi tanladi!", "tugma": "Tayoqchamni topaman"},
    "ru": {"top": "ЛАВКА ОЛЛИВАНДЕРА · С 382 ГОДА", "said": "Палочка выбирает волшебника", "anon": "Моя палочка",
           "kim": "%s · моя палочка", "inch": "дюймов", "foot1": "А какая палочка выберет вас?", "foot2": "t.me/garripotterkinobot",
           "matn": "Меня выбрала палочка: %s!", "tugma": "Найти свою палочку"},
    "en": {"top": "OLLIVANDERS · SINCE 382 B.C.", "said": "The wand chooses the wizard", "anon": "My wand",
           "kim": "%s's wand", "inch": "inches", "foot1": "Which wand will choose you?", "foot2": "t.me/garripotterkinobot",
           "matn": "I was chosen by a wand: %s!", "tugma": "Find my wand"},
}


def nomi(lang, wood, core):
    return "%s, %s" % (MATN["woods"][wood].get(lang) or MATN["woods"][wood]["uz"],
                       MATN["cores"][core].get(lang) or MATN["cores"][core]["uz"])


def render(name, lang, wood, core, flex, path):
    from PIL import Image, ImageDraw, ImageFilter
    import hpxat
    t = TX.get(lang) or TX["uz"]
    wd, cr, fl = MATN["woods"][wood], MATN["cores"][core], MATN["flex"][flex]
    im = Image.new("RGB", (W, H), BG)
    glow = Image.new("RGB", (W, H), BG)
    ImageDraw.Draw(glow).ellipse([-150, 80, W + 150, 1180], fill=(110, 80, 30))
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

    D = 700
    art = Image.open(os.path.join(ART_DIR, wood + ".jpg")).convert("RGB").resize((D, D), Image.LANCZOS)
    mask = Image.new("L", (D * 2, D * 2), 0)
    ImageDraw.Draw(mask).ellipse([0, 0, D * 2 - 1, D * 2 - 1], fill=255)
    mask = mask.resize((D, D), Image.LANCZOS)
    ax, ay = (W - D) // 2, 230
    d.ellipse([ax - 10, ay - 10, ax + D + 9, ay + D + 9], outline=(120, 92, 40), width=3)
    d.ellipse([ax - 4, ay - 4, ax + D + 3, ay + D + 3], outline=GOLD, width=4)
    im.paste(art, (ax, ay), mask)
    d = ImageDraw.Draw(im)

    y = ay + D + 70
    center(t["said"], hpxat._font(hpxat.FONT_ITALIC, 48, 500), y, DIM)
    y += 96
    kim = (t["kim"] % name) if name else t["anon"]
    center(kim, fit(kim, hpxat.FONT_MAIN, 70, 500, W - 160), y, TEXT)
    y += 100
    nom = wd.get(lang) or wd["uz"]
    center(nom, fit(nom, hpxat.FONT_MAIN, 180, 600, W - 120), y, GOLD)
    y += 230
    d.line([(W / 2 - 60, y), (W / 2 + 60, y)], fill=GOLD, width=3)
    y += 40
    qator = "%s · %s %s · %s" % (cr.get(lang) or cr["uz"], fl["len"], t["inch"], fl.get(lang) or fl["uz"])
    center(qator, fit(qator, hpxat.FONT_MAIN, 48, 500, W - 140), y, TEXT)
    y += 76
    izoh = wd.get("t_" + lang) or wd.get("t_uz") or ""
    if izoh:
        izoh = izoh[0].upper() + izoh[1:]
        center(izoh, fit(izoh, hpxat.FONT_ITALIC, 42, 500, W - 200), y, DIM)

    center(t["foot1"], hpxat._font(hpxat.FONT_MAIN, 40, 600), H - 250, GOLD)
    center(t["foot2"], hpxat._font(hpxat.FONT_MAIN, 30, 500), H - 190, DIM)
    tmp = path + ".tmp"
    im.save(tmp, "JPEG", quality=88, optimize=True, progressive=True)
    os.replace(tmp, path)
    return path


def path_of(token):
    return os.path.join(OUT_DIR, token + ".jpg")


def ensure(user_id, name, lang, wood, core, flex):
    import hpxat
    if wood not in MATN["woods"] or core not in MATN["cores"] or flex not in MATN["flex"]:
        raise ValueError("tayoqcha")
    lang = lang if lang in TX else "uz"
    name = hpxat.clean_name(name)
    os.makedirs(OUT_DIR, exist_ok=True)
    raw = "tq|%s|%s|%s|%s|%s|%s" % (user_id, name or "", lang, wood, core, flex)
    token = hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]
    if not os.path.exists(path_of(token)):
        render(name, lang, wood, core, flex, path_of(token))
    return token


_tez = {}


async def api_share(request):
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
    lang = lang if lang in TX else "uz"
    wood, core, flex = str(body.get("wood", "")), str(body.get("core", "")), str(body.get("flex", ""))
    if wood not in MATN["woods"] or core not in MATN["cores"] or flex not in MATN["flex"]:
        return cors(web.json_response({"ok": False, "error": "no_wand"}))
    try:
        token = await asyncio.to_thread(ensure, uid, user.get("first_name"), lang, wood, core, flex)
    except Exception as e:
        logging.error("Tayoqcha rasmini yasashda xato: %s", e)
        return cors(web.json_response({"ok": False, "error": "server"}, status=500))
    url = "%s/api/tayoqcha/img/%s.jpg" % (_cfg.get("public_base", ""), token)
    share_id = None
    if uid > 0 and _cfg.get("share"):
        try:
            share_id = await _cfg["share"](uid, lang, url, TX[lang]["matn"] % nomi(lang, wood, core), TX[lang]["tugma"])
        except Exception as e:
            logging.error("Tayoqcha ulashish xabari tayyorlanmadi: %s", e)
    return cors(web.json_response({"ok": True, "url": url, "share_id": share_id}))


async def api_file(request):
    token = request.match_info.get("token", "")
    if not re.fullmatch(r"[0-9a-f]{20}", token) or not os.path.exists(path_of(token)):
        return web.Response(status=404, text="yoq")
    return web.FileResponse(path_of(token), headers={"Cache-Control": "public, max-age=604800",
                                                     "Access-Control-Allow-Origin": "*"})


def register(app, cfg):
    """cfg: verify_init_data, cors, public_base, share."""
    _cfg.update(cfg)
    app.router.add_route("*", "/api/tayoqcha/share", api_share)
    app.router.add_get("/api/tayoqcha/img/{token}.jpg", api_file)
    logging.info("Tayoqcha ulashish: %d yog'och", len(MATN["woods"]))
