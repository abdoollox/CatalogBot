# -*- coding: utf-8 -*-
"""Duel (egasi, 2026-10-09). 1-BOSQICH: kompyuter raqiblar bilan duel va haftalik SARALASH jadvali.

REJA (egasi tasdiqlagan): duel - haftalik turnir, Chempionlar ligasi kabi. Dushanba-chorshanba SARALASH (kompyuter
raqiblar bilan, eng yaxshi natija bo'yicha jadval), payshanba 1/8, juma chorak, shanba yarim final, yakshanba final -
eng yaxshi 16 kishi (yetmasa 8). Pley-off JONLI: o'quvchilar BELGILANGAN VAQTDA onlayn bo'ladi (egasi: «yopiq»,
har kim o'z vaqtida o'ynaydigan duel YOQMADI - qayta taklif qilmang). Ball: pley-offga chiqqanga +5, chorak +10,
yarim final +15, final +20, g'olib +30 - SHU HAFTA kubogiga tushishi shart (keyingi haftaga o'tmasin).

PLEY-OFF (2-bosqich): payshanba 00:00 dan keyin birinchi so'rovda TO'R tuziladi (saralash jadvalining eng yaxshi
16 / 8 / 4 / 2 tasi; 1-o'rin oxirgisi bilan). Har bosqich o'z kunida soat 21:00 da (Toshkent): 16 - payshanba,
8 - juma, 4 - shanba, 2 - yakshanba. Duelchi «arena»ga kiradi ({arena: id} - har 1,5 soniyada so'raydi); ikkalasi
kelgach duel boshlanadi; 5 daqiqa ichida kelmagan yutqazadi (ikkalasi kelmasa - saralashda yuqori turgani o'tadi).
Raund: 30 soniya ichida tur + aniqlik yuboriladi ({arena, move, acc}); yubormagan - «afsun chiqmadi». Holat DANGASA
hisoblanadi (har so'rovda va 15 soniyada bir fon aylanasi - `kuzatuvchi`). BALL: to'rga kirganga +5; g'alaba uchun
1/8 da +10, chorakda +15, yarim finalda +20, finalda +30 ('dars' manbasi, ref duel:<hafta>:<bosqich>) - darhol,
ya'ni SHU hafta kubogiga. ESLATMA: o'sha kuni 10:00 da va duelga 10 daqiqa qolganda (20:50) - boyo'g'li + bot.
Sinov: admin {sinov: 1} - kompyuter raqib bilan arena (ballsiz), jonli oqimni tekshirish uchun.

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
import json
import logging
import random
import time
from datetime import datetime, timedelta

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

PLEYOFF_DAN = "2026-10-12"     # shu haftadan (dushanba sanasi) boshlab pley-off o'tkaziladi
SOAT = 21                      # duellar boshlanadigan soat (Toshkent)
KUTISH = 300                   # kelmagan duelchi shuncha soniya kutiladi
RAUND_T = 30                   # raundga vaqt (tur tanlash + chizish)
PAUZA = 6                      # raund natijasi ko'rsatiladigan vaqt
BOR = 15                       # oxirgi so'rovdan shuncha soniya o'tmagan bo'lsa - arenada
BOSQICH_KUN = {16: 3, 8: 4, 4: 5, 2: 6}        # dushanbadan necha kun keyin
BOSQICH_BALL = {16: 10, 8: 15, 4: 20, 2: 30}   # shu bosqichdagi g'alaba uchun
KIRISH_BALL = 5
BOT_UID = -999                 # sinov raqibi (kompyuter)

_cfg = {}


def _now():
    return hpcup.now_tk()


def _ep(dt=None):
    return (dt or _now()).timestamp()


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
        conn.execute("CREATE TABLE IF NOT EXISTS duel_turnir (hafta TEXT PRIMARY KEY, hajm INTEGER NOT NULL, vaqt TEXT NOT NULL)")
        conn.execute("CREATE TABLE IF NOT EXISTS duel_match ("
                     " id INTEGER PRIMARY KEY AUTOINCREMENT, hafta TEXT NOT NULL, bosqich INTEGER NOT NULL, joy INTEGER NOT NULL,"
                     " a INTEGER, b INTEGER, a_seed INTEGER, b_seed INTEGER, bosh REAL NOT NULL, holat TEXT NOT NULL DEFAULT 'kutmoqda',"
                     " golib INTEGER, sabab TEXT, a_jon INTEGER NOT NULL DEFAULT 3, b_jon INTEGER NOT NULL DEFAULT 3,"
                     " raund INTEGER NOT NULL DEFAULT 0, r_bosh REAL, a_yur TEXT, a_acc INTEGER, b_yur TEXT, b_acc INTEGER,"
                     " a_sum INTEGER NOT NULL DEFAULT 0, b_sum INTEGER NOT NULL DEFAULT 0, a_keldi REAL, b_keldi REAL, oxirgi TEXT,"
                     " UNIQUE (hafta, bosqich, joy))")
        conn.execute("CREATE TABLE IF NOT EXISTS duel_eslatma (hafta TEXT NOT NULL, bosqich INTEGER NOT NULL, tur TEXT NOT NULL,"
                     " PRIMARY KEY (hafta, bosqich, tur))")
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


# ============================== PLEY-OFF ==============================

def _tartib(n):
    """To'rdagi o'rinlar tartibi: 1 va 2 faqat finalda uchrashadi. _tartib(8) = [1, 8, 4, 5, 2, 7, 3, 6]."""
    t = [1, 2]
    while len(t) < n:
        m = len(t) * 2 + 1
        t = [x for s in t for x in (s, m - s)]
    return t


def _bosqich_vaqti(hafta, bosqich):
    """Bosqich boshlanadigan vaqt (epoch): hafta dushanbasi + kun, 21:00 Toshkent."""
    y, m, d = (int(x) for x in hafta.split("-"))
    dt = datetime(y, m, d, SOAT, 0, 0, tzinfo=_now().tzinfo) + timedelta(days=BOSQICH_KUN[bosqich])
    return dt.timestamp()


def _saral(conn, hafta):
    return conn.execute(
        "SELECT s.user_id, SUM(s.ball) AS ball, MAX(s.vaqt) AS vaqt, COALESCE(u.first_name, 'Sehrgar') AS name, u.house "
        "FROM duel_saral s JOIN users u ON u.user_id = s.user_id WHERE s.hafta=? AND u.house IS NOT NULL AND s.user_id > 0 "
        "GROUP BY s.user_id ORDER BY ball DESC, vaqt ASC", (hafta,)).fetchall()


def _tor_tuz(conn, hafta, berish):
    """Payshanbadan boshlab bir marta: saralash jadvalidan to'r. Qatnashchilarga kirish bali."""
    if hafta < PLEYOFF_DAN or _now().weekday() < 3:
        return
    cur = conn.execute("INSERT OR IGNORE INTO duel_turnir (hafta, hajm, vaqt) VALUES (?,0,?)", (hafta, hpcup._utc_iso(_now())))
    if cur.rowcount < 1:
        return
    rows = _saral(conn, hafta)
    hajm = 16 if len(rows) >= 16 else 8 if len(rows) >= 8 else 4 if len(rows) >= 4 else 2 if len(rows) >= 2 else 0
    conn.execute("UPDATE duel_turnir SET hajm=? WHERE hafta=?", (hajm, hafta))
    if not hajm:
        return
    t, s = _tartib(hajm), hajm
    for i in range(hajm // 2):
        a, b = t[2 * i], t[2 * i + 1]
        conn.execute("INSERT INTO duel_match (hafta, bosqich, joy, a, b, a_seed, b_seed, bosh) VALUES (?,?,?,?,?,?,?,?)",
                     (hafta, hajm, i, rows[a - 1]["user_id"], rows[b - 1]["user_id"], a, b, _bosqich_vaqti(hafta, hajm)))
    s = hajm // 2
    while s >= 2:
        for i in range(s // 2):
            conn.execute("INSERT INTO duel_match (hafta, bosqich, joy, bosh) VALUES (?,?,?,?)", (hafta, s, i, _bosqich_vaqti(hafta, s)))
        s //= 2
    for r in rows[:hajm]:
        berish.append((r["user_id"], "duel:%s:k" % hafta, KIRISH_BALL))


def _tugat(conn, m, golib, sabab, berish):
    conn.execute("UPDATE duel_match SET holat='tugadi', golib=?, sabab=? WHERE id=?", (golib, sabab, m["id"]))
    if m["hafta"].startswith("sinov"):
        return
    berish.append((golib, "duel:%s:%d" % (m["hafta"], m["bosqich"]), BOSQICH_BALL.get(m["bosqich"], 0)))
    nb = m["bosqich"] // 2
    if nb >= 2:
        yon = "a" if m["joy"] % 2 == 0 else "b"
        seed = m["a_seed"] if golib == m["a"] else m["b_seed"]
        conn.execute("UPDATE duel_match SET %s=?, %s_seed=? WHERE hafta=? AND bosqich=? AND joy=?" % (yon, yon),
                     (golib, seed, m["hafta"], nb, m["joy"] // 2))


def _match_yur(conn, m, now, berish, rnd=random):
    """Bitta uchrashuvni hozirgi vaqtga keltiradi (boshlash, raundni hal qilish, tugatish)."""
    if m["holat"] == "tugadi" or m["a"] is None or m["b"] is None or now < m["bosh"]:
        return
    bor = lambda yon: m[yon] == BOT_UID or (m[yon + "_keldi"] is not None and now - m[yon + "_keldi"] <= BOR)
    if m["holat"] == "kutmoqda":
        if bor("a") and bor("b"):
            conn.execute("UPDATE duel_match SET holat='ketmoqda', raund=1, r_bosh=?, a_jon=?, b_jon=? WHERE id=? AND holat='kutmoqda'", (now, JON, JON, m["id"]))
        elif now >= m["bosh"] + KUTISH:
            # kelgan deb: boshlanish vaqtida yoki undan keyin arenada ko'ringan (hozir chiqib ketgan bo'lsa ham)
            keldi = lambda yon: m[yon] == BOT_UID or (m[yon + "_keldi"] is not None and m[yon + "_keldi"] >= m["bosh"] - BOR)
            if keldi("a") != keldi("b"):
                _tugat(conn, m, m["a"] if keldi("a") else m["b"], "kelmadi", berish)
            else:
                _tugat(conn, m, m["a"] if (m["a_seed"] or 99) < (m["b_seed"] or 99) else m["b"], "ikkalasi", berish)
        return
    if now < (m["r_bosh"] or 0):
        return                                  # raund natijasi ko'rsatilmoqda
    ay, aa, by, ba = m["a_yur"], m["a_acc"], m["b_yur"], m["b_acc"]
    for yon in ("a", "b"):                      # sinov raqibi 3 soniyadan keyin o'zi yuradi
        if m[yon] == BOT_UID and m[yon + "_yur"] is None and now >= m["r_bosh"] + 3:
            tur, acc = _raqib_yurishi(2, "", rnd)
            if yon == "a":
                ay, aa = tur, acc
            else:
                by, ba = tur, acc
            conn.execute("UPDATE duel_match SET %s_yur=?, %s_acc=? WHERE id=?" % (yon, yon), (tur, acc, m["id"]))
    if not ((ay and by) or now >= m["r_bosh"] + RAUND_T):
        return
    if not ay:
        ay, aa = "hujum", 0
    if not by:
        by, ba = "hujum", 0
    w = hal_qil(ay, aa, by, ba)
    aj, bj = m["a_jon"] - (1 if w < 0 else 0), m["b_jon"] - (1 if w > 0 else 0)
    asum, bsum = m["a_sum"] + aa, m["b_sum"] + ba
    ox = json.dumps({"r": m["raund"], "a": [ay, aa], "b": [by, ba], "w": w})
    tugadi = aj <= 0 or bj <= 0 or m["raund"] >= RAUND_MAX
    conn.execute("UPDATE duel_match SET a_jon=?, b_jon=?, a_sum=?, b_sum=?, oxirgi=?, a_yur=NULL, a_acc=NULL, b_yur=NULL, b_acc=NULL, "
                 "raund=?, r_bosh=? WHERE id=?", (aj, bj, asum, bsum, ox, m["raund"] + (0 if tugadi else 1), now + PAUZA, m["id"]))
    if tugadi:
        if aj != bj:
            golib = m["a"] if aj > bj else m["b"]
        elif asum != bsum:
            golib = m["a"] if asum > bsum else m["b"]
        else:
            golib = m["a"] if (m["a_seed"] or 99) < (m["b_seed"] or 99) else m["b"]
        _tugat(conn, m, golib, "duel", berish)


def _eslatmalar(conn, hafta, xabarlar):
    """Bugungi eslatmalar: to'rga kirganlar (payshanba 10:00), duel kuni 10:00 va 20:50."""
    t = conn.execute("SELECT hajm FROM duel_turnir WHERE hafta=?", (hafta,)).fetchone()
    if not t or not t["hajm"]:
        return
    hozir = _now()
    kun, daq = hozir.weekday(), hozir.hour * 60 + hozir.minute
    def belgi(bosqich, tur):
        return conn.execute("INSERT OR IGNORE INTO duel_eslatma (hafta, bosqich, tur) VALUES (?,?,?)", (hafta, bosqich, tur)).rowcount > 0
    if (kun > 3 or (kun == 3 and daq >= 600)) and belgi(0, "kirdi"):
        for m in conn.execute("SELECT a, b, bosqich FROM duel_match WHERE hafta=? AND bosqich=?", (hafta, t["hajm"])).fetchall():
            for u in (m["a"], m["b"]):
                xabarlar.append((u, "kirdi", m["bosqich"]))
    for bosqich, k in BOSQICH_KUN.items():
        if bosqich > t["hajm"] or k != kun:
            continue
        tur = "on" if SOAT * 60 - 10 <= daq < SOAT * 60 + 5 else "ertalab" if 600 <= daq < SOAT * 60 - 10 else None
        if tur == "ertalab" and bosqich == t["hajm"] and k == 3:
            continue                            # payshanba: «kirdi» xatining o'zi yetadi
        if tur and belgi(bosqich, tur):
            for m in conn.execute("SELECT a, b FROM duel_match WHERE hafta=? AND bosqich=? AND holat<>'tugadi' "
                                  "AND a IS NOT NULL AND b IS NOT NULL", (hafta, bosqich)).fetchall():
                for u in (m["a"], m["b"]):
                    xabarlar.append((u, tur, bosqich))


def _tick():
    """Turnirni hozirgi vaqtga keltiradi. Qaytaradi: (beriladigan ballar, yuboriladigan xatlar)."""
    berish, xabarlar = [], []
    hafta, now = hpdars._hafta(), _ep()
    conn = hpcup._connect()
    try:
        _tor_tuz(conn, hafta, berish)
        for i in range(4):                      # g'olib keyingi bosqichga o'tgach u ham tekshiriladi
            for m in conn.execute("SELECT * FROM duel_match WHERE holat<>'tugadi' AND a IS NOT NULL AND b IS NOT NULL AND bosh<=?", (now,)).fetchall():
                _match_yur(conn, m, now, berish)
        _eslatmalar(conn, hafta, xabarlar)
        conn.commit()
    finally:
        conn.close()
    return berish, xabarlar


KUN_NOMI = {"uz": {16: "payshanba", 8: "juma", 4: "shanba", 2: "yakshanba"}, "ru": {16: "четверг", 8: "пятница", 4: "суббота", 2: "воскресенье"},
            "en": {16: "Thursday", 8: "Friday", 4: "Saturday", 2: "Sunday"}}
BOSQICH_NOMI = {"uz": {16: "1/8 final", 8: "chorak final", 4: "yarim final", 2: "final"}, "ru": {16: "1/8 финала", 8: "четвертьфинал", 4: "полуфинал", 2: "финал"},
                "en": {16: "round of 16", 8: "quarter-final", 4: "semi-final", 2: "final"}}


def xat_matni(tur, bosqich):
    """{til: (sarlavha, matn)} - duel xatlari."""
    k, b = KUN_NOMI, BOSQICH_NOMI
    if tur == "kirdi":
        return {"uz": ("Siz duel turnirining pley-offiga chiqdingiz!", "Birinchi duelingiz — %s: %s kuni soat 21:00 da. Vaqtida ilovaga kiring: Xogvarts → Duel. 5 daqiqa ichida kelmagan duelchi yutqazadi." % (b["uz"][bosqich], k["uz"][bosqich])),
                "ru": ("Вы вышли в плей-офф дуэльного турнира!", "Ваша первая дуэль — %s: %s, 21:00. Зайдите вовремя: Хогвартс → Дуэль. Кто не придёт в течение 5 минут — проигрывает." % (b["ru"][bosqich], k["ru"][bosqich])),
                "en": ("You are through to the duelling play-offs!", "Your first duel is the %s: %s at 21:00. Be on time: Hogwarts → Duel. Anyone who fails to turn up within 5 minutes loses." % (b["en"][bosqich], k["en"][bosqich]))}
    if tur == "ertalab":
        return {"uz": ("Bugun 21:00 da duelingiz bor", "Duel turniri, %s. Soat 21:00 da ilovaga kiring: Xogvarts → Duel. Kelmagan duelchi yutqazadi." % b["uz"][bosqich]),
                "ru": ("Сегодня в 21:00 ваша дуэль", "Дуэльный турнир, %s. Зайдите в 21:00: Хогвартс → Дуэль. Не пришедший проигрывает." % b["ru"][bosqich]),
                "en": ("Your duel is today at 21:00", "Duelling tournament, %s. Come in at 21:00: Hogwarts → Duel. A duellist who does not turn up loses." % b["en"][bosqich])}
    return {"uz": ("Duelga 10 daqiqa qoldi!", "Raqibingiz kutmoqda (%s). Hoziroq ilovaga kiring: Xogvarts → Duel." % b["uz"][bosqich]),
            "ru": ("До дуэли 10 минут!", "Соперник ждёт (%s). Зайдите прямо сейчас: Хогвартс → Дуэль." % b["ru"][bosqich]),
            "en": ("10 minutes to your duel!", "Your opponent is waiting (%s). Come in now: Hogwarts → Duel." % b["en"][bosqich])}


async def tick():
    berish, xabarlar = await asyncio.to_thread(_tick)
    for uid, ref, pts in berish:
        if pts > 0 and uid and uid > 0:
            await asyncio.to_thread(hpcup._award, uid, "dars", ref, pts)
    for uid, tur, bosqich in xabarlar:
        if uid and uid > 0 and _cfg.get("xat"):
            try:
                await _cfg["xat"](uid, xat_matni(tur, bosqich))
            except Exception as e:
                logging.error("Duel xati yuborilmadi (%s): %s", uid, e)
    return len(berish), len(xabarlar)


async def kuzatuvchi(interval=15):
    """Fon aylanasi: hech kim so'ramasa ham uchrashuvlar yopiladi va eslatmalar vaqtida ketadi."""
    while True:
        try:
            await tick()
        except Exception as e:
            logging.error("Duel kuzatuvchisi: %s", e)
        await asyncio.sleep(interval)


def _odamlar(conn, uidlar):
    uidlar = [u for u in set(uidlar) if u is not None and u > 0]
    if not uidlar:
        return {}
    q = conn.execute("SELECT user_id, COALESCE(first_name, 'Sehrgar') AS name, house FROM users WHERE user_id IN (%s)" % ",".join("?" * len(uidlar)), uidlar)
    return {r["user_id"]: {"name": hpdars._ism(r["name"]), "house": r["house"]} for r in q}


def _kim(od, uid, seed):
    if uid is None:
        return None
    if uid == BOT_UID:
        return {"uid": 0, "name": "Sinov raqibi", "house": None, "seed": 0}
    o = od.get(uid, {"name": "Sehrgar", "house": None})
    return {"uid": uid, "name": o["name"], "house": o["house"], "seed": seed}


def _kubok(conn, uid, hafta):
    """Pley-off holati ilova uchun."""
    if hafta < PLEYOFF_DAN:
        return {"from": PLEYOFF_DAN, "size": None}
    t = conn.execute("SELECT hajm FROM duel_turnir WHERE hafta=?", (hafta,)).fetchone()
    if not t:
        return {"size": None, "hour": SOAT}
    ms = conn.execute("SELECT * FROM duel_match WHERE hafta=? ORDER BY bosqich DESC, joy", (hafta,)).fetchall()
    od = _odamlar(conn, [x for m in ms for x in (m["a"], m["b"])])
    bosq, men = {}, None
    for m in ms:
        bosq.setdefault(m["bosqich"], []).append({
            "id": m["id"], "a": _kim(od, m["a"], m["a_seed"]), "b": _kim(od, m["b"], m["b_seed"]), "winner": m["golib"],
            "state": m["holat"], "lives": [m["a_jon"], m["b_jon"]], "why": m["sabab"]})
        if uid in (m["a"], m["b"]) and m["holat"] != "tugadi":
            # eng yaqin (eng katta bosqichli) tugamagan uchrashuvi; raqibi hali aniqlanmagan bo'lishi mumkin
            men = men or {"id": m["id"], "stage": m["bosqich"], "ts": m["bosh"], "ready": m["a"] is not None and m["b"] is not None}
    return {"size": t["hajm"], "hour": SOAT, "wait": KUTISH, "now": _ep(), "my": men,
            "stages": [{"stage": b, "ts": _bosqich_vaqti(hafta, b), "matches": bosq[b]} for b in sorted(bosq, reverse=True)]}


def _arena(uid, mid, tur=None, acc=0, rnd=random):
    """Arena so'rovi: kelganini belgilaydi, (bo'lsa) yurishni yozadi, uchrashuvni hozirga keltiradi va holatni qaytaradi."""
    uid, now, berish = int(uid), _ep(), []
    conn = hpcup._connect()
    try:
        m = conn.execute("SELECT * FROM duel_match WHERE id=?", (int(mid),)).fetchone()
        if not m or uid not in (m["a"], m["b"]):
            return None, berish
        yon = "a" if m["a"] == uid else "b"
        if m["holat"] != "tugadi":
            conn.execute("UPDATE duel_match SET %s_keldi=? WHERE id=?" % yon, (now, m["id"]))
            if tur and m["holat"] == "ketmoqda" and now >= (m["r_bosh"] or 0) and m[yon + "_yur"] is None:
                conn.execute("UPDATE duel_match SET %s_yur=?, %s_acc=? WHERE id=?" % (yon, yon), (tur, acc, m["id"]))
            m = conn.execute("SELECT * FROM duel_match WHERE id=?", (m["id"],)).fetchone()
            _match_yur(conn, m, now, berish, rnd)
            conn.commit()
            m = conn.execute("SELECT * FROM duel_match WHERE id=?", (m["id"],)).fetchone()
        u = "b" if yon == "a" else "a"
        od = _odamlar(conn, [m[u]])
        ox = json.loads(m["oxirgi"]) if m["oxirgi"] else None
        last = None
        if ox:
            w = ox["w"] if yon == "a" else -ox["w"]
            last = {"r": ox["r"], "mine": ox[yon][0], "acc": ox[yon][1], "his": ox[u][0], "racc": ox[u][1], "win": w}
        if m["holat"] == "tugadi":
            phase = "reveal" if (m["sabab"] == "duel" and now < (m["r_bosh"] or 0)) else "over"
        elif m["holat"] == "kutmoqda":
            phase = "early" if now < m["bosh"] else "wait"
        else:
            phase = "reveal" if now < (m["r_bosh"] or 0) else "pick"
        return {
            "id": m["id"], "stage": m["bosqich"], "test": m["hafta"].startswith("sinov"), "phase": phase,
            "starts_in": max(0, int(m["bosh"] - now)), "wait_left": max(0, int(m["bosh"] + KUTISH - now)),
            "round": m["raund"], "deadline_in": max(0, int((m["r_bosh"] or now) + RAUND_T - now)) if phase == "pick" else 0,
            "next_in": max(0, int((m["r_bosh"] or now) - now)) if phase == "reveal" else 0,
            "lives": m[yon + "_jon"], "rlives": m[u + "_jon"], "moved": m[yon + "_yur"] is not None,
            "opp": dict(_kim(od, m[u], m[u + "_seed"]), here=(m[u] == BOT_UID or (m[u + "_keldi"] is not None and now - m[u + "_keldi"] <= BOR))),
            "last": last, "over": m["holat"] == "tugadi", "won": m["golib"] == uid, "why": m["sabab"],
        }, berish
    finally:
        conn.close()


def _sinov(uid):
    """Admin uchun sinov uchrashuvi: kompyuter raqib bilan, 12 soniyadan keyin boshlanadi, ballsiz."""
    uid, hafta = int(uid), "sinov:%d" % int(uid)
    conn = hpcup._connect()
    try:
        conn.execute("DELETE FROM duel_match WHERE hafta=?", (hafta,))
        cur = conn.execute("INSERT INTO duel_match (hafta, bosqich, joy, a, b, a_seed, b_seed, bosh) VALUES (?,2,0,?,?,1,2,?)", (hafta, uid, BOT_UID, _ep() + 12))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


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
            "rules": {"lives": JON, "fail": KAM, "top": TOP, "round": RAUND_T},
            "cup": _kubok(conn, uid, hafta), "admin": uid in set(_cfg.get("admin_ids") or ()),
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
    try:
        await tick()
    except Exception as e:
        logging.error("Duel tick: %s", e)
    if body.get("sinov") and uid in set(_cfg.get("admin_ids") or ()):
        qosh["test_id"] = await asyncio.to_thread(_sinov, uid)
    elif body.get("arena") is not None:
        tur = str(body.get("move")) if body.get("move") in TURLAR else None
        try:
            mid, acc = int(body.get("arena")), max(0, min(100, int(body.get("acc") or 0)))
        except (TypeError, ValueError):
            mid, acc = 0, 0
        ar, berish = await asyncio.to_thread(_arena, uid, mid, tur, acc)
        if ar is None:
            return cors(web.json_response({"ok": False, "error": "no_match"}))
        for u, ref, pts in berish:
            if pts > 0 and u and u > 0:
                await asyncio.to_thread(hpcup._award, u, "dars", ref, pts)
        if ar["over"] and berish and _cfg.get("log"):
            try:
                await _cfg["log"](user, "duel_pleyoff_%d_%s" % (ar["stage"], "yutdi" if ar["won"] else "yutqazdi"))
            except Exception:
                pass
        return cors(web.json_response({"ok": True, "arena": ar}))
    elif body.get("start") is not None:
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
