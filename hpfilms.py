# -*- coding: utf-8 -*-
"""Filmlar bazasi - yopiq GURUHDAN (mavzularga bo'lingan "Hogwarts Cinema").

Ilgari filmlar eski yopiq kanaldan (DB_CHANNEL_ID) va catalog.py ga QO'LDA
yozilgan xabar raqamlari bilan yuborilardi. Kanaldagi post o'chsa yoki
almashsa film jimgina ishlamay qolardi (2026-09-27 da hp1 shunday bo'ldi).
Endi manba - guruh: qaysi film qaysi xabarda ekanini bot o'zi aniqlaydi.

Sozlash (bir marta, admin):
    Filmlar turgan mavzuda `/filmlar` deb yozing. Bot guruh va mavzuni eslab
    qoladi va mavzudagi videolarni o'qiydi (musiqa skaneri usulida: har xabar
    adminning bot bilan shaxsiy chatiga nusxalab o'qiladi va darhol o'chiriladi;
    guruhga hech narsa yozilmaydi). Natija - shaxsiy chatda jadval.
    `/filmlar 1200` - 1200-xabardan boshlab o'qiydi (mavzu ildizidan emas).

Qaysi film va til - video nomidan / izohidan:
    "Harry Potter and the Philosopher's Stone (2001)(1080p)(uz).mp4" -> hp1_uz
    Aniqlanmaganlari jadvalda alohida ko'rsatiladi, ularni qo'lda bog'lash:
        /film hp1_uz 1234     - hp1 o'zbekchasi guruhdagi 1234-xabar
        /film hp1_uz -        - bog'lanishni olib tashlash (eski kanalga qaytadi)
        /film                 - hozirgi holat (shaxsiy chatda)
Mavzuga keyin yangi video tashlansa - o'zi taniladi va adminga xabar boradi.

Bog'lanmagan film eski kanaldan yuborilaveradi - hech narsa buzilmaydi.
"""

import asyncio
import json
import logging
import os
import re

from aiogram import types
from aiogram.filters import Command

import catalog
import hpmusic          # guruhni o'qish vositalari (_peek, _inbox, _tg) - bir xil usul

STORE = "/data/films.json"     # MUTLAQ yo'l: faqat /data konteynerdan tashqarida yashaydi
SCAN_PACE = 0.35

_cfg = {}
_data = {"group": None, "thread": None, "map": {}, "seen": {}}
_scan_task = None


# --- SAQLASH ---

def load():
    global _data
    try:
        with open(STORE, encoding="utf-8") as f:
            d = json.load(f)
        for k, v in (("group", None), ("thread", None), ("map", {}), ("seen", {})):
            d.setdefault(k, v)
        _data = d
    except FileNotFoundError:
        pass
    except Exception as e:
        logging.error("films.json o'qilmadi: %s", e)


def _save():
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, STORE)


# --- YUBORISH UCHUN MANBA ---

def source(movie_key, lang):
    """(chat_id, message_id) - film qayerdan nusxalanadi. Guruhda bo'lmasa - None."""
    item = _data["map"].get("%s_%s" % (movie_key, lang))
    if item and _data.get("group"):
        return _data["group"], int(item["mid"])
    return None


def in_group(movie_key, lang):
    return source(movie_key, lang) is not None


# --- NOMDAN FILM VA TIL ---

_FB_WORDS = ("fantastic", "beasts", "fantastik", "maxluq", "твари", "фантастич")


def film_of(text):
    """Matndan film id si (hp1..hp8, fb1..fb3) yoki None."""
    n = (text or "").lower().replace("’", "'").replace("_", " ").replace(".", " ")
    if any(w in n for w in _FB_WORDS):
        if any(w in n for w in ("grindelwald", "гриндельвальд", "crimes", "jinoyat", "преступлен")):
            return "fb2"
        if any(w in n for w in ("dumbledore", "дамблдор", "dambldor", "secrets", "тайны", "sirlar")):
            return "fb3"
        m = re.search(r"\b([123])\b", re.sub(r"\b(19|20)\d\d\b|\d{3,4}p\b", " ", n))
        return "fb" + m.group(1) if m else "fb1"
    # Garri Potter: yil va sifat raqamlari ("2001", "1080p") chalg'itmasin
    clean = re.sub(r"\b(19|20)\d\d\b|\b\d{3,4}p\b|\b[hx]26[45]\b", " ", n)
    album = hpmusic.title_album(clean)
    if album:
        return album
    for line in clean.splitlines():
        a = hpmusic.title_album(line)
        if a:
            return a
    return None


_LANG = [
    ("uz", re.compile(r"(^|[^a-z])(uz|uzb|o'?zbek\w*|uzbek\w*|узб\w*)([^a-z]|$)")),
    ("ru", re.compile(r"(^|[^a-z])(ru|rus|russian|рус\w*)([^a-z]|$)")),
    ("en", re.compile(r"(^|[^a-z])(en|eng|english|ingliz\w*|англ\w*)([^a-z]|$)")),
]


def lang_of(text):
    n = (text or "").lower().replace("’", "'")
    found = [code for code, rx in _LANG if rx.search(n)]
    return found[0] if len(found) == 1 else None


def _video(m):
    """Xabardagi video (yoki video hujjat) - bo'lmasa None."""
    if m is None:
        return None
    if m.video:
        return m.video
    doc = m.document
    if doc and (doc.mime_type or "").startswith("video/"):
        return doc
    return None


def _item(mid, m, v):
    return {"mid": mid, "name": getattr(v, "file_name", None) or "",
            "cap": (m.caption or "")[:300], "size": int(getattr(v, "file_size", 0) or 0),
            "dur": int(getattr(v, "duration", 0) or 0)}


def _guess(it):
    text = "%s\n%s" % (it["name"], it["cap"])
    return film_of(text), lang_of(text)


# --- HISOBOT ---

def table_text():
    flag = {"uz": "🇺🇿", "ru": "🇷🇺", "en": "🇬🇧"}
    qator = ["🎬 Filmlar manbasi (✅ guruh · 📦 eski kanal · ❌ yo'q)", ""]
    for fid in catalog.FILMS:
        belgilar = []
        for l in catalog.LANGS:
            if in_group(fid, l):
                b = "✅"
            elif catalog.is_ready(fid, l):
                b = "📦"
            else:
                b = "❌"
            belgilar.append(flag[l] + b)
        qator.append("%-4s %s" % (fid, "  ".join(belgilar)))
    return "\n".join(qator)


async def _tell(text):
    bot = _cfg["bot"]
    for uid in sorted(_cfg.get("admin_ids", ())):
        try:
            await hpmusic._tg(bot.send_message, uid, text[:4000], disable_notification=True)
            return
        except Exception:
            continue


def _place(it, film, lang):
    """Topilgan videoni jadvalga qo'yadi. Joy bo'sh bo'lmasa - kattaroq xabar raqami (yangisi) ustun."""
    key = "%s_%s" % (film, lang)
    old = _data["map"].get(key)
    if old and old.get("manual"):
        return False                      # qo'lda bog'langanini skaner almashtirmaydi
    if old and int(old["mid"]) >= it["mid"]:
        return False
    _data["map"][key] = dict(it)
    return True


# --- SKANER ---

async def scan(chat, start, upto):
    bot = _cfg["bot"]
    inbox, note = await hpmusic._inbox(bot, "🎬 Filmlar mavzusini o'qiyapman — bu yerda bir lahza "
                                            "xabarlar ko'rinib o'chadi.")
    if not inbox:
        raise RuntimeError("hech bir admin bot bilan shaxsiy chat ochmagan (/start bosing)")
    topilgan, tanilmagan = 0, []
    for mid in range(start, upto):
        m = await hpmusic._peek(bot, chat, mid, inbox)
        v = _video(m)
        if v is not None:
            topilgan += 1
            it = _item(mid, m, v)
            film, lang = _guess(it)
            _data["seen"][str(mid)] = it
            if film and lang:
                _place(it, film, lang)
            else:
                tanilmagan.append(it)
        await asyncio.sleep(SCAN_PACE)
    _save()
    try:
        await bot.delete_message(inbox, note)
    except Exception:
        pass
    return topilgan, tanilmagan


async def _scan_job(chat, start, upto):
    global _scan_task
    try:
        n, tanilmagan = await scan(chat, start, upto)
        matn = "🎬 O'qib chiqdim: %d ta video.\n\n%s" % (n, table_text())
        if tanilmagan:
            matn += "\n\nNomidan tanilmaganlar (qo'lda: /film hp1_uz <raqam>):\n" + "\n".join(
                "• %d — %s" % (x["mid"], (x["name"] or x["cap"] or "?")[:70]) for x in tanilmagan[:30])
        await _tell(matn)
    except Exception as e:
        logging.error("Film skaneri to'xtadi: %s", e)
        await _tell("❌ Filmlarni o'qish to'xtadi: %s\nQayta /filmlar yozsangiz boshidan boshlaydi." % e)
    finally:
        _scan_task = None


# --- BUYRUQLAR ---

def _is_admin(message):
    u = message.from_user
    if u and u.id in _cfg.get("admin_ids", ()):
        return True
    return bool(message.sender_chat and message.sender_chat.id == message.chat.id)


async def on_scan_command(message: types.Message):
    global _scan_task
    if not _is_admin(message):
        return
    if message.chat.type == "private":
        await message.answer("Bu buyruq guruhda, filmlar turgan mavzuda yoziladi.\n\n" + table_text())
        return
    if message.chat.type != "supergroup":
        return
    if _scan_task and not _scan_task.done():
        await message.reply("O'qish allaqachon ketmoqda.")
        return
    thread = message.message_thread_id if message.is_topic_message else None
    bolak = (message.text or "").split()
    start = (thread or 0) + 1
    if len(bolak) > 1 and bolak[1].isdigit():
        start = int(bolak[1])
    upto = message.message_id
    _data.update({"group": message.chat.id, "thread": thread})
    _save()
    daq = max(1, round((upto - start) * (SCAN_PACE + 0.5) / 60))
    try:
        await message.delete()             # guruhda buyruq izi qolmasin
    except Exception:
        pass
    await _tell("🔎 Filmlar mavzusini o'qiyapman (~%d daq, %d xabar). Tugagach jadval yuboraman."
                % (daq, upto - start))
    _scan_task = asyncio.create_task(_scan_job(message.chat.id, start, upto))


async def on_film_command(message: types.Message):
    """Shaxsiy chatda: /film - holat; /film hp1_uz 1234 - qo'lda bog'lash; /film hp1_uz - - olib tashlash."""
    if message.chat.type != "private" or not _is_admin(message):
        return
    bolak = (message.text or "").split()
    if len(bolak) == 1:
        await message.answer(table_text())
        return
    key = bolak[1].lower()
    m = re.fullmatch(r"(hp[1-8]|fb[1-3])_(uz|ru|en)", key)
    if not m or len(bolak) < 3:
        await message.answer("Masalan: /film hp1_uz 1234  yoki  /film hp1_uz -")
        return
    if bolak[2] == "-":
        _data["map"].pop(key, None)
        _save()
        await message.answer("Olib tashlandi: %s (eski kanaldan yuboriladi)\n\n%s" % (key, table_text()))
        return
    if not bolak[2].isdigit() or not _data.get("group"):
        await message.answer("Avval guruhdagi filmlar mavzusida /filmlar yozing, keyin raqam bering.")
        return
    mid = int(bolak[2])
    m2 = await hpmusic._peek(_cfg["bot"], _data["group"], mid, message.chat.id)
    v = _video(m2)
    if v is None:
        await message.answer("%d-xabarda video topilmadi." % mid)
        return
    it = _item(mid, m2, v)
    it["manual"] = True
    _data["map"][key] = it
    _save()
    await message.answer("✅ %s -> guruhdagi %d-xabar (%s)\n\n%s" % (key, mid, it["name"] or "nomsiz", table_text()))


async def on_group_video(message: types.Message):
    """Filmlar mavzusiga yangi video tashlandi - o'zi taniladi."""
    v = _video(message)
    if v is None:
        return
    it = _item(message.message_id, message, v)
    film, lang = _guess(it)
    _data["seen"][str(it["mid"])] = it
    if film and lang and _place(it, film, lang):
        _save()
        await _tell("🎬 Yangi video bog'landi: %s_%s <- %d-xabar (%s)" % (film, lang, it["mid"], it["name"]))
    else:
        _save()
        await _tell("🎬 Yangi video tanilmadi: %d-xabar (%s)\nQo'lda: /film hp1_uz %d"
                    % (it["mid"], it["name"] or it["cap"][:60] or "nomsiz", it["mid"]))


def _in_films_topic(message):
    if not _data.get("group") or message.chat.id != _data["group"]:
        return False
    th = message.message_thread_id if message.is_topic_message else None
    return th == _data.get("thread")


# --- ULASH ---

def register(dp, bot, cfg):
    """cfg: admin_ids. hpmusic DAN KEYIN ulanadi (uning vositalari ishlatiladi),
    lekin guruhdagi musiqa handleridan OLDIN - filmlar mavzusi boshqa bo'lgani uchun
    ular to'qnashmaydi."""
    _cfg.update(cfg)
    _cfg["bot"] = bot
    load()
    dp.message.register(on_scan_command, Command("filmlar"))
    dp.message.register(on_film_command, Command("film"))
    dp.message.register(on_group_video, _in_films_topic)
    logging.info("Filmlar: %d ta film-til guruhdan", len(_data["map"]))
