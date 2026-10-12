"""Supurgi poygasi (egasi, 2026-10-12) - to'rtinchi haftalik turnir: DUSHANBA 21:00 (Toshkent).

Hamma bir vaqtda BIR XIL yo'lda uchadi (Uchish darsi o'yini, «aniqlik = tezlik» qoidasi). Bir necha BOSQICH:
  - har bosqichda sanoqdan (SANOQ soniya) keyin hamma birga uchadi; natija - uchish vaqti + jarimalar
    (o'tkazib yuborilgan halqa va bladjer zarbasi - har biri XATO_MS);
  - bosqichdan keyin tezroq yarmi keyingisiga o'tadi (kamida QOLADI kishi), qolganlar tomosha qiladi;
  - oxirgi bosqich - final: eng tez uchgan g'olib.
Bosqichlar soni ishtirokchilarga qarab: 4 kishigacha - bitta (faqat final), 8 gacha - ikkita, undan ko'p - uchta.
Bosqich hamma uchib bo'lgach (yoki BOSQICH_T soniyada) yopiladi; ulgurmagan - eng oxirida. Bosqichlar orasida NATIJA_T soniya.
Ishtirokchi - poyga boshlanishidan ZAL soniya oldindan boshlanishigacha sahifada bo'lgan har bir saralangan o'quvchi
(oldindan yozilish shart emas; «Qatnashaman» - eslatma olish uchun). Kechikkan - tomoshabin.
BALL (kubokka): 1-o'rin +30, 2-o'rin +20, 3-o'rin +10; finalda uchib bo'lgan qolganlarga +5.

Yo'l - har bosqichga alohida URUG' (hafta va maxfiy qiymatdan): ilovaga faqat bosqich boshlanganda yuboriladi.
Vaqt: ilova uchish vaqtini o'zi o'lchaydi, server uni o'z soati bilan solishtiradi (ilova aytgani server o'lchaganidan
ko'pi bilan MUHLAT_MS ga kam bo'lishi mumkin - sanoqdagi kechikish uchun), shuning uchun internet tezligi natijaga ta'sir qilmaydi.

So'rovlar - POST /api/poyga: {} holat, {join: 1|0} yozilish, {heat: n, ms, xato} bosqich natijasi.
"""

import asyncio
import hashlib
import logging
import os
from datetime import datetime, timedelta

from aiohttp import web

import hpcup
import hpdars

BOSH_HAFTA = "2026-10-19"     # birinchi poyga shu haftada (dushanba 19-oktabr)
TURNIR_KUN = 0                # dushanba
SOAT = 21
ZAL = 120                     # boshlanishidan shuncha soniya oldin «zal» ochiladi (kelganlar sanaladi)
SANOQ = 6                     # bosqich ochilgach uchishgacha sanoq
BOSQICH_T = 100               # bosqich eng ko'pi shuncha davom etadi (sanoq bilan birga)
NATIJA_T = 14                 # bosqichlar orasida natija ko'rsatiladigan vaqt
KUTISH = 2                    # hamma uchib bo'lgach bosqich shuncha soniyadan keyin yopiladi
XATO_MS = 3000                # har xato (halqa / bladjer) uchun jarima
ENG_KAM_MS = 9000             # bundan tez uchib bo'lmaydi (soxta natijadan himoya)
MUHLAT_MS = 2500              # ilova o'lchagan vaqt server o'lchaganidan shunchagacha kam bo'lishi mumkin
QOLADI = 3                    # bosqichdan keyin kamida shuncha kishi qoladi
BALL_ORIN = {1: 30, 2: 20, 3: 10}
BALL_FINAL = 5
TUGASH = 3 * 3600             # boshlanganidan shuncha o'tgach keyingi haftaga yozilish ochiladi

_cfg = {}
_qulf = None


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
        conn.execute("CREATE TABLE IF NOT EXISTS pg_natija (hafta TEXT NOT NULL, user_id INTEGER NOT NULL, bosqich INTEGER NOT NULL, ms INTEGER NOT NULL,"
                     " xato INTEGER NOT NULL DEFAULT 0, vaqt REAL NOT NULL, PRIMARY KEY (hafta, user_id, bosqich))")
        conn.execute("CREATE TABLE IF NOT EXISTS pg_eslatma (hafta TEXT NOT NULL, tur TEXT NOT NULL, PRIMARY KEY (hafta, tur))")
        conn.commit()
    finally:
        conn.close()


def _turnir_vaqti(hafta):
    y, m, d = (int(x) for x in hafta.split("-"))
    return (datetime(y, m, d, SOAT, 0, 0, tzinfo=_now().tzinfo) + timedelta(days=TURNIR_KUN)).timestamp()


def _hafta():
    """Navbatdagi (yoki hozir ketayotgan) poyga haftasi (dushanba sanasi)."""
    h = max(hpdars._hafta(), BOSH_HAFTA)
    if _ep() >= _turnir_vaqti(h) + TUGASH:
        y, m, d = (int(x) for x in h.split("-"))
        h = (datetime(y, m, d) + timedelta(days=7)).strftime("%Y-%m-%d")
    return h


def _urug(hafta, bosqich):
    """Shu bosqich yo'lining urug'i - oldindan bilib bo'lmaydi."""
    sir = hashlib.sha256(("poyga|%s|%s|%s" % (os.getenv("BOT_TOKEN", ""), hafta, bosqich)).encode()).hexdigest()
    return int(sir[:8], 16) % 900000 + 1000


def bosqichlar_soni(n):
    return 1 if n <= 4 else 2 if n <= 8 else 3


def otadiganlar(n):
    """Bosqichdan keyin nechta kishi qoladi (tirik n kishidan)."""
    return min(n, max(QOLADI, (n + 1) // 2))


def _natijalar(conn, hafta, bosqich):
    """Shu bosqichning tirik ishtirokchilari tartibi: [(uid, ms yoki None)] - uchib bo'lganlar tezligi bo'yicha, ulgurmaganlar oxirida."""
    tirik = [r["user_id"] for r in conn.execute("SELECT user_id FROM pg_oyinchi WHERE hafta=? AND tirik=1", (hafta,))]
    ms = {r["user_id"]: r["ms"] for r in conn.execute("SELECT user_id, ms FROM pg_natija WHERE hafta=? AND bosqich=?", (hafta, bosqich))}
    return sorted(((u, ms.get(u)) for u in tirik), key=lambda p: (p[1] is None, p[1] or 0, p[0]))


def _yakunla(conn, hafta, t, berish, now):
    """O'rinlar: finalchilar final vaqti bo'yicha, keyin kechroq chiqqanlar (o'sha bosqichdagi vaqti bo'yicha)."""
    final = t["jami"] - 1
    tartib = [u for u, _ in _natijalar(conn, hafta, final)]
    final_ms = {r["user_id"]: r["ms"] for r in conn.execute("SELECT user_id, ms FROM pg_natija WHERE hafta=? AND bosqich=?", (hafta, final))}
    chiqqan = conn.execute("SELECT o.user_id, o.chiqdi, n.ms FROM pg_oyinchi o LEFT JOIN pg_natija n ON n.hafta=o.hafta AND n.user_id=o.user_id AND n.bosqich=o.chiqdi "
                           "WHERE o.hafta=? AND o.tirik=0", (hafta,)).fetchall()
    tartib += [r["user_id"] for r in sorted(chiqqan, key=lambda r: (-(r["chiqdi"] or 0), r["ms"] is None, r["ms"] or 0, r["user_id"]))]
    for i, u in enumerate(tartib):
        orin = i + 1
        conn.execute("UPDATE pg_oyinchi SET orin=? WHERE hafta=? AND user_id=?", (orin, hafta, u))
        if u in final_ms:                        # ball faqat finalda uchib bo'lganlarga
            berish.append((u, "poyga:%s" % hafta, BALL_ORIN.get(orin, BALL_FINAL)))
    golib = tartib[0] if tartib and tartib[0] in final_ms else None
    conn.execute("UPDATE pg_turnir SET holat='tugadi', golib=?, tugadi=? WHERE hafta=?", (golib, now, hafta))


def _yur(conn, hafta, berish, now):
    """Poygani hozirgi vaqtga keltiradi: tugagan bosqichlarni yopadi."""
    T0 = _turnir_vaqti(hafta)
    if now < T0:
        return
    t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()
    if not t:
        soni = conn.execute("SELECT COUNT(*) FROM pg_oyinchi WHERE hafta=?", (hafta,)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO pg_turnir (hafta, bosh, jami, soni) VALUES (?,?,?,?)", (hafta, T0, bosqichlar_soni(soni), soni))
        if soni < 2:                             # bir kishi bilan poyga bo'lmaydi
            conn.execute("UPDATE pg_turnir SET holat='tugadi', tugadi=? WHERE hafta=?", (now, hafta))
            conn.execute("UPDATE pg_oyinchi SET tirik=0 WHERE hafta=?", (hafta,))
        t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()
    while t["holat"] == "ketmoqda":
        k, bosh = t["bosqich"], t["bosh"]
        if now < bosh + SANOQ:
            break                                # natija ko'rsatilmoqda yoki sanoq ketmoqda
        nat = _natijalar(conn, hafta, k)
        hammasi = all(ms is not None for _, ms in nat)
        oxirgi = conn.execute("SELECT MAX(vaqt) FROM pg_natija WHERE hafta=? AND bosqich=?", (hafta, k)).fetchone()[0] or 0
        if not (now >= bosh + BOSQICH_T or (hammasi and now >= oxirgi + KUTISH)):
            break                                # hali uchishyapti
        yopildi = min(now, bosh + BOSQICH_T) if not hammasi else max(oxirgi + KUTISH, bosh + SANOQ)
        if k + 1 >= t["jami"]:
            _yakunla(conn, hafta, t, berish, yopildi)
        else:
            qoladi = otadiganlar(len(nat))
            for i, (u, ms) in enumerate(nat):
                if i >= qoladi or ms is None:    # ulgurmagan hech qachon o'tmaydi
                    conn.execute("UPDATE pg_oyinchi SET tirik=0, chiqdi=? WHERE hafta=? AND user_id=?", (k, hafta, u))
            qoldi = conn.execute("SELECT COUNT(*) FROM pg_oyinchi WHERE hafta=? AND tirik=1", (hafta,)).fetchone()[0]
            if qoldi < 1:                        # hech kim uchib bo'lmadi - poyga shu bosqichda tugaydi
                conn.execute("UPDATE pg_turnir SET jami=? WHERE hafta=?", (k + 1, hafta))
                conn.execute("UPDATE pg_oyinchi SET tirik=1, chiqdi=NULL WHERE hafta=? AND chiqdi=?", (hafta, k))
                _yakunla(conn, hafta, dict(t, jami=k + 1), berish, yopildi)
            else:
                conn.execute("UPDATE pg_turnir SET bosqich=?, bosh=? WHERE hafta=?", (k + 1, yopildi + NATIJA_T, hafta))
        t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()


def _eslatmalar(conn, hafta, xabarlar):
    hozir = _now()
    if hozir.weekday() != TURNIR_KUN or hozir.timestamp() >= _turnir_vaqti(hafta):
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
        conn.commit()
    finally:
        conn.close()
    return berish, xabarlar


def xat_matni(tur):
    if tur == "elon":
        return {"uz": ("Bugun 21:00 da birinchi supurgi poygasi!", "Hamma bir vaqtda bir xil yo'lda uchadi: halqalarning o'rtasidan o'tgan tezlashadi, sekinroq yarmi har bosqichda chiqib ketadi. Soat 21:00 da ilovada Xogvarts → Poyga sahifasida bo'ling. G'olibga +30 ball. Hozirdan mashq qilsangiz bo'ladi."),
                "ru": ("Сегодня в 21:00 первая гонка на мётлах!", "Все летят одновременно по одной трассе: кто точнее проходит кольца — тот быстрее; медленная половина выбывает после каждого этапа. В 21:00 будьте в приложении: Хогвартс → Гонка. Победителю +30 очков. Потренироваться можно уже сейчас."),
                "en": ("The first broom race is today at 21:00!", "Everyone flies the same course at once: pass the hoops dead centre to go faster; the slower half drops out after each heat. Be in the app at 21:00: Hogwarts → Race. +30 points for the winner. You can practise right now.")}
    if tur == "ertalab":
        return {"uz": ("Bugun 21:00 da supurgi poygasi", "Poyga bugun soat 21:00 da. Ilovaga kiring: Xogvarts → Poyga. Kechikkanlar faqat tomosha qiladi. Hozircha mashq qilib oling."),
                "ru": ("Сегодня в 21:00 гонка на мётлах", "Гонка сегодня в 21:00. Зайдите: Хогвартс → Гонка. Опоздавшие только смотрят. А пока — потренируйтесь."),
                "en": ("The broom race is today at 21:00", "The race is today at 21:00. Come in: Hogwarts → Race. Latecomers can only watch. Meanwhile, practise.")}
    return {"uz": ("Poygaga 10 daqiqa qoldi!", "Supurgi poygasi 21:00 da boshlanadi. Hoziroq ilovaga kiring: Xogvarts → Poyga."),
            "ru": ("До гонки 10 минут!", "Гонка на мётлах начнётся в 21:00. Зайдите прямо сейчас: Хогвартс → Гонка."),
            "en": ("10 minutes to the race!", "The broom race starts at 21:00. Come in now: Hogwarts → Race.")}


async def _elon_yubor():
    try:
        n = await _cfg["elon"](xat_matni("elon"))
        logging.info("Poyga e'loni yuborildi: %s kishi", n)
    except Exception as e:
        logging.error("Poyga e'loni yuborilmadi: %s", e)


async def tick():
    async with _qulf:
        berish, xabarlar = await asyncio.to_thread(_tick)
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


async def kuzatuvchi(interval=15):
    while True:
        try:
            await tick()
        except Exception as e:
            logging.error("Poyga kuzatuvchisi: %s", e)
        try:
            T0 = _turnir_vaqti(_hafta())
            tez = T0 - 600 <= _ep() <= T0 + 3 * (BOSQICH_T + NATIJA_T) + 60
        except Exception:
            tez = False
        await asyncio.sleep(2 if tez else interval)


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


def _natija_yoz(uid, bosqich, ms, xato):
    """Bosqich natijasi: faqat tirik ishtirokchi, faqat hozirgi bosqichga, bir marta. Vaqt server soati bilan tekshiriladi."""
    uid, hafta, now = int(uid), _hafta(), _ep()
    conn = hpcup._connect()
    try:
        t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()
        if not t or t["holat"] != "ketmoqda" or t["bosqich"] != bosqich:
            return False
        uchdi = (now - (t["bosh"] + SANOQ)) * 1000          # server o'lchagan uchish vaqti
        if uchdi < ENG_KAM_MS or now > t["bosh"] + BOSQICH_T + 3:
            return False
        o = conn.execute("SELECT tirik FROM pg_oyinchi WHERE hafta=? AND user_id=?", (hafta, uid)).fetchone()
        if not o or not o["tirik"]:
            return False
        try:
            aytgan = float(ms)
        except (TypeError, ValueError):
            aytgan = uchdi
        sof = max(ENG_KAM_MS, min(uchdi, max(aytgan, uchdi - MUHLAT_MS)))
        xato = max(0, min(int(xato or 0), 80))
        cur = conn.execute("INSERT OR IGNORE INTO pg_natija (hafta, user_id, bosqich, ms, xato, vaqt) VALUES (?,?,?,?,?,?)",
                           (hafta, uid, bosqich, int(sof) + xato * XATO_MS, xato, now))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _ism(conn, uid):
    r = conn.execute("SELECT COALESCE(first_name, 'Sehrgar') AS name, house FROM users WHERE user_id=?", (uid,)).fetchone()
    return {"uid": uid, "name": hpdars._ism(r["name"]) if r else "Sehrgar", "house": r["house"] if r else None}


def _oxirgi(conn, hafta_dan_oldin):
    r = conn.execute("SELECT hafta, golib, soni FROM pg_turnir WHERE holat='tugadi' AND golib IS NOT NULL AND hafta < ? ORDER BY hafta DESC LIMIT 1",
                     (hafta_dan_oldin,)).fetchone()
    return dict(_ism(conn, r["golib"]), n=r["soni"]) if r else None


def _jadval(conn, hafta, bosqich, uid, qoladi=None):
    """Bosqich natijalari jadvali (hammasi): o'rin, ism, vaqt, o'tdimi."""
    out = []
    for i, (u, ms) in enumerate(_natijalar_hamma(conn, hafta, bosqich)):
        d = _ism(conn, u)
        d.update(place=i + 1, ms=ms, me=u == uid)
        if qoladi is not None:
            d["through"] = i < qoladi and ms is not None
        out.append(d)
    return out


def _natijalar_hamma(conn, hafta, bosqich):
    """Shu bosqichda uchgan (yoki uchishi kerak bo'lgan) hamma: bosqich yopilgach `tirik` o'zgargan bo'ladi, shuning uchun chiqdi >= bosqich ham olinadi."""
    kim = [r["user_id"] for r in conn.execute("SELECT user_id FROM pg_oyinchi WHERE hafta=? AND (tirik=1 OR chiqdi >= ?)", (hafta, bosqich))]
    ms = {r["user_id"]: r["ms"] for r in conn.execute("SELECT user_id, ms FROM pg_natija WHERE hafta=? AND bosqich=?", (hafta, bosqich))}
    return sorted(((u, ms.get(u)) for u in kim), key=lambda p: (p[1] is None, p[1] or 0, p[0]))


def _holat(uid):
    uid, hafta, now = int(uid), _hafta(), _ep()
    T0 = _turnir_vaqti(hafta)
    conn = hpcup._connect()
    try:
        if T0 - ZAL <= now < T0:                 # zalda bo'lganlar ishtirokchi bo'ladi
            conn.execute("INSERT OR IGNORE INTO pg_oyinchi (hafta, user_id, keldi) VALUES (?,?,?)", (hafta, uid, now))
        conn.execute("UPDATE pg_oyinchi SET keldi=? WHERE hafta=? AND user_id=?", (now, hafta, uid))
        conn.commit()
        t = conn.execute("SELECT * FROM pg_turnir WHERE hafta=?", (hafta,)).fetchone()
        men = conn.execute("SELECT * FROM pg_oyinchi WHERE hafta=? AND user_id=?", (hafta, uid)).fetchone()
        yozilgan = conn.execute("SELECT COUNT(*) FROM pg_qatnash WHERE hafta=?", (hafta,)).fetchone()[0]
        javob = {
            "ok": True, "now": now,
            "tour": {"ts": T0, "now": now, "open": now < T0, "n": yozilgan,
                     "joined": conn.execute("SELECT 1 FROM pg_qatnash WHERE hafta=? AND user_id=?", (hafta, uid)).fetchone() is not None},
            "rules": {"count": SANOQ, "heat": BOSQICH_T, "show": NATIJA_T, "hall": ZAL, "penalty": XATO_MS // 1000, "keep": QOLADI,
                      "final_pts": BALL_FINAL, "points": {str(k): v for k, v in BALL_ORIN.items()}},
            "last": _oxirgi(conn, hafta),
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
        javob["alive"] = conn.execute("SELECT COUNT(*) FROM pg_oyinchi WHERE hafta=? AND tirik=1", (hafta,)).fetchone()[0]
        javob["heats"] = t["jami"]
        if t["holat"] == "tugadi":
            javob["phase"] = "tugadi"
            javob["played"] = t["soni"] >= 2
            top = conn.execute("SELECT o.user_id, o.orin, o.chiqdi FROM pg_oyinchi o WHERE o.hafta=? AND o.orin IS NOT NULL ORDER BY o.orin LIMIT 10", (hafta,)).fetchall()
            final = t["jami"] - 1
            fms = {r["user_id"]: r["ms"] for r in conn.execute("SELECT user_id, ms FROM pg_natija WHERE hafta=? AND bosqich=?", (hafta, final))}
            javob["top"] = [dict(_ism(conn, r["user_id"]), place=r["orin"], ms=fms.get(r["user_id"]), me=r["user_id"] == uid) for r in top]
            if men and men["orin"]:
                javob["me"]["points"] = BALL_ORIN.get(men["orin"], BALL_FINAL) if uid in fms else 0
                javob["me"]["ms"] = fms.get(uid)
            return javob
        k, bosh = t["bosqich"], t["bosh"]
        if now < bosh:                           # oldingi bosqich natijasi ko'rsatilmoqda
            javob["phase"] = "natija"
            javob["heat"] = {"n": k - 1}
            oldingi = _natijalar_hamma(conn, hafta, k - 1)
            javob["results"] = _jadval(conn, hafta, k - 1, uid, otadiganlar(len(oldingi)))
            javob["next_in"] = int(bosh - now) + 1
            javob["next_final"] = k + 1 >= t["jami"]
            return javob
        javob["phase"] = "poyga"
        mening = conn.execute("SELECT ms, xato FROM pg_natija WHERE hafta=? AND user_id=? AND bosqich=?", (hafta, uid, k)).fetchone()
        uchgan = conn.execute("SELECT COUNT(*) FROM pg_natija WHERE hafta=? AND bosqich=?", (hafta, k)).fetchone()[0]
        javob["heat"] = {"n": k, "seed": _urug(hafta, k), "start_in": round(bosh + SANOQ - now, 2), "left": max(0, round(bosh + BOSQICH_T - now, 1)),
                         "final": k + 1 >= t["jami"], "done": uchgan, "keep": otadiganlar(javob["alive"]) if k + 1 < t["jami"] else None,
                         "mine": {"ms": mening["ms"], "xato": mening["xato"]} if mening else None}
        if mening:                               # uchib bo'lganga - hozirgacha kelganlar jadvali
            javob["results"] = [r for r in _jadval(conn, hafta, k, uid) if r["ms"] is not None]
        return javob
    finally:
        conn.close()


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
    if not hpcup._get_house(uid):
        return cors(web.json_response({"ok": False, "error": "no_house"}))
    qosh = {}
    try:
        await tick()                             # avval holat hozirgi vaqtga keltiriladi
    except Exception as e:
        logging.error("Poyga tick: %s", e)
    if body.get("join") is not None:
        qosh["join_ok"] = await asyncio.to_thread(_yozil, uid, bool(body.get("join")))
    elif body.get("heat") is not None:
        try:
            qosh["heat_ok"] = await asyncio.to_thread(_natija_yoz, uid, int(body.get("heat")), body.get("ms"), body.get("xato"))
        except (TypeError, ValueError):
            qosh["heat_ok"] = False
        try:
            await tick()                         # oxirgi uchuvchi bo'lsa bosqich tezroq yopilsin
        except Exception as e:
            logging.error("Poyga tick: %s", e)
    javob = await asyncio.to_thread(_holat, uid)
    javob.update(qosh)
    if javob.get("phase") == "tugadi" and javob["me"].get("place") and _cfg.get("log") and body.get("log_end"):
        try:
            await _cfg["log"](user, "poyga_%d" % javob["me"]["place"])
        except Exception:
            pass
    return cors(web.json_response(javob))


def register(app, cfg):
    """cfg: verify_init_data, cors, log, xat, elon. hpdars DAN KEYIN ulanadi."""
    global _qulf
    _cfg.update(cfg)
    _qulf = asyncio.Lock()
    _init()
    app.router.add_route("*", "/api/poyga", api_poyga)
    logging.info("Supurgi poygasi ulandi")
