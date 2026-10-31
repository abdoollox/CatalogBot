"""Kundalik Xabarnoma (egasi, 2026-11-01): ilova ichidagi gazeta, kechagi natijalardan o'zi tuziladi.

Nomi: «Payg'ambar» so'zi o'zbekchada ishlatilmaydi (egasi: bizda ilohiy so'z). Ruscha va inglizcha nomi asardagidek.
Bir kunning soni birinchi so'ralganda hisoblanib `gazeta` jadvaliga yoziladi va keyin o'zgarmaydi.
Server faqat ma'lumot beradi, sarlavha va matnni ilova o'z tilida tuzadi (js/09-gazeta.js).
So'rov: POST /api/gazeta {}. Faqat saralangan o'quvchilarga.
"""

import asyncio
import json
import logging
from datetime import datetime, timedelta

from aiohttp import web

import hpcup
import hpdars

BOSH_KUN = "2026-11-01"        # 1-son
SOAT = "22:00"                 # turnirlar boshlanishi
TURNIR = {0: "poyga", 1: "tosh", 2: "chess", 4: "vik", 5: "mjang", 6: "duel"}      # hafta kuni (dushanba = 0)

_cfg = {}
_korildi = set()


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS gazeta (kun TEXT PRIMARY KEY, malumot TEXT NOT NULL, vaqt TEXT NOT NULL)")
        conn.commit()
    finally:
        conn.close()


def _sana(kun):
    return datetime(*(int(x) for x in kun.split("-")))


def _odam(conn, uid):
    r = conn.execute("SELECT first_name, house FROM users WHERE user_id=?", (uid,)).fetchone()
    return {"uid": uid, "name": hpdars._ism(r["first_name"]) if r else "Sehrgar", "house": r["house"] if r else None}


def _kubok(conn, kecha, kun):
    """Kecha tushgan hafta: fakultetlar bali, yopilganmi, g'olib."""
    s = hpcup._kun_mavsumi(conn, kecha)
    if not s:
        return None
    ball = {h: 0 for h in hpcup.HOUSES}
    for r in conn.execute("SELECT u.house AS h, SUM(p.points) AS n FROM points p JOIN users u ON u.user_id=p.user_id "
                          "WHERE p.season_id=? AND u.house IN %s GROUP BY u.house" % hpcup._UY_SQL, (s["id"],)):
        ball[r["h"]] = r["n"] or 0
    uylar = sorted(({"h": h, "p": p} for h, p in ball.items()), key=lambda x: -x["p"])
    tugash = datetime.fromisoformat(s["ends_at"].replace("Z", "+00:00")).astimezone(hpcup.TASHKENT).strftime("%Y-%m-%d")
    yopildi = tugash < kun
    return {"houses": uylar, "closed": yopildi, "ends_today": tugash == kun,
            "winner": (s["winner_house"] or uylar[0]["h"]) if yopildi and uylar[0]["p"] else None}


def _bellashuv(conn, kecha):
    """Kecha har fanda birinchi o'rin."""
    eng = {}
    for r in conn.execute("SELECT user_id, source_ref, points, id FROM points WHERE source_ref LIKE ? AND user_id > 0 ORDER BY points DESC, id", ("m:%%:%s" % kecha,)):
        fan = r["source_ref"].split(":")[1]
        eng.setdefault(fan, r["user_id"])
    out = []
    for fan in hpdars.DARSLAR:
        if fan in eng:
            d = _odam(conn, eng[fan])
            d["fan"] = fan
            out.append(d)
    return out


def _turnir_kartasi(conn, tur, hafta):
    """Shu haftaning tugagan turniri: hpgolib kartasi yoki None. Turnir qoliplari har modulda o'zicha."""
    import hpgolib
    if tur == "poyga":
        import hppoyga
        return hppoyga._goliblar(conn, hafta, 0)
    if tur == "vik":
        import hpviktorina
        return hpviktorina._goliblar(conn, hafta, 0)
    if tur == "tosh":
        import hptosh as m
        jadval, bosh, q = "tosh_match", "tosh", "tosh_qatnash"
    elif tur == "chess":
        import hpshturnir as m
        jadval, bosh, q = "sh_match", "shaxmat", "sh_qatnash"
    elif tur == "mjang":
        import hpmjang as m
        jadval, bosh, q = "mj_match", "mjang", "mj_qatnash"
    else:
        import hpduel as m
        jadval, bosh, q = "duel_match", "duel", "duel_qatnash"
    return hpgolib.tor(conn, jadval, hafta, bosh, 0, "SELECT COUNT(*) FROM %s WHERE hafta=?" % q, m._turnir_vaqti)


def _kechagi_turnir(conn, kecha):
    sana = _sana(kecha)
    tur = TURNIR.get(sana.weekday())
    if not tur:
        return None
    hafta = (sana - timedelta(days=sana.weekday())).strftime("%Y-%m-%d")
    try:
        k = _turnir_kartasi(conn, tur, hafta)
    except Exception:
        logging.exception("gazeta: turnir natijasi")
        return None
    if not k or not k.get("top") or datetime.fromtimestamp(k["ts"], hpcup.TASHKENT).strftime("%Y-%m-%d") != kecha:
        return None                             # kecha turnir o'tmagan (kam odam) - eski g'olib yozilmasin
    g = k["top"][0]
    return {"kind": tur, "n": k.get("n") or 0, "winner": {"uid": g["uid"], "name": g["name"], "house": g["house"]}, "points": g["points"]}


def _yangi(conn, kecha):
    y, m, d = (int(x) for x in kecha.split("-"))
    bosh = datetime(y, m, d, tzinfo=hpcup.TASHKENT)
    return conn.execute("SELECT COUNT(*) FROM users WHERE user_id > 0 AND sorted_at >= ? AND sorted_at < ?",
                        (hpcup._utc_iso(bosh), hpcup._utc_iso(bosh + timedelta(days=1)))).fetchone()[0]


def _son(kun):
    """Kunning soni: bor bo'lsa bazadan, yo'q bo'lsa hisoblab yozadi."""
    conn = hpcup._connect()
    try:
        r = conn.execute("SELECT malumot FROM gazeta WHERE kun=?", (kun,)).fetchone()
        if r:
            return json.loads(r["malumot"])
    finally:
        conn.close()
    hpdars.yakunla(kun)                         # kechagi bellashuv sovrinlari bu so'rovdan oldin berilgan bo'lsin
    kecha = (_sana(kun) - timedelta(days=1)).strftime("%Y-%m-%d")
    conn = hpcup._connect()
    try:
        bell = _bellashuv(conn, kecha)
        son = {}
        for b in bell:
            son[b["uid"]] = son.get(b["uid"], 0) + 1
        yulduz = max(son, key=lambda u: son[u]) if son else None
        bugun = TURNIR.get(_sana(kun).weekday())
        m = {"no": (_sana(kun) - _sana(BOSH_KUN)).days + 1, "day": kun, "yesterday": kecha,
             "cup": _kubok(conn, kecha, kun), "bell": bell, "fans": len(hpdars.DARSLAR),
             "tour": _kechagi_turnir(conn, kecha), "today": {"kind": bugun, "at": SOAT} if bugun else None,
             "new": _yangi(conn, kecha),
             "star": dict(_odam(conn, yulduz), n=son[yulduz]) if yulduz and son[yulduz] >= 2 else None}
        conn.execute("INSERT OR REPLACE INTO gazeta (kun, malumot, vaqt) VALUES (?,?,?)",
                     (kun, json.dumps(m, ensure_ascii=False), hpcup._utc_iso(hpcup.now_tk())))
        conn.commit()
        return m
    finally:
        conn.close()


async def api_gazeta(request):
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
    kun = hpcup.now_tk().strftime("%Y-%m-%d")
    m = await asyncio.to_thread(_son, kun)
    if body.get("read") and (uid, kun) not in _korildi and _cfg.get("log"):       # kuniga bir marta
        _korildi.add((uid, kun))
        try:
            await _cfg["log"](user, "gazeta_oqidi")
        except Exception:
            pass
    return cors(web.json_response(dict(m, ok=True)))


def register(app, cfg):
    """cfg: verify_init_data, cors, log."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/gazeta", api_gazeta)
    logging.info("Kundalik Xabarnoma ulandi")
