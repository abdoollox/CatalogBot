"""Nishonlar (profil sahifasidagi yutuqlar) - egasi, 2026-10-04.

Nishon bazadagi mavjud izlardan hisoblanadi (olingan filmlar, fakultet, tayoqcha, ballar,
do'stlar, albom, serial), shuning uchun eski foydalanuvchilar ham o'z nishonlarini oladi.
Bir marta olingan nishon `nishon` jadvaliga yoziladi va qaytib olinmaydi.
Galleon berilmaydi (egasi: hozircha yo'q).

API: /api/nishon
  {}            -> o'zining ro'yxati: hamma nishon (olingan/olinmagan, bajarilish) + `yangi`
  {seen: true}  -> yangi nishonlar ko'rildi deb belgilanadi
  {uid: N}      -> boshqa odamning FAQAT olingan nishonlari (boshqalar ham ko'ra oladi)
"""

import asyncio
import logging
import os
import re
import sqlite3
import time

from aiohttp import web

DB_PATH = os.getenv("HP_DB_PATH", "/data/hp.db")
_cfg = {}

# Tartib ilovadagi ko'rinish tartibi. (kod, guruh)
NISHONLAR = (
    ("film_1", "kino"), ("film_8", "kino"), ("fb_3", "kino"), ("poliglot", "kino"),
    ("oquvchi", "yol"), ("tayoqcha", "yol"), ("patronus", "yol"),
    ("ball_1", "kubok"), ("streak_7", "kubok"), ("perfect_week", "kubok"),
    ("kubok_golib", "kubok"), ("top_3", "kubok"),
    ("dost_1", "dostlik"), ("dost_5", "dostlik"), ("shaxmat", "dostlik"),
    ("albom", "kolleksiya"), ("serial_1", "kolleksiya"),
)
KODLAR = tuple(k for k, _ in NISHONLAR)

_FILM = re.compile(r"^(?:web_)?((?:hp[1-8])|(?:fb[1-3]))_(uz|ru|en)(?:@\w+)?$")
_SERIAL = re.compile(r"^(?:web_)?sr_s\d+e\d+_")


def _db():
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    return conn


def _init():
    conn = _db()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS nishon ("
            " user_id INTEGER NOT NULL, code TEXT NOT NULL, vaqt TEXT NOT NULL,"
            " korildi INTEGER NOT NULL DEFAULT 0, PRIMARY KEY (user_id, code))")
        conn.commit()
    finally:
        conn.close()


def _one(conn, sql, args=()):
    """Jadval yoki ustun hali bo'lmasa ham yiqilmaydi."""
    try:
        return conn.execute(sql, args).fetchone()
    except sqlite3.OperationalError:
        return None


def _all(conn, sql, args=()):
    try:
        return conn.execute(sql, args).fetchall()
    except sqlite3.OperationalError:
        return []


def _top3(conn, uid):
    """Yopilgan haftalarning birortasida saralanganlar orasida eng ko'p ball to'plagan uchlikdami."""
    if _one(conn, "SELECT 1 FROM galleon_mukofot WHERE user_id=? AND top>0", (uid,)):
        return True
    for s in _all(conn, "SELECT DISTINCT p.season_id FROM points p JOIN seasons s ON s.id=p.season_id "
                        "WHERE p.user_id=? AND s.status='closed'", (uid,)):
        ilk = _all(conn,
                   "SELECT p.user_id FROM points p JOIN users u ON u.user_id=p.user_id "
                   "WHERE p.season_id=? AND u.house IS NOT NULL AND p.user_id>0 "
                   "GROUP BY p.user_id ORDER BY SUM(p.points) DESC, MAX(p.created_at) LIMIT 3", (s[0],))
        if any(r[0] == uid for r in ilk):
            return True
    return False


def hisob(conn, uid):
    """{kod: (bor, kerak)} - bor >= kerak bo'lsa nishon olingan."""
    uid = int(uid)
    filmlar, tillar, serial = set(), set(), False
    for r in _all(conn, "SELECT DISTINCT payload FROM events WHERE user_id=?", (uid,)):
        m = _FILM.match(r[0] or "")
        if m:
            filmlar.add(m.group(1))
            tillar.add(m.group(2))
        elif _SERIAL.match(r[0] or ""):
            serial = True
    hp = len([f for f in filmlar if f.startswith("hp")])
    fb = len([f for f in filmlar if f.startswith("fb")])

    u = _one(conn, "SELECT house, refs FROM users WHERE user_id=?", (uid,))
    house = u["house"] if u else None
    refs = int(u["refs"] or 0) if u else 0
    w = _one(conn, "SELECT wand_at FROM users WHERE user_id=?", (uid,))
    wand = bool(w and w[0])
    pt = _one(conn, "SELECT patronus FROM users WHERE user_id=?", (uid,))
    patronus = bool(pt and pt[0])

    ball = bool(_one(conn, "SELECT 1 FROM points WHERE user_id=? LIMIT 1", (uid,))
                or _one(conn, "SELECT 1 FROM points_arxiv WHERE user_id=? LIMIT 1", (uid,)))
    eski = {r[0] for r in _all(conn, "SELECT DISTINCT code FROM badges WHERE user_id=?", (uid,))}
    kun = _one(conn, "SELECT MAX(n) FROM (SELECT COUNT(DISTINCT DATE(created_at)) n FROM points "
                     "WHERE user_id=? GROUP BY season_id)", (uid,))
    kun = int(kun[0] or 0) if kun else 0
    if "streak_7" in eski:
        kun = 7
    golib = bool(_one(conn, "SELECT 1 FROM galleon_mukofot WHERE user_id=? AND golib>0", (uid,))) or bool(
        house and _one(conn, "SELECT 1 FROM points p JOIN seasons s ON s.id=p.season_id "
                             "WHERE p.user_id=? AND s.status='closed' AND s.winner_house=? LIMIT 1", (uid, house)))
    shaxmat = bool(_one(conn, "SELECT 1 FROM points WHERE user_id=? AND source_type='chess_win' LIMIT 1", (uid,))
                   or _one(conn, "SELECT 1 FROM chess_ratings WHERE user_id=? AND wins>0", (uid,)))
    albom = bool(_one(conn, "SELECT 1 FROM album_egasi WHERE user_id=? LIMIT 1", (uid,)))

    return {
        "film_1": (min(len(filmlar), 1), 1),
        "film_8": (hp, 8),
        "fb_3": (fb, 3),
        "poliglot": (len(tillar), 3),
        "oquvchi": (1 if house else 0, 1),
        "tayoqcha": (1 if wand else 0, 1),
        "patronus": (1 if patronus else 0, 1),
        "ball_1": (1 if ball else 0, 1),
        "streak_7": (min(kun, 7), 7),
        "perfect_week": (1 if "perfect_week" in eski else 0, 1),
        "kubok_golib": (1 if golib else 0, 1),
        "top_3": (1 if _top3(conn, uid) else 0, 1),
        "dost_1": (min(refs, 1), 1),
        "dost_5": (min(refs, 5), 5),
        "shaxmat": (1 if shaxmat else 0, 1),
        "albom": (1 if albom else 0, 1),
        "serial_1": (1 if serial else 0, 1),
    }


def _royxat(uid, seen=False):
    """O'zining ro'yxati. Yangi bajarilganlarni jadvalga yozadi."""
    uid = int(uid)
    conn = _db()
    try:
        h = hisob(conn, uid)
        bor = {r["code"]: r for r in conn.execute("SELECT code, vaqt, korildi FROM nishon WHERE user_id=?", (uid,))}
        hozir = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        yozildi = False
        for kod in KODLAR:
            if kod not in bor and h[kod][0] >= h[kod][1]:
                conn.execute("INSERT OR IGNORE INTO nishon (user_id, code, vaqt, korildi) VALUES (?,?,?,0)",
                             (uid, kod, hozir))
                bor[kod] = {"code": kod, "vaqt": hozir, "korildi": 0}
                yozildi = True
        yangi = [k for k in KODLAR if k in bor and not bor[k]["korildi"]]
        if seen and yangi:
            conn.execute("UPDATE nishon SET korildi=1 WHERE user_id=?", (uid,))
            yozildi = True
        if yozildi:
            conn.commit()
        lst = []
        for kod, guruh in NISHONLAR:
            b, k = h[kod]
            got = kod in bor
            lst.append({"code": kod, "group": guruh, "got": got, "at": bor[kod]["vaqt"] if got else None,
                        "have": k if got else min(b, k), "need": k})
        return {"ok": True, "list": lst, "new": [] if seen else yangi,
                "count": len([x for x in lst if x["got"]]), "total": len(lst)}
    finally:
        conn.close()


def _boshqa(uid):
    """Boshqa odamning olingan nishonlari (avval hisoblab yozib qo'yamiz - u ilovani ochmagan bo'lsa ham)."""
    uid = int(uid)
    conn = _db()
    try:
        if not _one(conn, "SELECT 1 FROM users WHERE user_id=?", (uid,)):
            return {"ok": True, "list": [], "count": 0, "total": len(KODLAR)}
        h = hisob(conn, uid)
        bor = {r["code"]: r["vaqt"] for r in conn.execute("SELECT code, vaqt FROM nishon WHERE user_id=?", (uid,))}
        hozir = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        yozildi = False
        for kod in KODLAR:
            if kod not in bor and h[kod][0] >= h[kod][1]:
                conn.execute("INSERT OR IGNORE INTO nishon (user_id, code, vaqt, korildi) VALUES (?,?,?,0)",
                             (uid, kod, hozir))
                bor[kod] = hozir
                yozildi = True
        if yozildi:
            conn.commit()
        lst = [{"code": k, "group": g, "got": True, "at": bor[k]} for k, g in NISHONLAR if k in bor]
        return {"ok": True, "list": lst, "count": len(lst), "total": len(KODLAR)}
    finally:
        conn.close()


async def api_nishon(request):
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
    boshqa = body.get("uid") or request.query.get("uid")
    try:
        if boshqa and int(boshqa) != uid:
            return cors(web.json_response(await asyncio.to_thread(_boshqa, int(boshqa))))
        return cors(web.json_response(await asyncio.to_thread(_royxat, uid, bool(body.get("seen")))))
    except (TypeError, ValueError):
        return cors(web.json_response({"ok": False, "error": "bad_uid"}, status=400))
    except Exception as e:
        logging.error("Nishonlar hisoblanmadi (%s): %s", uid, e)
        return cors(web.json_response({"ok": False, "error": "server"}, status=500))


def register(app, cfg):
    """cfg: verify_init_data, cors."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/nishon", api_nishon)
    logging.info("Nishonlar: %d ta", len(KODLAR))
