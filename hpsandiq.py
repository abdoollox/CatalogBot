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


def kun_topshiriqlari(kun):
    """Shu kunning 6 ta topshirig'i (hammaga bir xil)."""
    r = random.Random("sandiq:" + kun)
    return ["daily"] + sorted(r.sample(HAVZA, 5), key=HAVZA.index)


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
    tasks = kun_topshiriqlari(kun)
    streak = _streak(conn, uid, kun)
    ochildi = bool(row and row["ochildi"])
    n = len([t for t in tasks if t in done])
    return {
        "ok": True, "kun": kun,
        "tasks": [{"code": t, "done": t in done} for t in tasks],
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
        tasks = kun_topshiriqlari(kun)
        bosqich = row["bosqich"]

        # Kunlik savolni server o'zi ko'radi - ilova aytmasa ham
        if "daily" not in done and _daily_bajarildi(conn, uid, kun):
            done.append("daily")
        if task and task in tasks and task not in done and task != "daily":
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
    task = task if isinstance(task, str) and task in HAVZA + ("daily",) else None
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
    logging.info("Kunlik sandiq: havzada %d topshiriq", len(HAVZA) + 1)
