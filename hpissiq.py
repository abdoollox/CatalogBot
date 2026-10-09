# -*- coding: utf-8 -*-
"""Issiqxona: har o'quvchining o'z o'simliklari (egasi, 2026-10-09) - Qo'riqxonaning «egizagi».

O'simlik QAYERDAN: «O'simlikshunoslik» darslaridan - har uch darsda bitta urug' (3-, 6-, ... 36-dars, jami 12 ta).
SUG'ORISH: BEPUL, har o'simlik kuniga bir marta. 3 marta sug'orilsa o'smir, 10 marta - yetilgan.
Sug'orilmasa JAZO YO'Q (qurimaydi) - faqat o'smaydi.
HOSIL: yetilgan o'simlik har 3-sug'orishda 1 ta hosil beradi. Hosil umumiy zaxiraga tushadi va Qo'riqxonada
maxluqni boqishga ishlatiladi (yemishi tugagan maxluqqa 1 hosil = 1 boqish; hpqoriq {feed, hosil}).
Kubok ballariga va galleonga ALOQASI YO'Q.

POST /api/issiq  (initData)
  {}                 -> holat: {hosil, list:[{kod, got, need, watered, stage, next, today, crop}], prices}
  {water: "mandragora"} yoki {water: "all"} -> sug'orish; javobda watered:[kod], grew:{kod: bosqich}, crop: nechta hosil
Jadvallar: issiq (user_id, kod, olgan, sugorildi, oxirgi), issiq_hosil (user_id, hosil).
"""

import asyncio
import logging

from aiohttp import web

import hpcup

# Tartib - olinish tartibi (ilova: js/09-issiqxona.js IS_TARTIB bilan bir xil)
OSIMLIKLAR = ("mandragora", "bubotuber", "puffapod", "geran", "mimbulus", "ditani",
              "jabra", "tentakula", "shayton", "akonit", "snargaluff", "tol")
HAR_DARS = 3
OSMIR, KATTA = 3, 10
HOSIL_HAR = 3                  # yetilgan o'simlik har nechanchi sug'orishda hosil beradi

_cfg = {}


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS issiq ("
                     " user_id INTEGER NOT NULL, kod TEXT NOT NULL, olgan TEXT NOT NULL,"
                     " sugorildi INTEGER NOT NULL DEFAULT 0, oxirgi TEXT, PRIMARY KEY (user_id, kod))")
        conn.execute("CREATE TABLE IF NOT EXISTS issiq_hosil (user_id INTEGER PRIMARY KEY, hosil INTEGER NOT NULL DEFAULT 0)")
        conn.commit()
    finally:
        conn.close()


def _bugun():
    return hpcup.now_tk().strftime("%Y-%m-%d")


def bosqich(n):
    """0 - nihol, 1 - o'smir, 2 - yetilgan."""
    return 2 if n >= KATTA else 1 if n >= OSMIR else 0


def hosil_soni(conn, uid):
    try:
        r = conn.execute("SELECT hosil FROM issiq_hosil WHERE user_id=?", (int(uid),)).fetchone()
        return int(r[0]) if r else 0
    except Exception:
        return 0


def hosil_ol(conn, uid):
    """Zaxiradan 1 hosil yechadi (Qo'riqxonada boqish uchun). True - yechildi. commit chaqiruvchida."""
    try:
        return conn.execute("UPDATE issiq_hosil SET hosil = hosil - 1 WHERE user_id=? AND hosil >= 1", (int(uid),)).rowcount > 0
    except Exception:
        return False


def _yangila(conn, uid):
    r = conn.execute("SELECT daraja FROM dars_daraja WHERE user_id=? AND dars='osimlik'", (uid,)).fetchone()
    daraja = int(r[0]) if r else 0
    stamp = hpcup._utc_iso(hpcup.now_tk())
    for k in OSIMLIKLAR[:daraja // HAR_DARS]:
        conn.execute("INSERT OR IGNORE INTO issiq (user_id, kod, olgan) VALUES (?,?,?)", (uid, k, stamp))


def _holat(uid):
    uid = int(uid)
    conn = hpcup._connect()
    try:
        _yangila(conn, uid)
        conn.commit()
        bor = {r["kod"]: r for r in conn.execute("SELECT kod, sugorildi, oxirgi FROM issiq WHERE user_id=?", (uid,))}
        kun, lst = _bugun(), []
        for i, k in enumerate(OSIMLIKLAR):
            r = bor.get(k)
            b = int(r["sugorildi"]) if r else 0
            st = bosqich(b)
            lst.append({
                "kod": k, "got": bool(r), "need": (i + 1) * HAR_DARS, "watered": b, "stage": st,
                "next": (OSMIR - b) if st == 0 else (KATTA - b) if st == 1 else 0,
                "today": bool(r and r["oxirgi"] == kun),
                "crop": (HOSIL_HAR - (b - KATTA) % HOSIL_HAR) if st == 2 else 0,
            })
        return {"ok": True, "hosil": hosil_soni(conn, uid), "list": lst,
                "prices": {"teen": OSMIR, "adult": KATTA, "crop_every": HOSIL_HAR}}
    finally:
        conn.close()


def _sugor(uid, kod):
    """Sug'orish (kod yoki "all"): (sug'orilganlar, {kod: yangi bosqich}, hosil soni)."""
    uid, kun = int(uid), _bugun()
    conn = hpcup._connect()
    try:
        _yangila(conn, uid)
        rows = conn.execute("SELECT kod, sugorildi, oxirgi FROM issiq WHERE user_id=?", (uid,)).fetchall()
        qilindi, osdi, hosil = [], {}, 0
        for r in rows:
            if (kod != "all" and r["kod"] != kod) or r["oxirgi"] == kun:
                continue
            cur = conn.execute("UPDATE issiq SET sugorildi = sugorildi + 1, oxirgi = ? WHERE user_id=? AND kod=? "
                               "AND (oxirgi IS NULL OR oxirgi <> ?)", (kun, uid, r["kod"], kun))
            if cur.rowcount < 1:
                continue
            b = int(r["sugorildi"]) + 1
            qilindi.append(r["kod"])
            if bosqich(b) != bosqich(b - 1):
                osdi[r["kod"]] = bosqich(b)
            if b > KATTA and (b - KATTA) % HOSIL_HAR == 0:
                hosil += 1
        if hosil:
            conn.execute("INSERT INTO issiq_hosil (user_id, hosil) VALUES (?,?) "
                         "ON CONFLICT(user_id) DO UPDATE SET hosil = hosil + excluded.hosil", (uid, hosil))
        conn.commit()
        return qilindi, osdi, hosil
    finally:
        conn.close()


def korinish(uid):
    """Boshqalarga ko'rinadigani (profil): [{kod, stage}]."""
    conn = hpcup._connect()
    try:
        bor = {r["kod"]: int(r["sugorildi"]) for r in conn.execute("SELECT kod, sugorildi FROM issiq WHERE user_id=?", (int(uid),))}
        return [{"kod": k, "stage": bosqich(bor[k])} for k in OSIMLIKLAR if k in bor]
    except Exception:
        return []
    finally:
        conn.close()


async def api_issiq(request):
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
    qosh = {}
    kod = str(body.get("water") or "")
    if kod:
        if kod != "all" and kod not in OSIMLIKLAR:
            return cors(web.json_response({"ok": False, "error": "unknown"}, status=404))
        qilindi, osdi, hosil = await asyncio.to_thread(_sugor, uid, kod)
        qosh = {"watered": qilindi, "grew": osdi, "crop": hosil}
        if qilindi and _cfg.get("log"):
            try:
                await _cfg["log"](user, "issiq_suv_" + (kod if kod != "all" else "hammasi"))
            except Exception as e:
                logging.error("Issiqxona: log yozilmadi: %s", e)
    javob = await asyncio.to_thread(_holat, uid)
    javob.update(qosh)
    return cors(web.json_response(javob))


def register(app, cfg):
    """cfg: verify_init_data, cors, log. hpdars DAN KEYIN ulanadi (dars_daraja jadvali kerak)."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/issiq", api_issiq)
    logging.info("Issiqxona: %d o'simlik", len(OSIMLIKLAR))
