# -*- coding: utf-8 -*-
"""Darslar (egasi, 2026-10-07): Xogvarts sahifasida kunlik savol o'rnida fanlar bo'limi.

Faqat SARALANGANLARGA. Ikki qism (egasi, 2026-10-07 kechqurun: mashq - ballsiz va cheklovsiz, ball - faqat bellashuvdan):

1) DARSLAR (mashq) - har fanda DARS_SONI ta dars (bosqich). Har odam o'z bosqichida: keyingi darsni o'tsa
     bosqichi +1. Kunlik chegara YO'Q, ball BERILMAYDI - xohlagancha o'tadi, o'tilganini qayta o'ynay oladi.
     Mavzu va qiyinlik dars raqamiga bog'liq (ilova hisoblaydi):
       afsun - 12 afsun x 2 aylana; iksir - 12 damlama x 2 aylana;
       tarix - Sehrgarlik tarixi: 46 dars; har darsda 6 yangi + 2 takror savol (277 ta savol havzasidan,
               avval filmlar tartibida), HAMMASIGA to'g'ri javob berilsa dars o'tadi (2026-10-08).

2) BELLASHUV (musobaqa) - kuniga bitta topshiriq HAMMAGA BIR XIL (sana bo'yicha), kim tezroq va xatosiz.
     Vaqtni SERVER o'lchaydi ({start} -> {finish}); har xato +3 soniya. Kuniga 3 urinish, eng yaxshisi hisob.
     tarix bellashuvi - 10 ta savol: javoblarni SERVER tekshiradi (to'g'ri javob ilovaga yuborilmaydi).
     Kun tugagach (keyingi kun birinchi so'rovda) eng yaxshilarga ball: 1-o'rin +15, 2-o'rin +10, 3-o'rin +7,
     4-10-o'rinlar +3. Ball kubokka 'dars' manbasi bo'lib yoziladi (ref "m:afsun:2026-10-08").

Kunlik savol ilovadan OLIB TASHLANDI (egasi, 2026-10-07): Shokolad qurbaqaning birinchi topshirig'i endi
tarix bellashuvida qatnashish (hpsandiq._daily_bajarildi). Server tomonda kunlik savol kodi turibdi (eski nusxalar uchun).
Kun - Toshkent vaqti. Qolgan fanlar ilovada "Tez orada" - qo'shilganda DARSLAR ga yoziladi.

API: POST /api/dars
  {}                                     -> holat (bosqichlar, bellashuv jadvali, kechagi g'oliblar)
  {done: "afsun", level: 7}              -> 7-dars o'tildi (faqat navbatdagi dars bosqichni oshiradi)
  {quiz: 7, lang: "uz"}                  -> tarix 7-darsining savollari (to'g'ri javobi bilan - mashq)
  {start: "afsun"}                       -> bellashuv urinishi boshlandi (tarixda - savollar qaytadi)
  {finish: "afsun", xato: 2}             -> bellashuv urinishi tugadi
  {finish: "tarix", answers: [1,0,3,2,1]} -> tarix: javoblar, xatoni server sanaydi
"""

import asyncio
import datetime as _dt
import json
import logging
import os
import random
import sqlite3
import time
from datetime import timedelta

from aiohttp import web

import hpcup
import hpsandiq

_cfg = {}
_kesh = {}                     # uid -> (vaqt, oxirgi holat javobi)
KESH_S = 5

DARS_SONI = 24                 # fanda nechta dars (bosqich); tarixda ko'proq - dars_soni() ga qarang
DARSLAR = {
    "tarix": {"items": ()},
    "afsun": {"items": ("lumos", "leviosa", "alohomora", "expelliarmus", "accio", "protego",
                        "incendio", "reparo", "stupefy", "aguamenti", "nox", "patronum",
                        "petrificus", "impedimenta", "riddikulus", "finite", "reducto", "diffindo",
                        "episkey", "silencio", "engorgio", "reducio", "colloportus", "obliviate")},
    "iksir": {"items": ("boils", "forget", "shrink", "antidote", "wiggenweld", "uyqu",
                        "skelegro", "living", "wit", "peace", "polyjuice", "felix")},
    # Qora kuchlardan himoya (2026-10-08): xavflar; bellashuvda shu kungi xavfdan to'lqinlar tartibi yasaladi (ilovada)
    "himoya": {"items": ("dementor", "boggart", "curse", "duelist", "dark", "troll",
                         "fire", "pixies", "inferi", "spider", "rock", "attacker")},
    # Uchish darsi (2026-10-08): bellashuv yo'nalishlari - nomdan urug' olinadi, halqalar tartibi ilovada yasaladi
    "uchish": {"items": ("y1", "y2", "y3", "y4", "y5", "y6", "y7", "y8", "y9", "y10", "y11", "y12")},
    # Sehrli maxluqlar parvarishi (2026-10-08): bellashuvda kartalar joylashuvi shu nomdan (urug') yasaladi
    "maxluq": {"items": ("m1", "m2", "m3", "m4", "m5", "m6", "m7", "m8", "m9", "m10", "m11", "m12")},
    # Astronomiya (2026-10-08): bellashuv savollari (burilgan turkumni tanish) shu nomdan (urug') yasaladi
    "astro": {"items": ("a1", "a2", "a3", "a4", "a5", "a6", "a7", "a8", "a9", "a10", "a11", "a12")},
    # O'simlikshunoslik (2026-10-08): bellashuvda ehtiyojlar tartibi shu nomdan (urug') yasaladi
    "osimlik": {"items": ("o1", "o2", "o3", "o4", "o5", "o6", "o7", "o8", "o9", "o10", "o11", "o12")},
    # Transfiguratsiya (2026-10-08): bellashuv savollari (afsun qoidasini topish) shu nomdan (urug') yasaladi
    "trans": {"items": ("t1", "t2", "t3", "t4", "t5", "t6", "t7", "t8", "t9", "t10", "t11", "t12")},
}
# Afsunlar (egasi, 2026-10-08): 24 afsun, 48 dars - 1-24 o'rganish, 25-36 vaziyat (afsunni o'zi topadi),
# 37-48 ketma-ket uch afsun (tartib ilovada: js/09-darslar.js afPlan). 2026-10-08 gacha 12 afsun edi:
# bellashuv mavzusi o'sha kunlar uchun eski ro'yxatdan (jadval o'zgarmasin).
AFSUN_DARS = 48
# Damlamalar (o'zbekcha nomi 2026-10-08 dan; kodda "iksir"): 12 damlama x 3 bosqich - oddiy, ko'proq masalliq,
# imtihon (retsept o'zi yopiladi). Tartib ilovada: js/09-darslar.js IK_BOSQ.
IKSIR_DARS = 36
HIMOYA_DARS = 36               # tartib ilovada: js/09-darslar.js hmPlan
UCHISH_DARS = 36               # js/09-darslar.js uchPlan
MAXLUQ_DARS = 36               # js/09-darslar.js mxPlan
ASTRO_DARS = 36                # js/09-darslar.js ylPlan
OSIMLIK_DARS = 36              # js/09-darslar.js osPlan
TRANS_DARS = 36                # js/09-darslar.js tfPlan
AFSUN_ESKI = 12
# Sehrgarlik tarixi darslari (egasi, 2026-10-08: bir kunda 4 kishi 24 darsni tugatdi - dars ko'proq, darsda savol
# ko'proq bo'lsin va HAMMA savolga to'g'ri javob bergan odamgina keyingi darsga o'tsin):
#   har darsda TARIX_DARS ta YANGI savol + TARIX_TAKROR ta oldingi darslardan takror (1-darsda takror yo'q);
#   darslar soni = havzadagi savollar // TARIX_DARS (277 savol -> 46 dars); o'tish - hammasi to'g'ri.
TARIX_DARS = 6
TARIX_TAKROR = 2
TARIX_ESKI_DARS = 4            # 2026-10-08 gacha darsda 4 savol edi (bosqichlarni ko'chirish uchun)
TARIX_BELL = 10                # tarix bellashuvida nechta savol (egasi, 2026-10-07: 5 ta kam, kamida 10)
TARIX_BELL_ESKI = 5            # 2026-10-07 gacha (o'sha kunning jadvali 5 savol bilan to'plangan)
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
        # Dars bahosi (1-5; ilova qo'yadi, eng yaxshisi saqlanadi) - «Qobiliyatlar» boshqalarga ham ko'rinishi uchun (2026-10-08)
        conn.execute("CREATE TABLE IF NOT EXISTS dars_baho ("
                     " user_id INTEGER NOT NULL, dars TEXT NOT NULL, daraja INTEGER NOT NULL, baho INTEGER NOT NULL,"
                     " PRIMARY KEY (user_id, dars, daraja))")
        conn.execute("CREATE TABLE IF NOT EXISTS dars_yakun ("
                     " kun TEXT NOT NULL, dars TEXT NOT NULL, vaqt TEXT NOT NULL, PRIMARY KEY (kun, dars))")
        conn.commit()
        # Bir martalik ko'chirish (2026-10-08): tarix darsi 4 savoldan 6 savolga o'tdi. Eski N-dars = N*4 savol
        # ko'rilgan, yangi hisobda bu N*4 // 6 dars (24-dars -> 16-dars): odam ko'rmagan savollari o'tilgan
        # bo'lib qolmasin. Belgi dars_yakun da ("migr", "tarix-6") - ikkinchi marta ishlamaydi.
        cur = conn.execute("INSERT OR IGNORE INTO dars_yakun (kun, dars, vaqt) VALUES ('migr', 'tarix-6', ?)",
                           (hpcup._utc_iso(hpcup.now_tk()),))
        if cur.rowcount > 0:
            conn.execute("UPDATE dars_daraja SET daraja = daraja * ? / ? WHERE dars = 'tarix'",
                         (TARIX_ESKI_DARS, TARIX_DARS))
        # Bir martalik ko'chirish (2026-10-08): afsunlarda 13-24-darslar eski 12 afsunning takrori edi, endi ular
        # YANGI afsunlar - o'rganilmagan afsun o'tilgan bo'lib qolmasin: 12 dan yuqori bosqich 12 ga tushadi.
        cur = conn.execute("INSERT OR IGNORE INTO dars_yakun (kun, dars, vaqt) VALUES ('migr', 'afsun-48', ?)",
                           (hpcup._utc_iso(hpcup.now_tk()),))
        if cur.rowcount > 0:
            conn.execute("UPDATE dars_daraja SET daraja = ? WHERE dars = 'afsun' AND daraja > ?", (AFSUN_ESKI, AFSUN_ESKI))
        conn.commit()
    finally:
        conn.close()


_savollar = None


def savollar():
    """Sehrgarlik tarixi savollari (questions/kino.json, 96 ta). Bir marta o'qiladi."""
    global _savollar
    if _savollar is None:
        try:
            with open(os.path.join(hpcup._questions_dir(), "kino.json"), encoding="utf-8") as f:
                _savollar = json.load(f)
        except Exception as e:
            logging.error("Tarix savollari o'qilmadi: %s", e)
            _savollar = []
    return _savollar


_bell_savollar = None


def bell_savollar():
    """Tarix BELLASHUVI uchun savollar havzasi: kino.json (96) + kunlik.json (120 - olib tashlangan kunlik savoldan)
    + tarix_savollar.json (kitoblar va sehrgarlar olami bo'yicha yangilari, 2026-10-08). Darslar faqat kino.json dan.
    Yangi savol qo'shish: tarix_savollar.json ga yozing (kalit takrorlanmasin) - kod o'zgarmaydi."""
    global _bell_savollar
    if _bell_savollar is None:
        hammasi = list(savollar())
        # tarix_savollar.json ATAYLAB questions/ papkasida EMAS: u papkani hpcup to'liq o'qiydi va faqat
        # "film"/"daily" turini taniydi - boshqa fayl kunlik savol yuklagichini buzadi (sinovlar ushlagan).
        for yol in (os.path.join(hpcup._questions_dir(), "kunlik.json"),
                    os.path.join(os.path.dirname(os.path.abspath(__file__)), "tarix_savollar.json")):
            fayl = os.path.basename(yol)
            try:
                with open(yol, encoding="utf-8") as f:
                    hammasi += [q for q in json.load(f) if q.get("uz") and isinstance(q.get("correct"), int)]
            except Exception as e:
                logging.error("Bellashuv savollari o'qilmadi (%s): %s", fayl, e)
        _bell_savollar = hammasi
    return _bell_savollar


def _savol(q, lang, javob):
    t = q.get(lang) or q["uz"]
    out = {"q": t["q"], "a": t["a"]}
    if javob:
        out["c"] = q["correct"]
    return out


def dars_soni(dars):
    """Fanda nechta dars bor."""
    if dars == "tarix":
        return max(1, len(bell_savollar()) // TARIX_DARS)
    if dars == "afsun":
        return AFSUN_DARS
    if dars == "iksir":
        return IKSIR_DARS
    if dars == "himoya":
        return HIMOYA_DARS
    if dars == "uchish":
        return UCHISH_DARS
    if dars == "maxluq":
        return MAXLUQ_DARS
    if dars == "astro":
        return ASTRO_DARS
    if dars == "osimlik":
        return OSIMLIK_DARS
    if dars == "trans":
        return TRANS_DARS
    return DARS_SONI


def tarix_dars(daraja, lang):
    """N-darsning savollari (1 dan), to'g'ri javobi bilan: 6 ta yangi + 2 ta oldingi darslardan takror, aralash.
    Tartib doimiy (dars raqamiga bog'liq) - qayta urinishda savollar o'sha, faqat o'rni o'zgarmaydi."""
    s = bell_savollar()
    n = int(daraja)
    bosh = (n - 1) * TARIX_DARS
    idx = list(range(bosh, min(bosh + TARIX_DARS, len(s))))
    if bosh > 0:
        idx += random.Random("takror|%d" % n).sample(range(bosh), min(TARIX_TAKROR, bosh))
    random.Random("aralash|%d" % n).shuffle(idx)
    return [_savol(s[i], lang, True) for i in idx]


def tarix_bell(kun):
    """Shu kungi bellashuv savollari (bell_savollar() dagi indekslar) - hammaga bir xil.
    2026-10-08 gacha havza faqat kino.json edi (o'sha kunlar jadvali o'zgarmasin)."""
    s = bell_savollar() if kun >= "2026-10-09" else savollar()
    return random.Random("tarix|" + kun).sample(range(len(s)), min(tarix_soni(kun), len(s)))


def tarix_soni(kun):
    """Shu kungi tarix bellashuvida nechta savol."""
    return TARIX_BELL if kun >= "2026-10-08" else TARIX_BELL_ESKI


def kun_mavzusi(dars, kun):
    """Bellashuvning shu kungi mavzusi (hammaga bir xil): ro'yxat bo'yicha aylanadi."""
    y, m, d = (int(x) for x in kun.split("-"))
    n = max(0, (_dt.date(y, m, d) - _dt.date(*BOSHI)).days)
    items = DARSLAR[dars]["items"]
    if not items:
        return str(tarix_soni(kun))         # tarix: savollar soni (savollarning o'zi tarix_bell(kun) dan)
    if dars == "afsun" and kun < "2026-10-09":
        items = items[:AFSUN_ESKI]
    return items[n % len(items)]


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
    """Jadval uchun ism: birinchi so'z. Ichida harf ham, raqam ham bo'lmasa ("." kabi) - "Sehrgar"."""
    raw = (raw or "").strip()
    soz = raw.split()[0][:20] if raw else ""
    return soz if any(ch.isalnum() for ch in soz) else "Sehrgar"


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
        out = {}
        dar = {r["dars"]: r for r in conn.execute(
            "SELECT dars, daraja FROM dars_daraja WHERE user_id=?", (uid,))}
        bah = {r["dars"]: r for r in conn.execute(
            "SELECT dars, COALESCE(SUM(baho),0) AS s, COUNT(*) AS n FROM dars_baho WHERE user_id=? GROUP BY dars", (uid,))}
        for kod in DARSLAR:
            r = dar.get(kod)
            jami = dars_soni(kod)
            b = bah.get(kod)
            out[kod] = {"level": min(int(r["daraja"]) if r else 0, jami), "total": jami,
                        "gs": int(b["s"]) if b else 0, "gn": int(b["n"]) if b else 0,       # baholar yig'indisi va soni
                        "contest": _bellashuv(conn, uid, kun, kod)}
        return out
    finally:
        conn.close()


def _dars_bajarildi(uid, dars, daraja):
    """N-dars o'tildi. Faqat NAVBATDAGI dars (bosqich + 1) bosqichni oshiradi. Oshgan bo'lsa True."""
    daraja = int(daraja)
    if not (1 <= daraja <= dars_soni(dars)):
        return False
    conn = hpcup._connect()
    try:
        conn.execute("INSERT OR IGNORE INTO dars_daraja (user_id, dars, daraja, kun) VALUES (?,?,0,NULL)", (uid, dars))
        cur = conn.execute("UPDATE dars_daraja SET daraja = ?, kun = ? WHERE user_id=? AND dars=? AND daraja = ?",
                           (daraja, hpcup.today_tk(), uid, dars, daraja - 1))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _baho_yoz(uid, juftlar):
    """[(dars, daraja, baho)] - o'tilgan darslarning bahosi (3-5), eng yaxshisi qoladi. Nechta qator yozilganini qaytaradi."""
    conn = hpcup._connect()
    try:
        dar = {r["dars"]: int(r["daraja"]) for r in conn.execute("SELECT dars, daraja FROM dars_daraja WHERE user_id=?", (uid,))}
        n = 0
        for dars, daraja, baho in juftlar:
            try:
                daraja, baho = int(daraja), int(baho)
            except (TypeError, ValueError):
                continue
            if dars not in DARSLAR or not (1 <= daraja <= dar.get(dars, 0)) or not (3 <= baho <= 5):
                continue
            conn.execute("INSERT INTO dars_baho (user_id, dars, daraja, baho) VALUES (?,?,?,?) "
                         "ON CONFLICT(user_id, dars, daraja) DO UPDATE SET baho = MAX(baho, excluded.baho)", (uid, dars, daraja, baho))
            n += 1
        conn.commit()
        return n
    finally:
        conn.close()


# Qobiliyatlar: har fan boshqa qobiliyatni mashq qildiradi (ilova: js/09-darslar.js QOB bilan BIR XIL bo'lsin)
QOBILIYAT = (("bilim", ("tarix",)), ("aniqlik", ("afsun",)), ("xotira", ("iksir", "maxluq")), ("tezlik", ("himoya",)),
             ("koord", ("uchish",)), ("fazo", ("astro",)), ("diqqat", ("osimlik",)), ("mantiq", ("trans",)))


def qobiliyat(uid):
    """[{id, score}] - 0..100: 70% o'tilgan darslar ulushi + 30% o'rtacha baho (bahosi yo'q fanda faqat darslar)."""
    conn = hpcup._connect()
    try:
        dar = {r["dars"]: int(r["daraja"]) for r in conn.execute("SELECT dars, daraja FROM dars_daraja WHERE user_id=?", (int(uid),))}
        bah = {r["dars"]: (int(r["s"]), int(r["n"])) for r in conn.execute(
            "SELECT dars, COALESCE(SUM(baho),0) AS s, COUNT(*) AS n FROM dars_baho WHERE user_id=? GROUP BY dars", (int(uid),))}
    except Exception:
        return []
    finally:
        conn.close()

    def fan(kod):
        jami = dars_soni(kod)
        ul = min(1.0, dar.get(kod, 0) / float(jami)) if jami else 0.0
        s, n = bah.get(kod, (0, 0))
        return 100.0 * (0.7 * ul + 0.3 * (ul * (s / float(n) - 1) / 4 if n else ul))
    return [{"id": k, "score": int(round(sum(round(fan(f)) for f in fl) / float(len(fl))))} for k, fl in QOBILIYAT]


def _daraja(uid, dars):
    conn = hpcup._connect()
    try:
        r = conn.execute("SELECT daraja FROM dars_daraja WHERE user_id=? AND dars=?", (uid, dars)).fetchone()
        return int(r["daraja"]) if r else 0
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
    lang = str(body.get("lang") or "uz")
    if lang not in ("uz", "ru", "en"):
        lang = "uz"
    dars = body.get("done") or body.get("start") or body.get("finish")
    if dars is not None:
        dars = str(dars)
        if dars not in DARSLAR:
            return {"ok": False, "error": "unknown"}
    if isinstance(body.get("grades"), dict):
        # Qurilmada saqlangan eski baholarni bir marta ko'chirish: {fan: {dars raqami: baho}}
        juft = []
        for f, m in list(body["grades"].items())[:20]:
            if isinstance(m, dict):
                juft += [(str(f), k, v) for k, v in list(m.items())[:60]]
        javob["synced"] = _baho_yoz(uid, juft)
    if body.get("quiz") is not None:
        # Tarix darsining savollari: o'tilgan yoki navbatdagi dars
        try:
            n = int(body.get("quiz"))
        except (TypeError, ValueError):
            n = 0
        if not (1 <= n <= min(dars_soni("tarix"), _daraja(uid, "tarix") + 1)):
            return {"ok": False, "error": "locked"}
        qs = tarix_dars(n, lang)
        javob.update(level=n, questions=qs, need=len(qs))        # o'tish uchun HAMMASI to'g'ri bo'lishi kerak
        return javob
    if body.get("done"):
        try:
            n = int(body.get("level") or 0)
        except (TypeError, ValueError):
            n = 0
        javob["new"] = _dars_bajarildi(uid, dars, n)
        javob["pts"] = 0                          # mashq uchun ball yo'q - ball bellashuvdan
        if body.get("grade") is not None:
            _baho_yoz(uid, [(dars, n, body.get("grade"))])
    elif body.get("start"):
        if not _boshla(uid, dars, kun):
            javob.update(ok=False, error="no_tries")
            return javob
        javob["started"] = True
        if dars == "tarix":
            s = bell_savollar()
            javob["questions"] = [_savol(s[i], lang, False) for i in tarix_bell(kun)]
    elif body.get("finish"):
        if dars == "tarix":
            s, idx, jv = bell_savollar(), tarix_bell(kun), body.get("answers")
            jv = jv if isinstance(jv, list) else []
            xato = sum(1 for k, i in enumerate(idx) if k >= len(jv) or jv[k] != s[i]["correct"])
            javob["wrong"] = xato
        else:
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
    amal = body.get("done") or body.get("start") or body.get("finish") or body.get("quiz") or body.get("grades")
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
    if amal:
        _kesh.pop(uid, None)           # amaldan keyin holat o'zgardi - keyingi so'rov yangidan hisoblanadi
    else:
        _kesh[uid] = (hozir, res)
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
