"""Jonli viktorina «Oxirgi sehrgar» (egasi, 2026-10-11) - uchinchi haftalik turnir.

Haftada bir marta, JUMA 21:00 (Toshkent). Hamma bir vaqtda BITTA savolga javob beradi:
  - savolga SAVOL_T soniya; xato javob bergan yoki javob bermagan CHIQIB KETADI;
  - keyin NATIJA_T soniya to'g'ri javob va zalda nechta sehrgar qolgani ko'rsatiladi; so'ng keyingi savol;
  - oxirida BITTA sehrgar qolsa - u g'olib. Savolda qolganlarning HAMMASI xato qilsa, hech kim chiqmaydi
    (savol bekor) - aks holda g'olibsiz qolardi;
  - SAVOL_MAX savoldan keyin ham bir necha kishi qolsa - o'rinlar javob tezligi bo'yicha (jami vaqt kam bo'lgani yuqori).
Ishtirokchi - turnir boshlanishidan ZAL soniya oldin bilan birinchi savol tugaguncha sahifada bo'lgan har bir saralangan
o'quvchi (oldindan yozilish shart emas; «Qatnashaman» - eslatma olish uchun). Kechikkan - tomoshabin.
O'RINLAR: kech chiqqan yuqori; bir savolda chiqqanlar orasida - to'g'ri javoblarga sarflangan jami vaqti kam bo'lgani.
BALL (kubokka): 1-o'rin +30, 2-o'rin +20, 3-o'rin +10; kamida YAXSHI ta savolga to'g'ri javob bergan har kimga +5 (uchlikdan tashqari).

Savollar - Sehrgarlik tarixi havzasidan (hpdars.bell_savollar), tartibi hafta va maxfiy qiymatdan (oldindan bilib bo'lmaydi).
To'g'ri javob ilovaga faqat savol vaqti tugagach yuboriladi.

So'rovlar - POST /api/viktorina: {} holat, {join: 1|0} yozilish, {q: n, answer: i} javob. Savol matni `lang` tilida.
"""

import asyncio
import hashlib
import json
import logging
import os
import random
from datetime import datetime, timedelta

from aiohttp import web

import hpcup
import hpdars

BOSH_HAFTA = "2026-10-12"     # birinchi viktorina shu haftada (juma 16-oktabr)
TURNIR_KUN = 4                # juma (dushanba = 0)
SOAT = 21
ZAL = 120                     # boshlanishidan shuncha soniya oldin «zal» ochiladi (kelganlar sanaladi)
SAVOL_T = 15                  # savolga javob vaqti
NATIJA_T = 7                  # to'g'ri javob ko'rsatiladigan vaqt
SAVOL_MAX = 30
YAXSHI = 5                    # shuncha to'g'ri javob - tasalli bali
BALL_ORIN = {1: 30, 2: 20, 3: 10}
BALL_YAXSHI = 5
TUGASH = 3 * 3600             # boshlanganidan shuncha o'tgach keyingi haftaga yozilish ochiladi
BOR = 12                      # so'nggi shuncha soniyada so'rov yuborgan - zalda

_cfg = {}
_qulf = None


def _now():
    return hpcup.now_tk()


def _ep():
    return _now().timestamp()


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS vk_turnir (hafta TEXT PRIMARY KEY, holat TEXT NOT NULL DEFAULT 'ketmoqda', savol INTEGER NOT NULL DEFAULT 0,"
                     " savollar TEXT NOT NULL DEFAULT '[]', soni INTEGER NOT NULL DEFAULT 0, golib INTEGER, tugadi REAL)")
        conn.execute("CREATE TABLE IF NOT EXISTS vk_qatnash (hafta TEXT NOT NULL, user_id INTEGER NOT NULL, vaqt TEXT NOT NULL, PRIMARY KEY (hafta, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS vk_oyinchi (hafta TEXT NOT NULL, user_id INTEGER NOT NULL, keldi REAL, tirik INTEGER NOT NULL DEFAULT 1,"
                     " chiqdi INTEGER, togri INTEGER NOT NULL DEFAULT 0, ms INTEGER NOT NULL DEFAULT 0, orin INTEGER, PRIMARY KEY (hafta, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS vk_javob (hafta TEXT NOT NULL, user_id INTEGER NOT NULL, savol INTEGER NOT NULL, javob INTEGER NOT NULL,"
                     " ms INTEGER NOT NULL, PRIMARY KEY (hafta, user_id, savol))")
        conn.execute("CREATE TABLE IF NOT EXISTS vk_eslatma (hafta TEXT NOT NULL, tur TEXT NOT NULL, PRIMARY KEY (hafta, tur))")
        conn.commit()
    finally:
        conn.close()


def _turnir_vaqti(hafta):
    y, m, d = (int(x) for x in hafta.split("-"))
    return (datetime(y, m, d, SOAT, 0, 0, tzinfo=_now().tzinfo) + timedelta(days=TURNIR_KUN)).timestamp()


def _hafta():
    """Navbatdagi (yoki hozir ketayotgan) viktorina haftasi."""
    h = max(hpdars._hafta(), BOSH_HAFTA)
    if _ep() >= _turnir_vaqti(h) + TUGASH:
        y, m, d = (int(x) for x in h.split("-"))
        h = (datetime(y, m, d) + timedelta(days=7)).strftime("%Y-%m-%d")
    return h


def _savollar(hafta):
    """Shu haftaning savollari (havzadagi tartib raqamlari) - maxfiy urug' bilan aralashtirilgan."""
    havza = hpdars.bell_savollar()
    sir = hashlib.sha256(("viktorina|" + os.getenv("BOT_TOKEN", "") + "|" + hafta).encode()).hexdigest()
    return random.Random(sir).sample(range(len(havza)), min(SAVOL_MAX, len(havza)))


def _savol_vaqti(hafta, n):
    """n-savol (0 dan) ochiladigan payt."""
    return _turnir_vaqti(hafta) + n * (SAVOL_T + NATIJA_T)


def _yakunla(conn, hafta, berish, now):
    """O'rinlarni belgilaydi va ballarni ro'yxatga qo'shadi."""
    rows = conn.execute("SELECT * FROM vk_oyinchi WHERE hafta=?", (hafta,)).fetchall()
    # kech chiqqan (yoki umuman chiqmagan) yuqori; keyin to'g'ri javoblar soni; keyin jami vaqt kam bo'lgani
    tartib = sorted(rows, key=lambda r: (-(r["chiqdi"] if r["chiqdi"] is not None else 10 ** 6), -r["togri"], r["ms"], r["user_id"]))
    for i, r in enumerate(tartib):
        orin = i + 1
        conn.execute("UPDATE vk_oyinchi SET orin=? WHERE hafta=? AND user_id=?", (orin, hafta, r["user_id"]))
        pts = BALL_ORIN.get(orin, BALL_YAXSHI if r["togri"] >= YAXSHI else 0)
        if pts and r["togri"] > 0:
            berish.append((r["user_id"], "viktorina:%s" % hafta, pts))
    golib = tartib[0]["user_id"] if tartib and tartib[0]["togri"] > 0 else None
    conn.execute("UPDATE vk_turnir SET holat='tugadi', golib=?, tugadi=? WHERE hafta=?", (golib, now, hafta))


def _yur(conn, hafta, berish, now):
    """Viktorinani hozirgi vaqtga keltiradi: vaqti tugagan savollarni hal qiladi."""
    T0 = _turnir_vaqti(hafta)
    if now < T0:
        return
    t = conn.execute("SELECT * FROM vk_turnir WHERE hafta=?", (hafta,)).fetchone()
    if not t:
        conn.execute("INSERT OR IGNORE INTO vk_turnir (hafta, savollar) VALUES (?,?)", (hafta, json.dumps(_savollar(hafta))))
        t = conn.execute("SELECT * FROM vk_turnir WHERE hafta=?", (hafta,)).fetchone()
    havza = hpdars.bell_savollar()
    tartib = json.loads(t["savollar"])
    while t["holat"] == "ketmoqda":
        n = t["savol"]
        if now < _savol_vaqti(hafta, n) + SAVOL_T:
            break                                # shu savolga hali javob berilmoqda
        if n == 0:
            soni = conn.execute("SELECT COUNT(*) FROM vk_oyinchi WHERE hafta=?", (hafta,)).fetchone()[0]
            conn.execute("UPDATE vk_turnir SET soni=? WHERE hafta=?", (soni, hafta))
            if soni < 2:                         # bir kishi bilan viktorina bo'lmaydi
                conn.execute("UPDATE vk_turnir SET holat='tugadi', tugadi=? WHERE hafta=?", (now, hafta))
                conn.execute("UPDATE vk_oyinchi SET tirik=0 WHERE hafta=?", (hafta,))
                break
        togri = havza[tartib[n]]["correct"]
        tiriklar = conn.execute("SELECT user_id FROM vk_oyinchi WHERE hafta=? AND tirik=1", (hafta,)).fetchall()
        javob = {r["user_id"]: r for r in conn.execute("SELECT * FROM vk_javob WHERE hafta=? AND savol=?", (hafta, n))}
        yutgan = [r["user_id"] for r in tiriklar if r["user_id"] in javob and javob[r["user_id"]]["javob"] == togri]
        for u in yutgan:
            conn.execute("UPDATE vk_oyinchi SET togri=togri+1, ms=ms+? WHERE hafta=? AND user_id=?", (javob[u]["ms"], hafta, u))
        if yutgan:                               # hech kim topmasa savol bekor - hamma qoladi
            for r in tiriklar:
                if r["user_id"] not in yutgan:
                    conn.execute("UPDATE vk_oyinchi SET tirik=0, chiqdi=? WHERE hafta=? AND user_id=?", (n, hafta, r["user_id"]))
        conn.execute("UPDATE vk_turnir SET savol=? WHERE hafta=?", (n + 1, hafta))
        qoldi = len(yutgan) if yutgan else len(tiriklar)
        if qoldi <= 1 or n + 1 >= len(tartib):
            _yakunla(conn, hafta, berish, now)
        t = conn.execute("SELECT * FROM vk_turnir WHERE hafta=?", (hafta,)).fetchone()


def _eslatmalar(conn, hafta, xabarlar):
    hozir = _now()
    if hozir.weekday() != TURNIR_KUN or hozir.timestamp() >= _turnir_vaqti(hafta):
        return
    daq = hozir.hour * 60 + hozir.minute
    tur = "on" if SOAT * 60 - 10 <= daq < SOAT * 60 else "ertalab" if 600 <= daq < SOAT * 60 - 10 else None
    if not tur:
        return
    if conn.execute("INSERT OR IGNORE INTO vk_eslatma (hafta, tur) VALUES (?,?)", (hafta, tur)).rowcount < 1:
        return
    if tur == "ertalab" and hafta == BOSH_HAFTA:
        xabarlar.append((0, "elon"))             # birinchi viktorina: hamma saralanganlarga e'lon
        return
    for r in conn.execute("SELECT user_id FROM vk_qatnash WHERE hafta=?", (hafta,)).fetchall():
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
        return {"uz": ("Bugun 21:00 da birinchi viktorina — «Oxirgi sehrgar»!", "Hamma bir vaqtda bitta savolga javob beradi, xato qilgan chiqib ketadi — oxirida qolgan g'olib. Soat 21:00 da ilovada Xogvarts → Jadval → Viktorina sahifasida bo'ling. G'olibga +30 ball."),
                "ru": ("Сегодня в 21:00 первая викторина — «Последний волшебник»!", "Все одновременно отвечают на один вопрос, ошибся — выбыл; побеждает тот, кто останется последним. В 21:00 будьте в приложении: Хогвартс → Расписание → Викторина. Победителю +30 очков."),
                "en": ("The first quiz is today at 21:00 — “The Last Wizard”!", "Everyone answers the same question at once; one mistake and you are out — the last one standing wins. Be in the app at 21:00: Hogwarts → Schedule → Quiz. +30 points for the winner.")}
    if tur == "ertalab":
        return {"uz": ("Bugun 21:00 da viktorina", "«Oxirgi sehrgar» bugun soat 21:00 da. Ilovaga kiring: Xogvarts → Jadval → Viktorina. Kechikkanlar faqat tomosha qiladi."),
                "ru": ("Сегодня в 21:00 викторина", "«Последний волшебник» сегодня в 21:00. Зайдите: Хогвартс → Расписание → Викторина. Опоздавшие только смотрят."),
                "en": ("The quiz is today at 21:00", "“The Last Wizard” is today at 21:00. Come in: Hogwarts → Schedule → Quiz. Latecomers can only watch.")}
    return {"uz": ("Viktorinaga 10 daqiqa qoldi!", "«Oxirgi sehrgar» 21:00 da boshlanadi. Hoziroq ilovaga kiring: Xogvarts → Jadval → Viktorina."),
            "ru": ("До викторины 10 минут!", "«Последний волшебник» начнётся в 21:00. Зайдите прямо сейчас: Хогвартс → Расписание → Викторина."),
            "en": ("10 minutes to the quiz!", "“The Last Wizard” starts at 21:00. Come in now: Hogwarts → Schedule → Quiz.")}


async def _elon_yubor():
    try:
        n = await _cfg["elon"](xat_matni("elon"))
        logging.info("Viktorina e'loni yuborildi: %s kishi", n)
    except Exception as e:
        logging.error("Viktorina e'loni yuborilmadi: %s", e)


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
                logging.error("Viktorina xati yuborilmadi (%s): %s", uid, e)
    return len(berish), len(xabarlar)


async def kuzatuvchi(interval=15):
    while True:
        try:
            await tick()
        except Exception as e:
            logging.error("Viktorina kuzatuvchisi: %s", e)
        try:
            T0 = _turnir_vaqti(_hafta())
            tez = T0 - 600 <= _ep() <= T0 + SAVOL_MAX * (SAVOL_T + NATIJA_T) + 60
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
            conn.execute("INSERT OR IGNORE INTO vk_qatnash (hafta, user_id, vaqt) VALUES (?,?,?)", (hafta, uid, hpcup._utc_iso(_now())))
        else:
            conn.execute("DELETE FROM vk_qatnash WHERE hafta=? AND user_id=?", (hafta, uid))
        conn.commit()
        return True
    finally:
        conn.close()


def _javob(uid, n, javob):
    """Javobni yozadi: faqat tirik ishtirokchi, faqat hozirgi savolga, bir marta."""
    uid, hafta, now = int(uid), _hafta(), _ep()
    conn = hpcup._connect()
    try:
        t = conn.execute("SELECT * FROM vk_turnir WHERE hafta=?", (hafta,)).fetchone()
        bosh = _savol_vaqti(hafta, n)
        if not t or t["holat"] != "ketmoqda" or t["savol"] != n or not (bosh <= now < bosh + SAVOL_T):
            return False
        o = conn.execute("SELECT tirik FROM vk_oyinchi WHERE hafta=? AND user_id=?", (hafta, uid)).fetchone()
        if not o or not o["tirik"]:
            return False
        cur = conn.execute("INSERT OR IGNORE INTO vk_javob (hafta, user_id, savol, javob, ms) VALUES (?,?,?,?,?)",
                           (hafta, uid, n, int(javob), int((now - bosh) * 1000)))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


def _ism(conn, uid):
    r = conn.execute("SELECT COALESCE(first_name, 'Sehrgar') AS name, house FROM users WHERE user_id=?", (uid,)).fetchone()
    return {"uid": uid, "name": hpdars._ism(r["name"]) if r else "Sehrgar", "house": r["house"] if r else None}


def _oxirgi(conn, hafta_dan_oldin):
    """Oldingi viktorina g'olibi (sahifada ko'rsatish uchun)."""
    r = conn.execute("SELECT hafta, golib, soni FROM vk_turnir WHERE holat='tugadi' AND golib IS NOT NULL AND hafta < ? ORDER BY hafta DESC LIMIT 1",
                     (hafta_dan_oldin,)).fetchone()
    return dict(_ism(conn, r["golib"]), n=r["soni"]) if r else None


def _holat(uid, lang="uz"):
    uid, hafta, now = int(uid), _hafta(), _ep()
    T0 = _turnir_vaqti(hafta)
    conn = hpcup._connect()
    try:
        # Zalda bo'lganlar ishtirokchi bo'ladi: boshlanishidan ZAL soniya oldindan birinchi savol tugaguncha
        if T0 - ZAL <= now < T0 + SAVOL_T:
            conn.execute("INSERT OR IGNORE INTO vk_oyinchi (hafta, user_id, keldi) VALUES (?,?,?)", (hafta, uid, now))
        conn.execute("UPDATE vk_oyinchi SET keldi=? WHERE hafta=? AND user_id=?", (now, hafta, uid))
        conn.commit()
        t = conn.execute("SELECT * FROM vk_turnir WHERE hafta=?", (hafta,)).fetchone()
        men = conn.execute("SELECT * FROM vk_oyinchi WHERE hafta=? AND user_id=?", (hafta, uid)).fetchone()
        yozilgan = conn.execute("SELECT COUNT(*) FROM vk_qatnash WHERE hafta=?", (hafta,)).fetchone()[0]
        javob = {
            "ok": True, "now": now,
            "tour": {"ts": T0, "now": now, "open": now < T0, "n": yozilgan,
                     "joined": conn.execute("SELECT 1 FROM vk_qatnash WHERE hafta=? AND user_id=?", (hafta, uid)).fetchone() is not None},
            "rules": {"q": SAVOL_T, "show": NATIJA_T, "max": SAVOL_MAX, "hall": ZAL, "good": YAXSHI, "good_pts": BALL_YAXSHI,
                      "points": {str(k): v for k, v in BALL_ORIN.items()}},
            "last": _oxirgi(conn, hafta),
            "me": {"in": bool(men), "alive": bool(men and men["tirik"]), "out": men["chiqdi"] if men else None,
                   "right": men["togri"] if men else 0, "place": men["orin"] if men else None},
        }
        if now < T0 - ZAL:
            javob["phase"] = "kutish"
            return javob
        jami = conn.execute("SELECT COUNT(*) FROM vk_oyinchi WHERE hafta=?", (hafta,)).fetchone()[0]
        tirik = conn.execute("SELECT COUNT(*) FROM vk_oyinchi WHERE hafta=? AND tirik=1", (hafta,)).fetchone()[0]
        javob["total"], javob["alive"] = jami, tirik
        if now < T0:
            javob["phase"] = "zal"
            javob["starts_in"] = int(T0 - now)
            return javob
        if not t:
            javob["phase"] = "zal"
            javob["starts_in"] = 0
            return javob
        havza, tartib = hpdars.bell_savollar(), json.loads(t["savollar"])

        def savol_matni(n, ochiq):
            q = havza[tartib[n]]
            m = q.get(lang) or q["uz"]
            s = {"n": n, "q": m["q"], "a": m["a"]}
            if ochiq:
                s["c"] = q["correct"]
            mj = conn.execute("SELECT javob FROM vk_javob WHERE hafta=? AND user_id=? AND savol=?", (hafta, uid, n)).fetchone()
            s["mine"] = mj["javob"] if mj else None
            return s

        if t["holat"] == "tugadi":
            javob["phase"] = "tugadi"
            top = conn.execute("SELECT o.user_id, o.orin, o.togri, COALESCE(u.first_name, 'Sehrgar') AS name, u.house FROM vk_oyinchi o "
                               "JOIN users u ON u.user_id = o.user_id WHERE o.hafta=? AND o.orin IS NOT NULL ORDER BY o.orin LIMIT 10", (hafta,)).fetchall()
            javob["top"] = [{"uid": r["user_id"], "place": r["orin"], "right": r["togri"], "name": hpdars._ism(r["name"]), "house": r["house"],
                             "me": r["user_id"] == uid} for r in top]
            javob["asked"] = t["savol"]
            javob["played"] = t["soni"] >= 2
            if men and men["orin"]:
                javob["me"]["points"] = BALL_ORIN.get(men["orin"], BALL_YAXSHI if men["togri"] >= YAXSHI else 0) if men["togri"] > 0 else 0
            # oxirgi savolning javobi yana bir oz ko'rinib turadi
            if t["savol"] > 0 and now < (t["tugadi"] or 0) + NATIJA_T:
                javob["question"] = savol_matni(t["savol"] - 1, True)
            return javob
        n = t["savol"]
        bosh = _savol_vaqti(hafta, n)
        if now < bosh:                           # oldingi savolning natijasi ko'rsatilmoqda
            javob["phase"] = "natija"
            javob["question"] = savol_matni(n - 1, True)
            javob["next_in"] = int(bosh - now) + 1
        else:
            javob["phase"] = "savol"
            javob["question"] = savol_matni(n, False)
            javob["left"] = max(0, round(bosh + SAVOL_T - now, 1))
        return javob
    finally:
        conn.close()


async def api_viktorina(request):
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
        await tick()                             # AVVAL holat hozirgi vaqtga keltiriladi (yangi savol ochilgan bo'lishi mumkin), keyin javob yoziladi
    except Exception as e:
        logging.error("Viktorina tick: %s", e)
    if body.get("join") is not None:
        qosh["join_ok"] = await asyncio.to_thread(_yozil, uid, bool(body.get("join")))
    elif body.get("answer") is not None:
        try:
            qosh["answer_ok"] = await asyncio.to_thread(_javob, uid, int(body.get("q")), int(body.get("answer")))
        except (TypeError, ValueError):
            qosh["answer_ok"] = False
    lang = body.get("lang") if body.get("lang") in ("uz", "ru", "en") else "uz"
    javob = await asyncio.to_thread(_holat, uid, lang)
    javob.update(qosh)
    if javob.get("phase") == "tugadi" and javob["me"].get("place") and _cfg.get("log") and body.get("log_end"):
        try:
            await _cfg["log"](user, "viktorina_%d" % javob["me"]["place"])
        except Exception:
            pass
    return cors(web.json_response(javob))


def register(app, cfg):
    """cfg: verify_init_data, cors, log, xat, elon. hpdars DAN KEYIN ulanadi."""
    global _qulf
    _cfg.update(cfg)
    _qulf = asyncio.Lock()
    _init()
    app.router.add_route("*", "/api/viktorina", api_viktorina)
    logging.info("Viktorina ulandi: %d savol havzada", len(hpdars.bell_savollar()))
