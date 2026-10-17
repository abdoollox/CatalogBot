"""Supurgi poygasi (egasi, 2026-10-12) - to'rtinchi haftalik turnir: DUSHANBA 22:00 (Toshkent).

BITTA UZLUKSIZ POYGA (egasi 2026-10-12 da bosqichli variantni rad etdi): hamma bir vaqtda BIR XIL yo'lda uchadi
(Uchish darsi o'yini, «aniqlik = tezlik» qoidasi). Har HALQA (10) ta halqada NAZORAT chizig'i: unga ENG OXIRIDA yetgan
uchuvchi poygani tark etadi. Shu tartibda davom etadi - oxirida bitta uchuvchi qoladi, u g'olib.
Halqalar soniga chegara yo'q: yo'l uzunligi = (ishtirokchilar - 1) * HALQA.
  - nazorat k (0 dan) = (k + 1) * HALQA - halqa. Tiriklarning bittasidan boshqa hammasi undan o'tgach MUHLAT_T soniya kutiladi
    (tarmoq kechikishi), so'ng eng sekini (yoki o'tmagani) chiqadi;
  - birinchi uchuvchi nazoratdan o'tgach NAZORAT_T soniya ichida yetib kelmaganlarning HAMMASI chiqadi (aloqasi uzilganlar);
  - hech kim QISM_T soniyada nazoratga yetmasa poyga yopiladi.
Ishtirokchi - poyga boshlanishidan ZAL soniya oldindan boshlanishigacha sahifada bo'lgan har bir saralangan o'quvchi
(oldindan yozilish shart emas; «Qatnashaman» - eslatma olish uchun). Kechikkan - tomoshabin.
BALL (kubokka): 1-o'rin +30, 2-o'rin +20, 3-o'rin +10; 4-6-o'ringa +5. Faqat haqiqatan uchganlarga (kamida UCHDI halqa).

Yo'l urug'i hafta va maxfiy qiymatdan: ilovaga faqat poyga boshlanganda yuboriladi.
Vaqt: ilova nazoratdan o'tgan vaqtini o'zi o'lchaydi, server uni o'z soati bilan solishtiradi (ilova aytgani server o'lchaganidan
ko'pi bilan MUHLAT_MS ga kam bo'lishi mumkin), shuning uchun internet tezligi natijaga deyarli ta'sir qilmaydi.
JONLI O'RINLAR: ilova har soniyada nechta halqadan o'tganini aytadi ({pos}) - bu faqat ko'rsatish uchun, XOTIRADA turadi (_jonli);
chiqib ketish faqat nazorat yozuvlaridan (pg_natija) hal qilinadi.

So'rovlar - POST /api/poyga: {} holat (to'liq), {join: 1|0} yozilish, {pos: n, cps: {k: ms}} uchish paytida (yengil javob).

DO'ST BILAN POYGA (o'quvchi taklifi, 2026-10-17; Toshchalar/Maxluqlar jangi qolipida): {dost: 1} ochiq taklif (DOST_MUDDAT),
{dqabul: id} - birinchi qabul qilgan raqib bo'ladi, {dbekor: id}; {doyin: id} holat, {doyin, dpos} uchish paytida joy, {doyin, dfin: ms} marra,
{doyin, dtashla: 1} - taslim. Ikkalasi DOST_SANOQ soniyadan keyin BIR XIL yo'ldan (DOST_HALQA halqa) uchadi; marraga tezroq yetgan yutadi.
Ball yo'q. Chatdagi karta (hpcup, ustun `poyga`) holati jonli yangilanadi (_ozgargan -> _dost_xabar).

SINOV POYGASI (faqat admin; {sinov: 1} boshlaydi, {sinov: 0} to'xtatadi): haqiqiy poyganing o'zi, lekin raqiblar - SINOV_BOT ta kompyuter
uchuvchi (manfiy id), start SINOV_KUT soniyadan keyin, ball berilmaydi, haqiqiy poygaga ta'sir qilmaydi. Hafta kaliti "sinov:<uid>:<vaqt>".
Sinov holati xotirada (_sinov) - bot qayta ishga tushsa sinov yo'qoladi.
"""

import asyncio
import hashlib
import logging
import os
import random
from datetime import datetime, timedelta

from aiohttp import web

import hpcup
import hpdars
import hpgolib

BOSH_HAFTA = "2026-10-12"     # birinchi poyga shu haftada (dushanba 12-oktabr; egasi 19-oktabrdan shu kunga ko'chirdi)
TURNIR_KUN = 0                # dushanba
SOAT = 22
ZAL = 120                     # boshlanishidan shuncha soniya oldin «zal» ochiladi (kelganlar sanaladi)
SANOQ = 6                     # poyga ochilgach uchishgacha sanoq
HALQA = 10                    # har shuncha halqada bitta uchuvchi chiqadi
MUHLAT_T = 1.5                # oxiridan oldingi uchuvchi nazoratdan o'tgach shuncha kutiladi
NAZORAT_T = 20                # birinchi uchuvchi nazoratdan o'tgach qolganlarga shuncha soniya
QISM_T = 75                   # hech kim shuncha vaqtda nazoratga yetmasa poyga yopiladi
HALQA_MS = 350                # bir halqaga bundan kam vaqt ketmaydi (soxta natijadan himoya)
MUHLAT_MS = 2500              # ilova o'lchagan vaqt server o'lchaganidan shunchagacha kam bo'lishi mumkin
UCHDI = 3                     # shuncha halqadan o'tgan - «haqiqatan uchgan» (ball olish sharti)
BALL_ORIN = {1: 30, 2: 20, 3: 10}
BALL_KEYIN = 5                # 4-o'rindan BALL_KEYIN_ORIN-o'ringacha
BALL_KEYIN_ORIN = 6
TUGASH = 3 * 3600             # boshlanganidan shuncha o'tgach keyingi haftaga yozilish ochiladi

SINOV_KUT = 20                # sinov poygasi shuncha soniyadan keyin boshlanadi
SINOV_UMR = 900               # sinov shuncha vaqtdan keyin o'zi unutiladi
SINOV_BOT = 9                 # kompyuter uchuvchilar soni
# (ism, fakultet, bir halqaga ketadigan o'rtacha vaqt soniyada) - tezdan sekinga
SINOV_BOTLAR = (("Viktor", "slytherin", 0.80), ("Jinni", "gryffindor", 0.86), ("Sedrik", "hufflepuff", 0.92), ("Chjou", "ravenclaw", 0.98),
                ("Oliver", "gryffindor", 1.05), ("Draco", "slytherin", 1.13), ("Luna", "ravenclaw", 1.22), ("Ron", "gryffindor", 1.33),
                ("Nevill", "gryffindor", 1.50))
DOST_HALQA = 30               # do'st bilan poyga yo'li (mashq bilan bir xil)
DOST_MUDDAT = 1800            # taklif shuncha soniya ochiq turadi
DOST_SANOQ = 8                # qabul qilingach start shuncha soniyadan keyin
DOST_KUT = 40                 # birinchisi marraga yetgach ikkinchisiga shuncha soniya
DOST_KELMADI = 30             # start bo'lib shuncha vaqt o'tsa ham uchmagan - kelmadi
DOST_MAX = 200                # poyga eng ko'pi shuncha davom etadi (keyin o'tgan halqalar bo'yicha)
BOT_UID0 = -9100              # kompyuter uchuvchilar: BOT_UID0 - i

_cfg = {}
_qulf = None
_sinov = {}                   # uid -> {"hafta": kalit, "t0": start vaqti}
_jonli = {}                   # hafta -> {uid: o'tilgan halqalar} (faqat ko'rsatish uchun)
_kesh = {}                    # hafta -> poyga holatining xotiradagi nusxasi (yengil javoblar uchun)
_ozgargan = set()             # holati o'zgargan do'stona poygalar - chatdagi taklif kartasi yangilanadi (_dost_xabar)


def _now():
    return hpcup.now_tk()


def _ep():
    return _now().timestamp()


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS pg_turnir (hafta TEXT PRIMARY KEY, holat TEXT NOT NULL DEFAULT 'ketmoqda', bosqich INTEGER NOT NULL DEFAULT 0,"
                     " bosh REAL NOT NULL, jami INTEGER NOT NULL DEFAULT 1, soni INTEGER NOT NULL DEFAULT 0, golib INTEGER, tugadi REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS pg_qatnash (hafta TEXT NOT NULL, user_id INTEGER NOT NULL, vaqt TEXT NOT NULL, PRIMARY KEY (hafta, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS pg_oyinchi (hafta TEXT NOT NULL, user_id INTEGER NOT NULL, keldi REAL, tirik INTEGER NOT NULL DEFAULT 1,"
                     " chiqdi INTEGER, orin INTEGER, PRIMARY KEY (hafta, user_id))")
        # bosqich = nazorat raqami (0 dan); -1 = «uchdi» belgisi. ms - startdan shu nazoratgacha vaqt.
        conn.execute("CREATE TABLE IF NOT EXISTS pg_natija (hafta TEXT NOT NULL, user_id INTEGER NOT NULL, bosqich INTEGER NOT NULL, ms INTEGER NOT NULL,"
                     " xato INTEGER NOT NULL DEFAULT 0, vaqt REAL NOT NULL, PRIMARY KEY (hafta, user_id, bosqich))")
        conn.execute("CREATE TABLE IF NOT EXISTS pg_eslatma (hafta TEXT NOT NULL, tur TEXT NOT NULL, PRIMARY KEY (hafta, tur))")
        conn.execute(hpcup.PG_DOST_DDL)
        conn.commit()
    finally:
        conn.close()


def _sinov_hafta(hafta):
    return str(hafta).startswith("sinov:")


def _turnir_vaqti(hafta):
    if _sinov_hafta(hafta):
        for v in list(_sinov.values()):
            if v["hafta"] == hafta:
                return v["t0"]
        return 0.0
    y, m, d = (int(x) for x in hafta.split("-"))
    return (datetime(y, m, d, SOAT, 0, 0, tzinfo=_now().tzinfo) + timedelta(days=TURNIR_KUN)).timestamp()


def _hafta():
    """Navbatdagi (yoki hozir ketayotgan) poyga haftasi (dushanba sanasi)."""
    h = max(hpdars._hafta(), BOSH_HAFTA)
    if _ep() >= _turnir_vaqti(h) + TUGASH:
        y, m, d = (int(x) for x in h.split("-"))
        h = (datetime(y, m, d) + timedelta(days=7)).strftime("%Y-%m-%d")
    return h


def _hafta_uchun(uid):
    """Shu odam hozir qaysi poygada: faol sinovi bo'lsa - o'sha, aks holda navbatdagi haqiqiy poyga."""
    v = _sinov.get(int(uid))
    if v and _ep() < v["t0"] + SINOV_UMR:
        return v["hafta"]
    if v:
        _sinov.pop(int(uid), None)
    return _hafta()


def _urug(hafta):
    """Poyga yo'lining urug'i - oldindan bilib bo'lmaydi."""
    sir = hashlib.sha256(("poyga|%s|%s" % (os.getenv("BOT_TOKEN", ""), hafta)).encode()).hexdigest()
    return int(sir[:8], 16) % 900000 + 1000


# ---------- sinov poygasi ----------

def _sinov_bosh(uid):
    """Admin uchun sinov poygasi: o'zi + kompyuter uchuvchilar, SINOV_KUT soniyadan keyin."""
    uid, now = int(uid), _ep()
    eski = _sinov.get(uid)
    hafta = "sinov:%d:%d" % (uid, int(now))
    conn = hpcup._connect()
    try:
        for j in ("pg_turnir", "pg_oyinchi", "pg_natija"):
            conn.execute("DELETE FROM %s WHERE hafta LIKE ?" % j, ("sinov:%d:%%" % uid,))
        conn.execute("INSERT INTO pg_oyinchi (hafta, user_id, keldi) VALUES (?,?,?)", (hafta, uid, now))
        for i in range(min(SINOV_BOT, len(SINOV_BOTLAR))):
            conn.execute("INSERT INTO pg_oyinchi (hafta, user_id, keldi) VALUES (?,?,?)", (hafta, BOT_UID0 - i, now))
            conn.execute("INSERT INTO pg_natija (hafta, user_id, bosqich, ms, vaqt) VALUES (?,?,-1,0,?)", (hafta, BOT_UID0 - i, now))
        conn.commit()
    finally:
        conn.close()
    if eski:
        _jonli.pop(eski["hafta"], None)
        _kesh.pop(eski["hafta"], None)
    _sinov[uid] = {"hafta": hafta, "t0": now + SINOV_KUT}
    return True


def _sinov_toxtat(uid):
    v = _sinov.pop(int(uid), None)
    if not v:
        return False
    _jonli.pop(v["hafta"], None)
    _kesh.pop(v["hafta"], None)
    conn = hpcup._connect()
    try:
        for j in ("pg_turnir", "pg_oyinchi", "pg_natija"):
            conn.execute("DELETE FROM %s WHERE hafta=?" % j, (v["hafta"],))
        conn.commit()
    finally:
        conn.close()
    return True


def _bot_qism(hafta, u, j):
    """Kompyuter uchuvchining j-qismga (HALQA ta halqa) ketadigan vaqti, soniyada: o'rtachasi atrofida, doimiy tasodif bilan."""
    i = BOT_UID0 - u
    tasodif = int(hashlib.sha256(("%s|%s|%s" % (hafta, j, u)).encode()).hexdigest()[:6], 16) / float(0xFFFFFF)
    return SINOV_BOTLAR[i][2] * HALQA * (1 + (tasodif - 0.5) * 0.2) + (1.6 * SINOV_BOTLAR[i][2] if j == 0 else 0)


def _bot_ms(hafta, u, k):
    """Kompyuter uchuvchi k-nazoratga startdan necha ms da yetadi."""
    return int(sum(_bot_qism(hafta, u, j) for j in range(k + 1)) * 1000)


def _bot_pos(hafta, u, otdi):
    """Kompyuter uchuvchi startdan `otdi` soniyada nechta halqadan o'tgan."""
    j, pos = 0, 0.0
    while j < 400:
        q = _bot_qism(hafta, u, j)
        if otdi < q:
            return round(pos + HALQA * max(0.0, otdi) / q, 1)
        otdi -= q
        pos += HALQA
        j += 1
    return float(pos)


def _sinov_botlar(conn, hafta, now):
    """Kompyuter uchuvchilar o'z vaqtida nazoratdan «o'tadi»."""
    t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()
    if not t or t["holat"] != "ketmoqda":
        return
    start = t["bosh"] + SANOQ
    for r in conn.execute("SELECT user_id FROM pg_oyinchi WHERE hafta=? AND tirik=1 AND user_id < 0", (hafta,)).fetchall():
        u = r["user_id"]
        if not 0 <= BOT_UID0 - u < len(SINOV_BOTLAR):
            continue
        for k in range(t["bosqich"], t["bosqich"] + 3):
            ms = _bot_ms(hafta, u, k)
            if now >= start + ms / 1000.0:
                conn.execute("INSERT OR IGNORE INTO pg_natija (hafta, user_id, bosqich, ms, xato, vaqt) VALUES (?,?,?,?,0,?)",
                             (hafta, u, k, ms, start + ms / 1000.0))


# ---------- poyga ----------

def _tiriklar(conn, hafta):
    return [r["user_id"] for r in conn.execute("SELECT user_id FROM pg_oyinchi WHERE hafta=? AND tirik=1", (hafta,))]


def _otganlar(conn, hafta, k):
    return {r["user_id"]: (r["ms"], r["vaqt"]) for r in conn.execute("SELECT user_id, ms, vaqt FROM pg_natija WHERE hafta=? AND bosqich=?", (hafta, k))}


def _tugat(conn, hafta, berish, now):
    """Poyga yakuni: qolganlarga o'rin (odatda bitta - g'olib), ballar."""
    tirik = _tiriklar(conn, hafta)
    oxirgi = {}
    for r in conn.execute("SELECT user_id, MAX(bosqich) AS k FROM pg_natija WHERE hafta=? AND bosqich >= 0 GROUP BY user_id", (hafta,)).fetchall():
        ms = conn.execute("SELECT ms FROM pg_natija WHERE hafta=? AND user_id=? AND bosqich=?", (hafta, r["user_id"], r["k"])).fetchone()[0]
        oxirgi[r["user_id"]] = (r["k"], ms)
    tirik.sort(key=lambda u: (-oxirgi.get(u, (-1, 0))[0], oxirgi.get(u, (-1, 0))[1], u))
    for i, u in enumerate(tirik):
        conn.execute("UPDATE pg_oyinchi SET orin=? WHERE hafta=? AND user_id=?", (i + 1, hafta, u))
    uchgan = {r["user_id"] for r in conn.execute("SELECT DISTINCT user_id FROM pg_natija WHERE hafta=?", (hafta,))}
    golib = tirik[0] if tirik and tirik[0] in uchgan else None
    if not _sinov_hafta(hafta):
        for r in conn.execute("SELECT user_id, orin FROM pg_oyinchi WHERE hafta=? AND orin IS NOT NULL", (hafta,)).fetchall():
            if r["user_id"] in uchgan and _ball(r["orin"]):          # ball faqat haqiqatan uchganlarga
                berish.append((r["user_id"], "poyga:%s" % hafta, _ball(r["orin"])))
    conn.execute("UPDATE pg_turnir SET holat='tugadi', golib=?, tugadi=? WHERE hafta=?", (golib, now, hafta))


def _yur(conn, hafta, berish, now):
    """Poygani hozirgi vaqtga keltiradi: yopilgan nazoratlarda oxirgilarni chiqaradi."""
    T0 = _turnir_vaqti(hafta)
    if not T0 or now < T0:
        return
    t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()
    if not t:
        soni = conn.execute("SELECT COUNT(*) FROM pg_oyinchi WHERE hafta=?", (hafta,)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO pg_turnir (hafta, bosh, jami, soni) VALUES (?,?,?,?)", (hafta, T0, max(1, soni - 1), soni))
        if soni < 2:                             # bir kishi bilan poyga bo'lmaydi
            conn.execute("UPDATE pg_turnir SET holat='tugadi', tugadi=? WHERE hafta=?", (now, hafta))
            conn.execute("UPDATE pg_oyinchi SET tirik=0 WHERE hafta=?", (hafta,))
        t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()
    while t["holat"] == "ketmoqda":
        k, start = t["bosqich"], t["bosh"] + SANOQ
        if now < start:
            break
        tirik = _tiriklar(conn, hafta)
        if len(tirik) <= 1:
            _tugat(conn, hafta, berish, now)
            break
        otgan = {u: v for u, v in _otganlar(conn, hafta, k).items() if u in tirik}
        qism_boshi = max(start, t["tugadi"] or 0)            # `tugadi` poyga paytida - oldingi nazorat yopilgan payt
        chiqadi = None
        if otgan and len(otgan) >= len(tirik) - 1 and now >= max(v[1] for v in otgan.values()) + MUHLAT_T:
            if len(otgan) == len(tirik):
                chiqadi = [max(otgan, key=lambda u: (otgan[u][0], u))]
            else:
                chiqadi = [u for u in tirik if u not in otgan]
        elif otgan and now >= min(v[1] for v in otgan.values()) + NAZORAT_T:
            chiqadi = [u for u in tirik if u not in otgan]
        elif not otgan and now >= qism_boshi + QISM_T:      # hech kim uchmayapti - poyga yopiladi
            _tugat(conn, hafta, berish, now)
            break
        if not chiqadi:
            break
        oldingi = _otganlar(conn, hafta, k - 1) if k > 0 else {}
        chiqadi.sort(key=lambda u: (u not in oldingi, oldingi.get(u, (0, 0))[0], u))     # yaxshirog'i yuqoriroq o'rin oladi
        for i, u in enumerate(chiqadi):
            conn.execute("UPDATE pg_oyinchi SET tirik=0, chiqdi=?, orin=? WHERE hafta=? AND user_id=?",
                         (k, len(tirik) - len(chiqadi) + 1 + i, hafta, u))
        if len(tirik) - len(chiqadi) <= 1:
            _tugat(conn, hafta, berish, now)
            break
        conn.execute("UPDATE pg_turnir SET bosqich=?, tugadi=? WHERE hafta=?", (k + 1, now, hafta))
        t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()


def _ism(conn, uid):
    if uid < 0 and 0 <= BOT_UID0 - uid < len(SINOV_BOTLAR):      # sinov poygasining kompyuter uchuvchisi
        b = SINOV_BOTLAR[BOT_UID0 - uid]
        return {"uid": None, "name": b[0], "house": b[1]}
    r = conn.execute("SELECT COALESCE(first_name, 'Sehrgar') AS name, house FROM users WHERE user_id=?", (uid,)).fetchone()
    return {"uid": uid, "name": hpdars._ism(r["name"]) if r else "Sehrgar", "house": r["house"] if r else None}


def _kesh_yangila(conn, hafta):
    """Poyga holatini xotiraga oladi - uchayotganlarga yengil javob berish uchun."""
    t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()
    if not t:
        _kesh.pop(hafta, None)
        return None
    ismlar = (_kesh.get(hafta) or {}).get("ism") or {}
    k = {"holat": t["holat"], "k": t["bosqich"], "soni": t["soni"], "bosh": t["bosh"], "golib": t["golib"], "tirik": [], "orin": {}, "nazorat": {}, "ism": ismlar}
    for r in conn.execute("SELECT user_id, tirik, chiqdi, orin FROM pg_oyinchi WHERE hafta=?", (hafta,)).fetchall():
        u = r["user_id"]
        if u not in ismlar:
            ismlar[u] = _ism(conn, u)
        if r["tirik"]:
            k["tirik"].append(u)
        if r["orin"]:
            k["orin"][u] = (r["orin"], r["chiqdi"])
    for r in conn.execute("SELECT user_id, MAX(bosqich) AS m FROM pg_natija WHERE hafta=? GROUP BY user_id", (hafta,)):
        k["nazorat"][r["user_id"]] = r["m"] + 1
    _kesh[hafta] = k
    return k


def _taxta(hafta, uid, now):
    """Jonli jadval: tiriklar oldinda ketayotganidan boshlab, keyin chiqqanlar (kech chiqqani yuqorida)."""
    k = _kesh.get(hafta)
    if not k:
        return []
    jon, otdi = _jonli.get(hafta) or {}, now - (k["bosh"] + SANOQ)
    tirik, chiq = [], []
    for u in k["ism"]:
        d = dict(k["ism"][u])
        orin = k["orin"].get(u)
        if u in k["tirik"]:
            pos = max(jon.get(u, 0), k["nazorat"].get(u, 0) * HALQA)
            if u < 0 and k["holat"] == "ketmoqda":
                pos = max(pos, _bot_pos(hafta, u, otdi))
            d.update(pos=pos, me=u == uid, place=orin[0] if orin else None)
            tirik.append(d)
        elif orin:
            d.update(pos=((orin[1] if orin[1] is not None else -1) + 1) * HALQA, me=u == uid, place=orin[0], out=True)
            chiq.append(d)
    tirik.sort(key=lambda d: (d["place"] or 0, -d["pos"]))
    chiq.sort(key=lambda d: d["place"])
    return tirik[:60] + chiq[:40]


def _eslatmalar(conn, hafta, xabarlar):
    hozir = _now()
    T0 = _turnir_vaqti(hafta)
    # FAQAT poyga kunining o'zida (2026-10-12 xatosi: faqat hafta kuni tekshirilardi - birinchi poyga keyingi haftada bo'lsa ham
    # «bugun poyga» e'loni bir hafta oldin, shu dushanbada hammaga ketib qolgan)
    if hozir.timestamp() >= T0 or datetime.fromtimestamp(T0, hozir.tzinfo).date() != hozir.date():
        return
    daq = hozir.hour * 60 + hozir.minute
    tur = "on" if SOAT * 60 - 10 <= daq < SOAT * 60 else "ertalab" if 600 <= daq < SOAT * 60 - 10 else None
    if not tur:
        return
    if conn.execute("INSERT OR IGNORE INTO pg_eslatma (hafta, tur) VALUES (?,?)", (hafta, tur)).rowcount < 1:
        return
    if tur == "ertalab" and hafta == BOSH_HAFTA:
        xabarlar.append((0, "elon"))             # birinchi poyga: hamma saralanganlarga e'lon
        return
    for r in conn.execute("SELECT user_id FROM pg_qatnash WHERE hafta=?", (hafta,)).fetchall():
        xabarlar.append((r["user_id"], tur))


def _tick():
    berish, xabarlar = [], []
    hafta, now = _hafta(), _ep()
    conn = hpcup._connect()
    try:
        _yur(conn, hafta, berish, now)
        _eslatmalar(conn, hafta, xabarlar)
        _dost_tick(conn, now)
        if now >= _turnir_vaqti(hafta):
            _kesh_yangila(conn, hafta)
        for uid, v in list(_sinov.items()):      # sinov poygalari: kompyuter uchuvchilar va nazoratlar
            if now >= v["t0"] + SINOV_UMR:
                _sinov.pop(uid, None)
                _jonli.pop(v["hafta"], None)
                _kesh.pop(v["hafta"], None)
                continue
            _sinov_botlar(conn, v["hafta"], now)
            _yur(conn, v["hafta"], [], now)
            _kesh_yangila(conn, v["hafta"])
        conn.commit()
    finally:
        conn.close()
    for h in [h for h in list(_kesh) if h != hafta and not any(v["hafta"] == h for v in _sinov.values())]:
        _jonli.pop(h, None)
        _kesh.pop(h, None)
    return berish, xabarlar


def xat_matni(tur):
    if tur == "elon":
        return {"uz": ("Bugun 22:00 da birinchi supurgi poygasi!", "Hamma bir vaqtda bir xil yo'lda uchadi: halqalarning o'rtasidan o'tgan tezlashadi. Har 10 halqada eng oxirgi uchuvchi poygani tark etadi — oxirida qolgan g'olib. Soat 22:00 da ilovada Xogvarts → Poyga sahifasida bo'ling. G'olibga +30 ball. Hozirdan mashq qilsangiz bo'ladi."),
                "ru": ("Сегодня в 22:00 первая гонка на мётлах!", "Все летят одновременно по одной трассе: кто точнее проходит кольца — тот быстрее. Каждые 10 колец последний пилот выбывает — побеждает тот, кто останется. В 22:00 будьте в приложении: Хогвартс → Гонка. Победителю +30 очков. Потренироваться можно уже сейчас."),
                "en": ("The first broom race is today at 22:00!", "Everyone flies the same course at once: pass the hoops dead centre to go faster. Every 10 hoops the last flyer drops out — the last one left wins. Be in the app at 22:00: Hogwarts → Race. +30 points for the winner. You can practise right now.")}
    if tur == "ertalab":
        return {"uz": ("Bugun 22:00 da supurgi poygasi", "Poyga bugun soat 22:00 da. Ilovaga kiring: Xogvarts → Poyga. Kechikkanlar faqat tomosha qiladi. Hozircha mashq qilib oling."),
                "ru": ("Сегодня в 22:00 гонка на мётлах", "Гонка сегодня в 22:00. Зайдите: Хогвартс → Гонка. Опоздавшие только смотрят. А пока — потренируйтесь."),
                "en": ("The broom race is today at 22:00", "The race is today at 22:00. Come in: Hogwarts → Race. Latecomers can only watch. Meanwhile, practise.")}
    return {"uz": ("Poygaga 10 daqiqa qoldi!", "Supurgi poygasi 22:00 da boshlanadi. Hoziroq ilovaga kiring: Xogvarts → Poyga."),
            "ru": ("До гонки 10 минут!", "Гонка на мётлах начнётся в 22:00. Зайдите прямо сейчас: Хогвартс → Гонка."),
            "en": ("10 minutes to the race!", "The broom race starts at 22:00. Come in now: Hogwarts → Race.")}


async def _elon_yubor():
    try:
        n = await _cfg["elon"](xat_matni("elon"))
        logging.info("Poyga e'loni yuborildi: %s kishi", n)
    except Exception as e:
        logging.error("Poyga e'loni yuborilmadi: %s", e)


async def tick():
    async with _qulf:
        berish, xabarlar = await asyncio.to_thread(_tick)
    await _dost_xabar()
    for uid, ref, pts in berish:
        if pts > 0 and uid and uid > 0:
            await asyncio.to_thread(hpcup._award, uid, "dars", ref, pts)
    for uid, tur in xabarlar:
        if tur == "elon":
            if _cfg.get("elon"):
                asyncio.create_task(_elon_yubor())
            continue
        if uid and uid > 0 and _cfg.get("xat"):
            try:
                await _cfg["xat"](uid, xat_matni(tur))
            except Exception as e:
                logging.error("Poyga xati yuborilmadi (%s): %s", uid, e)
    return len(berish), len(xabarlar)


def _ketmoqda():
    """Hozir biror poyga (haqiqiy yoki sinov) ketyaptimi - fon aylanasi tezligini belgilaydi."""
    if _sinov:
        return True
    try:
        h = _hafta()
        T0, now = _turnir_vaqti(h), _ep()
        if T0 - 5 <= now <= T0 + 30:
            return True
        return now > T0 and (_kesh.get(h) or {}).get("holat") == "ketmoqda"
    except Exception:
        return False


async def kuzatuvchi(interval=15):
    while True:
        try:
            await tick()
        except Exception as e:
            logging.error("Poyga kuzatuvchisi: %s", e)
        await asyncio.sleep(1 if _ketmoqda() else interval)


def _yozil(uid, on):
    uid, hafta = int(uid), _hafta()
    if _ep() >= _turnir_vaqti(hafta):
        return False
    conn = hpcup._connect()
    try:
        if on:
            conn.execute("INSERT OR IGNORE INTO pg_qatnash (hafta, user_id, vaqt) VALUES (?,?,?)", (hafta, uid, hpcup._utc_iso(_now())))
        else:
            conn.execute("DELETE FROM pg_qatnash WHERE hafta=? AND user_id=?", (hafta, uid))
        conn.commit()
        return True
    finally:
        conn.close()


def _nazorat_yoz(uid, hafta, cps, uchdi):
    """Nazoratdan o'tish yozuvlari: faqat tirik uchuvchi, vaqt server soati bilan tekshiriladi. Qaytaradi: qabul qilingan (yoki eskirgan) raqamlar."""
    uid, now, tasdiq = int(uid), _ep(), []
    conn = hpcup._connect()
    try:
        t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()
        if not t:
            return tasdiq
        o = conn.execute("SELECT tirik FROM pg_oyinchi WHERE hafta=? AND user_id=?", (hafta, uid)).fetchone()
        if not o:
            return tasdiq
        otdi = (now - (t["bosh"] + SANOQ)) * 1000          # server o'lchagan uchish vaqti
        if uchdi and o["tirik"] and t["holat"] == "ketmoqda":
            conn.execute("INSERT OR IGNORE INTO pg_natija (hafta, user_id, bosqich, ms, vaqt) VALUES (?,?,-1,0,?)", (hafta, uid, now))
        for kalit, ms in list((cps or {}).items())[:8]:
            try:
                k, aytgan = int(kalit), float(ms)
            except (TypeError, ValueError):
                continue
            if t["holat"] != "ketmoqda" or not o["tirik"] or k < t["bosqich"]:
                tasdiq.append(k)                 # eskirgan - ilova qayta yubormasin
                continue
            if k > t["bosqich"] + 5 or otdi < (k + 1) * HALQA * HALQA_MS:
                continue
            sof = min(otdi, max(aytgan, otdi - MUHLAT_MS))
            conn.execute("INSERT OR IGNORE INTO pg_natija (hafta, user_id, bosqich, ms, xato, vaqt) VALUES (?,?,?,?,0,?)", (hafta, uid, k, int(sof), now))
            tasdiq.append(k)
        conn.commit()
        return tasdiq
    finally:
        conn.close()


def _yozilganlar(conn, hafta, uid):
    """Turnir sahifasidagi «Yozilganlar» ro'yxati (barcha turnirlarda bir xil ko'rinish): oldin yozilgan - tepada."""
    rows = conn.execute(
        "SELECT q.user_id, COALESCE(u.first_name, 'Sehrgar') AS name, u.house FROM pg_qatnash q JOIN users u ON u.user_id = q.user_id "
        "WHERE q.hafta=? AND u.house IS NOT NULL AND q.user_id > 0 ORDER BY q.vaqt ASC", (hafta,)).fetchall()
    return [{"uid": r["user_id"], "name": hpdars._ism(r["name"]), "house": r["house"], "me": r["user_id"] == uid} for r in rows]


def _oxirgi(conn, hafta_dan_oldin):
    r = conn.execute("SELECT hafta, golib, soni FROM pg_turnir WHERE holat='tugadi' AND golib IS NOT NULL AND hafta < ? AND hafta NOT LIKE 'sinov:%' "
                     "ORDER BY hafta DESC LIMIT 1", (hafta_dan_oldin,)).fetchone()
    return dict(_ism(conn, r["golib"]), n=r["soni"]) if r else None


def _goliblar(conn, hafta, uid):
    """Eng oxirgi tugagan poyganing birinchi uchligi (ballari bilan) - keyingi poyga tugaguncha sahifada turadi."""
    r = conn.execute("SELECT hafta, soni FROM pg_turnir WHERE holat='tugadi' AND golib IS NOT NULL AND hafta <= ? AND hafta NOT LIKE 'sinov:%' "
                     "ORDER BY hafta DESC LIMIT 1", (hafta,)).fetchone()
    if not r:
        return None
    orinlar = [(x["user_id"], x["orin"]) for x in conn.execute("SELECT user_id, orin FROM pg_oyinchi WHERE hafta=? AND orin <= 3 ORDER BY orin", (r["hafta"],))]
    return hpgolib.karta(conn, orinlar, "poyga:%s" % r["hafta"], uid, r["soni"], _turnir_vaqti(r["hafta"]))


def _ball(orin):
    return BALL_ORIN.get(orin, BALL_KEYIN if orin and orin <= BALL_KEYIN_ORIN else 0)


def _holat(uid):
    uid, hafta, now = int(uid), _hafta_uchun(uid), _ep()
    T0 = _turnir_vaqti(hafta)
    conn = hpcup._connect()
    try:
        if T0 - ZAL <= now < T0:                 # zalda bo'lganlar ishtirokchi bo'ladi
            conn.execute("INSERT OR IGNORE INTO pg_oyinchi (hafta, user_id, keldi) VALUES (?,?,?)", (hafta, uid, now))
            conn.commit()
        t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()
        men = conn.execute("SELECT * FROM pg_oyinchi WHERE hafta=? AND user_id=?", (hafta, uid)).fetchone()
        yozilgan = conn.execute("SELECT COUNT(*) FROM pg_qatnash WHERE hafta=?", (hafta,)).fetchone()[0]
        javob = {
            "ok": True, "now": now,
            "tour": {"ts": T0, "now": now, "open": now < T0, "n": yozilgan,
                     "joined": conn.execute("SELECT 1 FROM pg_qatnash WHERE hafta=? AND user_id=?", (hafta, uid)).fetchone() is not None,
                     "players": _yozilganlar(conn, hafta, uid)},
            "rules": {"count": SANOQ, "every": HALQA, "hall": ZAL, "wait": NAZORAT_T, "next_pts": BALL_KEYIN, "next_to": BALL_KEYIN_ORIN,
                      "points": {str(k): v for k, v in BALL_ORIN.items()}},
            "last": _oxirgi(conn, hafta if not _sinov_hafta(hafta) else "9"),
            "champs": _goliblar(conn, hafta if not _sinov_hafta(hafta) else "9", uid),
            "test": _sinov_hafta(hafta), "can_test": uid in (_cfg.get("admin_ids") or ()),
            "me": {"in": bool(men), "alive": bool(men and men["tirik"]), "out": men["chiqdi"] if men else None, "place": men["orin"] if men else None},
        }
        if now < T0 - ZAL:
            javob["phase"] = "kutish"
            return javob
        jami = conn.execute("SELECT COUNT(*) FROM pg_oyinchi WHERE hafta=?", (hafta,)).fetchone()[0]
        javob["total"] = jami
        if now < T0 or not t:
            javob["phase"] = "zal"
            javob["starts_in"] = max(0, int(T0 - now))
            return javob
        k = _kesh_yangila(conn, hafta)
        javob["alive"] = len(k["tirik"])
        javob["board"] = _taxta(hafta, uid, now)
        if t["holat"] == "tugadi":
            javob["phase"] = "tugadi"
            javob["played"] = t["soni"] >= 2
            uchgan = conn.execute("SELECT 1 FROM pg_natija WHERE hafta=? AND user_id=? LIMIT 1", (hafta, uid)).fetchone()
            if men and men["orin"]:
                javob["me"]["points"] = _ball(men["orin"]) if uchgan and not _sinov_hafta(hafta) else 0
            return javob
        javob["phase"] = "poyga"
        javob["race"] = {"seed": _urug(hafta), "start_in": round(t["bosh"] + SANOQ - now, 2), "rings": max(1, t["soni"] - 1) * HALQA, "every": HALQA,
                         "cp": t["bosqich"], "pos": (_jonli.get(hafta) or {}).get(uid, 0)}
        return javob
    finally:
        conn.close()


def _yengil(uid, hafta, now, tasdiq):
    """Uchayotgan odamga qisqa javob - bazaga murojaatsiz (xotiradagi nusxadan)."""
    k = _kesh.get(hafta)
    if not k:
        return None
    men = k["orin"].get(uid)
    return {"ok": True, "light": True, "phase": "poyga" if k["holat"] == "ketmoqda" else "tugadi", "cp": k["k"], "every": HALQA,
            "alive": len(k["tirik"]), "me": {"in": True, "alive": uid in k["tirik"], "place": men[0] if men else None},
            "board": _taxta(hafta, uid, now), "ack": tasdiq or []}


# ---------- do'st bilan poyga (o'quvchi taklifi, 2026-10-17) ----------

def _dost(uid):
    """Do'stga taklif: a = chaqiruvchi, b bo'sh, `bosh` - taklif muddati. Oldingi ochiq taklifi bekor bo'ladi."""
    now = _ep()
    conn = hpcup._connect()
    try:
        for r in conn.execute("SELECT id FROM pg_dost WHERE holat='kutmoqda' AND a=?", (uid,)).fetchall():
            _ozgargan.add(r["id"])
        conn.execute("UPDATE pg_dost SET holat='tugadi', sabab='bekor' WHERE holat='kutmoqda' AND a=?", (uid,))
        cur = conn.execute("INSERT INTO pg_dost (a, bosh, holat, vaqt) VALUES (?,?,'kutmoqda',?)", (uid, now + DOST_MUDDAT, hpcup._utc_iso(_now())))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _dost_qabul(uid, mid):
    """Taklifni qabul qilish. (id | None, xato)."""
    now = _ep()
    conn = hpcup._connect()
    try:
        m = conn.execute("SELECT * FROM pg_dost WHERE id=?", (int(mid),)).fetchone()
        if not m:
            return None, "yoq"
        if uid in (m["a"], m["b"]):
            return m["id"], None
        if m["b"] is not None:
            return None, "band"
        if m["holat"] != "kutmoqda" or now >= (m["bosh"] or 0):
            return None, "muddat"
        cur = conn.execute("UPDATE pg_dost SET b=?, holat='ketmoqda', bosh=?, urug=? WHERE id=? AND b IS NULL AND holat='kutmoqda'",
                           (uid, now + DOST_SANOQ, random.randint(1000, 900999), m["id"]))
        conn.commit()
        if cur.rowcount:
            _ozgargan.add(m["id"])
        return (m["id"], None) if cur.rowcount else (None, "band")
    finally:
        conn.close()


def _dost_bekor(uid, mid):
    conn = hpcup._connect()
    try:
        n = conn.execute("UPDATE pg_dost SET holat='tugadi', sabab='bekor' WHERE id=? AND holat='kutmoqda' AND a=?", (int(mid), uid)).rowcount
        conn.commit()
        if n:
            _ozgargan.add(int(mid))
        return n > 0
    finally:
        conn.close()


def taklif_info(mid):
    """Telegram kartasi uchun: ochiq taklif bo'lsa {a, name}, aks holda None."""
    conn = hpcup._connect()
    try:
        m = conn.execute("SELECT * FROM pg_dost WHERE id=?", (int(mid),)).fetchone()
        if not m or m["b"] is not None or m["holat"] != "kutmoqda" or _ep() >= (m["bosh"] or 0):
            return None
        r = conn.execute("SELECT first_name FROM users WHERE user_id=?", (m["a"],)).fetchone()
        return {"a": m["a"], "name": (r["first_name"] if r else None) or "Sehrgar"}
    finally:
        conn.close()


def _dost_yakun(conn, m, golib, sabab):
    conn.execute("UPDATE pg_dost SET holat='tugadi', golib=?, sabab=? WHERE id=? AND holat='ketmoqda'", (golib, sabab, m["id"]))
    _ozgargan.add(m["id"])
    return conn.execute("SELECT * FROM pg_dost WHERE id=?", (m["id"],)).fetchone()


def _dost_yur(conn, m, now):
    """Natija vaqti kelgan bo'lsa poygani yakunlaydi: ikkalasi marraga yetdi - tezrog'i; bittasi yetib, ikkinchisiga DOST_KUT
    o'tdi - yetgani; hech kim uchmadi - kelmadi; DOST_MAX dan keyin - ko'proq halqa o'tgani."""
    if not m or m["holat"] != "ketmoqda":
        return m
    bosh, fa, fb = m["bosh"] or 0, m["a_ms"], m["b_ms"]
    if fa is not None and fb is not None:
        return _dost_yakun(conn, m, None if fa == fb else (m["a"] if fa < fb else m["b"]), "oyin")
    if fa is not None or fb is not None:
        bir = m["a_fin"] if fa is not None else m["b_fin"]
        if now >= (bir or now) + DOST_KUT or now >= bosh + DOST_MAX:
            return _dost_yakun(conn, m, m["a"] if fa is not None else m["b"], "oyin")
        return m
    pa, pb = m["a_pos"] or 0, m["b_pos"] or 0
    if now >= bosh + DOST_KELMADI and (pa <= 0 or pb <= 0):
        if pa <= 0 and pb <= 0:
            return _dost_yakun(conn, m, None, "ikkalasi")
        return _dost_yakun(conn, m, m["a"] if pa > 0 else m["b"], "kelmadi")
    if now >= bosh + DOST_MAX:
        return _dost_yakun(conn, m, None if pa == pb else (m["a"] if pa > pb else m["b"]), "vaqt")
    return m


def _dost_tick(conn, now):
    """Fon aylanasi: muddati o'tgan takliflar va natijasi kelgan poygalar (hech kim ilovani ochmasa ham chat kartasi yangilansin)."""
    for r in conn.execute("SELECT id FROM pg_dost WHERE holat='kutmoqda' AND bosh <= ?", (now,)).fetchall():
        _ozgargan.add(r["id"])
    conn.execute("UPDATE pg_dost SET holat='tugadi', sabab='muddat' WHERE holat='kutmoqda' AND bosh <= ?", (now,))
    for m in conn.execute("SELECT * FROM pg_dost WHERE holat='ketmoqda'").fetchall():
        _dost_yur(conn, m, now)


def _dost_holat(conn, m, uid, now):
    yon = "a" if m["a"] == uid else "b" if m["b"] == uid else None
    g = {"id": m["id"], "state": m["holat"], "me": yon, "friend": True, "rings": DOST_HALQA, "every": HALQA,
         "a": _ism(conn, m["a"]), "b": _ism(conn, m["b"]) if m["b"] else None,
         "pos": [round(m["a_pos"] or 0, 1), round(m["b_pos"] or 0, 1)], "ms": [m["a_ms"], m["b_ms"]],
         "winner": "a" if m["golib"] and m["golib"] == m["a"] else "b" if m["golib"] and m["golib"] == m["b"] else None, "why": m["sabab"]}
    if m["holat"] == "kutmoqda":
        g["expires_in"] = max(0, int((m["bosh"] or 0) - now))
    elif m["b"] is not None:
        g["seed"] = m["urug"]
        g["start_in"] = round((m["bosh"] or 0) - now, 2)
        g["wait"] = DOST_KUT
    return g


def _dost_oyin(uid, mid, pos=None, fin=None, tashla=False):
    """Do'stona poyga holati; uchayotgan o'yinchi joyini (pos), marra vaqtini (fin, ms) yoki taslimni aytadi."""
    now = _ep()
    conn = hpcup._connect()
    try:
        m = conn.execute("SELECT * FROM pg_dost WHERE id=?", (int(mid),)).fetchone()
        if not m:
            return {"ok": False, "error": "yoq"}
        yon = "a" if m["a"] == uid else "b" if m["b"] == uid else None
        if yon and m["holat"] == "ketmoqda" and m["b"] is not None:
            if tashla and m[yon + "_ms"] is None:
                m = _dost_yakun(conn, m, m["b"] if yon == "a" else m["a"], "tashladi")
            elif fin is not None and m[yon + "_ms"] is None:
                otdi = (now - (m["bosh"] or 0)) * 1000                # server o'lchagan uchish vaqti
                if otdi >= DOST_HALQA * HALQA_MS:
                    sof = int(min(otdi, max(float(fin), otdi - MUHLAT_MS)))
                    conn.execute("UPDATE pg_dost SET %s_ms=?, %s_fin=?, %s_pos=? WHERE id=?" % (yon, yon, yon), (sof, now, DOST_HALQA, m["id"]))
                    _ozgargan.add(m["id"])
            elif pos is not None and now >= (m["bosh"] or 0) - 1:
                conn.execute("UPDATE pg_dost SET %s_pos=MAX(%s_pos, ?) WHERE id=?" % (yon, yon), (max(0.0, min(float(pos), DOST_HALQA)), m["id"]))
            m = conn.execute("SELECT * FROM pg_dost WHERE id=?", (m["id"],)).fetchone()
        m = _dost_yur(conn, m, now)
        conn.commit()
        return {"ok": True, "dost": _dost_holat(conn, m, uid, now)}
    finally:
        conn.close()


async def _dost_xabar():
    """Holati o'zgargan do'stona poygalarning chatdagi kartalarini yangilaydi (hpbot bergan chaqiruv orqali)."""
    fn = _cfg.get("dost_ozgardi")
    while _ozgargan:
        mid = _ozgargan.pop()
        if fn:
            try:
                await fn(mid)
            except Exception as e:
                logging.error("poyga kartasi yangilanmadi (%s): %s", mid, e)


async def dost_yarat(uid):
    """Chatdan taklif (hpbot): yangi do'stona poyga, id."""
    mid = await asyncio.to_thread(_dost, int(uid))
    await _dost_xabar()
    return mid


async def _dost_api(uid, body):
    """Do'stona poyga so'rovlari - saralanmagan do'st ham qatnasha oladi (Telegram kartasi bilan kelgan yangi odam)."""
    try:
        if body.get("dqabul") is not None:
            mid, xato = await asyncio.to_thread(_dost_qabul, uid, int(body.get("dqabul")))
            if xato:
                return {"ok": False, "error": xato}
            javob = await asyncio.to_thread(_dost_oyin, uid, mid)
        elif body.get("dbekor") is not None:
            ok = await asyncio.to_thread(_dost_bekor, uid, int(body.get("dbekor")))
            javob = {"ok": True, "bekor_ok": ok}
        else:
            pos = body.get("dpos")
            fin = body.get("dfin")
            javob = await asyncio.to_thread(_dost_oyin, uid, int(body.get("doyin")), float(pos) if pos is not None else None,
                                            float(fin) if fin is not None else None, bool(body.get("dtashla")))
    except (TypeError, ValueError):
        return {"ok": False, "error": "bad"}
    await _dost_xabar()
    return javob


async def api_poyga(request):
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
    if body.get("dqabul") is not None or body.get("dbekor") is not None or body.get("doyin") is not None:
        return cors(web.json_response(await _dost_api(uid, body)))
    if body.get("pos") is not None:              # uchish paytidagi tez-tez so'rov: iloji boricha yengil
        hafta, now = _hafta_uchun(uid), _ep()
        k = _kesh.get(hafta)
        if k and uid in k["ism"]:
            try:
                pos = round(max(0.0, min(float(body.get("pos")), 100000.0)), 1)      # kasr bilan - raqiblar ekranda silliq ko'rinsin
            except (TypeError, ValueError):
                pos = 0.0
            jon = _jonli.setdefault(hafta, {})
            birinchi = pos >= UCHDI and jon.get(uid, 0) < UCHDI
            if uid in k["tirik"]:
                jon[uid] = max(pos, jon.get(uid, 0))
            cps = body.get("cps") if isinstance(body.get("cps"), dict) and body.get("cps") else None
            tasdiq = None
            if cps or birinchi:
                tasdiq = await asyncio.to_thread(_nazorat_yoz, uid, hafta, cps, birinchi)
                if cps:
                    try:
                        await tick()
                    except Exception as e:
                        logging.error("Poyga tick: %s", e)
            javob = _yengil(uid, hafta, now, tasdiq)
            if javob:
                return cors(web.json_response(javob))
    if not hpcup._get_house(uid):
        return cors(web.json_response({"ok": False, "error": "no_house"}))
    qosh = {}
    try:
        await tick()                             # avval holat hozirgi vaqtga keltiriladi
    except Exception as e:
        logging.error("Poyga tick: %s", e)
    if body.get("sinov") is not None and uid in (_cfg.get("admin_ids") or ()):
        if body.get("sinov"):
            qosh["sinov_ok"] = await asyncio.to_thread(_sinov_bosh, uid)
        else:
            qosh["sinov_ok"] = await asyncio.to_thread(_sinov_toxtat, uid)
    elif body.get("join") is not None:
        qosh["join_ok"] = await asyncio.to_thread(_yozil, uid, bool(body.get("join")))
    elif body.get("dost"):
        mid = await asyncio.to_thread(_dost, uid)
        await _dost_xabar()
        if _cfg.get("log"):
            try:
                await _cfg["log"](user, "poyga_dost_taklif")
            except Exception:
                pass
        return cors(web.json_response(await asyncio.to_thread(_dost_oyin, uid, mid)))
    javob = await asyncio.to_thread(_holat, uid)
    javob.update(qosh)
    if javob.get("phase") == "tugadi" and javob["me"].get("place") and _cfg.get("log") and body.get("log_end") and not javob.get("test"):
        try:
            await _cfg["log"](user, "poyga_%d" % javob["me"]["place"])
        except Exception:
            pass
    return cors(web.json_response(javob))


def register(app, cfg):
    """cfg: verify_init_data, cors, log, xat, elon, admin_ids. hpdars DAN KEYIN ulanadi."""
    global _qulf
    _cfg.update(cfg)
    _qulf = asyncio.Lock()
    _init()
    app.router.add_route("*", "/api/poyga", api_poyga)
    logging.info("Supurgi poygasi ulandi")
