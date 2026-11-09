# -*- coding: utf-8 -*-
"""Donat (egasi, 2026-11-08): ixtiyoriy, reklamasiz; galleon yoki o'yinda ustunlik BERILMAYDI.

- To'lov tashqi xizmatda (taps.uz kabi; Click / Payme / Uzum). Havolani egasi botga yozadi:
  /donat havola https://...   (havola ochiq repoga yozilmaydi - /data/donat.json da)
  /donat                      - holat
  /donat ochir                - tugmani yashirish
  Havola bo'lmasa Direktor xonasida hech narsa ko'rinmaydi.
- Ilova havolani /api/goya javobidagi `donat` maydonidan oladi (hpgoya chaqiradi: havola()).
- Kim to'lagani avtomatik bilinmaydi: egasi paneldan (POST /api/donat/panel, X-Dash-Token)
  odamni Telegram nomi yoki id bilan topib «Xogvarts homiysi» nishonini beradi - jadval `homiy`,
  nishon hpnishon «homiy» (olinmaguncha ro'yxatda ko'rinmaydi), va Dambldordan rahmat xati
  (boyo'g'li pochtasi + bot).
"""
import asyncio
import json
import logging
import os
import re
import time

from aiogram import types
from aiogram.filters import Command
from aiohttp import web

import hpcup

PATH = os.getenv("HP_DONAT_PATH", "/data/donat.json")

RAHMAT = {
    "uz": ("Dambldordan rahmat",
           "Loyihaga qo'shgan hissangiz uchun katta rahmat! U G'oyalar kosasidagi g'oyalarni hayotga "
           "tatbiq etishga yordam beradi. Profilingizga «Xogvarts homiysi» nishoni qo'shildi."),
    "ru": ("Благодарность от Дамблдора",
           "Огромное спасибо за ваш вклад в проект! Он поможет воплотить идеи из Чаши идей. "
           "В ваш профиль добавлен значок «Покровитель Хогвартса»."),
    "en": ("Thank you from Dumbledore",
           "Thank you so much for supporting the project! Your contribution helps bring the ideas from "
           "the Idea Bowl to life. The «Patron of Hogwarts» badge has been added to your profile."),
}

_cfg = {}


# ---------------------------------------------------------------- havola

HAMMAGA = False   # egasi, 2026-11-09: donat qismi hozircha FAQAT ADMINGA ko'rinsin (True - hammaga)


def havola_kimga(admin):
    """Ilovaga beriladigan havola: hammaga ochiq bo'lmasa faqat adminga."""
    return havola() if (HAMMAGA or admin) else None


def havola():
    try:
        with open(PATH, encoding="utf-8") as f:
            return (json.load(f) or {}).get("havola") or None
    except Exception:
        return None


def _saqla(url):
    os.makedirs(os.path.dirname(PATH) or ".", exist_ok=True)
    tmp = PATH + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump({"havola": url, "vaqt": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}, f)
    os.replace(tmp, PATH)


def _togri(url):
    return bool(re.match(r"^https://[A-Za-z0-9.\-]+\.[A-Za-z]{2,}(/[^\s<>\"']*)?$", url or "")) and len(url) <= 300


# ---------------------------------------------------------------- homiylar

def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS homiy (user_id INTEGER PRIMARY KEY, vaqt TEXT NOT NULL, izoh TEXT)")
        conn.commit()
    finally:
        conn.close()


def top(kim):
    """Telegram nomi (@ bilan yoki @siz) yoki id -> (uid, ism, username) yoki None."""
    kim = (str(kim or "")).strip()
    conn = hpcup._connect()
    try:
        if re.match(r"^-?\d{1,15}$", kim):
            r = conn.execute("SELECT user_id, first_name, username FROM users WHERE user_id=?", (int(kim),)).fetchone()
        else:
            u = kim.lstrip("@").strip()
            if not re.match(r"^[A-Za-z0-9_]{3,40}$", u):
                return None
            r = conn.execute("SELECT user_id, first_name, username FROM users WHERE LOWER(username)=LOWER(?)", (u,)).fetchone()
        return (r["user_id"], r["first_name"] or "", r["username"] or "") if r else None
    finally:
        conn.close()


def ber(uid, izoh=""):
    """Homiy qiladi. True - yangi, False - oldin ham homiy edi."""
    _init()
    conn = hpcup._connect()
    try:
        bor = conn.execute("SELECT 1 FROM homiy WHERE user_id=?", (int(uid),)).fetchone()
        if bor:
            return False
        conn.execute("INSERT INTO homiy (user_id, vaqt, izoh) VALUES (?,?,?)",
                     (int(uid), time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()), (izoh or "")[:200]))
        conn.commit()
        return True
    finally:
        conn.close()


def olib_tashla(uid):
    _init()
    conn = hpcup._connect()
    try:
        n = conn.execute("DELETE FROM homiy WHERE user_id=?", (int(uid),)).rowcount
        conn.execute("DELETE FROM nishon WHERE user_id=? AND code='homiy'", (int(uid),))
        conn.commit()
        return n > 0
    except Exception:
        return False
    finally:
        conn.close()


def royxat():
    _init()
    conn = hpcup._connect()
    try:
        return [{"uid": r["user_id"], "ism": r["first_name"] or "", "username": r["username"] or "",
                 "house": r["house"], "vaqt": r["vaqt"], "izoh": r["izoh"] or ""}
                for r in conn.execute("SELECT h.user_id, h.vaqt, h.izoh, u.first_name, u.username, u.house "
                                      "FROM homiy h LEFT JOIN users u ON u.user_id=h.user_id ORDER BY h.vaqt DESC")]
    finally:
        conn.close()


# ---------------------------------------------------------------- panel

async def api_panel(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    if not _cfg["dash_ok"](request):
        return cors(web.json_response({"ok": False, "error": "bad_token"}, status=403))
    try:
        body = await request.json() if request.method == "POST" else {}
    except Exception:
        body = {}
    javob = {}
    if body.get("kim"):
        t = await asyncio.to_thread(top, body["kim"])
        if not t:
            return cors(web.json_response({"ok": False, "error": "topilmadi"}))
        yangi = await asyncio.to_thread(ber, t[0], body.get("izoh") or "")
        javob = {"berildi": {"uid": t[0], "ism": t[1], "username": t[2]}, "yangi": yangi}
        if yangi and _cfg.get("xat"):
            try:
                await _cfg["xat"](t[0], RAHMAT, True)
            except Exception as e:
                logging.warning("Homiy rahmat xati ketmadi (%s): %s", t[0], e)
    elif body.get("olib"):
        javob = {"olindi": await asyncio.to_thread(olib_tashla, body["olib"])}
    rows = await asyncio.to_thread(royxat)
    return cors(web.json_response(dict(javob, ok=True, rows=rows, havola=bool(havola()))))


# ---------------------------------------------------------------- admin buyrug'i

async def on_donat(message: types.Message):
    u = message.from_user
    if not (u and u.id in _cfg.get("admin_ids", ()) and message.chat.type == "private"):
        return
    bolak = (message.text or "").split()
    if len(bolak) > 2 and bolak[1].lower() == "havola":
        url = bolak[2].strip("<>\"'«»`")
        if not _togri(url):
            await message.answer("Havola noto'g'ri. Yozilishi: /donat havola https://...")
            return
        await asyncio.to_thread(_saqla, url)
        await message.answer("Donat havolasi saqlandi ✅ Direktor xonasida «Hissa qo'shish» tugmasi paydo bo'ldi.")
        return
    if len(bolak) > 1 and bolak[1].lower() == "ochir":
        await asyncio.to_thread(_saqla, None)
        await message.answer("Donat tugmasi yashirildi.")
        return
    h = havola()
    n = len(await asyncio.to_thread(royxat))
    await message.answer(("Donat havolasi: %s" % h if h else "Donat havolasi: yo'q (tugma ko'rinmaydi)") +
                         "\nHomiylar: %d kishi\n\nBuyruqlar: /donat havola https://...  |  /donat ochir\n"
                         "Homiy nishoni — panelda, «Fikrlar» bo'limida." % n)


def register(dp, app, cfg):
    """cfg: cors, dash_ok, admin_ids, xat (hppochta.odamga_xat)."""
    _cfg.update(cfg)
    _init()
    dp.message.register(on_donat, Command("donat"))
    app.router.add_route("*", "/api/donat/panel", api_panel)
    logging.info("Donat moduli ulandi")
