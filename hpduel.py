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

QOIDA: har duelchida 5 jon (JON). Har raundda ikkalasi bir vaqtda tur tanlaydi - hujum / himoya / hiyla - va afsunni
chizadi (aniqlik 0..100, ilova o'lchaydi). Afsun KUCHI = aniqlik, ustun tur bo'lsa +25 (hujum hiyladan, hiyla himoyadan,
himoya hujumdan ustun). Kuchi baland yutadi (farq 5 dan kam - durang). Aniqlik 35 dan past - afsun chiqmadi (kuch 0).
Yutqazgan 1 jon yo'qotadi. Ya'ni yaxshi chizgan odam noqulay turda ham yuta oladi - mahorat omaddan muhimroq.

YANGI FORMAT (egasi, 2026-10-10) - yuqoridagi «saralash + 4 kunlik pley-off» o'rniga:
  SARALASH YO'Q, 16 CHEGARASI YO'Q. Turnir HAFTADA BIR MARTA, BIR OQSHOMDA: TURNIR_KUN (yakshanba) soat 21:00 da boshlanib,
  g'olib shu kuni aniqlanadi. Qatnashish - «Qatnashaman» tugmasi ({join: 1}), yozilish turnirdan YOPILISH (5 daqiqa) oldin yopiladi.
  ISTALGAN SONDAGI ishtirokchi: to'r eng yaqin 2 ning darajasiga to'ldiriladi, REYTINGI yuqorilar birinchi bosqichni
  o'tkazib yuboradi («bye» - futbol kubogidagi kabi), pastdagilar dastlabki bosqichda o'ynaydi. Har duelga eng ko'pi MATCH_T
  (5 daqiqa), bosqichlar orasida ORALIQ (1 daqiqa); raund RAUND_T (20 s) + natija PAUZA (5 s). Vaqt tugasa: joni ko'p,
  keyin aniqliklar yig'indisi, keyin reytingdagi o'rni. Kelmagan duelchi KUTISH (1 daqiqa) kutiladi.
  REYTING (duel_reyting): hamma 1000 dan boshlaydi, har duel natijasi bo'yicha (Elo usuli): jonli duelda K=32,
  kompyuter raqib bilan K=16 (raqib reytingi qat'iy: 850 / 1050 / 1250). Kuchli raqibni yengsa ko'p, kuchsizni yengsa oz qo'shiladi.
  BALL: g'alaba uchun 1/8 da +5, chorakda +10, yarim finalda +20, finalda +30; undan oldingi bosqichlarga berilmaydi.

POST /api/duel  (initData)
  {join: 1|0}                -> turnirga yozilish / chiqish
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
JON = 5                        # egasi, 2026-10-09: 3 emas, 5 jon
KAM = 35                       # bundan past aniqlik - afsun chiqmadi
DURANG = 5                     # kuchlar farqi shundan kam bo'lsa durang
USTUN = 25                     # ustun tur uchun kuchga qo'shimcha (hujum > hiyla > himoya > hujum)
RAUND_MAX = 20
# Kompyuter raqiblar: (o'rtacha aniqlik, tarqoqlik, o'yinchining odatiga qarshi o'ynash ehtimoli)
RAQIBLAR = {1: (50, 15, 0.0), 2: (68, 11, 0.3), 3: (84, 8, 0.5)}
TOP = 16

PLEYOFF_DAN = "2026-10-05"     # shu haftadan (dushanba sanasi) boshlab turnir o'tkaziladi
TURNIR_KUN = 6                 # haftaning kuni (0 - dushanba): yakshanba. Kelajakda har kunga alohida turnir bo'lishi mumkin
SOAT = 21                      # turnir boshlanadigan soat (Toshkent)
MATCH_T = 300                  # bitta duelga eng ko'p vaqt (s)
ORALIQ = 60                    # bosqichlar orasidagi tanaffus (s)
YOPILISH = 300                 # yozilish turnirdan shuncha oldin yopiladi va to'r tuziladi
KUTISH = 60                    # kelmagan duelchi shuncha soniya kutiladi
RAUND_T = 20                   # raundga vaqt (tur tanlash + chizish)
PAUZA = 5                      # raund natijasi ko'rsatiladigan vaqt
BOR = 15                       # oxirgi so'rovdan shuncha soniya o'tmagan bo'lsa - arenada
BOSQICH_BALL = {16: 5, 8: 10, 4: 20, 2: 30}    # shu bosqichdagi G'ALABA uchun (egasi, 2026-10-10); oldingi bosqichlarga yo'q
REYTING0, K_JONLI, K_BOT = 1000, 32, 16
BOT_R = {1: 850, 2: 1050, 3: 1250}              # kompyuter raqiblarning qat'iy reytingi
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
        conn.execute("CREATE TABLE IF NOT EXISTS duel_qatnash (hafta TEXT NOT NULL, user_id INTEGER NOT NULL, vaqt TEXT NOT NULL,"
                     " PRIMARY KEY (hafta, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS duel_reyting (user_id INTEGER PRIMARY KEY, reyting REAL NOT NULL, oyin INTEGER NOT NULL DEFAULT 0,"
                     " galaba INTEGER NOT NULL DEFAULT 0)")
        # Duel TARIXI (egasi, 2026-10-10): har raund yoziladi - keyin raund-raund qayta ko'rish uchun
        for jadval in ("duel_oyin", "duel_match"):
            if "tarix" not in [r[1] for r in conn.execute("PRAGMA table_info(%s)" % jadval)]:
                conn.execute("ALTER TABLE %s ADD COLUMN tarix TEXT NOT NULL DEFAULT '[]'" % jadval)
        # Reyting BIR MARTA eski duellardan hisoblanadi (kompyuter raqiblar bilan o'ynalganlari, tartibi bilan)
        if conn.execute("INSERT OR IGNORE INTO duel_eslatma (hafta, bosqich, tur) VALUES ('migr', 0, 'reyting')").rowcount > 0:
            for g in conn.execute("SELECT user_id, daraja, holat FROM duel_oyin WHERE holat IN ('yutdi','yutqazdi') ORDER BY id").fetchall():
                _elo_bot(conn, g["user_id"], g["daraja"], g["holat"] == "yutdi")
        conn.commit()
    finally:
        conn.close()


def kuch(tur, acc, raqib_turi):
    """Afsun kuchi: chizish aniqligi + ustun tur uchun qo'shimcha. Aniqlik KAM dan past - afsun chiqmadi (0)."""
    if acc < KAM:
        return 0
    return acc + (USTUN if YENGADI[tur] == raqib_turi else 0)


def hal_qil(men, macc, u, uacc):
    """Raund natijasi: 1 - men yutdim, -1 - yutqazdim, 0 - durang. KUCHI baland yutadi (egasi, 2026-10-09:
    ilgari tur hal qilardi - bu omad o'yini edi; endi aniqlik hal qiladi, to'g'ri tur esa ustunlik beradi)."""
    mk, uk = kuch(men, macc, u), kuch(u, uacc, men)
    if abs(mk - uk) < DURANG:
        return 0
    return 1 if mk > uk else -1


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


def _turnir_vaqti(hafta):
    """Turnir boshlanadigan payt (epoch): hafta dushanbasi + TURNIR_KUN, SOAT:00 Toshkent."""
    y, m, d = (int(x) for x in hafta.split("-"))
    return (datetime(y, m, d, SOAT, 0, 0, tzinfo=_now().tzinfo) + timedelta(days=TURNIR_KUN)).timestamp()


def _bosqich_vaqti(hafta, bosqich, hajm):
    """Bosqich boshlanadigan vaqt: birinchi bosqich (hajm) - turnir boshida, keyingilari har MATCH_T + ORALIQ da."""
    n, b = 0, hajm
    while b > bosqich:
        b //= 2
        n += 1
    return _turnir_vaqti(hafta) + n * (MATCH_T + ORALIQ)


# ---------- reyting (Elo) ----------
def _reyting(conn, uid):
    r = conn.execute("SELECT reyting, oyin, galaba FROM duel_reyting WHERE user_id=?", (int(uid),)).fetchone()
    return (float(r["reyting"]), int(r["oyin"]), int(r["galaba"])) if r else (float(REYTING0), 0, 0)


def _reyting_yoz(conn, uid, r, yutdi):
    conn.execute("INSERT INTO duel_reyting (user_id, reyting, oyin, galaba) VALUES (?,?,1,?) "
                 "ON CONFLICT(user_id) DO UPDATE SET reyting=excluded.reyting, oyin=oyin+1, galaba=galaba+excluded.galaba",
                 (int(uid), float(r), 1 if yutdi else 0))


def _kutilgan(ra, rb):
    return 1.0 / (1.0 + 10 ** ((rb - ra) / 400.0))


def _elo_bot(conn, uid, daraja, yutdi):
    """Kompyuter raqib bilan duel: raqib reytingi qat'iy (BOT_R), K kichik - oson raqibni yengib reyting «bosib» bo'lmaydi."""
    if int(uid) <= 0:
        return 0
    r = _reyting(conn, uid)[0]
    farq = K_BOT * ((1.0 if yutdi else 0.0) - _kutilgan(r, BOT_R.get(int(daraja), REYTING0)))
    _reyting_yoz(conn, uid, r + farq, yutdi)
    return int(round(farq))


def _elo_jonli(conn, golib, yutqazgan):
    """Jonli duel: ikkala tomonning reytingi o'zgaradi."""
    if not golib or not yutqazgan or golib <= 0 or yutqazgan <= 0:
        return
    rg, ry = _reyting(conn, golib)[0], _reyting(conn, yutqazgan)[0]
    farq = K_JONLI * (1.0 - _kutilgan(rg, ry))
    _reyting_yoz(conn, golib, rg + farq, True)
    _reyting_yoz(conn, yutqazgan, ry - farq, False)


def _qatnashchilar(conn, hafta):
    """Yozilganlar - REYTING bo'yicha (yuqoridan), teng bo'lsa ko'proq o'ynagan, keyin oldin yozilgan."""
    return conn.execute(
        "SELECT q.user_id, COALESCE(r.reyting, ?) AS reyting, COALESCE(r.oyin, 0) AS oyin, q.vaqt, COALESCE(u.first_name, 'Sehrgar') AS name, u.house "
        "FROM duel_qatnash q JOIN users u ON u.user_id = q.user_id LEFT JOIN duel_reyting r ON r.user_id = q.user_id "
        "WHERE q.hafta=? AND u.house IS NOT NULL AND q.user_id > 0 ORDER BY reyting DESC, oyin DESC, q.vaqt ASC", (REYTING0, hafta)).fetchall()


def _tor_tuz(conn, hafta, berish):
    """Turnirdan YOPILISH soniya oldin bir marta: yozilganlardan to'r. Istalgan son: to'r eng yaqin 2 ning darajasiga
    to'ldiriladi, reytingi yuqorilar birinchi bosqichni o'tkazib yuboradi (raqibi yo'q - «bye»)."""
    if hafta < PLEYOFF_DAN or _ep() < _turnir_vaqti(hafta) - YOPILISH:
        return
    cur = conn.execute("INSERT OR IGNORE INTO duel_turnir (hafta, hajm, vaqt) VALUES (?,0,?)", (hafta, hpcup._utc_iso(_now())))
    if cur.rowcount < 1:
        return
    rows = _qatnashchilar(conn, hafta)
    n = len(rows)
    if n < 2:
        return
    hajm = 2
    while hajm < n:
        hajm *= 2
    conn.execute("UPDATE duel_turnir SET hajm=? WHERE hafta=?", (hajm, hafta))
    s = hajm
    while s >= 2:                                # hamma bosqich uchrashuvlari oldindan (bo'sh) yaratiladi
        for i in range(s // 2):
            conn.execute("INSERT INTO duel_match (hafta, bosqich, joy, bosh, a_jon, b_jon) VALUES (?,?,?,?,?,?)",
                         (hafta, s, i, _bosqich_vaqti(hafta, s, hajm), JON, JON))
        s //= 2
    t = _tartib(hajm)
    for i in range(hajm // 2):
        a, b = t[2 * i], t[2 * i + 1]
        conn.execute("UPDATE duel_match SET a=?, a_seed=?, b=?, b_seed=? WHERE hafta=? AND bosqich=? AND joy=?",
                     (rows[a - 1]["user_id"], a, rows[b - 1]["user_id"] if b <= n else None, b if b <= n else None, hafta, hajm, i))
        if b > n:                                # raqibi yo'q: kuchli duelchi keyingi bosqichga o'tadi
            m = conn.execute("SELECT * FROM duel_match WHERE hafta=? AND bosqich=? AND joy=?", (hafta, hajm, i)).fetchone()
            _tugat(conn, m, m["a"], "bye", berish)


def _tugat(conn, m, golib, sabab, berish):
    conn.execute("UPDATE duel_match SET holat='tugadi', golib=?, sabab=? WHERE id=?", (golib, sabab, m["id"]))
    if m["hafta"].startswith("sinov"):
        return
    if sabab != "bye":
        berish.append((golib, "duel:%s:%d" % (m["hafta"], m["bosqich"]), BOSQICH_BALL.get(m["bosqich"], 0)))
    if sabab in ("duel", "vaqt"):                # haqiqatan o'ynalgan duel - reytingga ta'sir qiladi
        _elo_jonli(conn, golib, m["b"] if golib == m["a"] else m["a"])
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
    if now >= m["bosh"] + MATCH_T and not m["hafta"].startswith("sinov"):
        # Duelga ajratilgan vaqt tugadi: joni ko'p, keyin aniqliklar yig'indisi, keyin reytingdagi o'rni
        if m["a_jon"] != m["b_jon"]:
            g = m["a"] if m["a_jon"] > m["b_jon"] else m["b"]
        elif m["a_sum"] != m["b_sum"]:
            g = m["a"] if m["a_sum"] > m["b_sum"] else m["b"]
        else:
            g = m["a"] if (m["a_seed"] or 99) < (m["b_seed"] or 99) else m["b"]
        _tugat(conn, m, g, "vaqt", berish)
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
    tarix = _tarix_ol(m)
    tarix.append({"a": [ay, aa], "b": [by, ba], "w": w})
    conn.execute("UPDATE duel_match SET a_jon=?, b_jon=?, a_sum=?, b_sum=?, oxirgi=?, a_yur=NULL, a_acc=NULL, b_yur=NULL, b_acc=NULL, "
                 "raund=?, r_bosh=?, tarix=? WHERE id=?", (aj, bj, asum, bsum, ox, m["raund"] + (0 if tugadi else 1), now + PAUZA,
                                                           json.dumps(tarix), m["id"]))
    if tugadi:
        if aj != bj:
            golib = m["a"] if aj > bj else m["b"]
        elif asum != bsum:
            golib = m["a"] if asum > bsum else m["b"]
        else:
            golib = m["a"] if (m["a_seed"] or 99) < (m["b_seed"] or 99) else m["b"]
        _tugat(conn, m, golib, "duel", berish)


def _eslatmalar(conn, hafta, xabarlar):
    """Turnir kuni yozilganlarga: ertalab 10:00 va boshlanishiga 10 daqiqa qolganda."""
    if hafta < PLEYOFF_DAN:
        return
    hozir = _now()
    if hozir.weekday() != TURNIR_KUN:
        return
    daq = hozir.hour * 60 + hozir.minute
    tur = "on" if SOAT * 60 - 10 <= daq < SOAT * 60 else "ertalab" if 600 <= daq < SOAT * 60 - 10 else None
    if not tur:
        return
    if conn.execute("INSERT OR IGNORE INTO duel_eslatma (hafta, bosqich, tur) VALUES (?,0,?)", (hafta, tur)).rowcount < 1:
        return
    for r in conn.execute("SELECT user_id FROM duel_qatnash WHERE hafta=?", (hafta,)).fetchall():
        xabarlar.append((r["user_id"], tur, 0))


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




def xat_matni(tur, bosqich=0):
    """{til: (sarlavha, matn)} - duel turniri xatlari (yozilganlarga)."""
    if tur == "ertalab":
        return {"uz": ("Bugun 21:00 da duel turniri", "Siz turnirga yozilgansiz. Soat 21:00 da ilovaga kiring: Xogvarts → Duel. Turnir bir oqshomda tugaydi; 1 daqiqa ichida kelmagan duelchi yutqazadi."),
                "ru": ("Сегодня в 21:00 дуэльный турнир", "Вы записаны на турнир. Зайдите в 21:00: Хогвартс → Дуэль. Турнир проходит за один вечер; кто не придёт в течение минуты — проигрывает."),
                "en": ("The duelling tournament is today at 21:00", "You are signed up. Come in at 21:00: Hogwarts → Duel. The tournament is played in one evening; anyone who is a minute late loses.")}
    return {"uz": ("Turnirga 10 daqiqa qoldi!", "Duel turniri 21:00 da boshlanadi. Hoziroq ilovaga kiring: Xogvarts → Duel."),
            "ru": ("До турнира 10 минут!", "Дуэльный турнир начнётся в 21:00. Зайдите прямо сейчас: Хогвартс → Дуэль."),
            "en": ("10 minutes to the tournament!", "The duelling tournament starts at 21:00. Come in now: Hogwarts → Duel.")}


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
        # turnir oqshomida (boshlanishdan 6 daqiqa oldin - 1,5 soat keyin) tez-tez: bosqichlar oralig'i atigi 1 daqiqa
        try:
            farq = _ep() - _turnir_vaqti(hpdars._hafta())
        except Exception:
            farq = None
        await asyncio.sleep(3 if (farq is not None and -360 <= farq <= 5400) else interval)


def _tarix_ol(row):
    """Yozilgan raundlar ro'yxati (ustun hali bo'lmagan eski qatorda - bo'sh)."""
    try:
        return json.loads(row["tarix"] or "[]")
    except (KeyError, IndexError, TypeError, ValueError):
        return []


def _raundlar(tarix, men_a=True):
    """Raundlar ko'ruvchi tomonidan: mine/acc - birinchi tomon, his/racc - ikkinchi, win - birinchi tomon uchun."""
    out = []
    for r in tarix:
        a, b = (r["a"], r["b"]) if men_a else (r["b"], r["a"])
        out.append({"mine": a[0], "acc": a[1], "his": b[0], "racc": b[1], "win": r["w"] if men_a else -r["w"]})
    return out


def _tarixim(uid, n=20):
    """O'quvchining tugagan duellari: mashq (kompyuter raqib) va pley-off - eng yangisi birinchi."""
    uid = int(uid)
    conn = hpcup._connect()
    try:
        out = []
        for g in conn.execute("SELECT * FROM duel_oyin WHERE user_id=? AND holat IN ('yutdi','yutqazdi') ORDER BY id DESC LIMIT ?", (uid, n)):
            out.append({"k": "o", "id": g["id"], "level": g["daraja"], "won": g["holat"] == "yutdi", "lives": [g["jon"], g["rjon"]],
                        "rounds": g["raund"], "saved": bool(_tarix_ol(g)), "time": g["vaqt"]})
        ms = conn.execute("SELECT * FROM duel_match WHERE (a=? OR b=?) AND holat='tugadi' AND hafta NOT LIKE 'sinov%' ORDER BY id DESC LIMIT ?",
                          (uid, uid, n)).fetchall()
        od = _odamlar(conn, [x for m in ms for x in (m["a"], m["b"])])
        for m in ms:
            men_a = m["a"] == uid
            u = "b" if men_a else "a"
            out.append({"k": "m", "id": m["id"], "stage": m["bosqich"], "won": m["golib"] == uid, "why": m["sabab"],
                        "lives": [m["a_jon"], m["b_jon"]] if men_a else [m["b_jon"], m["a_jon"]],
                        "rounds": len(_tarix_ol(m)), "saved": bool(_tarix_ol(m)), "opp": _kim(od, m[u], m[u + "_seed"]),
                        "time": datetime.fromtimestamp(m["bosh"], tz=_now().tzinfo).astimezone().isoformat()})
        out.sort(key=lambda x: str(x["time"]), reverse=True)
        return out[:n]
    finally:
        conn.close()


def _qayta(uid, tur, oid):
    """Bitta duelni raund-raund qaytaradi. Mashq dueli - faqat egasiga; pley-off uchrashuvi (tugagan) - HAMMAGA:
    o'ynamagan odamga 1-tomon (a) nuqtai nazaridan."""
    uid = int(uid)
    conn = hpcup._connect()
    try:
        if tur == "o":
            g = conn.execute("SELECT * FROM duel_oyin WHERE id=? AND user_id=?", (int(oid), uid)).fetchone()
            if not g or g["holat"] == "ketmoqda":
                return None
            return {"k": "o", "id": g["id"], "level": g["daraja"], "won": g["holat"] == "yutdi", "lives": [g["jon"], g["rjon"]],
                    "start": JON, "rounds": _raundlar(_tarix_ol(g)), "me": True}
        m = conn.execute("SELECT * FROM duel_match WHERE id=? AND holat='tugadi'", (int(oid),)).fetchone()
        if not m or (m["hafta"].startswith("sinov") and uid not in (m["a"], m["b"])):
            return None
        men_a = m["b"] != uid
        od = _odamlar(conn, [m["a"], m["b"]])
        a, b = ("a", "b") if men_a else ("b", "a")
        return {"k": "m", "id": m["id"], "stage": m["bosqich"], "why": m["sabab"], "me": uid in (m["a"], m["b"]),
                "won": m["golib"] == m[a], "p1": _kim(od, m[a], m[a + "_seed"]), "p2": _kim(od, m[b], m[b + "_seed"]),
                "lives": [m[a + "_jon"], m[b + "_jon"]], "start": JON, "rounds": _raundlar(_tarix_ol(m), men_a)}
    finally:
        conn.close()


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
    if not t["hajm"]:
        return {"size": 0, "hour": SOAT}
    ms = conn.execute("SELECT * FROM duel_match WHERE hafta=? ORDER BY bosqich DESC, joy", (hafta,)).fetchall()
    od = _odamlar(conn, [x for m in ms for x in (m["a"], m["b"])])
    bosq, men = {}, None
    for m in ms:
        bosq.setdefault(m["bosqich"], []).append({
            "id": m["id"], "a": _kim(od, m["a"], m["a_seed"]), "b": _kim(od, m["b"], m["b_seed"]), "winner": m["golib"],
            "state": m["holat"], "lives": [m["a_jon"], m["b_jon"]], "why": m["sabab"], "rounds": len(_tarix_ol(m))})
        if uid in (m["a"], m["b"]) and m["holat"] != "tugadi":
            # eng yaqin (eng katta bosqichli) tugamagan uchrashuvi; raqibi hali aniqlanmagan bo'lishi mumkin
            men = men or {"id": m["id"], "stage": m["bosqich"], "ts": m["bosh"], "ready": m["a"] is not None and m["b"] is not None}
    return {"size": t["hajm"], "hour": SOAT, "wait": KUTISH, "now": _ep(), "my": men,
            "match_t": MATCH_T, "gap": ORALIQ,
            "stages": [{"stage": b, "ts": _bosqich_vaqti(hafta, b, t["hajm"]), "points": BOSQICH_BALL.get(b, 0), "matches": bosq[b]}
                       for b in sorted(bosq, reverse=True)]}


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
            "lives": JON if m["holat"] == "kutmoqda" else m[yon + "_jon"], "rlives": JON if m["holat"] == "kutmoqda" else m[u + "_jon"], "moved": m[yon + "_yur"] is not None,
            "opp": dict(_kim(od, m[u], m[u + "_seed"]), here=(m[u] == BOT_UID or (m[u + "_keldi"] is not None and now - m[u + "_keldi"] <= BOR))),
            "last": last, "over": m["holat"] == "tugadi", "won": m["golib"] == uid, "why": m["sabab"],
            "next": _keyingi(conn, uid, m, now), "match_left": max(0, int(m["bosh"] + MATCH_T - now)),
        }, berish
    finally:
        conn.close()


def _keyingi(conn, uid, m, now):
    """Shu turnirdagi navbatdagi (tugamagan) dueli: {id, in} - g'olib keyingi bosqichga shu orqali o'tadi."""
    if m["holat"] != "tugadi" or m["golib"] != uid or m["hafta"].startswith("sinov"):
        return None
    k = conn.execute("SELECT id, bosh FROM duel_match WHERE hafta=? AND holat<>'tugadi' AND (a=? OR b=?) ORDER BY bosqich DESC LIMIT 1",
                     (m["hafta"], uid, uid)).fetchone()
    return {"id": k["id"], "in": max(0, int(k["bosh"] - now))} if k else None


def _yozil(uid, on):
    """Turnirga yozilish / chiqish. Yozilish turnirdan YOPILISH soniya oldin yopiladi."""
    uid, hafta = int(uid), hpdars._hafta()
    if hafta < PLEYOFF_DAN or _ep() >= _turnir_vaqti(hafta) - YOPILISH:
        return False
    conn = hpcup._connect()
    try:
        if on:
            conn.execute("INSERT OR IGNORE INTO duel_qatnash (hafta, user_id, vaqt) VALUES (?,?,?)", (hafta, uid, hpcup._utc_iso(hpcup.now_tk())))
        else:
            conn.execute("DELETE FROM duel_qatnash WHERE hafta=? AND user_id=?", (hafta, uid))
        conn.commit()
        return True
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
        # REYTING jadvali: kamida bitta duel o'ynaganlar
        rows = conn.execute(
            "SELECT r.user_id, r.reyting, r.oyin, r.galaba, COALESCE(u.first_name, 'Sehrgar') AS name, u.house "
            "FROM duel_reyting r JOIN users u ON u.user_id = r.user_id WHERE u.house IS NOT NULL AND r.user_id > 0 AND r.oyin > 0 "
            "ORDER BY r.reyting DESC, r.oyin DESC").fetchall()
        rm = _reyting(conn, uid)
        orin = next((i + 1 for i, r in enumerate(rows) if r["user_id"] == uid), None)
        ts = _turnir_vaqti(hafta) if hafta >= PLEYOFF_DAN else _turnir_vaqti(PLEYOFF_DAN)
        qat = _qatnashchilar(conn, hafta) if hafta >= PLEYOFF_DAN else []
        return {
            "ok": True, "week": hafta, "mine": {"1": men.get(1, 0), "2": men.get(2, 0), "3": men.get(3, 0), "total": sum(men.values())},
            "rating": {"r": int(round(rm[0])), "games": rm[1], "wins": rm[2], "place": orin, "n": len(rows)},
            "n": len(rows), "place": orin,
            "top": [{"uid": r["user_id"], "name": hpdars._ism(r["name"]), "house": r["house"], "score": int(round(r["reyting"])),
                     "games": int(r["oyin"]), "me": r["user_id"] == uid} for r in rows[:TOP]],
            "rules": {"lives": JON, "fail": KAM, "top": TOP, "round": RAUND_T, "bonus": USTUN, "match": MATCH_T, "gap": ORALIQ, "wait": KUTISH,
                      "points": {str(k): v for k, v in BOSQICH_BALL.items()}, "bots": {str(k): v for k, v in BOT_R.items()}},
            # Turnir: qachon, yozilish ochiqmi, o'zi yozilganmi, nechta odam yozilgan (reyting bo'yicha birinchi 30 tasi)
            "tour": {"ts": ts, "now": _ep(), "open": hafta >= PLEYOFF_DAN and _ep() < ts - YOPILISH, "joined": any(r["user_id"] == uid for r in qat),
                     "n": len(qat), "close": YOPILISH,
                     "players": [{"uid": r["user_id"], "name": hpdars._ism(r["name"]), "house": r["house"], "r": int(round(r["reyting"])),
                                  "me": r["user_id"] == uid} for r in qat[:30]]},
            "cup": _kubok(conn, uid, hafta), "admin": uid in set(_cfg.get("admin_ids") or ()), "now": _ep(),
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
        tarix = _tarix_ol(g)
        tarix.append({"a": [tur, acc], "b": [utur, uacc], "w": w})
        conn.execute("UPDATE duel_oyin SET jon=?, rjon=?, raund=?, acc_sum=?, turlar=?, holat=?, tarix=? WHERE id=?",
                     (jon, rjon, raund, acc_sum, g["turlar"] + tur[2], ("yutdi" if yutdi else "yutqazdi") if tugadi else "ketmoqda",
                      json.dumps(tarix), g["id"]))
        farq = _elo_bot(conn, uid, daraja, yutdi) if tugadi else 0
        conn.commit()
        return {"round": {"mine": tur, "his": utur, "acc": acc, "racc": uacc, "win": w},
                "game": {"id": g["id"], "level": daraja, "lives": jon, "rlives": rjon, "round": raund,
                         "over": tugadi, "won": bool(yutdi), "score": natija, "delta": farq}}
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
    if body.get("join") is not None:
        qosh["join_ok"] = await asyncio.to_thread(_yozil, uid, bool(body.get("join")))
        if _cfg.get("log"):
            try:
                await _cfg["log"](user, "duel_turnir_" + ("yozildi" if body.get("join") else "chiqdi"))
            except Exception:
                pass
    elif body.get("history"):
        qosh["history"] = await asyncio.to_thread(_tarixim, uid)
    elif isinstance(body.get("replay"), dict):
        try:
            rp = await asyncio.to_thread(_qayta, uid, "o" if body["replay"].get("k") == "o" else "m", int(body["replay"].get("id")))
        except (TypeError, ValueError):
            rp = None
        if rp is None:
            return cors(web.json_response({"ok": False, "error": "no_duel"}))
        qosh["replay"] = rp
    elif body.get("sinov") and uid in set(_cfg.get("admin_ids") or ()):
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
