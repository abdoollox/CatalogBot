# -*- coding: utf-8 -*-
"""Serial (HBO, 2026-12-25) - qismlar yopiq GURUHDAN, filmlar kabi (hpfilms).

Maqsad (egasi, 2026-10-03): qism chiqqanda faylni baza guruhiga tashlashning o'zi
yetarli bo'lsin - kod o'zgartirish va joylash kerak emas. Shuning uchun qismlar
ro'yxati catalog.py da EMAS, shu yerda: bot qaysi video qaysi qism ekanini o'zi
aniqlaydi va ilovaga `/api/serial` orqali beradi.

Guruhda HAR TIL uchun alohida mavzu. Sozlash (bir marta, admin):
    o'zbekcha qismlar mavzusida:  /serial uz
    ruscha:                       /serial ru
    inglizcha:                    /serial en
Shundan keyin mavzuga tashlangan har video o'zi taniladi. Fasl va qism raqami
video NOMIDAN yoki IZOHIDAN olinadi:
    "S01E03", "s1e3", "1x03", "1-fasl 3-qism", "Сезон 1 серия 3",
    "Season 1 Episode 3"; fasl yozilmasa ("3-qism", "E03") - 1-fasl.
Tanilmasa - adminning shaxsiy chatiga yoziladi, qo'lda bog'lash buyrug'i bilan.

Adminning bot bilan shaxsiy chatida:
    /serial               - holat (qaysi qismlar bor, rejim)
    /serial sinov         - qismlarni FAQAT adminlar ko'radi (boshlang'ich holat)
    /serial ochiq         - hammaga ochiladi
    /qism s1e3_uz 1234    - 1-fasl 3-qism o'zbekchasi guruhdagi 1234-xabar
    /qism s1e3_uz -       - bog'lanishni olib tashlash

Qism RASMI: shu mavzuga rasm tashlanadi, izohiga qism raqami yoziladi ("1-fasl 3-qism").
Rasm hamma til uchun bitta; /data/serial/s1e3.jpg, ilovaga /api/serial/cover/s1e3.jpg.
Rasmi yo'q qismda ilova umumiy serial rasmini ko'rsatadi.

Yangi qism haqida xabar (boyo'g'li pochtasi + bot): o'zi KETMAYDI. Rejim "ochiq"
bo'lsa, admin qism bog'langani haqidagi xabar ostidagi tugmani bosadi - noto'g'ri
fayl tashlansa hammaga xabar ketib qolmasin.
"""

import asyncio
import json
import logging
import os
import re
import time

from aiohttp import web
from aiogram import F, types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import hpfilms          # video ajratish (_video, _item) - bir xil usul
import hpmusic          # _tg: sekinlash va tarmoq uzilishiga chidamli so'rov

COVER_DIR = "/data/serial"     # qism rasmlari: s1e3.jpg (til farq qilmaydi)
STORE = "/data/serial.json"    # MUTLAQ yo'l: faqat /data konteynerdan tashqarida yashaydi
LANGS = ("uz", "ru", "en")
SEND_GAP = 4                   # bir odam qism so'rashi orasidagi soniya

_cfg = {}
# topics: {mavzu raqami: til}; eps: {"s1e3_uz": video}; elon: e'lon qilingan kalitlar
_data = {"group": None, "topics": {}, "eps": {}, "ochiq": False, "elon": []}
_oxirgi = {}                   # uid -> oxirgi yuborish vaqti


# --- SAQLASH ---

def load():
    global _data
    try:
        with open(STORE, encoding="utf-8") as f:
            d = json.load(f)
        for k, v in (("group", None), ("topics", {}), ("eps", {}), ("ochiq", False), ("elon", [])):
            d.setdefault(k, v)
        _data = d
    except FileNotFoundError:
        pass
    except Exception as e:
        logging.error("serial.json o'qilmadi: %s", e)


def _save():
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_data, f, ensure_ascii=False)
    os.replace(tmp, STORE)


# --- NOMDAN FASL VA QISM ---

_SE = [
    re.compile(r"\bs(\d{1,2})\s*[._ -]?\s*e(\d{1,3})\b"),                       # S01E03, s1.e3
    re.compile(r"\b(\d{1,2})x(\d{1,3})\b"),                                     # 1x03
    re.compile(r"(\d{1,2})\s*[-.]?\s*(?:fasl|mavsum|sezon)\w*\W+(\d{1,3})\s*[-.]?\s*qism"),
    re.compile(r"(?:сезон|season)\s*(\d{1,2})\W+(?:серия|эпизод|episode|ep)\s*(\d{1,3})"),
    re.compile(r"(\d{1,2})\s*[-.]?\s*сезон\w*\W+(\d{1,3})\s*[-.]?\s*(?:серия|эпизод)"),
]
_E = [
    re.compile(r"(\d{1,3})\s*[-.]?\s*qism"),                                    # 3-qism
    re.compile(r"(\d{1,3})\s*[-.]?\s*(?:серия|эпизод)"),                        # 3 серия
    re.compile(r"(?:серия|эпизод|episode|qism)\s*(\d{1,3})"),                   # серия 3, Episode 3
    re.compile(r"\be(?:p)?\s*[._ -]?(\d{1,3})\b"),                              # E03, ep 3
]


def ep_of(text):
    """Matndan (fasl, qism) yoki None. Fasl yozilmagan bo'lsa - 1."""
    n = (text or "").lower().replace("’", "'").replace("_", " ")
    n = re.sub(r"\b(19|20)\d\d\b|\b\d{3,4}p\b|\b[hx]\.?26[45]\b", " ", n)       # yil, sifat, kodek
    for rx in _SE:
        m = rx.search(n)
        if m:
            s, e = int(m.group(1)), int(m.group(2))
            if 1 <= s <= 20 and 1 <= e <= 99:
                return s, e
    for rx in _E:
        m = rx.search(n)
        if m and 1 <= int(m.group(1)) <= 99:
            return 1, int(m.group(1))
    return None


_KEY = re.compile(r"^s(\d{1,2})e(\d{1,3})_(uz|ru|en)$")


def key(s, e, lang):
    return "s%de%d_%s" % (s, e, lang)


def parse_key(k):
    m = _KEY.match((k or "").lower())
    return (int(m.group(1)), int(m.group(2)), m.group(3)) if m else None


def source(s, e, lang):
    """(chat_id, message_id) - qism qayerdan nusxalanadi. Yo'q bo'lsa None."""
    it = _data["eps"].get(key(s, e, lang))
    if it and _data.get("group"):
        return _data["group"], int(it["mid"])
    return None


# --- ILOVA UCHUN RO'YXAT ---

def _is_admin_id(uid):
    return uid is not None and int(uid) in _cfg.get("admin_ids", ())


def public_list(uid=None):
    """Ilovaga beriladigan ro'yxat. Sinov rejimida faqat admin ko'radi."""
    if not _data.get("ochiq") and not _is_admin_id(uid):
        return []
    out = []
    for k, it in _data["eps"].items():
        p = parse_key(k)
        if not p:
            continue
        out.append({"s": p[0], "e": p[1], "lang": p[2], "dur": int(it.get("dur") or 0),
                    "at": int(it.get("at") or 0)})
    out.sort(key=lambda x: (x["s"], x["e"], x["lang"]))
    return out


def cover_path(s, e):
    return os.path.join(COVER_DIR, "s%de%d.jpg" % (s, e))


def covers():
    """{"s1e3": versiya} - rasmi bor qismlar (versiya = fayl vaqti, keshni yangilash uchun)."""
    out = {}
    try:
        for f in os.listdir(COVER_DIR):
            m = re.match(r"^(s\d{1,2}e\d{1,3})\.jpg$", f)
            if m:
                out[m.group(1)] = int(os.path.getmtime(os.path.join(COVER_DIR, f)))
    except FileNotFoundError:
        pass
    return out


def table_text():
    if not _data["eps"]:
        qism = "Hali bitta ham qism yo'q."
    else:
        qator = {}
        for k in _data["eps"]:
            p = parse_key(k)
            if p:
                qator.setdefault((p[0], p[1]), []).append(p[2])
        qism = "\n".join("%d-fasl %d-qism: %s" % (s, e, " ".join(sorted(t)))
                         for (s, e), t in sorted(qator.items()))
    mavzu = ", ".join(sorted(_data["topics"].values())) or "yo'q"
    rejim = "OCHIQ (hamma ko'radi)" if _data.get("ochiq") else "SINOV (faqat adminlar ko'radi)"
    rasm = ", ".join(sorted(covers())) or "yo'q"
    return "📺 Serial\nRejim: %s\nMavzular: %s\nRasmi bor qismlar: %s\n\n%s" % (rejim, mavzu, rasm, qism)


# --- ADMIN ---

async def _tell(text, markup=None):
    bot = _cfg["bot"]
    for uid in sorted(_cfg.get("admin_ids", ())):
        try:
            await hpmusic._tg(bot.send_message, uid, text[:4000], disable_notification=True,
                              reply_markup=markup)
            return
        except Exception:
            continue


def _is_admin(message):
    u = message.from_user
    if u and u.id in _cfg.get("admin_ids", ()):
        return True
    return bool(message.sender_chat and message.sender_chat.id == message.chat.id)


def _place(it, s, e, lang, how):
    """Qismni jadvalga qo'yadi. Qo'lda bog'langan avtomatik bilan almashtirilmaydi.
    Yangi (ilgari bo'lmagan) qism bo'lsa True."""
    k = key(s, e, lang)
    old = _data["eps"].get(k)
    if old and old.get("by") == "qolda" and how != "qolda":
        return False
    yangi = old is None
    _data["eps"][k] = dict(it, by=how, at=(old or {}).get("at") or int(time.time()))
    return yangi


def _elon_tugma(s, e):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="📣 Hammaga xabar berish", callback_data="srl_elon:%d:%d" % (s, e))]])


async def on_serial_command(message: types.Message):
    if not _is_admin(message):
        return
    bolak = (message.text or "").split()
    if message.chat.type == "private":
        if len(bolak) > 1 and bolak[1].lower() in ("ochiq", "sinov"):
            _data["ochiq"] = bolak[1].lower() == "ochiq"
            _save()
        await message.answer(table_text() + "\n\nMavzu qo'shish: guruhdagi serial mavzusida /serial uz "
                             "(yoki ru, en).\nRejim: /serial ochiq  |  /serial sinov")
        return
    if message.chat.type != "supergroup":
        return
    lang = next((b.lower() for b in bolak[1:] if b.lower() in LANGS), None)
    try:
        await message.delete()             # guruhda buyruq izi qolmasin
    except Exception:
        pass
    if not lang:
        await _tell("Mavzu tilini ham yozing: /serial uz (yoki ru, en).")
        return
    thread = message.message_thread_id if message.is_topic_message else None
    _data["group"] = message.chat.id
    _data["topics"][str(thread)] = lang
    _save()
    await _tell("📺 Serial mavzusi eslab qolindi: %s.\nEndi shu mavzuga tashlangan video o'zi taniladi. "
                "Nomida yoki izohida qism raqami bo'lsin: S01E03 yoki «1-fasl 3-qism».\n"
                "Hozir rejim: %s." % (lang, "ochiq" if _data.get("ochiq") else "sinov (faqat adminlar ko'radi)"))


async def on_qism_command(message: types.Message):
    """Shaxsiy chatda: /qism s1e3_uz 1234  yoki  /qism s1e3_uz -"""
    if not _is_admin(message) or message.chat.type != "private":
        return
    bolak = (message.text or "").split()
    p = parse_key(bolak[1]) if len(bolak) > 1 else None
    if not p or len(bolak) < 3:
        await message.answer("Yozilishi: /qism s1e3_uz 1234 (guruhdagi xabar raqami) yoki /qism s1e3_uz -")
        return
    k = key(*p)
    if bolak[2] == "-":
        _data["eps"].pop(k, None)
        _save()
        await message.answer("Olib tashlandi: %s\n\n%s" % (k, table_text()))
        return
    if not bolak[2].isdigit():
        await message.answer("Xabar raqami son bo'lishi kerak.")
        return
    _place({"mid": int(bolak[2]), "name": "", "cap": "", "size": 0, "dur": 0}, p[0], p[1], p[2], "qolda")
    _save()
    await message.answer("Bog'landi: %s ← %s-xabar\n\n%s" % (k, bolak[2], table_text()))


def _in_serial_topic(message):
    if not _data.get("group") or message.chat.id != _data["group"]:
        return False
    return hpfilms._topic_of(message) in _data["topics"]


def _in_serial_photo(message):
    return _in_serial_topic(message) and _photo(message) is not None


async def on_group_video(message: types.Message):
    """Serial mavzusiga video tashlandi - qism o'zi taniladi."""
    v = hpfilms._video(message)
    if v is None:
        return
    it = hpfilms._item(message.message_id, message, v)
    lang = _data["topics"].get(hpfilms._topic_of(message))
    se = ep_of("%s\n%s" % (it["name"], it["cap"]))
    if not se or not lang:
        await _tell("📺 Video tanilmadi: %d-xabar (%s)\nQo'lda: /qism s1e1_%s %d"
                    % (it["mid"], it["name"] or it["cap"][:60] or "nomsiz", lang or "uz", it["mid"]))
        return
    yangi = _place(it, se[0], se[1], lang, "nom")
    _save()
    matn = "📺 %d-fasl %d-qism (%s) %s ← %d-xabar" % (
        se[0], se[1], lang, "bog'landi" if yangi else "yangilandi", it["mid"])
    if not _data.get("ochiq"):
        await _tell(matn + "\nRejim: sinov — ilovada faqat adminlar ko'radi. Ochish: /serial ochiq")
    elif yangi and ("s%de%d" % se) not in _data["elon"]:
        await _tell(matn + "\nIlovada ko'rinadi. Odamlarga xabar berish uchun tugmani bosing "
                    "(boshqa tillarni ham tashlab bo'lgach).", _elon_tugma(*se))
    else:
        await _tell(matn)


def _photo(m):
    """Xabardagi rasm (yoki rasm hujjat) file_id si - bo'lmasa None."""
    if getattr(m, "photo", None):
        return max(m.photo, key=lambda x: (x.width or 0) * (x.height or 0)).file_id
    doc = getattr(m, "document", None)
    if doc and (doc.mime_type or "").startswith("image/"):
        return doc.file_id
    return None


async def on_group_photo(message: types.Message):
    """Serial mavzusiga RASM tashlandi, izohida qism raqami bor - o'sha qismning rasmi bo'ladi.
    Rasm hamma til uchun bitta (qaysi til mavzusiga tashlansa ham)."""
    fid = _photo(message)
    if not fid:
        return
    se = ep_of(message.caption or "")
    if not se:
        await _tell("🖼 Rasm tanilmadi (%d-xabar): izohiga qism raqamini yozing, masalan «1-fasl 3-qism»."
                    % message.message_id)
        return
    try:
        os.makedirs(COVER_DIR, exist_ok=True)
        tmp = cover_path(*se) + ".tmp"
        await _cfg["bot"].download(fid, destination=tmp)
        os.replace(tmp, cover_path(*se))
    except Exception as e:
        logging.error("Serial rasmi saqlanmadi (%s): %s", se, e)
        await _tell("⚠️ %d-fasl %d-qism rasmi saqlanmadi: %s" % (se[0], se[1], e))
        return
    await _tell("🖼 %d-fasl %d-qism rasmi saqlandi." % se)


async def api_cover(request):
    m = re.match(r"^s(\d{1,2})e(\d{1,3})$", request.match_info.get("key", ""))
    path = cover_path(int(m.group(1)), int(m.group(2))) if m else None
    if not path or not os.path.isfile(path):
        return _cfg["cors"](web.Response(status=404))
    return _cfg["cors"](web.FileResponse(path, headers={"Cache-Control": "public, max-age=31536000, immutable"}))


# --- YANGI QISM E'LONI (boyo'g'li pochtasi + bot) ---

ELON = {
    "uz": ("Yangi qism chiqdi: %d-fasl, %d-qism", "Garri Potter seriali — kutubxonada sizni kutmoqda."),
    "ru": ("Вышла новая серия: сезон %d, серия %d", "Сериал «Гарри Поттер» — ждёт вас в библиотеке."),
    "en": ("New episode is out: Season %d, Episode %d", "The Harry Potter series is waiting in the library."),
}


async def on_elon(call: types.CallbackQuery):
    if not _is_admin_id(call.from_user.id):
        await call.answer()
        return
    try:
        _, s, e = call.data.split(":")
        s, e = int(s), int(e)
    except ValueError:
        await call.answer()
        return
    belgi = "s%de%d" % (s, e)
    tillar = [lang for lang in LANGS if key(s, e, lang) in _data["eps"]]
    if not _data.get("ochiq") or not tillar:
        await call.answer("Rejim sinov yoki qism yo'q — xabar yuborilmadi.", show_alert=True)
        return
    if belgi in _data["elon"]:
        await call.answer("Bu qism haqida allaqachon xabar berilgan.", show_alert=True)
        return
    _data["elon"].append(belgi)
    _save()
    await call.answer("Xabar yuborilmoqda…")
    try:
        await call.message.edit_reply_markup(reply_markup=None)
    except Exception:
        pass
    elon = _cfg.get("elon")
    if elon:
        # Faqat qismi bor tildagi odamlarga: o'z tilida yo'q qism haqida xabar chalg'itadi
        asyncio.create_task(elon({lang: (ELON[lang][0] % (s, e), ELON[lang][1]) for lang in tillar}))
    await _tell("📣 %d-fasl %d-qism haqida xabar ketmoqda (%s)." % (s, e, ", ".join(tillar)))


# --- HTTP ---

CAP = {
    "uz": ("Garri Potter · serial", "%d-fasl, %d-qism", "Til", "O'zbekcha"),
    "ru": ("Гарри Поттер · сериал", "Сезон %d, серия %d", "Язык", "Русский"),
    "en": ("Harry Potter · the series", "Season %d, Episode %d", "Language", "English"),
}
APP_LINK = "https://t.me/garripotterkinobot/catalog?startapp=serial"


def caption(s, e, lang, ui):
    c = CAP.get(ui) or CAP["uz"]
    brand = _cfg["brand"](ui) if _cfg.get("brand") else "GARRI POTTER"
    return "<b>%s</b>\n%s\n\n%s: %s\n\n✅ <b><a href=\"%s\">%s</a></b>" % (
        c[0], c[1] % (s, e), c[2], (CAP.get(lang) or c)[3], APP_LINK, brand)


async def api_list(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    user = _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", ""))
    uid = int(user["id"]) if user else None
    eps = public_list(uid)
    return cors(web.json_response({"ok": True, "eps": eps, "covers": covers() if eps else {},
                                   "test": not _data.get("ochiq") and _is_admin_id(uid)}))


async def api_send(request):
    """Ilova so'ragan qismni chatga yuboradi (filmlar kabi: himoyalangan nusxa)."""
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
    try:
        s, e = int(body.get("s", 0)), int(body.get("e", 0))
    except (TypeError, ValueError):
        s = e = 0
    lang = str(body.get("lang", "uz"))
    ui = str(body.get("ui", lang))
    if not _data.get("ochiq") and not _is_admin_id(uid):
        return cors(web.json_response({"ok": False, "error": "not_ready"}))
    manba = source(s, e, lang) if lang in LANGS else None
    if not manba:
        return cors(web.json_response({"ok": False, "error": "not_ready"}))
    hozir = time.time()
    if hozir - _oxirgi.get(uid, 0) < SEND_GAP:
        return cors(web.json_response({"ok": False, "error": "slow"}))
    _oxirgi[uid] = hozir
    chat = _cfg["tg_chat_id"](uid)
    if await _cfg["is_subscribed"](chat) is False:
        return cors(web.json_response({"ok": False, "error": "not_subscribed"}))
    try:
        sent = await _cfg["bot"].copy_message(chat_id=chat, from_chat_id=manba[0], message_id=manba[1],
                                              caption=caption(s, e, lang, ui), parse_mode="HTML",
                                              protect_content=True)
    except Exception as err:
        logging.error("Serial qismi yuborilmadi (%s): %s", key(s, e, lang), err)
        if "not found" in str(err).lower():
            await _tell("⚠️ Serial qismi yuborilmadi: %s — guruhdagi xabar topilmadi." % key(s, e, lang))
            return cors(web.json_response({"ok": False, "error": "film_missing"}))
        return cors(web.json_response({"ok": False, "error": "send_failed"}))
    if uid > 0 and _cfg.get("log"):
        try:
            await _cfg["log"](user, "sr_" + key(s, e, lang))
        except Exception as log_err:
            logging.error("Serial logi yozilmadi: %s", log_err)
    return cors(web.json_response({"ok": True, "message_id": sent.message_id}))


# --- ULASH ---

def register(dp, bot, app, cfg):
    """cfg: admin_ids, verify_init_data, cors, is_subscribed, tg_chat_id, log, brand, elon.
    hpfilms DAN OLDIN ulanadi (mavzu filtri alohida, lekin tartib aniq bo'lsin)."""
    _cfg.update(cfg)
    _cfg["bot"] = bot
    load()
    dp.message.register(on_serial_command, Command("serial"))
    dp.message.register(on_qism_command, Command("qism"))
    dp.message.register(on_group_photo, _in_serial_photo)
    dp.message.register(on_group_video, _in_serial_topic)
    dp.callback_query.register(on_elon, F.data.startswith("srl_elon:"))
    app.router.add_route("*", "/api/serial", api_list)
    app.router.add_route("*", "/api/serial/send", api_send)
    app.router.add_get("/api/serial/cover/{key}.jpg", api_cover)
    logging.info("Serial: %d ta qism-til, %d mavzu, rejim %s", len(_data["eps"]), len(_data["topics"]),
                 "ochiq" if _data.get("ochiq") else "sinov")
