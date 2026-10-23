"""Kunlik sandiq (egasi, 2026-10-05): har kuni 6 ta topshiriq, bosqichli mukofot, ketma-ketlik.

Namuna - "Castle Busters" o'yinidagi kunlik sovg'a. Faqat SARALANGAN o'quvchilarga.

  6 ta topshiriqning HAMMASI bajarilganda sandiq ochiladi (odam o'zi bosadi): +10 ball va 1 galleon.
  Ungacha hech qanday ball berilmaydi (egasi, 2026-10-05: oraliq mukofot yo'q).
  7 kun ketma-ket -> katta sandiq: qo'shimcha +3 galleon (har 7-kunda)

Topshiriqlar hammaga bir xil: kunlik savol har doim, qolgan 5 tasi shu kun uchun havzadan
tanlanadi (sana bo'yicha - qayta ishga tushsa ham o'zgarmaydi). Kunlik savolni server o'zi
tekshiradi; qolganlarini ilova xabar qiladi (kichik mukofot - soxtalashtirishga arzimaydi).
Kun - Toshkent vaqti bilan. Ballar kubokka 'sandiq' manbasi bo'lib yoziladi.

API: /api/sandiq
  {}             -> holat
  {task: "chat"} -> topshiriq bajarildi (bugungi ro'yxatda bo'lsa)
  {open: true}   -> sandiqni ochish (6 ta bajarilgan bo'lsa)
"""

import asyncio
import datetime as _dt
import hashlib
import json
import os
import logging
import random
import sqlite3
from datetime import timedelta

from aiohttp import web

import hpcup

_cfg = {}

# --- Shokolad qurbaqa kartochkalari (egasi, 2026-10-05) ---
# Sandiq o'rnida: 6 ta topshiriq bajarilganda quti ochiladi va SHU KUNNING kartochkasi beriladi
# (hammaga bir xil; o'tkazib yuborilsa keyingi aylanada yana keladi). Kolleksiya - `qurbaqa` jadvali.
KARTALAR = ("dumbledore", "merlin", "morgana", "flamel",
            "gryffindor", "slytherin", "ravenclaw", "hufflepuff",
            "circe", "paracelsus", "agrippa", "ptolemy",
            "cliodna", "hengist", "grunnion", "scamander",
            "bott", "wright", "gregory", "uric",
            "gwenog", "wildsmith", "whitehorn", "potter")
KARTA_BOSHI = (2026, 10, 5)         # birinchi kartochka kuni


def kun_kartasi(kun):
    """Shu kunning kartochkasi. Har aylana (24 kun) o'z tartibida, takrorsiz."""
    y, m, d = (int(x) for x in kun.split("-"))
    n = (_dt.date(y, m, d) - _dt.date(*KARTA_BOSHI)).days
    if n < 0:
        n = 0
    # Tartib SIR (egasi, 2026-10-05): ertaga kim chiqishini hech kim bilmasin. Repo ochiq, shuning uchun
    # urug'ga serverdagi maxfiy qiymat (bot tokeni) qo'shiladi - koddan hisoblab bo'lmaydi.
    sir = hashlib.sha256(("qurbaqa|" + os.getenv("BOT_TOKEN", "")).encode()).hexdigest()
    tartib = random.Random("%s:%d" % (sir, n // len(KARTALAR))).sample(KARTALAR, len(KARTALAR))
    return tartib[n % len(KARTALAR)]


HAVZA = ("chat", "music", "chess", "owl", "cup", "share", "house")   # "daily" har doim bor
BOSQICH = ()                        # oraliq mukofot yo'q (ilgari: 2 va 4 topshiriqda +5 ball)
SANDIQ_BALL = 10
SANDIQ_GALLEON = 1
KATTA_HAR = 7                       # har 7-kun ketma-ket
KATTA_GALLEON = 3


def _init():
    conn = hpcup._connect()
    try:
        conn.execute(
            "CREATE TABLE IF NOT EXISTS sandiq ("
            " user_id INTEGER NOT NULL, kun TEXT NOT NULL,"
            " done TEXT NOT NULL DEFAULT '[]',"       # bajarilgan topshiriq kodlari (JSON)
            " bosqich INTEGER NOT NULL DEFAULT 0,"    # nechta oraliq mukofot berilgan (0..2)
            " ochildi TEXT,"                          # sandiq ochilgan vaqt (UTC ISO)
            " PRIMARY KEY (user_id, kun))")
        conn.execute(
            "CREATE TABLE IF NOT EXISTS qurbaqa ("
            " user_id INTEGER NOT NULL, card TEXT NOT NULL, soni INTEGER NOT NULL DEFAULT 1,"
            " vaqt TEXT NOT NULL, PRIMARY KEY (user_id, card))")
        conn.commit()
    finally:
        conn.close()


# --- YANGI RO'YXAT (egasi, 2026-10-11: «hozirgilari juda oddiy bo'lib qoldi») ---
# Har kuni 2 ta YENGIL + 3 ta O'RTACHA + 1 ta QIYIN vazifa; «sahifani och» turidagilar olib tashlandi.
# Sehrgarlik tarixi bellashuvi endi majburiy emas - boshqalar qatorida (bell3 ichida) navbat bilan.
YANGI_DAN = "2026-10-12"            # shu kundan yangi ro'yxat (oldingi kunlar eski ro'yxatda qoladi)
OSON = ("parvarish", "chat", "share")
ORTA = ("dars", "bell3", "duel", "chess", "rek", "kitob")
QIYIN = ("duel_yut", "bell_top", "alo", "rek_yangi")
# «O'z rekordingizni yangilang» juda qiyin - o'quvchilar so'radi (chat, 2026-10-23); shu kundan qiyin vazifalar
# havzasida yo'q (oldingi kunlar o'zgarmasin - bugungi ro'yxat hammaga allaqachon chiqqan)
REK_YOQ_DAN = "2026-10-25"
QIYIN2 = tuple(x for x in QIYIN if x != "rek_yangi")
# Bularni SERVER o'zi ko'radi (ilova aytgani bilan sanalmaydi); qolganlarini ilova xabar qiladi
SERVERDA = ("parvarish", "bell3", "bell_top", "duel", "duel_yut")
BELL_SONI = 3                       # «bell3»: nechta fanda bellashuvda qatnashish kerak
HAMMASI = tuple(dict.fromkeys(HAVZA + ("daily",) + OSON + ORTA + QIYIN))
# BIRINCHI KUN (egasi, 2026-10-11): yangi o'quvchiga birinchi qutisini ochguncha ENG SODDA vazifalar - 2-kursda hammasi ochiq
# joylar (Do'stlar 4-kursdan, Issiqxona/Qo'riqxona 3-kursdan - shuning uchun «share» va «parvarish» yo'q). Ilova har birini
# yo'riqnoma bilan bajartiradi (js/09-yoriqnoma.js). Quti ochilgan kunning oxirigacha shu ro'yxat, ertasiga - odatdagi.
BIRINCHI = ("daily", "chat", "dars", "kitob", "music", "house")


def kun_topshiriqlari(kun):
    """Shu kunning 6 ta topshirig'i (hammaga bir xil)."""
    if kun < YANGI_DAN:
        r = random.Random("sandiq:" + kun)
        return ["daily"] + sorted(r.sample(HAVZA, 5), key=HAVZA.index)
    r = random.Random("qurbaqa2:" + kun)
    return r.sample(OSON, 2) + r.sample(ORTA, 3) + r.sample(QIYIN if kun < REK_YOQ_DAN else QIYIN2, 1)


def _bor(conn, sql, args):
    try:
        return conn.execute(sql, args).fetchone() is not None
    except sqlite3.OperationalError:
        return False


def _topshiriqlar(conn, uid, kun):
    """O'quvchining bugungi ro'yxati. «Parvarish» faqat o'simligi yoki maxluqi borlarga: ikkalasi ham yo'q odamga
    uning o'rniga shu kuni tushmagan uchinchi yengil vazifa beriladi."""
    if _birinchi_kun(conn, uid, kun):
        return list(BIRINCHI)
    tasks = kun_topshiriqlari(kun)
    if "parvarish" in tasks and not (_bor(conn, "SELECT 1 FROM issiq WHERE user_id=? LIMIT 1", (uid,))
                                     or _bor(conn, "SELECT 1 FROM qoriq WHERE user_id=? LIMIT 1", (uid,))):
        zaxira = [t for t in OSON if t not in tasks]
        if zaxira:
            tasks[tasks.index("parvarish")] = zaxira[0]
    return tasks


def _birinchi_kun(conn, uid, kun):
    """Kurslar joriy qilingandan keyin saralangan (yoki sinov) o'quvchi hali birorta kun qutisini ochmagan bo'lsa."""
    import hpdars                                    # hpdars hpcup ga tayanadi - shu yerda
    if int(uid) > 0:
        u = conn.execute("SELECT sorted_at FROM users WHERE user_id=?", (int(uid),)).fetchone()
        if not u or (u["sorted_at"] or "") < hpdars.KURS_ESKI:
            return False
    return not _bor(conn, "SELECT 1 FROM sandiq WHERE user_id=? AND ochildi IS NOT NULL AND kun<?", (int(uid), kun))


def _serverda_bajarildi(conn, uid, kun, kod):
    """SERVERDA ro'yxatidagi vazifa bajarilganmi (bazadagi izlardan)."""
    if kod == "parvarish":
        return (_bor(conn, "SELECT 1 FROM issiq WHERE user_id=? AND oxirgi=? LIMIT 1", (uid, kun))
                or _bor(conn, "SELECT 1 FROM qoriq WHERE user_id=? AND oxirgi=? LIMIT 1", (uid, kun)))
    if kod == "bell3":
        try:
            n = conn.execute("SELECT COUNT(DISTINCT dars) FROM dars_bellashuv WHERE user_id=? AND kun=? AND ms IS NOT NULL", (uid, kun)).fetchone()[0]
        except sqlite3.OperationalError:
            n = 0
        return n >= BELL_SONI
    if kod == "bell_top":
        # hozir biror fanning bugungi jadvalida birinchi o'ntalikda (kun davomida o'rin o'zgarishi mumkin - bir marta kirgani yetarli)
        try:
            rows = conn.execute("SELECT dars, ms, vaqt FROM dars_bellashuv WHERE user_id=? AND kun=? AND ms IS NOT NULL", (uid, kun)).fetchall()
            for r in rows:
                oldinda = conn.execute(
                    "SELECT COUNT(*) FROM dars_bellashuv b JOIN users u ON u.user_id = b.user_id WHERE b.kun=? AND b.dars=? AND b.ms IS NOT NULL "
                    "AND u.house IS NOT NULL AND b.user_id > 0 AND b.user_id<>? AND (b.ms < ? OR (b.ms = ? AND b.vaqt < ?))",
                    (kun, r["dars"], uid, r["ms"], r["ms"], r["vaqt"])).fetchone()[0]
                if oldinda < 10:
                    return True
        except sqlite3.OperationalError:
            pass
        return False
    if kod in ("duel", "duel_yut"):
        bosh = _kun_boshi_utc(kun)
        holat = "('yutdi')" if kod == "duel_yut" else "('yutdi','yutqazdi')"
        if _bor(conn, "SELECT 1 FROM duel_oyin WHERE user_id=? AND holat IN %s AND vaqt >= ? LIMIT 1" % holat, (uid, bosh)):
            return True
        # jonli duel (turnir yoki do'stona): bugun boshlangan va haqiqatan o'ynalgan
        y, m, d = (int(x) for x in kun.split("-"))
        t0 = hpcup.now_tk().replace(year=y, month=m, day=d, hour=0, minute=0, second=0, microsecond=0).timestamp()
        shart = "golib=?" if kod == "duel_yut" else "(a=? OR b=?)"
        arg = (uid,) if kod == "duel_yut" else (uid, uid)
        return _bor(conn, "SELECT 1 FROM duel_match WHERE %s AND holat='tugadi' AND sabab IN ('duel','vaqt') AND bosh >= ? AND bosh < ? "
                          "AND hafta NOT LIKE 'sinov%%' LIMIT 1" % shart, arg + (t0, t0 + 86400))
    return False


def _kun_boshi_utc(kun):
    """Toshkent kunining boshlanishi, UTC ISO."""
    t = hpcup.now_tk().replace(hour=0, minute=0, second=0, microsecond=0)
    y, m, d = (int(x) for x in kun.split("-"))
    return hpcup._utc_iso(t.replace(year=y, month=m, day=d))


def _daily_bajarildi(conn, uid, kun):
    """Kunning birinchi (doimiy) topshirig'i bajarilganmi.

    Egasi, 2026-10-07: kunlik savol olib tashlandi - o'rniga SEHRGARLIK TARIXI BELLASHUVIda qatnashish
    (hpdars: dars_bellashuv, natijasi bor). Topshiriq kodi "daily" bo'lib qoldi (ilova va jadval shu nomni biladi).
    Eski yo'l (kunlik savolga javob) ham hisobga olinadi: ilovaning eski nusxasi ochiq qolgan odamlar uchun."""
    try:
        r = conn.execute(
            "SELECT 1 FROM dars_bellashuv WHERE user_id=? AND kun=? AND dars='tarix' AND ms IS NOT NULL LIMIT 1",
            (uid, kun)).fetchone()
        if r:
            return True
    except sqlite3.OperationalError:
        pass
    try:
        r = conn.execute(
            "SELECT 1 FROM answers a JOIN questions q ON q.id = a.question_id "
            "WHERE a.user_id=? AND q.kind='daily' AND a.answered_at >= ? LIMIT 1",
            (uid, _kun_boshi_utc(kun))).fetchone()
        return bool(r)
    except sqlite3.OperationalError:
        return False


def _streak(conn, uid, kun):
    """Ketma-ket ochilgan kunlar soni: bugun ochilgan bo'lsa bugundan, bo'lmasa kechadan orqaga."""
    ochilgan = {r[0] for r in conn.execute(
        "SELECT kun FROM sandiq WHERE user_id=? AND ochildi IS NOT NULL", (uid,))}
    t = hpcup.now_tk()
    y, m, d = (int(x) for x in kun.split("-"))
    t = t.replace(year=y, month=m, day=d)
    if kun not in ochilgan:
        t -= timedelta(days=1)
    n = 0
    while t.strftime("%Y-%m-%d") in ochilgan:
        n += 1
        t -= timedelta(days=1)
    return n


def _holat(conn, uid, kun, mukofot=None):
    row = conn.execute("SELECT done, bosqich, ochildi FROM sandiq WHERE user_id=? AND kun=?", (uid, kun)).fetchone()
    done = json.loads(row["done"]) if row else []
    tasks = _topshiriqlar(conn, uid, kun)
    bir = tasks == list(BIRINCHI)
    streak = _streak(conn, uid, kun)
    ochildi = bool(row and row["ochildi"])
    n = len([t for t in tasks if t in done])
    return {
        "ok": True, "kun": kun, "first": bir,
        "tasks": [{"code": t, "done": t in done, "tier": 1 if bir or t in OSON else 3 if t in QIYIN else 2} for t in tasks],
        "bell_need": BELL_SONI,
        "n": n, "total": len(tasks),
        "opened": ochildi, "can_open": n >= len(tasks) and not ochildi,
        "streak": streak,
        # Bugun ochilsa katta sandiq bo'ladimi (7-, 14-... kun)
        "big": (not ochildi) and (streak + 1) % KATTA_HAR == 0,
        "prizes": {"steps": [list(b) for b in BOSQICH], "ball": SANDIQ_BALL, "gal": SANDIQ_GALLEON,
                   "big_every": KATTA_HAR, "big_gal": KATTA_GALLEON},
        # Bugungi kartochka SIR: faqat quti ochilgandan keyin aytiladi
        "card": kun_kartasi(kun) if ochildi else None,
        "cards": {r[0]: r[1] for r in conn.execute("SELECT card, soni FROM qurbaqa WHERE user_id=?", (uid,))},
        "cards_total": len(KARTALAR),
        "reward": mukofot,
    }


def _ish(uid, task=None, ochish=False):
    """Bitta tranzaksiyada: topshiriqni belgilash / sandiqni ochish. Holatni qaytaradi."""
    uid = int(uid)
    kun = hpcup.today_tk()
    conn = hpcup._connect()
    mukofot = None
    ball = []                       # [(ref, pts)] - tranzaksiyadan keyin yoziladi
    try:
        if not hpcup._get_house(uid):
            return {"ok": False, "error": "no_house"}
        conn.execute("INSERT OR IGNORE INTO sandiq (user_id, kun) VALUES (?,?)", (uid, kun))
        row = conn.execute("SELECT done, bosqich, ochildi FROM sandiq WHERE user_id=? AND kun=?", (uid, kun)).fetchone()
        done = json.loads(row["done"])
        tasks = _topshiriqlar(conn, uid, kun)
        bosqich = row["bosqich"]

        # Kunlik savolni server o'zi ko'radi - ilova aytmasa ham
        if "daily" in tasks and "daily" not in done and _daily_bajarildi(conn, uid, kun):
            done.append("daily")
        for t in tasks:                              # server o'zi ko'radigan vazifalar
            if t in SERVERDA and t not in done and _serverda_bajarildi(conn, uid, kun, t):
                done.append(t)
        if task and task in tasks and task not in done and task != "daily" and task not in SERVERDA:
            done.append(task)
        n = len([t for t in tasks if t in done])
        while bosqich < len(BOSQICH) and n >= BOSQICH[bosqich][0]:
            ball.append(("%s:%d" % (kun, BOSQICH[bosqich][0]), BOSQICH[bosqich][1]))
            bosqich += 1
        conn.execute("UPDATE sandiq SET done=?, bosqich=? WHERE user_id=? AND kun=?",
                     (json.dumps(done), bosqich, uid, kun))
        if ball:
            mukofot = {"ball": sum(p for _, p in ball)}

        if ochish and n >= len(tasks) and not row["ochildi"]:
            # Shart so'rovning o'zida: ikki marta bosilsa ham bir marta ochiladi
            cur = conn.execute("UPDATE sandiq SET ochildi=? WHERE user_id=? AND kun=? AND ochildi IS NULL",
                               (hpcup._utc_iso(hpcup.now_tk()), uid, kun))
            if cur.rowcount > 0:
                streak = _streak(conn, uid, kun)
                gal = SANDIQ_GALLEON + (KATTA_GALLEON if streak % KATTA_HAR == 0 else 0)
                conn.execute("UPDATE users SET galleons = galleons + ? WHERE user_id=?", (gal, uid))
                ball.append((kun + ":sandiq", SANDIQ_BALL))
                karta = kun_kartasi(kun)
                yangi = not conn.execute("SELECT 1 FROM qurbaqa WHERE user_id=? AND card=?", (uid, karta)).fetchone()
                if yangi:
                    conn.execute("INSERT INTO qurbaqa (user_id, card, soni, vaqt) VALUES (?,?,1,?)",
                                 (uid, karta, hpcup._utc_iso(hpcup.now_tk())))
                else:
                    conn.execute("UPDATE qurbaqa SET soni = soni + 1 WHERE user_id=? AND card=?", (uid, karta))
                mukofot = {"ball": SANDIQ_BALL, "gal": gal, "big": streak % KATTA_HAR == 0, "streak": streak,
                           "opened": True, "card": karta, "card_new": yangi}
        conn.commit()
    finally:
        conn.close()

    for ref, pts in ball:
        hpcup._award(uid, "sandiq", ref, pts)

    conn = hpcup._connect()
    try:
        return _holat(conn, uid, kun, mukofot)
    finally:
        conn.close()


async def api_sandiq(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    body = {}
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            return cors(web.json_response({"ok": False, "error": "bad_json"}, status=400))
    user = _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", "")
                                    or str(body.get("initData", "")))
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
    task = body.get("task")
    task = task if isinstance(task, str) and task in HAMMASI else None
    try:
        res = await asyncio.to_thread(_ish, int(user["id"]), task, bool(body.get("open")))
    except Exception as e:
        logging.error("Sandiq xatosi (%s): %s", user.get("id"), e)
        return cors(web.json_response({"ok": False, "error": "server"}, status=500))
    if res.get("reward") and res["reward"].get("opened") and _cfg.get("log"):
        try:
            await _cfg["log"](user, "sandiq_katta" if res["reward"].get("big") else "sandiq")
        except Exception as e:
            logging.error("Sandiq logi yozilmadi: %s", e)
    return cors(web.json_response(res))


def register(app, cfg):
    """cfg: verify_init_data, cors, log."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/sandiq", api_sandiq)
    logging.info("Shokolad qurbaqa: %d yengil, %d o'rtacha, %d qiyin vazifa", len(OSON), len(ORTA), len(QIYIN))
