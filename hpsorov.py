"""So'rovnoma (egasi, 2026-10-12): o'quvchilardan fikr so'rash - birinchisi turnirlar boshlanish vaqti haqida.

Diqqat: «ovoz berish» egasi rad etgan narsalar ro'yxatida turadi - bu so'rovnomani egasi O'ZI so'radi (o'quvchi turnirlarni 22:00 ga
ko'chirishni taklif qilgan). Yangi so'rovnoma faqat egasi aytganda qo'shiladi.

Bitta faol so'rovnoma (SOROV). Faqat saralangan o'quvchilar; har kim bitta ovoz, muddat tugaguncha o'zgartira oladi.
Natija (har variantga nechta ovoz) faqat ovoz bergandan keyin ko'rinadi. YOQIQ = False bo'lsa faqat adminlarga ko'rinadi (ko'rik).
So'rovlar - POST /api/sorov: {} holat, {vote: "<variant>"} ovoz.
"""

import asyncio
import logging
from datetime import datetime

from aiohttp import web

import hpcup

YOQIQ = True                   # egasi 2026-10-12 da tasdiqladi: variantlar 20/21/22, 18-oktabrgacha, faqat bosh sahifada (xabar yuborilmaydi)
SOROV = {
    "id": "turnir-vaqti-1",
    "tugaydi": "2026-10-18T23:59:00+05:00",
    "variantlar": ("20", "21", "22"),      # soat (Toshkent)
}

_cfg = {}


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS sorov_ovoz (sorov TEXT NOT NULL, user_id INTEGER NOT NULL, variant TEXT NOT NULL, vaqt TEXT NOT NULL,"
                     " PRIMARY KEY (sorov, user_id))")
        conn.commit()
    finally:
        conn.close()


def _tugash():
    return datetime.fromisoformat(SOROV["tugaydi"]).timestamp()


def _ochiq():
    return hpcup.now_tk().timestamp() < _tugash()


def _ovoz(uid, variant):
    if variant not in SOROV["variantlar"] or not _ochiq():
        return False
    conn = hpcup._connect()
    try:
        conn.execute("INSERT INTO sorov_ovoz (sorov, user_id, variant, vaqt) VALUES (?,?,?,?) "
                     "ON CONFLICT(sorov, user_id) DO UPDATE SET variant=excluded.variant, vaqt=excluded.vaqt",
                     (SOROV["id"], int(uid), variant, hpcup._utc_iso(hpcup.now_tk())))
        conn.commit()
        return True
    finally:
        conn.close()


def _holat(uid, admin):
    if not YOQIQ and not admin:
        return {"ok": True, "on": False}
    conn = hpcup._connect()
    try:
        men = conn.execute("SELECT variant FROM sorov_ovoz WHERE sorov=? AND user_id=?", (SOROV["id"], int(uid))).fetchone()
        javob = {"ok": True, "on": True, "id": SOROV["id"], "open": _ochiq(), "left": max(0, int(_tugash() - hpcup.now_tk().timestamp())),
                 "ends": SOROV["tugaydi"], "mine": men["variant"] if men else None, "preview": not YOQIQ,
                 "options": [{"k": v} for v in SOROV["variantlar"]]}
        if men or not _ochiq() or admin:          # natija - ovoz bergandan keyin (adminga doim)
            son = {r["variant"]: r["n"] for r in conn.execute("SELECT variant, COUNT(*) AS n FROM sorov_ovoz WHERE sorov=? GROUP BY variant", (SOROV["id"],))}
            for o in javob["options"]:
                o["n"] = son.get(o["k"], 0)
            javob["total"] = sum(son.values())
        return javob
    finally:
        conn.close()


async def api_sorov(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    try:
        body = await request.json()
    except Exception:
        body = {}
    user = _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", "") or str(body.get("initData", "")))
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
    uid = int(user["id"])
    if not hpcup._get_house(uid):
        return cors(web.json_response({"ok": False, "error": "no_house"}))
    admin = uid in (_cfg.get("admin_ids") or ())
    qosh = {}
    if body.get("vote") is not None and (YOQIQ or admin):
        qosh["vote_ok"] = await asyncio.to_thread(_ovoz, uid, str(body.get("vote")))
        if qosh["vote_ok"] and _cfg.get("log"):
            try:
                await _cfg["log"](user, "sorov_%s_%s" % (SOROV["id"], body.get("vote")))
            except Exception:
                pass
    javob = await asyncio.to_thread(_holat, uid, admin)
    javob.update(qosh)
    return cors(web.json_response(javob))


def register(app, cfg):
    """cfg: verify_init_data, cors, log, admin_ids."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/sorov", api_sorov)
    logging.info("So'rovnoma ulandi (%s)", "ochiq" if YOQIQ else "faqat adminlarga")
