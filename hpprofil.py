# -*- coding: utf-8 -*-
"""Sehrgar profili: boshqa odam (yoki o'zi) haqida ilovada ko'rinadigan ma'lumot.

POST /api/profil {uid} -> ism, fakultet, qachon saralangan, tayoqcha, Patronus, nishonlar,
ballar, filmlar, kartochkalar, shaxmat. Faqat ilova ichida allaqachon ochiq narsalar
(chatda ism va fakultet, nishonlar) - Telegram username, til, galleon KO'RSATILMAYDI.

Tayoqcha serverda alohida saqlanmaydi: ilova uni hodisa qilib yozadi ("wand_oak_phoenix_rigid"),
oxirgisi olinadi.
"""

import asyncio
import json
import logging
import os
import re
import sqlite3

from aiohttp import web

import hpcup
import hpnishon

DB_PATH = os.getenv("HP_DB_PATH", "/data/hp.db")
HERE = os.path.dirname(os.path.abspath(__file__))
_cfg = {}
_FILM = re.compile(r"^(?:web_)?((?:hp[1-8])|(?:fb[1-3]))_(?:uz|ru|en)(?:~\w+)?(?:@\w+)?$")
_WAND = re.compile(r"^wand_([a-z]+)_([a-z]+)_([a-z]+)$")

try:
    with open(os.path.join(HERE, "tayoqcha_matn.json"), encoding="utf-8") as _f:
        _T = json.load(_f)
except Exception:
    _T = {"woods": {}, "cores": {}, "flex": {}}


def wand_of(conn, uid):
    """Oxirgi tanlangan tayoqcha {wood, core, flex} yoki None."""
    for (p,) in conn.execute("SELECT payload FROM events WHERE user_id=? AND payload LIKE 'wand_%' "
                             "ORDER BY id DESC LIMIT 5", (uid,)):
        m = _WAND.match(p or "")
        if m and m.group(1) in _T["woods"] and m.group(2) in _T["cores"] and m.group(3) in _T["flex"]:
            return {"wood": m.group(1), "core": m.group(2), "flex": m.group(3)}
    return None


def _one(conn, sql, args=()):
    try:
        return conn.execute(sql, args).fetchone()
    except sqlite3.OperationalError:
        return None                      # jadval hali yo'q


def profil(uid, men):
    uid = int(uid)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    try:
        u = _one(conn, "SELECT first_name, house, sorted_at, created_at FROM users WHERE user_id=?", (uid,))
        if not u:
            return None
        ls = _one(conn, "SELECT last_seen_at FROM users WHERE user_id=?", (uid,))
        pt = _one(conn, "SELECT patronus FROM users WHERE user_id=?", (uid,))
        hafta = _one(conn, "SELECT COALESCE(SUM(p.points),0) FROM points p JOIN seasons s ON s.id=p.season_id "
                           "WHERE p.user_id=? AND s.status='active'", (uid,))
        jami = _one(conn, "SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=?", (uid,))
        filmlar = set()
        for (p,) in conn.execute("SELECT DISTINCT payload FROM events WHERE user_id=?", (uid,)):
            m = _FILM.match(p or "")
            if m:
                filmlar.add(m.group(1))
        karta = _one(conn, "SELECT COUNT(*) FROM qurbaqa WHERE user_id=?", (uid,))
        ch = _one(conn, "SELECT rating, games, wins FROM chess_ratings WHERE user_id=?", (uid,))
        out = {
            "ok": True, "uid": uid, "me": uid == int(men),
            "name": (u[0] or "").strip()[:40], "house": u[1], "since": (u[2] or u[3] or "")[:10],
            # Oxirgi marta ilovada bo'lgan vaqti (chatdagi kabi); hozir ilovada bo'lsa online
            "online": hpcup.presence_online(uid), "seen": hpcup.presence_seen(uid, ls[0] if ls else None),
            "wand": wand_of(conn, uid), "patronus": pt[0] if pt else None,
            "points": {"week": int(hafta[0]) if hafta else 0, "all": int(jami[0]) if jami else 0},
            "films": len(filmlar), "cards": int(karta[0]) if karta else 0,
            "chess": {"rating": int(ch[0]), "games": int(ch[1]), "wins": int(ch[2])} if ch and ch[1] else None,
        }
    finally:
        conn.close()
    try:
        b = hpnishon._boshqa(uid)
        out["badges"] = [x["code"] for x in b["list"]]
        out["badges_total"] = b["total"]
    except Exception as e:
        logging.error("Profil: nishonlar olinmadi (%s): %s", uid, e)
        out["badges"], out["badges_total"] = [], len(hpnishon.KODLAR)
    try:
        import hpqoriq
        out["creatures"] = hpqoriq.korinish(uid)          # qo'riqxonasi: [{kod, stage}]
    except Exception as e:
        logging.error("Profil: qo'riqxona olinmadi (%s): %s", uid, e)
        out["creatures"] = []
    try:
        import hpdars
        out["skills"] = hpdars.qobiliyat(uid)             # qobiliyatlar: [{id, score}]
    except Exception as e:
        logging.error("Profil: qobiliyatlar olinmadi (%s): %s", uid, e)
        out["skills"] = []
    return out


async def api_profil(request):
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
    try:
        uid = int(body.get("uid") or user["id"])
    except (TypeError, ValueError):
        return cors(web.json_response({"ok": False, "error": "bad_uid"}, status=400))
    try:
        res = await asyncio.to_thread(profil, uid, user["id"])
    except Exception as e:
        logging.error("Profil hisoblanmadi (%s): %s", uid, e)
        return cors(web.json_response({"ok": False, "error": "server"}, status=500))
    if not res:
        return cors(web.json_response({"ok": False, "error": "unknown"}, status=404))
    return cors(web.json_response(res))


def register(app, cfg):
    """cfg: verify_init_data, cors. hpnishon DAN KEYIN ulanadi."""
    _cfg.update(cfg)
    app.router.add_route("*", "/api/profil", api_profil)
