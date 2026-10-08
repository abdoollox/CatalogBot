# -*- coding: utf-8 -*-
"""Qo'riqxona: har o'quvchining o'z maxluqlari (egasi, 2026-10-08).

Maxluq QAYERDAN: «Sehrli maxluqlar parvarishi» darslaridan - har uch darsda bittasi (3-, 6-, ... 33-dars, jami 11 ta);
o'n ikkinchisi (ajdar bolasi) noyob - shu fan bellashuvida birinchi uchlikka kirganga.
BOQISH: yemish galleonga olinadi (1 galleon = 5 porsiya, har maxluqning o'z yemishi), har maxluq kuniga bir marta
boqiladi. 3 marta boqilsa o'smir, 10 marta - katta. Boqilmasa JAZO YO'Q (o'lmaydi, kichraymaydi) - faqat o'smaydi.
FOYDA: katta maxluq har 7-boqishda 1 galleon sovg'a keltiradi (7 porsiya = 1,4 galleon turadi, ya'ni pul «bosilmaydi»).
Kubok ballariga ALOQASI YO'Q.

POST /api/qoriq  (initData)
  {}                 -> holat: {gal, list:[{kod, got, need, fed, stage, next, food, today, gift}], prices}
  {buy: "gippo"}     -> yemish olish            {error: "pul" | "yoq"}
  {feed: "gippo"}    -> boqish                  {error: "yemish" | "bugun" | "yoq"}; javobda grew / gift
Jadval: qoriq (user_id, kod, olgan, boqildi, oxirgi, yemish).
"""

import asyncio
import logging

from aiohttp import web

import hpcup

# Tartib - olinish tartibi (ilova: js/09-darslar.js QR_TARTIB bilan bir xil); oxirgisi noyob
MAXLUQLAR = ("gippo", "boyogli", "niffler", "flobber", "testral", "qurbaqa",
             "kalmar", "boutrakl", "salamandra", "mushuk", "kalamush", "ajdar")
DARSDAN = MAXLUQLAR[:-1]
NOYOB = "ajdar"
HAR_DARS = 3                   # har nechta darsda bitta maxluq
NARX = 1                       # galleon
PORSIYA = 5                    # bir xaridda nechta porsiya
OSMIR, KATTA = 3, 10           # shuncha boqilganda bosqich o'zgaradi
SOVGA_HAR, SOVGA = 7, 1        # katta maxluq har 7-boqishda 1 galleon keltiradi

_cfg = {}


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS qoriq ("
                     " user_id INTEGER NOT NULL, kod TEXT NOT NULL, olgan TEXT NOT NULL,"
                     " boqildi INTEGER NOT NULL DEFAULT 0, oxirgi TEXT, yemish INTEGER NOT NULL DEFAULT 0,"
                     " PRIMARY KEY (user_id, kod))")
        conn.commit()
    finally:
        conn.close()


def _bugun():
    return hpcup.now_tk().strftime("%Y-%m-%d")


def bosqich(boqildi):
    """0 - bola, 1 - o'smir, 2 - katta."""
    return 2 if boqildi >= KATTA else 1 if boqildi >= OSMIR else 0


def _yangila(conn, uid):
    """Darslar va bellashuvga qarab egalik qatorlarini to'ldiradi (bir marta beriladi, qaytarib olinmaydi)."""
    r = conn.execute("SELECT daraja FROM dars_daraja WHERE user_id=? AND dars='maxluq'", (uid,)).fetchone()
    daraja = int(r[0]) if r else 0
    kodlar = list(DARSDAN[:daraja // HAR_DARS])
    if conn.execute("SELECT 1 FROM points WHERE user_id=? AND source_type='dars' AND source_ref LIKE 'm:maxluq:%' "
                    "AND points >= 7 LIMIT 1", (uid,)).fetchone():
        kodlar.append(NOYOB)
    stamp = hpcup._utc_iso(hpcup.now_tk())
    for k in kodlar:
        conn.execute("INSERT OR IGNORE INTO qoriq (user_id, kod, olgan) VALUES (?,?,?)", (uid, k, stamp))
    return daraja


def _holat(uid):
    uid = int(uid)
    conn = hpcup._connect()
    try:
        _yangila(conn, uid)
        conn.commit()
        bor = {r["kod"]: r for r in conn.execute("SELECT kod, boqildi, oxirgi, yemish FROM qoriq WHERE user_id=?", (uid,))}
        g = conn.execute("SELECT galleons FROM users WHERE user_id=?", (uid,)).fetchone()
        kun, lst = _bugun(), []
        for i, k in enumerate(MAXLUQLAR):
            r = bor.get(k)
            b = int(r["boqildi"]) if r else 0
            st = bosqich(b)
            lst.append({
                "kod": k, "got": bool(r), "need": 0 if k == NOYOB else (i + 1) * HAR_DARS,
                "fed": b, "stage": st, "next": (OSMIR - b) if st == 0 else (KATTA - b) if st == 1 else 0,
                "food": int(r["yemish"]) if r else 0, "today": bool(r and r["oxirgi"] == kun),
                "gift": (SOVGA_HAR - (b - KATTA) % SOVGA_HAR) if st == 2 else 0,
            })
        return {"ok": True, "gal": int(g[0] or 0) if g else 0, "list": lst,
                "prices": {"gal": NARX, "n": PORSIYA, "teen": OSMIR, "adult": KATTA, "gift_every": SOVGA_HAR, "gift": SOVGA}}
    finally:
        conn.close()


def _ol(uid, kod):
    """Yemish olish: "ok" | "pul" | "yoq"."""
    uid = int(uid)
    conn = hpcup._connect()
    try:
        _yangila(conn, uid)
        if not conn.execute("SELECT 1 FROM qoriq WHERE user_id=? AND kod=?", (uid, kod)).fetchone():
            conn.commit()
            return "yoq"
        # Bitta so'rovda tekshirib yechamiz: ikki marta bosilsa ham pul ortiqcha ketmaydi
        cur = conn.execute("UPDATE users SET galleons = galleons - ? WHERE user_id = ? AND galleons >= ?", (NARX, uid, NARX))
        if cur.rowcount < 1:
            conn.rollback()
            return "pul"
        conn.execute("UPDATE qoriq SET yemish = yemish + ? WHERE user_id=? AND kod=?", (PORSIYA, uid, kod))
        conn.commit()
        return "ok"
    finally:
        conn.close()


def _boq(uid, kod):
    """Boqish: (holat, o'sdimi, sovg'a). holat: "ok" | "yoq" | "yemish" | "bugun"."""
    uid, kun = int(uid), _bugun()
    conn = hpcup._connect()
    try:
        r = conn.execute("SELECT boqildi, oxirgi, yemish FROM qoriq WHERE user_id=? AND kod=?", (uid, kod)).fetchone()
        if not r:
            return "yoq", None, 0
        if r["oxirgi"] == kun:
            return "bugun", None, 0
        if int(r["yemish"]) < 1:
            return "yemish", None, 0
        cur = conn.execute("UPDATE qoriq SET boqildi = boqildi + 1, yemish = yemish - 1, oxirgi = ? "
                           "WHERE user_id=? AND kod=? AND yemish >= 1 AND (oxirgi IS NULL OR oxirgi <> ?)", (kun, uid, kod, kun))
        if cur.rowcount < 1:
            conn.rollback()
            return "bugun", None, 0
        b = int(r["boqildi"]) + 1
        osdi = bosqich(b) if bosqich(b) != bosqich(b - 1) else None
        sovga = SOVGA if (b > KATTA and (b - KATTA) % SOVGA_HAR == 0) else 0
        if sovga:
            conn.execute("UPDATE users SET galleons = galleons + ? WHERE user_id=?", (sovga, uid))
        conn.commit()
        return "ok", osdi, sovga
    finally:
        conn.close()


def korinish(uid):
    """Boshqalarga ko'rinadigani (profil): [{kod, stage}] - olinish tartibida."""
    conn = hpcup._connect()
    try:
        bor = {r["kod"]: int(r["boqildi"]) for r in conn.execute("SELECT kod, boqildi FROM qoriq WHERE user_id=?", (int(uid),))}
        return [{"kod": k, "stage": bosqich(bor[k])} for k in MAXLUQLAR if k in bor]
    except Exception:
        return []
    finally:
        conn.close()


async def api_qoriq(request):
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
    kod = str(body.get("buy") or body.get("feed") or "")
    if kod:
        if kod not in MAXLUQLAR:
            return cors(web.json_response({"ok": False, "error": "unknown"}, status=404))
        if body.get("buy"):
            holat = await asyncio.to_thread(_ol, uid, kod)
            log = "qoriq_yemish_" + kod
        else:
            holat, osdi, sovga = await asyncio.to_thread(_boq, uid, kod)
            log = "qoriq_boq_" + kod
            if holat == "ok":
                qosh = {"fed": kod, "grew": osdi, "gift": sovga}
        if holat != "ok":
            javob = await asyncio.to_thread(_holat, uid)
            javob.update({"ok": False, "error": holat})
            return cors(web.json_response(javob))
        if _cfg.get("log"):
            try:
                await _cfg["log"](user, log)
            except Exception as e:
                logging.error("Qo'riqxona: log yozilmadi: %s", e)
    javob = await asyncio.to_thread(_holat, uid)
    javob.update(qosh)
    return cors(web.json_response(javob))


def register(app, cfg):
    """cfg: verify_init_data, cors, log. hpdars DAN KEYIN ulanadi (dars_daraja jadvali kerak)."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/qoriq", api_qoriq)
    logging.info("Qo'riqxona: %d maxluq", len(MAXLUQLAR))
