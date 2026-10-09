# -*- coding: utf-8 -*-
"""Duel (egasi, 2026-10-09). 1-BOSQICH: kompyuter raqiblar bilan duel va haftalik SARALASH jadvali.

REJA (egasi tasdiqlagan): duel - haftalik turnir, Chempionlar ligasi kabi. Dushanba-chorshanba SARALASH (kompyuter
raqiblar bilan, eng yaxshi natija bo'yicha jadval), payshanba 1/8, juma chorak, shanba yarim final, yakshanba final -
eng yaxshi 16 kishi (yetmasa 8). Pley-off JONLI: o'quvchilar BELGILANGAN VAQTDA onlayn bo'ladi (egasi: «yopiq»,
har kim o'z vaqtida o'ynaydigan duel YOQMADI - qayta taklif qilmang). Ball: pley-offga chiqqanga +5, chorak +10,
yarim final +15, final +20, g'olib +30 - SHU HAFTA kubogiga tushishi shart (keyingi haftaga o'tmasin).
PLEY-OFF HALI QURILMAGAN - bu faylda faqat duelning o'zi va saralash.

QOIDA: har duelchida 3 jon. Har raundda ikkalasi bir vaqtda tur tanlaydi - hujum / himoya / hiyla - va afsunni
chizadi (aniqlik 0..100, ilova o'lchaydi). Hujum hiylani, hiyla himoyani, himoya hujumni yengadi; turlar bir xil
bo'lsa aniqrog'i yutadi (farq 5 dan kam - durang). Aniqlik 35 dan past - afsun chiqmadi. Yutqazgan 1 jon yo'qotadi.

POST /api/duel  (initData)
  {}                         -> holat: {week, mine:{1,2,3,total}, top:[...], place, n, rules}
  {start: 1|2|3}             -> yangi duel: {game:{id, level, lives, rlives, round}}
  {game: id, move: tur, acc} -> raund: {round:{mine, his, acc, racc, win}, game:{..., over, won, score}}
Jadvallar: duel_oyin, duel_saral (user_id, hafta, daraja, ball - haftadagi eng yaxshisi).
"""

import asyncio
import logging
import random

from aiohttp import web

import hpcup
import hpdars

TURLAR = ("hujum", "himoya", "hiyla")
YENGADI = {"hujum": "hiyla", "hiyla": "himoya", "himoya": "hujum"}
JON = 3
KAM = 35                       # bundan past aniqlik - afsun chiqmadi
DURANG = 5                     # bir xil turda aniqlik farqi shundan kam bo'lsa durang
RAUND_MAX = 12
# Kompyuter raqiblar: (o'rtacha aniqlik, tarqoqlik, o'yinchining odatiga qarshi o'ynash ehtimoli)
RAQIBLAR = {1: (50, 15, 0.0), 2: (68, 11, 0.3), 3: (84, 8, 0.5)}
TOP = 16

_cfg = {}


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS duel_oyin ("
                     " id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, daraja INTEGER NOT NULL,"
                     " jon INTEGER NOT NULL, rjon INTEGER NOT NULL, raund INTEGER NOT NULL DEFAULT 0,"
                     " acc_sum INTEGER NOT NULL DEFAULT 0, turlar TEXT NOT NULL DEFAULT '', holat TEXT NOT NULL DEFAULT 'ketmoqda',"
                     " hafta TEXT NOT NULL, vaqt TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS duel_saral ("
                     " user_id INTEGER NOT NULL, hafta TEXT NOT NULL, daraja INTEGER NOT NULL, ball INTEGER NOT NULL,"
                     " vaqt TEXT NOT NULL, PRIMARY KEY (user_id, hafta, daraja))")
        conn.commit()
    finally:
        conn.close()


def hal_qil(men, macc, u, uacc):
    """Raund natijasi: 1 - men yutdim, -1 - yutqazdim, 0 - durang."""
    mok, uok = macc >= KAM, uacc >= KAM
    if not mok and not uok:
        return 0
    if mok != uok:
        return 1 if mok else -1
    if men == u:
        return 0 if abs(macc - uacc) < DURANG else (1 if macc > uacc else -1)
    return 1 if YENGADI[men] == u else -1


def _raqib_yurishi(daraja, turlar, rnd=random):
    orta, tarq, qarshi = RAQIBLAR[daraja]
    tur = rnd.choice(TURLAR)
    if turlar and rnd.random() < qarshi:
        # o'yinchi eng ko'p ishlatgan turni yengadigan tur
        kop = max(TURLAR, key=lambda t: turlar.count(t[2]))
        tur = next(t for t in TURLAR if YENGADI[t] == kop)
    return tur, max(0, min(100, int(round(rnd.gauss(orta, tarq)))))


def ball(daraja, jon, acc_orta):
    """G'alaba uchun saralash bali: raqib darajasi + qolgan jon + o'rtacha aniqlik."""
    return daraja * 100 + jon * 20 + int(acc_orta * 0.5)


def _holat(uid):
    uid, hafta = int(uid), hpdars._hafta()
    conn = hpcup._connect()
    try:
        men = {int(r["daraja"]): int(r["ball"]) for r in conn.execute(
            "SELECT daraja, ball FROM duel_saral WHERE user_id=? AND hafta=?", (uid, hafta))}
        rows = conn.execute(
            "SELECT s.user_id, SUM(s.ball) AS ball, MAX(s.vaqt) AS vaqt, COALESCE(u.first_name, 'Sehrgar') AS name, u.house "
            "FROM duel_saral s JOIN users u ON u.user_id = s.user_id WHERE s.hafta=? AND u.house IS NOT NULL AND s.user_id > 0 "
            "GROUP BY s.user_id ORDER BY ball DESC, vaqt ASC", (hafta,)).fetchall()
        return {
            "ok": True, "week": hafta, "mine": {"1": men.get(1, 0), "2": men.get(2, 0), "3": men.get(3, 0), "total": sum(men.values())},
            "n": len(rows), "place": next((i + 1 for i, r in enumerate(rows) if r["user_id"] == uid), None),
            "top": [{"uid": r["user_id"], "name": hpdars._ism(r["name"]), "house": r["house"], "score": int(r["ball"]),
                     "me": r["user_id"] == uid} for r in rows[:TOP]],
            "rules": {"lives": JON, "fail": KAM, "top": TOP},
        }
    finally:
        conn.close()


def _boshla(uid, daraja):
    uid = int(uid)
    conn = hpcup._connect()
    try:
        conn.execute("UPDATE duel_oyin SET holat='tashlandi' WHERE user_id=? AND holat='ketmoqda'", (uid,))
        cur = conn.execute("INSERT INTO duel_oyin (user_id, daraja, jon, rjon, hafta, vaqt) VALUES (?,?,?,?,?,?)",
                           (uid, daraja, JON, JON, hpdars._hafta(), hpcup._utc_iso(hpcup.now_tk())))
        conn.commit()
        return {"id": cur.lastrowid, "level": daraja, "lives": JON, "rlives": JON, "round": 0, "over": False}
    finally:
        conn.close()


def _yur(uid, oyin, tur, acc, rnd=random):
    """Bitta raund. None - o'yin topilmadi/tugagan."""
    uid = int(uid)
    conn = hpcup._connect()
    try:
        g = conn.execute("SELECT * FROM duel_oyin WHERE id=? AND user_id=? AND holat='ketmoqda'", (int(oyin), uid)).fetchone()
        if not g:
            return None
        daraja = int(g["daraja"])
        utur, uacc = _raqib_yurishi(daraja, g["turlar"], rnd)
        w = hal_qil(tur, acc, utur, uacc)
        jon, rjon, raund = int(g["jon"]) - (1 if w < 0 else 0), int(g["rjon"]) - (1 if w > 0 else 0), int(g["raund"]) + 1
        acc_sum = int(g["acc_sum"]) + acc
        tugadi = jon <= 0 or rjon <= 0 or raund >= RAUND_MAX
        yutdi = tugadi and jon > rjon
        natija = 0
        if tugadi:
            if yutdi:
                natija = ball(daraja, jon, acc_sum / float(raund))
                conn.execute("INSERT INTO duel_saral (user_id, hafta, daraja, ball, vaqt) VALUES (?,?,?,?,?) "
                             "ON CONFLICT(user_id, hafta, daraja) DO UPDATE SET vaqt = CASE WHEN excluded.ball > ball THEN excluded.vaqt ELSE vaqt END, "
                             "ball = MAX(ball, excluded.ball)", (uid, g["hafta"], daraja, natija, hpcup._utc_iso(hpcup.now_tk())))
        conn.execute("UPDATE duel_oyin SET jon=?, rjon=?, raund=?, acc_sum=?, turlar=?, holat=? WHERE id=?",
                     (jon, rjon, raund, acc_sum, g["turlar"] + tur[2], ("yutdi" if yutdi else "yutqazdi") if tugadi else "ketmoqda", g["id"]))
        conn.commit()
        return {"round": {"mine": tur, "his": utur, "acc": acc, "racc": uacc, "win": w},
                "game": {"id": g["id"], "level": daraja, "lives": jon, "rlives": rjon, "round": raund,
                         "over": tugadi, "won": bool(yutdi), "score": natija}}
    finally:
        conn.close()


async def api_duel(request):
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
    qosh = {}
    if body.get("start") is not None:
        try:
            daraja = int(body.get("start"))
        except (TypeError, ValueError):
            daraja = 0
        if daraja not in RAQIBLAR:
            return cors(web.json_response({"ok": False, "error": "unknown"}, status=404))
        qosh["game"] = await asyncio.to_thread(_boshla, uid, daraja)
    elif body.get("move") is not None:
        tur = str(body.get("move"))
        try:
            acc, oyin = max(0, min(100, int(body.get("acc")))), int(body.get("game"))
        except (TypeError, ValueError):
            acc, oyin = 0, 0
        if tur not in TURLAR:
            return cors(web.json_response({"ok": False, "error": "unknown"}, status=404))
        r = await asyncio.to_thread(_yur, uid, oyin, tur, acc)
        if r is None:
            return cors(web.json_response({"ok": False, "error": "no_game"}))
        qosh = r
        if r["game"]["over"] and _cfg.get("log"):
            try:
                await _cfg["log"](user, "duel_%d_%s" % (r["game"]["level"], "yutdi" if r["game"]["won"] else "yutqazdi"))
            except Exception as e:
                logging.error("Duel: log yozilmadi: %s", e)
    javob = await asyncio.to_thread(_holat, uid)
    javob.update(qosh)
    return cors(web.json_response(javob))


def register(app, cfg):
    """cfg: verify_init_data, cors, log. hpdars DAN KEYIN ulanadi."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/duel", api_duel)
    logging.info("Duel: %d raqib", len(RAQIBLAR))
