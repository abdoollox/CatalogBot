# -*- coding: utf-8 -*-
"""Filmlar bazasi - yopiq GURUHDAN (mavzularga bo'lingan "Database" guruhi).

Ilgari filmlar eski yopiq kanaldan (DB_CHANNEL_ID) va catalog.py ga QO'LDA
yozilgan xabar raqamlari bilan yuborilardi. Kanaldagi post o'chsa yoki
almashsa film jimgina ishlamay qolardi (2026-09-27 da hp1 shunday bo'ldi).
Endi manba - guruh: qaysi film qaysi xabarda ekanini bot o'zi aniqlaydi.

Guruhda HAR TIL uchun alohida mavzu bor. Sozlash (bir marta, admin):
    o'zbekcha filmlar mavzusida:  /filmlar uz
    ruscha filmlar mavzusida:     /filmlar ru
    inglizcha filmlar mavzusida:  /filmlar en
Bot mavzu va uning tilini eslab qoladi, mavzudagi eski videolarni o'qiydi
(musiqa skaneri usulida: har xabar adminning bot bilan shaxsiy chatiga
nusxalab o'qiladi va darhol o'chiriladi; guruhga hech narsa yozilmaydi).
Natija - adminning shaxsiy chatida 11 film x 3 til jadvali.
`/filmlar uz 1200` - 1200-xabardan boshlab o'qiydi (mavzu ildizidan emas).

Qaysi film - video nomidan / izohidan ("...Philosopher's Stone...mp4" -> hp1).
Qaysi til - avval nomidan ("(uz)", "rus", "ENG"...), nomda bo'lmasa - mavzu
tilidan. ESKI xabarlarni o'qiganda xabar qaysi mavzudaligi bilinmaydi (Telegram
nusxada buni aytmaydi), shuning uchun tili faqat mavzudan olinganlari jadvalda
⚠️ bilan belgilanadi - tekshirib qo'yish kerak. YANGI tashlangan videoning
mavzusi aniq ma'lum - uning tili ishonchli.

Qo'lda (adminning bot bilan shaxsiy chatida):
    /film                 - hozirgi holat
    /film hp1_uz 1234     - hp1 o'zbekchasi guruhdagi 1234-xabar
    /film hp1_uz -        - bog'lanishni olib tashlash (eski kanalga qaytadi)
Bog'lanmagan film YUBORILMAYDI (eski kanal 2026-09-30 dan ishlatilmaydi) -
foydalanuvchi "tez orada" / tushunarli xabar ko'radi, admin ogohlantiriladi.

Zaxira ham shu guruhga: "Arxiv" mavzusida /arxiv yozilsa, backup_hp.py
kundalik arxivni o'sha mavzuga yuboradi (/data/backup_target.json).
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
BACKUP_TARGET = "/data/backup_target.json"
SCAN_PACE = 0.35
LANGS = ("uz", "ru", "en")

_cfg = {}
# topics: {mavzu raqami: til}; map: {"hp1_uz": video}; seen: {xabar: video};
# empty: o'qilgan, lekin video bo'lmagan xabarlar (qayta o'qilmasin)
_data = {"group": None, "topics": {}, "map": {}, "seen": {}, "empty": []}
_scan_task = None


# --- SAQLASH ---

def load():
    global _data
    try:
        with open(STORE, encoding="utf-8") as f:
            d = json.load(f)
        d.pop("thread", None)          # birinchi (bitta mavzuli) variant qoldig'i
        for k, v in (("group", None), ("topics", {}), ("map", {}), ("seen", {}), ("empty", [])):
            d.setdefault(k, v)
        _data = d
    except FileNotFoundError:
        pass
    except Exception as e:
        logging.error("films.json o'qilmadi: %s", e)


def _save():
    tmp = STORE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(_data, f, ensure_ascii=False)
    os.replace(tmp, STORE)


# --- YUBORISH UCHUN MANBA ---

# --- SIFAT (egasi, 2026-10-04) ---
# Har film-til bir nechta sifatda bo'lishi mumkin. Odamga "1080p/720p" emas, "Full HD" va "HD"
# deb ko'rsatiladi (hamma ham raqamlarni tushunmaydi). Jadval kaliti: Full HD - "hp1_uz"
# (avvalgidek, eski yozuvlar o'z joyida), boshqa sifat - "hp1_uz@hd".
QUALITIES = ("fhd", "hd", "sd")        # ko'rsatish tartibi: yaxshisi birinchi
Q_LABEL = {"fhd": "Full HD", "hd": "HD", "sd": "SD"}      # SD = 480p (egasi 2026-10-07 da qo'shdi: internet sust bo'lganlar uchun)
Q_PIX = {"fhd": "1080p", "hd": "720p", "sd": "480p"}
_Q_SD = re.compile(r"(?<![0-9])480\s*p?\b|\bsd\s*480\b", re.I)
_Q_HD = re.compile(r"(?<![0-9])720\s*p?\b|\bhd\s*720\b", re.I)
_Q_FHD = re.compile(r"(?<![0-9])1080\s*p?\b|full\s*hd|\bfhd\b", re.I)


def quality_of(it):
    """Videoning sifati: avval nomi/izohidan ("720p", "1080p"), bo'lmasa balandligidan."""
    text = "%s\n%s" % (it.get("name") or "", it.get("cap") or "")
    if _Q_SD.search(text):
        return "sd"
    if _Q_HD.search(text):
        return "hd"
    if _Q_FHD.search(text):
        return "fhd"
    # Balandlik: keng ekranli 720p = 534, 480p = 356 atrofida
    h = int(it.get("h") or 0)
    if 0 < h <= 500:
        return "sd"
    return "hd" if 0 < h <= 800 else "fhd"


def _mkey(movie_key, lang, q="fhd"):
    return "%s_%s" % (movie_key, lang) + ("" if q == "fhd" else "@" + q)


def qualities(movie_key, lang):
    """{sifat: fayl hajmi (bayt)} - shu film-tilda mavjud sifatlar."""
    if not _data.get("group"):
        return {}
    out = {}
    for q in QUALITIES:
        it = _data["map"].get(_mkey(movie_key, lang, q))
        if it:
            out[q] = int(it.get("size") or 0)
    return out


def source(movie_key, lang, q=None):
    """(chat_id, message_id) - film qayerdan nusxalanadi. Guruhda bo'lmasa - None.
    q berilmasa - mavjudlarining eng yaxshisi."""
    if not _data.get("group"):
        return None
    for one in ([q] if q else QUALITIES):
        item = _data["map"].get(_mkey(movie_key, lang, one))
        if item:
            return _data["group"], int(item["mid"])
    return None


def in_group(movie_key, lang):
    return source(movie_key, lang) is not None


def public_map():
    """Ilova uchun: {"hp1_uz": {"fhd": hajm, "hd": hajm}} - faqat bor sifatlar."""
    out = {}
    for fid in catalog.FILMS:
        for l in catalog.LANGS:
            qs = qualities(fid, l)
            if qs:
                out["%s_%s" % (fid, l)] = qs
    return out


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
    for line in [clean] + clean.splitlines():
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
            "dur": int(getattr(v, "duration", 0) or 0), "h": int(getattr(v, "height", 0) or 0)}


_SKIP = re.compile(r"\[\s*\d\s*\]|2160p|\b4k\b|ultra\s*hd|\buhd\b", re.I)


def _skip(it):
    """Hozircha ishlatilmaydigan video: 4K va qismlarga bo'lingan ("[1]", "[2]") nusxalar.
    Bot filmni BITTA fayl bilan yuboradi (1080p). Ingliz mavzusida 4K nusxalar ikki
    qismda turibdi - ular bog'lansa odam filmning yarmini olardi (2026-09-30).
    Kelajakdagi "sifat tanlash" uchun ular seen da saqlanib turadi."""
    return bool(_SKIP.search("%s\n%s" % (it["name"], it["cap"])))


def _guess(it, topic_lang):
    """(film, til, til_manbasi). Manba: "nom" - nomidan (ishonchli), "mavzu" - mavzudan."""
    text = "%s\n%s" % (it["name"], it["cap"])
    lang = lang_of(text)
    how = "nom"
    if not lang and topic_lang:
        lang, how = topic_lang, "mavzu"
    return film_of(text), lang, how


def rebuild():
    """Jadvalni o'qilgan videolardan qoidalar bo'yicha qayta tuzadi (qo'lda bog'langanlar qoladi).
    Qoida o'zgarsa guruhni qayta o'qish shart emas."""
    manual = {k: v for k, v in _data["map"].items() if v.get("by") == "qolda"}
    _data["map"] = dict(manual)
    noaniq = set(_data.get("noaniq", []))
    for _, it in sorted(_data["seen"].items(), key=lambda x: int(x[0])):
        if _skip(it) or it["mid"] in noaniq:
            continue
        film, lang, how = _guess(it, it.get("tl"))
        if film and lang:
            _place(it, film, lang, how)


# --- HISOBOT ---

def table_text():
    flag = {"uz": "🇺🇿", "ru": "🇷🇺", "en": "🇬🇧"}
    qator = ["🎬 Filmlar manbasi", "✅ guruh · ⚠️ guruh (tili mavzudan, tekshiring) · ❌ yo'q", ""]
    for fid in catalog.FILMS:
        belgilar = []
        for l in catalog.LANGS:
            it = _data["map"].get("%s_%s" % (fid, l))
            hd = _data["map"].get(_mkey(fid, l, "hd"))
            sd = _data["map"].get(_mkey(fid, l, "sd"))
            if it and _data.get("group"):
                b = "⚠️" if it.get("by") == "mavzu" else "✅"
            else:
                b = "❌"
            belgilar.append(flag[l] + b + ("+HD" if hd else "") + ("+SD" if sd else ""))
        qator.append("%-4s %s" % (fid, "  ".join(belgilar)))
    kopi = sum(1 for it in _data["seen"].values() if _skip(it))
    if kopi:
        qator += ["", "📀 4K / qismlarga bo'lingan videolar: %d ta — hozircha ishlatilmaydi (keyin sifat tanlash uchun)." % kopi]
    shubha = ["%s ← %d-xabar (%s)" % (k, v["mid"], (v["name"] or v["cap"] or "nomsiz")[:50])
              for k, v in sorted(_data["map"].items()) if v.get("by") == "mavzu"]
    if shubha:
        qator += ["", "⚠️ Tili nomidan emas, mavzudan olinganlar:"] + ["• " + x for x in shubha]
    return "\n".join(qator)


async def _tell(text):
    bot = _cfg["bot"]
    for uid in sorted(_cfg.get("admin_ids", ())):
        try:
            await hpmusic._tg(bot.send_message, uid, text[:4000], disable_notification=True)
            return
        except Exception:
            continue


def _place(it, film, lang, how):
    """Topilgan videoni jadvalga qo'yadi.

    Ustunlik: qo'lda bog'langan > tili nomidan aniqlangan > tili mavzudan olingan;
    teng bo'lsa - kattaroq xabar raqami (yangi yuklangani). Har SIFAT alohida o'rin:
    720p nusxa 1080p ning o'rnini egallamaydi."""
    key = _mkey(film, lang, quality_of(it))
    it = dict(it, by=how)
    old = _data["map"].get(key)
    if old:
        rank = {"qolda": 3, "nom": 2, "mavzu": 1}
        if rank.get(old.get("by"), 2) > rank[how]:
            return False
        if rank.get(old.get("by"), 2) == rank[how] and int(old["mid"]) >= it["mid"]:
            return False
    _data["map"][key] = it
    return True


# --- SKANER ---

async def scan(chat, start, upto, topic_lang):
    bot = _cfg["bot"]
    inbox, note = await hpmusic._inbox(bot, "🎬 Filmlar mavzusini o'qiyapman — bu yerda bir lahza "
                                            "xabarlar ko'rinib o'chadi.")
    if not inbox:
        raise RuntimeError("hech bir admin bot bilan shaxsiy chat ochmagan (/start bosing)")
    empty = set(_data["empty"])
    noaniq = set(_data.get("noaniq", []))
    topilgan, tanilmagan = 0, []
    for mid in range(start, upto):
        it = _data["seen"].get(str(mid))
        if it is None and mid not in empty:
            # Boshqa mavzuni o'qiganda ko'rilgan xabar qayta o'qilmaydi
            m = await hpmusic._peek(bot, chat, mid, inbox)
            v = _video(m)
            if v is None:
                empty.add(mid)
            else:
                it = _item(mid, m, v)
                _data["seen"][str(mid)] = it
            await asyncio.sleep(SCAN_PACE)
        if it is None:
            continue
        topilgan += 1
        if _skip(it):
            continue
        if topic_lang and not it.get("tl"):
            it["tl"] = topic_lang        # qayta hisoblash (rebuild) uchun
        film, lang, how = _guess(it, topic_lang)
        if film and lang and how == "mavzu":
            # Tili nomida yo'q video ikki mavzuning oralig'iga tushsa - qaysi
            # mavzudaligi noma'lum: hech qaysi tilga bog'lanmaydi, qo'lda tanlanadi.
            boshqa = [k for k, v in _data["map"].items()
                      if v.get("by") == "mavzu" and v["mid"] == it["mid"] and not k.endswith("_" + lang)]
            if boshqa:
                for k in boshqa:
                    _data["map"].pop(k, None)
                noaniq.add(it["mid"])
            if it["mid"] in noaniq or it["mid"] in _data.setdefault("noaniq", []):
                tanilmagan.append(it)
                continue
        if film and lang:
            _place(it, film, lang, how)
        else:
            tanilmagan.append(it)
    _data["empty"] = sorted(empty)
    _data["noaniq"] = sorted(noaniq)
    _save()
    try:
        await bot.delete_message(inbox, note)
    except Exception:
        pass
    return topilgan, tanilmagan


async def _scan_job(chat, start, upto, topic_lang):
    global _scan_task
    try:
        n, tanilmagan = await scan(chat, start, upto, topic_lang)
        matn = "🎬 O'qib chiqdim (%s mavzusi): %d ta video.\n\n%s" % (topic_lang, n, table_text())
        if tanilmagan:
            matn += "\n\nNomidan tanilmaganlar (qo'lda: /film hp1_uz <raqam>):\n" + "\n".join(
                "• %d — %s" % (x["mid"], (x["name"] or x["cap"] or "?")[:70]) for x in tanilmagan[:30])
        await _tell(matn)
    except Exception as e:
        logging.error("Film skaneri to'xtadi: %s", e)
        await _tell("❌ Filmlarni o'qish to'xtadi: %s\nQayta /filmlar yozsangiz davom etadi." % e)
    finally:
        _scan_task = None


# --- BUYRUQLAR ---

def _is_admin(message):
    u = message.from_user
    if u and u.id in _cfg.get("admin_ids", ()):
        return True
    return bool(message.sender_chat and message.sender_chat.id == message.chat.id)


async def on_scan_command(message: types.Message):
    """Guruhdagi til mavzusida: /filmlar uz  (ixtiyoriy: /filmlar uz 1200)."""
    global _scan_task
    if not _is_admin(message):
        return
    if message.chat.type == "private":
        await message.answer("Bu buyruq guruhda, har til mavzusida yoziladi: /filmlar uz, /filmlar ru, "
                             "/filmlar en\n\n" + table_text())
        return
    if message.chat.type != "supergroup":
        return
    bolak = (message.text or "").split()
    lang = next((b.lower() for b in bolak[1:] if b.lower() in LANGS), None)
    try:
        await message.delete()             # guruhda buyruq izi qolmasin
    except Exception:
        pass
    if not lang:
        await _tell("Mavzu tilini ham yozing: /filmlar uz (yoki ru, en).")
        return
    if _scan_task and not _scan_task.done():
        await _tell("O'qish allaqachon ketmoqda — tugagach keyingi mavzuda yozing.")
        return
    thread = message.message_thread_id if message.is_topic_message else None
    start = (thread or 0) + 1
    raqam = [b for b in bolak[1:] if b.isdigit()]
    if raqam:
        start = int(raqam[0])
    upto = message.message_id
    _data["group"] = message.chat.id
    _data["topics"][str(thread)] = lang
    _save()
    bosh = set(_data["empty"])
    yangi = sum(1 for mid in range(start, upto) if str(mid) not in _data["seen"] and mid not in bosh)
    daq = max(1, round(yangi * (SCAN_PACE + 0.5) / 60))
    await _tell("🔎 %s mavzusini o'qiyapman (~%d daq). Tugagach jadval yuboraman." % (lang, daq))
    _scan_task = asyncio.create_task(_scan_job(message.chat.id, start, upto, lang))


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
    # Ixtiyoriy sifat: /film hp1_uz hd 1234 (yozilmasa - Full HD)
    if m and len(bolak) > 2 and bolak[2].lower() in QUALITIES:
        key = _mkey(m.group(1), m.group(2), bolak.pop(2).lower())
    if not m or len(bolak) < 3:
        await message.answer("Masalan: /film hp1_uz 1234  ·  /film hp1_uz hd 1234  ·  /film hp1_uz -")
        return
    if bolak[2] == "-":
        _data["map"].pop(key, None)
        _save()
        await message.answer("Olib tashlandi: %s (endi yuborilmaydi)\n\n%s" % (key, table_text()))
        return
    if not bolak[2].isdigit() or not _data.get("group"):
        await message.answer("Avval guruhdagi til mavzusida /filmlar uz yozing, keyin raqam bering.")
        return
    mid = int(bolak[2])
    m2 = await hpmusic._peek(_cfg["bot"], _data["group"], mid, message.chat.id)
    v = _video(m2)
    if v is None:
        await message.answer("%d-xabarda video topilmadi." % mid)
        return
    it = _item(mid, m2, v)
    _data["seen"][str(mid)] = it
    _data["map"][key] = dict(it, by="qolda")
    _save()
    await message.answer("✅ %s -> guruhdagi %d-xabar (%s)\n\n%s" % (key, mid, it["name"] or "nomsiz", table_text()))


async def on_stream_test(message: types.Message):
    """Shaxsiy chatda (admin): /oqim hp1_uz hd - oqim (stream) nega ishlamayotganini ajratish uchun
    filmni IKKI XIL yuboradi: A - himoyalangan (odamlarga boradigan holat), B - himoyasiz.
    Qaysi biri darhol ochilsa - sabab shundan bilinadi."""
    if message.chat.type != "private" or not _is_admin(message):
        return
    bolak = (message.text or "").split()
    m = re.fullmatch(r"(hp[1-8]|fb[1-3])_(uz|ru|en)", bolak[1].lower()) if len(bolak) > 1 else None
    q = bolak[2].lower() if len(bolak) > 2 and bolak[2].lower() in QUALITIES else None
    manba = source(m.group(1), m.group(2), q) if m else None
    if not manba:
        await message.answer("Masalan: /oqim hp1_uz hd")
        return
    bot = _cfg["bot"]
    for nom, himoya in (("A — himoyalangan (hozir odamlarga shunday boradi)", True), ("B — himoyasiz", False)):
        try:
            await bot.copy_message(chat_id=message.chat.id, from_chat_id=manba[0], message_id=manba[1],
                                   caption="Oqim sinovi: " + nom, protect_content=himoya)
        except Exception as e:
            await message.answer("%s yuborilmadi: %s" % (nom, e))


def _topic_of(message):
    return str(message.message_thread_id if message.is_topic_message else None)


def _in_films_topic(message):
    if not _data.get("group") or message.chat.id != _data["group"]:
        return False
    return _topic_of(message) in _data["topics"]


async def on_group_video(message: types.Message):
    """Til mavzusiga yangi video tashlandi - o'zi taniladi (mavzusi aniq, tili ishonchli)."""
    v = _video(message)
    if v is None:
        return
    it = _item(message.message_id, message, v)
    topic_lang = _data["topics"].get(_topic_of(message))
    it["tl"] = topic_lang
    film = film_of("%s\n%s" % (it["name"], it["cap"]))
    _data["seen"][str(it["mid"])] = it
    if _skip(it):
        _save()
        await _tell("🎬 4K / qismli video saqlandi, lekin hozircha ishlatilmaydi: %d-xabar (%s)"
                    % (it["mid"], it["name"]))
        return
    if film and topic_lang and _place(it, film, topic_lang, "nom"):
        _save()
        await _tell("🎬 Yangi video bog'landi: %s_%s · %s ← %d-xabar (%s)"
                    % (film, topic_lang, Q_LABEL[quality_of(it)], it["mid"], it["name"]))
    else:
        _save()
        await _tell("🎬 Yangi video tanilmadi: %d-xabar (%s)\nQo'lda: /film hp1_%s %d"
                    % (it["mid"], it["name"] or it["cap"][:60] or "nomsiz", topic_lang or "uz", it["mid"]))


async def on_archive_command(message: types.Message):
    """"Arxiv" mavzusida /arxiv - kundalik zaxira shu mavzuga yuboriladi."""
    if not _is_admin(message) or message.chat.type != "supergroup":
        return
    thread = message.message_thread_id if message.is_topic_message else None
    tmp = BACKUP_TARGET + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"chat": message.chat.id, "thread": thread}, f)
    os.replace(tmp, BACKUP_TARGET)
    try:
        await message.delete()
    except Exception:
        pass
    await hpmusic._tg(_cfg["bot"].send_message, message.chat.id,
                      "🗄 Kundalik zaxira har kecha soat 03:00 da shu mavzuga keladi.",
                      message_thread_id=thread, disable_notification=True)


# --- ULASH ---

def register(dp, bot, cfg):
    """cfg: admin_ids. hpmusic DAN KEYIN ulanadi (uning vositalari ishlatiladi)."""
    _cfg.update(cfg)
    _cfg["bot"] = bot
    load()
    if _data["seen"]:
        rebuild()
        _save()
    dp.message.register(on_scan_command, Command("filmlar"))
    dp.message.register(on_film_command, Command("film"))
    dp.message.register(on_stream_test, Command("oqim"))
    dp.message.register(on_archive_command, Command("arxiv"))
    dp.message.register(on_group_video, _in_films_topic)
    logging.info("Filmlar: %d ta film-til guruhdan, %d mavzu", len(_data["map"]), len(_data["topics"]))
