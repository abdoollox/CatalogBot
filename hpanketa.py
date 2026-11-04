"""So'rovnoma «Bizni qanday topdingiz?» (egasi, 2026-11-04): reklamada nimani ta'kidlash kerakligini o'quvchilarning o'zidan bilish.

Hamma foydalanuvchiga (saralanmaganga ham), bir marta. Savollar matni ilovada uch tilda (js/09-anketa.js), serverda faqat
kalitlar - ilova yuborgan javob shu ro'yxat bilan tekshiriladi. Yangi so'rovnoma: ANKETA ni almashtiring (yangi id).
YOQIQ = False bo'lsa faqat adminlarga ko'rinadi (ko'rik).
So'rovlar - POST /api/anketa: {} holat, {javob: {kalit: qiymat | [qiymatlar] | matn}} javob.
Panel - GET /api/anketa/panel (X-Dash-Token): har variantga nechta javob va yozma javoblar (odam id siz).
"""

import asyncio
import json
import logging

from aiohttp import web

import hpcup

YOQIQ = False
ANKETA = {
    "id": "qayerdan-1",
    "savollar": [
        {"k": "qayerdan", "tur": "bir", "shart": True,
         "v": ("dost", "tg_kanal", "tg_qidiruv", "instagram", "tiktok", "youtube", "boshqa")},
        {"k": "nega", "tur": "kop", "shart": True,
         "v": ("ozbekcha", "bepul", "hammasi_birda", "sifat", "xogvarts", "boshqa")},
        {"k": "yoqadi", "tur": "kop", "shart": True,
         "v": ("filmlar", "pleyer", "darslar", "turnirlar", "kubok", "chat", "soundtrack", "kitoblar", "maxluqlar")},
        {"k": "tavsiya", "tur": "matn", "shart": False},
        {"k": "yosh", "tur": "bir", "shart": False, "v": ("12", "13_17", "18_24", "25_34", "35")},
    ],
}
MATN_MAX = 300

_cfg = {}


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS anketa_javob (anketa TEXT NOT NULL, user_id INTEGER NOT NULL, javob TEXT NOT NULL,"
                     " til TEXT, saralangan INTEGER, vaqt TEXT NOT NULL, PRIMARY KEY (anketa, user_id))")
        conn.commit()
    finally:
        conn.close()


def tekshir(javob):
    """Ilova yuborgan javobni tozalaydi. Noto'g'ri bo'lsa None."""
    if not isinstance(javob, dict):
        return None
    toza = {}
    for s in ANKETA["savollar"]:
        q = javob.get(s["k"])
        if s["tur"] == "bir":
            q = q if q in s["v"] else None
        elif s["tur"] == "kop":
            q = [x for x in s["v"] if isinstance(q, list) and x in q] or None
        else:
            q = str(q or "").strip()[:MATN_MAX] or None
        if q is None:
            if s["shart"]:
                return None
            continue
        toza[s["k"]] = q
    return toza


def _bormi(uid):
    conn = hpcup._connect()
    try:
        return conn.execute("SELECT 1 FROM anketa_javob WHERE anketa=? AND user_id=?", (ANKETA["id"], int(uid))).fetchone() is not None
    finally:
        conn.close()


def _yoz(uid, toza, til):
    conn = hpcup._connect()
    try:
        cur = conn.execute("INSERT OR IGNORE INTO anketa_javob (anketa, user_id, javob, til, saralangan, vaqt) VALUES (?,?,?,?,?,?)",
                           (ANKETA["id"], int(uid), json.dumps(toza, ensure_ascii=False), til,
                            1 if hpcup._get_house(uid) else 0, hpcup._utc_iso(hpcup.now_tk())))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


def panel(admin_ids=()):
    """Har savol bo'yicha sanoq (bitta javob - bitta odam) va yozma javoblar. Adminlar sanalmaydi."""
    conn = hpcup._connect()
    try:
        rows = conn.execute("SELECT user_id, javob, til, saralangan, vaqt FROM anketa_javob WHERE anketa=? ORDER BY vaqt", (ANKETA["id"],)).fetchall()
    finally:
        conn.close()
    adm = {int(a) for a in admin_ids}
    son = {s["k"]: {v: 0 for v in s.get("v", ())} for s in ANKETA["savollar"] if s["tur"] != "matn"}
    matn, kun, n, sar = [], {}, 0, 0
    for r in rows:
        if r["user_id"] in adm:
            continue
        j = json.loads(r["javob"])
        n += 1
        sar += r["saralangan"] or 0
        kun[r["vaqt"][:10]] = kun.get(r["vaqt"][:10], 0) + 1
        for k, q in j.items():
            if k in son:
                for x in (q if isinstance(q, list) else [q]):
                    son[k][x] = son[k].get(x, 0) + 1
            else:
                matn.append({"k": k, "t": q, "til": r["til"], "vaqt": r["vaqt"], "qayerdan": j.get("qayerdan")})
    return {"id": ANKETA["id"], "on": YOQIQ, "n": n, "saralangan": sar, "son": son, "matn": matn[::-1], "kun": kun}


async def api_anketa(request):
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
    admin = uid in _cfg.get("admin_ids", ())
    if not YOQIQ and not admin:
        return cors(web.json_response({"ok": True, "on": False}))
    if "javob" in body:
        toza = tekshir(body.get("javob"))
        if toza is None:
            return cors(web.json_response({"ok": False, "error": "javob"}, status=400))
        til = str(body.get("lang") or "")[:2]
        yangi = await asyncio.to_thread(_yoz, uid, toza, til)
        if yangi and _cfg.get("log"):
            try:
                await _cfg["log"](user, "anketa_" + ANKETA["id"])
            except Exception:
                pass
        return cors(web.json_response({"ok": True, "on": True, "id": ANKETA["id"], "done": True}))
    done = await asyncio.to_thread(_bormi, uid)
    return cors(web.json_response({"ok": True, "on": True, "id": ANKETA["id"], "done": done, "preview": not YOQIQ}))


async def api_panel(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    if not _cfg["dash_ok"](request):
        return cors(web.json_response({"ok": False, "error": "bad_token"}, status=403))
    m = await asyncio.to_thread(panel, tuple(_cfg.get("admin_ids", ())))
    return cors(web.json_response(dict(m, ok=True)))


def register(app, cfg):
    """cfg: verify_init_data, cors, log, admin_ids, dash_ok."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/anketa", api_anketa)
    app.router.add_route("*", "/api/anketa/panel", api_panel)
    logging.info("So'rovnoma (anketa) ulandi")
