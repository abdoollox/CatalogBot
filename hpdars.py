# -*- coding: utf-8 -*-
"""Darslar (egasi, 2026-10-07): Xogvarts sahifasida kunlik savol o'rnida fanlar bo'limi.

Har fan - kichik interaktiv mashg'ulot, kuniga bir marta ball beradi. Faqat SARALANGANLARGA.
  tarix  - Sehrgarlik tarixi: bu KUNLIK SAVOL (ball eski yo'l bilan, 'daily'); bu yerda faqat holati.
  afsun  - Afsunlar: tayoqcha harakatini chizish. Bugungi afsun hammaga bir xil (sana bo'yicha).
  iksir  - Iksirlar: retsept bo'yicha masalliqlarni tartib bilan solish. Bugungi damlama hammaga bir xil.
Qolgan fanlar ilovada "Tez orada" bo'lib turadi - qo'shilganda DARSLAR ga yoziladi.

O'yin natijasini ilova xabar qiladi (kichik ball - soxtalashtirishga arzimaydi; kunlik sandiqdagi kabi).
Ball kubokka 'dars' manbasi bo'lib yoziladi (source_ref "afsun:2026-10-08"). Kun - Toshkent vaqti.

API: POST /api/dars
  {}               -> holat: {lessons: {tarix: {done}, afsun: {done, pts, item}, iksir: {...}}}
  {done: "afsun"}  -> dars bajarildi: {new, pts} + holat
"""

import asyncio
import datetime as _dt
import logging
import sqlite3

from aiohttp import web

import hpcup
import hpsandiq

_cfg = {}

# Kuniga beriladigan ball va shu fanning "kun mavzulari" (tartib ilovadagi ro'yxat bilan bir xil kodlar)
DARSLAR = {
    "afsun": {"pts": 5, "items": ("lumos", "leviosa", "alohomora", "expelliarmus", "accio", "protego",
                                  "incendio", "reparo", "stupefy", "aguamenti", "nox", "patronum")},
    "iksir": {"pts": 5, "items": ("boils", "forget", "shrink", "antidote", "wiggenweld", "uyqu",
                                  "skelegro", "living", "polyjuice", "felix")},
}
BOSHI = (2026, 10, 7)


def kun_mavzusi(dars, kun):
    """Shu kunning mavzusi (afsun yoki damlama kodi): ro'yxat bo'yicha aylanadi."""
    y, m, d = (int(x) for x in kun.split("-"))
    n = max(0, (_dt.date(y, m, d) - _dt.date(*BOSHI)).days)
    items = DARSLAR[dars]["items"]
    return items[n % len(items)]


def _bajarilgan(conn, uid, kun):
    """Bugun ball olingan darslar to'plami."""
    try:
        return {r[0].split(":")[0] for r in conn.execute(
            "SELECT source_ref FROM points WHERE user_id=? AND source_type='dars' AND source_ref LIKE ?",
            (uid, "%:" + kun))}
    except sqlite3.OperationalError:
        return set()


def _holat(uid, kun):
    conn = hpcup._connect()
    try:
        bor = _bajarilgan(conn, uid, kun)
        out = {"tarix": {"done": hpsandiq._daily_bajarildi(conn, uid, kun), "pts": hpcup.PTS_DAILY}}
        for kod, d in DARSLAR.items():
            out[kod] = {"done": kod in bor, "pts": d["pts"], "item": kun_mavzusi(kod, kun)}
        return out
    finally:
        conn.close()


def _ish(uid, dars):
    kun = hpcup.today_tk()
    if not hpcup._get_house(uid):
        return {"ok": False, "error": "no_house"}
    javob = {"ok": True, "kun": kun}
    if dars:
        if dars not in DARSLAR:
            return {"ok": False, "error": "unknown"}
        pts = DARSLAR[dars]["pts"]
        javob["new"] = bool(hpcup._award(uid, "dars", "%s:%s" % (dars, kun), pts))
        javob["pts"] = pts if javob["new"] else 0
    javob["lessons"] = _holat(uid, kun)
    return javob


async def api_dars(request):
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
    dars = body.get("done")
    try:
        res = await asyncio.to_thread(_ish, uid, str(dars) if dars else None)
    except Exception as e:
        logging.error("Dars holati hisoblanmadi (%s): %s", uid, e)
        return cors(web.json_response({"ok": False, "error": "server"}, status=500))
    if res.get("new") and _cfg.get("log"):
        try:
            await _cfg["log"](user, "dars_%s_%s" % (dars, res["lessons"][dars]["item"]))
        except Exception as e:
            logging.error("Dars logi yozilmadi: %s", e)
    return cors(web.json_response(res))


def register(app, cfg):
    """cfg: verify_init_data, cors, log."""
    _cfg.update(cfg)
    app.router.add_route("*", "/api/dars", api_dars)
    logging.info("Darslar: %s", ", ".join(DARSLAR))
