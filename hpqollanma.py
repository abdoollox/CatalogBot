# -*- coding: utf-8 -*-
"""Qo'llanma videolar ketma-ketligi (egasi, 2026-11-08).

Birinchi filmini olgan odamga 1 kundan keyin kanaldagi qo'llanma videolar bot orqali birin-ketin
yuboriladi - kuniga bittadan, faqat 10:00-21:00 (Toshkent). Maqsad: kutubxonadan Xogvartsga
(ilovaning qolgan qismiga) olib o'tish. Odam o'sha ishni allaqachon qilgan bo'lsa (xatni ochgan,
fakultetga tushgan ...) video o'tkazib yuboriladi. Videolar o'zbekcha, lekin hamma tildagilarga
boradi (egasi, 2026-11-08). Botni bloklagan yoki bot xabarlarini o'chirgan odamga hech narsa ketmaydi.

Video kanaldagi postdan nusxa qilinadi (copy_message: video + izoh), ostiga kanaldagi tugma.

Faqat ISHGA TUSHGANDAN KEYIN birinchi filmini olganlar oladi (BOSH) - eski odamlarga ommaviy
xabar bo'lib ketmasin. YOQIQ: False | "admin" (hech kimga avtomatik ketmaydi, /qollanma bilan
adminga ko'rik) | "hamma".

Admin buyruqlari (shaxsiy chat): /qollanma - butun ketma-ketlikni o'zingizga yuborish;
/qollanma holat - kim nechta video olgani.
"""
import asyncio
import logging
import os
import re
from datetime import datetime, timedelta

from aiogram import types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramForbiddenError, TelegramRetryAfter

import hpcup

YOQIQ = "hamma"   # egasi, 2026-11-08: «ma'qul»
BOSH = os.getenv("HP_QOLLANMA_BOSH", "2026-11-08 05:44:00")   # UTC; shundan keyin birinchi film olganlar
KUT = timedelta(days=1)          # birinchi filmdan keyin
ORALIQ = timedelta(days=1)       # videolar orasida
SOAT = (10, 21)                  # Toshkent
TILLAR = None                    # egasi: o'zbekcha videolar hamma tildagilarga ham boradi
BOT_URL = "https://t.me/garripotterkinobot?startapp="

# (kalit, kanal xabari, tugma, startapp, bajarilganmi - SQL: ? = user_id)
KETMA = [
    ("x", 39, "Xatni ochish", "q_xat",
     "SELECT 1 FROM onb_qadam WHERE user_id=? AND qadam='letter'"),
    ("tw", 40, "Tayoqchangizni olish", "q_tayoq",
     "SELECT 1 FROM onb_qadam WHERE user_id=? AND qadam='wand'"),
    ("f", 41, "Fakultetingizni bilish", "q_fakultet",
     "SELECT 1 FROM users WHERE user_id=? AND house IS NOT NULL"),
    ("p", 35, "Filmni ilovada ko'rish", "q_pleyer",
     "SELECT 1 FROM events WHERE user_id=? AND payload LIKE 'pleyer\\_%' ESCAPE '\\' LIMIT 1"),
    ("s", 36, "Soundtrack tinglash", "q_ost",
     "SELECT 1 FROM events WHERE user_id=? AND payload LIKE 'music\\_%' ESCAPE '\\' LIMIT 1"),
    ("k", 37, "Kitob o'qish", "q_kitob",
     "SELECT 1 FROM events WHERE user_id=? AND payload LIKE 'read\\_kt%' ESCAPE '\\' LIMIT 1"),
    ("g", 43, "G'oya yozish", "goya",
     "SELECT 1 FROM goya WHERE user_id=? LIMIT 1"),
]
_FILM = re.compile(r"^(?:web_|bot_)?[a-z]{2}\d+_(uz|ru|en)")

_cfg = {}


def _ulan():
    conn = hpcup._connect()
    conn.execute("CREATE TABLE IF NOT EXISTS qollanma_yubor (user_id INTEGER NOT NULL, kalit TEXT NOT NULL, "
                 "vaqt TEXT NOT NULL, holat TEXT, PRIMARY KEY (user_id, kalit))")
    return conn


def _vaqt(ts):
    return datetime.strptime(str(ts).replace("T", " ")[:19], "%Y-%m-%d %H:%M:%S")


def _iso(dt):
    return dt.strftime("%Y-%m-%d %H:%M:%S")


def _bajardi(conn, uid, sql):
    try:
        return bool(conn.execute(sql, (uid,)).fetchone())
    except Exception:
        return False


def _keyingi(conn, uid):
    """Shu odamga navbatdagi video (yuborilmagan va hali bajarilmagan ish) yoki None."""
    yub = {r["kalit"] for r in conn.execute("SELECT kalit FROM qollanma_yubor WHERE user_id=?", (uid,))}
    for v in KETMA:
        if v[0] in yub or _bajardi(conn, uid, v[4]):
            continue
        return v
    return None


def nomzodlar(hozir_utc=None):
    """[(uid, video)] - hozir video olishi kerak bo'lganlar (faqat YOQIQ == "hamma")."""
    hozir_utc = hozir_utc or datetime.utcnow()
    out = []
    conn = _ulan()
    try:
        birinchi = {}
        for r in conn.execute("SELECT user_id, payload, ts FROM events WHERE ts >= ? AND user_id > 0 ORDER BY id", (BOSH,)):
            if r["user_id"] not in birinchi and _FILM.match(r["payload"] or ""):
                birinchi[r["user_id"]] = r["ts"]
        for uid, ts in birinchi.items():
            if hozir_utc - _vaqt(ts) < KUT:
                continue
            # BOSH dan oldin film olgan bo'lsa - eski odam, olmaydi
            eski = False
            for r in conn.execute("SELECT payload FROM events WHERE user_id=? AND ts < ?", (uid, BOSH)):
                if _FILM.match(r["payload"] or ""):
                    eski = True
                    break
            if eski:
                continue
            u = conn.execute("SELECT lang FROM users WHERE user_id=?", (uid,)).fetchone()
            if TILLAR is not None and u is not None and u["lang"] not in TILLAR:
                continue
            try:
                s = conn.execute("SELECT bot FROM pochta_sozlama WHERE user_id=?", (uid,)).fetchone()
            except Exception:
                s = None
            if s is not None and not s["bot"]:
                continue
            ox = conn.execute("SELECT payload FROM events WHERE user_id=? AND payload IN ('blocked','start') "
                              "ORDER BY id DESC LIMIT 1", (uid,)).fetchone()
            if ox and ox["payload"] == "blocked":
                continue
            if conn.execute("SELECT 1 FROM qollanma_yubor WHERE user_id=? AND holat='bloklagan'", (uid,)).fetchone():
                continue
            oxirgi = conn.execute("SELECT MAX(vaqt) AS v FROM qollanma_yubor WHERE user_id=?", (uid,)).fetchone()["v"]
            if oxirgi and hozir_utc - _vaqt(oxirgi) < ORALIQ:
                continue
            v = _keyingi(conn, uid)
            if v:
                out.append((uid, v))
    finally:
        conn.close()
    return out


def _belgila(uid, kalit, holat, hozir_utc=None):
    conn = _ulan()
    try:
        conn.execute("INSERT OR REPLACE INTO qollanma_yubor (user_id, kalit, vaqt, holat) VALUES (?,?,?,?)",
                     (uid, kalit, _iso(hozir_utc or datetime.utcnow()), holat))
        conn.commit()
    finally:
        conn.close()


def tugmalar(v):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text=v[2], url=BOT_URL + v[3])]])


async def yubor(bot, uid, v):
    """Bitta videoni yuboradi; holat: yuborildi | bloklagan | xato."""
    for _ in range(2):
        try:
            await bot.copy_message(chat_id=uid, from_chat_id=_cfg["kanal"], message_id=v[1],
                                   reply_markup=tugmalar(v))
            return "yuborildi"
        except TelegramRetryAfter as e:
            await asyncio.sleep(min(int(e.retry_after) + 1, 60))
        except TelegramForbiddenError:
            return "bloklagan"
        except Exception as e:
            logging.error("Qo'llanma video %s -> %s: %s", v[0], uid, e)
            return "xato"
    return "xato"


async def aylana(bot):
    if YOQIQ != "hamma":
        return 0
    soat = hpcup.now_tk().hour
    if not (SOAT[0] <= soat < SOAT[1]):
        return 0
    n = 0
    for uid, v in await asyncio.to_thread(nomzodlar):
        holat = await yubor(bot, uid, v)
        await asyncio.to_thread(_belgila, uid, v[0], holat)
        n += 1
        await asyncio.sleep(0.1)
    if n:
        logging.info("Qo'llanma videolar: %d ta yuborildi", n)
    return n


async def kuzatuvchi(bot):
    while True:
        try:
            await aylana(bot)
        except Exception as e:
            logging.error("Qo'llanma kuzatuvchisi: %s", e)
        await asyncio.sleep(600)


def holat():
    conn = _ulan()
    try:
        odam = conn.execute("SELECT COUNT(DISTINCT user_id) AS n FROM qollanma_yubor").fetchone()["n"]
        qator = conn.execute("SELECT kalit, holat, COUNT(*) AS n FROM qollanma_yubor GROUP BY kalit, holat").fetchall()
    finally:
        conn.close()
    nom = {v[0]: v[2] for v in KETMA}
    s = ["Qo'llanma videolar — rejim: %s" % YOQIQ, "Olganlar: %d kishi" % odam]
    for v in KETMA:
        b = {r["holat"]: r["n"] for r in qator if r["kalit"] == v[0]}
        if b:
            s.append("• %s: %s" % (nom[v[0]], ", ".join("%s %d" % kv for kv in sorted(b.items()))))
    return "\n".join(s)


async def on_qollanma(message: types.Message):
    u = message.from_user
    if not (u and u.id in _cfg.get("admin_ids", ()) and message.chat.type == "private"):
        return
    bolak = (message.text or "").split()
    if len(bolak) > 1 and bolak[1].lower() == "holat":
        await message.answer(await asyncio.to_thread(holat))
        return
    await message.answer("Film olgan odam 1 kundan keyin shu videolarni kuniga bittadan oladi "
                         "(qilib bo'lgan ishiga oid video o'tkazib yuboriladi):")
    for i, v in enumerate(KETMA, 1):
        await message.answer("%d-kun" % i)
        await yubor(_cfg["bot"], u.id, v)
        await asyncio.sleep(0.4)


def register(dp, bot, cfg):
    _cfg.update(cfg)
    _cfg["bot"] = bot
    dp.message.register(on_qollanma, Command("qollanma"))
    asyncio.get_event_loop().create_task(kuzatuvchi(bot))
