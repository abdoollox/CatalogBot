# -*- coding: utf-8 -*-
"""Darslar (egasi, 2026-10-07): Xogvarts sahifasida kunlik savol o'rnida fanlar bo'limi.

Faqat SARALANGANLARGA. Ikki qism:

1) DARS (mashq) - har odamning O'Z BOSQICHI bor (kimdir 1-darsda, kimdir 100-darsda):
     kuniga bitta yangi dars -> bosqich +1 va +5 ball. Mavzu va qiyinlik bosqichga bog'liq
     (ro'yxat bo'yicha aylanadi; har aylanada qiyinroq - buni ilova hisoblaydi).
     Bugun bajarilgan bo'lsa - qayta o'ynash mashq, bosqich va ball o'zgarmaydi.
   tarix (Sehrgarlik tarixi) - bu KUNLIK SAVOL: ball eski yo'l bilan ('daily'), bu yerda faqat holati.

2) BELLASHUV (musobaqa) - kuniga bitta topshiriq HAMMAGA BIR XIL (sana bo'yicha), kim tezroq va xatosiz.
     Vaqtni SERVER o'lchaydi ({start} -> {finish}); har xato +3 soniya. Kuniga 3 urinish, eng yaxshisi hisob.
     Kun tugagach (keyingi kun birinchi so'rovda) eng yaxshilarga qo'shimcha ball: 1-o'rin +15, 2-o'rin +10,
     3-o'rin +7, 4-10-o'rinlar +3.

Ball kubokka 'dars' manbasi bo'lib yoziladi: dars "afsun:2026-10-08", bellashuv "m:afsun:2026-10-08".
Kun - Toshkent vaqti. Qolgan fanlar ilovada "Tez orada" - qo'shilganda DARSLAR ga yoziladi.

API: POST /api/dars
  {}                         -> holat (darslar, bosqichlar, bellashuv jadvali, kechagi g'oliblar)
  {done: "afsun"}            -> dars bajarildi
  {start: "afsun"}           -> bellashuv urinishi boshlandi
  {finish: "afsun", xato: 2} -> bellashuv urinishi tugadi
"""

import asyncio
import datetime as _dt
import logging
import sqlite3
import time
from datetime import timedelta

from aiohttp import web

import hpcup
import hpsandiq

_cfg = {}
_kesh = {}                     # uid -> (vaqt, oxirgi holat javobi)
KESH_S = 5

DARSLAR = {
    "afsun": {"pts": 5, "items": ("lumos", "leviosa", "alohomora", "expelliarmus", "accio", "protego",
                                  "incendio", "reparo", "stupefy", "aguamenti", "nox", "patronum")},
    "iksir": {"pts": 5, "items": ("boils", "forget", "shrink", "antidote", "wiggenweld", "uyqu",
                                  "skelegro", "living", "polyjuice", "felix")},
}
BOSHI = (2026, 10, 7)
URINISH = 3                    # bellashuvda kuniga nechta urinish
XATO_MS = 3000                 # har xato uchun jarima
ENG_KAM_MS = 1500              # bundan tez natija bo'lmaydi (soxta so'rovdan himoya)
ENG_KOP_MS = 5 * 60 * 1000     # bundan uzoq urinish hisobga olinmaydi
SOVRIN = (15, 10, 7)           # 1-3 o'rinlar
SOVRIN_10 = 3                  # 4-10 o'rinlar
TOP_N = 10


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS dars_daraja ("
                     " user_id INTEGER NOT NULL, dars TEXT NOT NULL, daraja INTEGER NOT NULL DEFAULT 0,"
                     " kun TEXT, PRIMARY KEY (user_id, dars))")
        conn.execute("CREATE TABLE IF NOT EXISTS dars_bellashuv ("
                     " kun TEXT NOT NULL, dars TEXT NOT NULL, user_id INTEGER NOT NULL,"
                     " ms INTEGER, xato INTEGER NOT NULL DEFAULT 0, urinish INTEGER NOT NULL DEFAULT 0,"
                     " boshladi REAL, vaqt TEXT, PRIMARY KEY (kun, dars, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS dars_yakun ("
                     " kun TEXT NOT NULL, dars TEXT NOT NULL, vaqt TEXT NOT NULL, PRIMARY KEY (kun, dars))")
        conn.commit()
    finally:
        conn.close()


def kun_mavzusi(dars, kun):
    """Bellashuvning shu kungi mavzusi (hammaga bir xil): ro'yxat bo'yicha aylanadi."""
    y, m, d = (int(x) for x in kun.split("-"))
    n = max(0, (_dt.date(y, m, d) - _dt.date(*BOSHI)).days)
    items = DARSLAR[dars]["items"]
    return items[n % len(items)]


def daraja_mavzusi(dars, daraja):
    """Shaxsiy darsning mavzusi: bosqich bo'yicha (0 - birinchi dars)."""
    items = DARSLAR[dars]["items"]
    return items[int(daraja) % len(items)]


def _kecha(kun):
    y, m, d = (int(x) for x in kun.split("-"))
    return (_dt.date(y, m, d) - timedelta(days=1)).strftime("%Y-%m-%d")


def _jadval(conn, kun, dars, limit=None):
    """Natijasi bor qatnashchilar, eng yaxshisidan: [(user_id, ms, xato, name, house)]."""
    sql = ("SELECT b.user_id, b.ms, b.xato, COALESCE(u.first_name, 'Sehrgar') AS name, u.house "
           "FROM dars_bellashuv b JOIN users u ON u.user_id = b.user_id "
           "WHERE b.kun=? AND b.dars=? AND b.ms IS NOT NULL AND u.house IS NOT NULL AND b.user_id > 0 "
           "ORDER BY b.ms ASC, b.vaqt ASC")
    rows = conn.execute(sql + (" LIMIT %d" % limit if limit else ""), (kun, dars)).fetchall()
    return rows


def sovrin(orin):
    """O'rin (1 dan) uchun qo'shimcha ball."""
    if orin <= len(SOVRIN):
        return SOVRIN[orin - 1]
    return SOVRIN_10 if orin <= TOP_N else 0


def yakunla(bugun):
    """Tugagan kunlar bellashuvini yakunlaydi: g'oliblarga ball. Takror chaqirilsa - hech narsa qilmaydi."""
    conn = hpcup._connect()
    berish = []
    try:
        kunlar = conn.execute(
            "SELECT DISTINCT b.kun, b.dars FROM dars_bellashuv b "
            "WHERE b.kun < ? AND b.ms IS NOT NULL AND NOT EXISTS "
            "(SELECT 1 FROM dars_yakun y WHERE y.kun = b.kun AND y.dars = b.dars) "
            "ORDER BY b.kun DESC LIMIT 12", (bugun,)).fetchall()
        for k in kunlar:
            # Avval belgi qo'yiladi: ikki so'rov bir vaqtda kelsa ham ball ikki marta ketmaydi
            cur = conn.execute("INSERT OR IGNORE INTO dars_yakun (kun, dars, vaqt) VALUES (?,?,?)",
                               (k["kun"], k["dars"], hpcup._utc_iso(hpcup.now_tk())))
            conn.commit()
            if cur.rowcount < 1:
                continue
            for i, r in enumerate(_jadval(conn, k["kun"], k["dars"], TOP_N)):
                berish.append((r["user_id"], "m:%s:%s" % (k["dars"], k["kun"]), sovrin(i + 1)))
    except sqlite3.OperationalError as e:
        logging.error("Bellashuv yakunlanmadi: %s", e)
    finally:
        conn.close()
    for uid, ref, pts in berish:
        if pts > 0:
            hpcup._award(uid, "dars", ref, pts)
    return len(berish)


def _ism(raw):
    raw = (raw or "Sehrgar").strip()
    return (raw.split()[0] if raw else "Sehrgar")[:20]


def _bellashuv(conn, uid, kun, dars):
    rows = _jadval(conn, kun, dars)
    top = [{"uid": r["user_id"], "name": _ism(r["name"]), "house": r["house"], "ms": r["ms"], "xato": r["xato"],
            "me": r["user_id"] == uid} for r in rows[:TOP_N]]
    orin = next((i + 1 for i, r in enumerate(rows) if r["user_id"] == uid), None)
    m = conn.execute("SELECT ms, xato, urinish FROM dars_bellashuv WHERE kun=? AND dars=? AND user_id=?",
                     (kun, dars, uid)).fetchone()
    # Kechagi natija
    kecha = _kecha(kun)
    krows = _jadval(conn, kecha, dars)
    korin = next((i + 1 for i, r in enumerate(krows) if r["user_id"] == uid), None)
    return {
        "item": kun_mavzusi(dars, kun), "top": top, "n": len(rows), "place": orin,
        "ms": m["ms"] if m else None, "tries": int(m["urinish"]) if m else 0, "max": URINISH,
        "prizes": {"top": list(SOVRIN), "ten": SOVRIN_10},
        "yesterday": {
            "top": [{"uid": r["user_id"], "name": _ism(r["name"]), "house": r["house"], "ms": r["ms"]}
                    for r in krows[:3]],
            "n": len(krows), "place": korin, "pts": sovrin(korin) if korin else 0,
        },
    }


def _holat(uid, kun):
    conn = hpcup._connect()
    try:
        out = {"tarix": {"done": hpsandiq._daily_bajarildi(conn, uid, kun), "pts": hpcup.PTS_DAILY}}
        dar = {r["dars"]: r for r in conn.execute(
            "SELECT dars, daraja, kun FROM dars_daraja WHERE user_id=?", (uid,))}
        for kod, d in DARSLAR.items():
            r = dar.get(kod)
            daraja = int(r["daraja"]) if r else 0
            bugun = bool(r and r["kun"] == kun)
            # Bugun bajarilgan bo'lsa - mashq uchun shu (oxirgi o'tilgan) dars qaytariladi
            ochiq = daraja - 1 if (bugun and daraja > 0) else daraja
            out[kod] = {"done": bugun, "pts": d["pts"], "level": daraja, "n": ochiq + 1,
                        "item": daraja_mavzusi(kod, ochiq), "cycle": ochiq // len(d["items"]),
                        "contest": _bellashuv(conn, uid, kun, kod)}
        return out
    finally:
        conn.close()


def _dars_bajarildi(uid, dars, kun):
    """Bosqichni oshiradi (kuniga bir marta). Yangi bo'lsa True."""
    conn = hpcup._connect()
    try:
        conn.execute("INSERT OR IGNORE INTO dars_daraja (user_id, dars, daraja, kun) VALUES (?,?,0,NULL)", (uid, dars))
        cur = conn.execute("UPDATE dars_daraja SET daraja = daraja + 1, kun = ? "
                           "WHERE user_id=? AND dars=? AND (kun IS NULL OR kun <> ?)", (kun, uid, dars, kun))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _boshla(uid, dars, kun):
    conn = hpcup._connect()
    try:
        conn.execute("INSERT OR IGNORE INTO dars_bellashuv (kun, dars, user_id) VALUES (?,?,?)", (kun, dars, uid))
        cur = conn.execute("UPDATE dars_bellashuv SET urinish = urinish + 1, boshladi = ? "
                           "WHERE kun=? AND dars=? AND user_id=? AND urinish < ?",
                           (time.time(), kun, dars, uid, URINISH))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _tugat(uid, dars, kun, xato):
    """Urinishni yopadi. (ms, eng_yaxshi_ms) yoki None (boshlanmagan / juda uzoq)."""
    conn = hpcup._connect()
    try:
        r = conn.execute("SELECT ms, boshladi FROM dars_bellashuv WHERE kun=? AND dars=? AND user_id=?",
                         (kun, dars, uid)).fetchone()
        if not r or not r["boshladi"]:
            return None
        sof = int((time.time() - float(r["boshladi"])) * 1000)
        conn.execute("UPDATE dars_bellashuv SET boshladi = NULL WHERE kun=? AND dars=? AND user_id=?", (kun, dars, uid))
        if sof > ENG_KOP_MS:
            conn.commit()
            return None
        ms = max(ENG_KAM_MS, sof) + max(0, min(int(xato), 50)) * XATO_MS
        if r["ms"] is None or ms < r["ms"]:
            conn.execute("UPDATE dars_bellashuv SET ms=?, xato=?, vaqt=? WHERE kun=? AND dars=? AND user_id=?",
                         (ms, max(0, min(int(xato), 50)), hpcup._utc_iso(hpcup.now_tk()), kun, dars, uid))
        conn.commit()
        return ms, (ms if r["ms"] is None else min(ms, r["ms"]))
    finally:
        conn.close()


def _ish(uid, body):
    kun = hpcup.today_tk()
    if not hpcup._get_house(uid):
        return {"ok": False, "error": "no_house"}
    try:
        yakunla(kun)
    except Exception as e:
        logging.error("Bellashuv yakuni: %s", e)
    javob = {"ok": True, "kun": kun}
    dars = body.get("done") or body.get("start") or body.get("finish")
    if dars is not None:
        dars = str(dars)
        if dars not in DARSLAR:
            return {"ok": False, "error": "unknown"}
    if body.get("done"):
        yangi = _dars_bajarildi(uid, dars, kun)
        pts = DARSLAR[dars]["pts"]
        if yangi:
            hpcup._award(uid, "dars", "%s:%s" % (dars, kun), pts)
        javob["new"] = yangi
        javob["pts"] = pts if yangi else 0
    elif body.get("start"):
        if not _boshla(uid, dars, kun):
            javob.update(ok=False, error="no_tries")
            return javob
        javob["started"] = True
    elif body.get("finish"):
        try:
            xato = int(body.get("xato") or 0)
        except (TypeError, ValueError):
            xato = 0
        r = _tugat(uid, dars, kun, xato)
        if not r:
            javob.update(ok=False, error="not_started")
            return javob
        javob["ms"], javob["best"] = r
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
    body = body if isinstance(body, dict) else {}
    # Holat so'rovi (amalsiz) bir odamdan 5 soniyada bir marta hisoblanadi - qolganiga oxirgi javob qaytadi.
    # Sabab: ilovaning 2026-10-07 dagi nusxasida bosh sahifa holatni to'xtovsiz so'rab turardi (cheksiz halqa).
    amal = body.get("done") or body.get("start") or body.get("finish")
    hozir = time.monotonic()
    if not amal:
        eski = _kesh.get(uid)
        if eski and hozir - eski[0] < KESH_S:
            return cors(web.json_response(eski[1]))
    try:
        res = await asyncio.to_thread(_ish, uid, body)
    except Exception as e:
        logging.error("Dars holati hisoblanmadi (%s): %s", uid, e)
        return cors(web.json_response({"ok": False, "error": "server"}, status=500))
    if len(_kesh) > 5000:
        _kesh.clear()
    _kesh[uid] = (hozir, res) if not amal else (0, res)        # amaldan keyin holat yangi - darhol qayta o'qilsin
    if _cfg.get("log") and res.get("ok"):
        try:
            if res.get("new"):
                d = str(body.get("done"))
                await _cfg["log"](user, "dars_%s_%d" % (d, res["lessons"][d]["level"]))
            elif "ms" in res:
                await _cfg["log"](user, "bellashuv_%s" % body.get("finish"))
        except Exception as e:
            logging.error("Dars logi yozilmadi: %s", e)
    return cors(web.json_response(res))


def register(app, cfg):
    """cfg: verify_init_data, cors, log."""
    _cfg.update(cfg)
    try:
        _init()
    except Exception as e:
        logging.error("Darslar jadvallari ochilmadi: %s", e)
    app.router.add_route("*", "/api/dars", api_dars)
    logging.info("Darslar: %s", ", ".join(DARSLAR))
