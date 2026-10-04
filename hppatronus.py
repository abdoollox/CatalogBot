"""Patronus (egasi, 2026-10-04): testni ilova o'tkazadi, natija shu yerda saqlanadi.

Qoidalar: faqat saralangan o'quvchiga, FAQAT BIR MARTA (qayta topshirib bo'lmaydi), bepul.
15 ta Patronus - asardagi qahramonlarniki. Natija `users.patronus` ustunida.

API: /api/patronus
  {}            -> {ok, code, at}            hozirgi Patronus (yo'q bo'lsa code = null)
  {code: "stag"} -> birinchi marta yozadi; allaqachon bor bo'lsa O'SHANI qaytaradi (o'zgarmaydi)
"""

import asyncio
import logging
import os
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


def register(app, cfg):
    """cfg: verify_init_data, cors, log."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/patronus", api_patronus)
    logging.info("Patronus: %d xil", len(KODLAR))
