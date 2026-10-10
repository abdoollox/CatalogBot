"""Shaxmat turniri — duel turniri bilan bir xil mexanizm (egasi, 2026-10-11).

Haftada bir marta, CHORSHANBA 21:00 (Toshkent), bir oqshomda tugaydi:
  - saralash yo'q: «Qatnashaman» tugmasini bosgan har bir saralangan o'quvchi o'ynaydi;
    yozilish turnirdan YOPILISH soniya oldin yopiladi va to'r tuziladi;
  - istalgan sondagi ishtirokchi: to'r eng yaqin 2 ning darajasiga to'ldiriladi, shaxmat reytingi
    yuqorilar birinchi bosqichni o'tkazib yuboradi (raqibi yo'q - «bye»);
  - har uchrashuv - oddiy jonli shaxmat o'yini (hpchess), har o'yinchiga 5 daqiqa; o'yinni SERVER o'zi ochadi.
    To'rda yuqori turgan (reytingi baland) oq donalar bilan o'ynaydi; DURANG bo'lsa qora donalar bilan
    o'ynagan keyingi bosqichga o'tadi (oqning ustunligi uchun tovon - «armageddon» qoidasi);
  - birinchi yurishini 60 soniyada qilmagan o'yinchi (kelmagan) yutqazadi;
  - keyingi bosqich o'yini ikkala raqib aniqlangach ORALIQ soniyadan keyin boshlanadi (qat'iy jadval yo'q -
    hech kim behuda kutmaydi);
  - ball (kubokka, darhol): g'alaba uchun 1/8 finalda +5, chorakda +10, yarim finalda +20, finalda +30.

So'rovlar - POST /api/chess/turnir: {} holat, {join: 1|0} yozilish/chiqish.
Hafta kaliti - NAVBATDAGI turnir haftasining dushanbasi: turnir tugagach (boshlanganidan TUGASH soniya o'tib)
keyingi haftaga yozilish darhol ochiladi.
"""

import asyncio
import logging
import time
from datetime import datetime, timedelta

from aiohttp import web

import hpchess
import hpcup
import hpdars

BOSH_HAFTA = "2026-10-12"     # birinchi turnir shu haftada (chorshanba 14-oktabr)
TURNIR_KUN = 2                # chorshanba (dushanba = 0)
SOAT = 21
YOPILISH = 300                # yozilish turnirdan shuncha soniya oldin yopiladi
ORALIQ = 60                   # ikkala raqib aniqlangach o'yin shuncha soniyadan keyin boshlanadi
TUGASH = 3 * 3600             # turnir boshlanganidan shuncha o'tgach keyingi haftaga yozilish ochiladi
BASE, INC = 300, 0            # har o'yinchiga 5 daqiqa
BOSQICH_BALL = {16: 5, 8: 10, 4: 20, 2: 30}
BOSQICH_T = 12 * 60 + ORALIQ  # bosqichning TAXMINIY davomiyligi (to'rda ko'rsatish uchun)

_cfg = {}


def _now():
    return hpcup.now_tk()


def _ep():
    return _now().timestamp()


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS sh_turnir (hafta TEXT PRIMARY KEY, hajm INTEGER NOT NULL DEFAULT 0, vaqt TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS sh_match ("
                     " id INTEGER PRIMARY KEY AUTOINCREMENT, hafta TEXT NOT NULL, bosqich INTEGER NOT NULL, joy INTEGER NOT NULL,"
                     " a INTEGER, b INTEGER, a_seed INTEGER, b_seed INTEGER, bosh REAL, holat TEXT NOT NULL DEFAULT 'kutmoqda',"
                     " golib INTEGER, sabab TEXT, game TEXT, UNIQUE (hafta, bosqich, joy))")
        conn.execute("CREATE TABLE IF NOT EXISTS sh_qatnash (hafta TEXT NOT NULL, user_id INTEGER NOT NULL, vaqt TEXT NOT NULL,"
                     " PRIMARY KEY (hafta, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS sh_eslatma (hafta TEXT NOT NULL, tur TEXT NOT NULL, PRIMARY KEY (hafta, tur))")
        conn.commit()
    finally:
        conn.close()


def _tartib(n):
    """To'rdagi o'rinlar tartibi: 1 va 2 faqat finalda uchrashadi. _tartib(8) = [1, 8, 4, 5, 2, 7, 3, 6]."""
    t = [1, 2]
    while len(t) < n:
        m = len(t) * 2 + 1
        t = [x for s in t for x in (s, m - s)]
    return t


def _turnir_vaqti(hafta):
    y, m, d = (int(x) for x in hafta.split("-"))
    return (datetime(y, m, d, SOAT, 0, 0, tzinfo=_now().tzinfo) + timedelta(days=TURNIR_KUN)).timestamp()


def _hafta():
    """Navbatdagi (yoki hozir ketayotgan) turnir haftasi."""
    h = max(hpdars._hafta(), BOSH_HAFTA)
    if _ep() >= _turnir_vaqti(h) + TUGASH:
        y, m, d = (int(x) for x in h.split("-"))
        h = (datetime(y, m, d) + timedelta(days=7)).strftime("%Y-%m-%d")
    return h


def _qatnashchilar(conn, hafta):
    """Yozilganlar - shaxmat REYTINGI bo'yicha (yuqoridan), teng bo'lsa ko'proq o'ynagan, keyin oldin yozilgan."""
    return conn.execute(
        "SELECT q.user_id, COALESCE(r.rating, ?) AS reyting, COALESCE(r.games, 0) AS oyin, q.vaqt, COALESCE(u.first_name, 'Sehrgar') AS name, u.house "
        "FROM sh_qatnash q JOIN users u ON u.user_id = q.user_id LEFT JOIN chess_ratings r ON r.user_id = q.user_id "
        "WHERE q.hafta=? AND u.house IS NOT NULL AND q.user_id > 0 ORDER BY reyting DESC, oyin DESC, q.vaqt ASC",
        (hpchess.RATING_START, hafta)).fetchall()


def _tugat(conn, m, golib, sabab, berish, now):
    """Uchrashuvni yopadi, ball ro'yxatiga qo'shadi va g'olibni keyingi bosqichga o'tkazadi."""
    conn.execute("UPDATE sh_match SET holat='tugadi', golib=?, sabab=? WHERE id=?", (golib, sabab, m["id"]))
    if sabab != "bye":
        berish.append((golib, "shaxmat:%s:%d" % (m["hafta"], m["bosqich"]), BOSQICH_BALL.get(m["bosqich"], 0)))
    nb = m["bosqich"] // 2
    if nb < 2:
        return
    yon = "a" if m["joy"] % 2 == 0 else "b"
    seed = m["a_seed"] if golib == m["a"] else m["b_seed"]
    conn.execute("UPDATE sh_match SET %s=?, %s_seed=? WHERE hafta=? AND bosqich=? AND joy=?" % (yon, yon),
                 (golib, seed, m["hafta"], nb, m["joy"] // 2))
    k = conn.execute("SELECT * FROM sh_match WHERE hafta=? AND bosqich=? AND joy=?", (m["hafta"], nb, m["joy"] // 2)).fetchone()
    if k["a"] is not None and k["b"] is not None and k["bosh"] is None:
        # ikkala raqib aniq: o'yin bir daqiqadan keyin (lekin turnir boshlanishidan oldin emas)
        conn.execute("UPDATE sh_match SET bosh=? WHERE id=?", (max(_turnir_vaqti(m["hafta"]), now + ORALIQ), k["id"]))


def _tor_tuz(conn, hafta, berish, now):
    """Turnirdan YOPILISH soniya oldin bir marta: yozilganlardan to'r."""
    if now < _turnir_vaqti(hafta) - YOPILISH:
        return
    cur = conn.execute("INSERT OR IGNORE INTO sh_turnir (hafta, hajm, vaqt) VALUES (?,0,?)", (hafta, hpcup._utc_iso(_now())))
    if cur.rowcount < 1:
        return
    rows = _qatnashchilar(conn, hafta)
    n = len(rows)
    if n < 2:
        return
    hajm = 2
    while hajm < n:
        hajm *= 2
    conn.execute("UPDATE sh_turnir SET hajm=? WHERE hafta=?", (hajm, hafta))
    s = hajm
    while s >= 2:
        for i in range(s // 2):
            conn.execute("INSERT INTO sh_match (hafta, bosqich, joy) VALUES (?,?,?)", (hafta, s, i))
        s //= 2
    t, T0 = _tartib(hajm), _turnir_vaqti(hafta)
    for i in range(hajm // 2):
        a, b = t[2 * i], t[2 * i + 1]
        conn.execute("UPDATE sh_match SET a=?, a_seed=?, b=?, b_seed=?, bosh=? WHERE hafta=? AND bosqich=? AND joy=?",
                     (rows[a - 1]["user_id"], a, rows[b - 1]["user_id"] if b <= n else None, b if b <= n else None, T0, hafta, hajm, i))
        if b > n:
            m = conn.execute("SELECT * FROM sh_match WHERE hafta=? AND bosqich=? AND joy=?", (hafta, hajm, i)).fetchone()
            _tugat(conn, m, m["a"], "bye", berish, now)


def _natija(conn, m, g):
    """Tugagan shaxmat o'yinidan uchrashuv g'olibi: (uid, sabab) yoki None (o'yin hali ketmoqda)."""
    if g is None:
        return m["a"], "ikkalasi"                 # o'yin yozuvi yo'qolgan - to'rda yuqori turgan o'tadi
    if g["status"] == "finished":
        if g["winner_uid"] in (m["a"], m["b"]):
            return g["winner_uid"], ("vaqt" if g["win_reason"] == "timeout" else "oyin")
        return m["b"], "durang"                   # durang: qora bilan o'ynagan (b) o'tadi
    if g["status"] == "aborted":
        yurish = len((g["moves"] or "").split())
        if yurish >= 1:
            return m["a"], "kelmadi"              # qora birinchi yurishini qilmadi
        korindi = hpchess._seen.get((g["id"], m["b"]))
        return (m["b"], "kelmadi") if korindi else (m["a"], "ikkalasi")
    return None


def _eslatmalar(conn, hafta, xabarlar):
    """Turnir kuni yozilganlarga: ertalab 10:00 va boshlanishiga 10 daqiqa qolganda."""
    hozir = _now()
    T0 = _turnir_vaqti(hafta)
    if hozir.weekday() != TURNIR_KUN or hozir.timestamp() >= T0:
        return
    daq = hozir.hour * 60 + hozir.minute
    tur = "on" if SOAT * 60 - 10 <= daq < SOAT * 60 else "ertalab" if 600 <= daq < SOAT * 60 - 10 else None
    if not tur:
        return
    if conn.execute("INSERT OR IGNORE INTO sh_eslatma (hafta, tur) VALUES (?,?)", (hafta, tur)).rowcount < 1:
        return
    if tur == "ertalab" and hafta == BOSH_HAFTA:
        # BIRINCHI turnir (egasi, 2026-10-11): ertalab HAMMA saralanganlarga e'lon - yozilganlarga alohida eslatma kerak emas
        xabarlar.append((0, "elon"))
        return
    for r in conn.execute("SELECT user_id FROM sh_qatnash WHERE hafta=?", (hafta,)).fetchall():
        xabarlar.append((r["user_id"], tur))


def _tick():
    """Turnirni hozirgi vaqtga keltiradi. Qaytaradi: (ballar, xatlar, boshlanadigan uchrashuvlar)."""
    berish, xabarlar, boshla = [], [], []
    hafta, now = _hafta(), _ep()
    conn = hpcup._connect()
    try:
        _tor_tuz(conn, hafta, berish, now)
        for m in conn.execute("SELECT * FROM sh_match WHERE holat='ketmoqda'").fetchall():
            g = conn.execute("SELECT * FROM chess_games WHERE id=?", (m["game"],)).fetchone()
            r = _natija(conn, m, g)
            if r:
                _tugat(conn, m, r[0], r[1], berish, now)
        for m in conn.execute("SELECT * FROM sh_match WHERE holat='kutmoqda' AND a IS NOT NULL AND b IS NOT NULL AND game IS NULL "
                              "AND bosh IS NOT NULL AND bosh<=?", (now,)).fetchall():
            boshla.append((m["id"], m["a"], m["b"]))
        _eslatmalar(conn, hafta, xabarlar)
        conn.commit()
    finally:
        conn.close()
    return berish, xabarlar, boshla


def _boshqa_oyinlar(uid):
    """Turnir o'yini boshlanishidan oldin: o'quvchining boshqa (oddiy) jonli o'yini bo'lsa bekor qilinadi."""
    now = time.time()
    conn = hpcup._connect()
    try:
        rows = conn.execute("SELECT * FROM chess_games WHERE v=2 AND status='active' AND (white_uid=? OR black_uid=?)", (uid, uid)).fetchall()
        changed = [hpchess._finish(conn, r, None, "turnir", now, aborted=True) for r in rows]
        conn.commit()
        return changed
    finally:
        conn.close()


def _oyin_yoz(mid, gid):
    conn = hpcup._connect()
    try:
        conn.execute("UPDATE sh_match SET game=?, holat='ketmoqda' WHERE id=? AND game IS NULL", (gid, int(mid)))
        conn.commit()
    finally:
        conn.close()


def xat_matni(tur):
    if tur == "elon":
        return {"uz": ("Bugun 21:00 da birinchi shaxmat turniri!", "Xogvartsda birinchi shaxmat turniri bugun soat 21:00 da o'tadi. Qatnashish uchun ilovada Xogvarts → Shaxmat sahifasiga kiring va «Qatnashaman» tugmasini bosing. Har o'yinchiga 5 daqiqa, g'alabalar fakultetingizga ball olib keladi. Yozilish 20:55 da yopiladi."),
                "ru": ("Сегодня в 21:00 первый шахматный турнир!", "Первый шахматный турнир Хогвартса пройдёт сегодня в 21:00 (время Ташкента). Чтобы участвовать, откройте Хогвартс → Шахматы и нажмите «Участвую». Каждому игроку 5 минут, победы приносят очки факультету. Запись закрывается в 20:55."),
                "en": ("The first chess tournament is today at 21:00!", "Hogwarts holds its first chess tournament today at 21:00 (Tashkent time). To take part, open Hogwarts → Chess in the app and tap “I'm in”. Each player has 5 minutes and wins earn points for your House. Sign-up closes at 20:55.")}
    if tur == "ertalab":
        return {"uz": ("Bugun 21:00 da shaxmat turniri", "Siz turnirga yozilgansiz. Soat 21:00 da ilovaga kiring: Xogvarts → Shaxmat. Birinchi yurishini 1 daqiqada qilmagan o'yinchi yutqazadi."),
                "ru": ("Сегодня в 21:00 шахматный турнир", "Вы записаны на турнир. Зайдите в 21:00: Хогвартс → Шахматы. Кто не сделает первый ход за 1 минуту — проигрывает."),
                "en": ("The chess tournament is today at 21:00", "You are signed up. Come in at 21:00: Hogwarts → Chess. Anyone who does not make their first move within a minute loses.")}
    return {"uz": ("Turnirga 10 daqiqa qoldi!", "Shaxmat turniri 21:00 da boshlanadi. Hoziroq ilovaga kiring: Xogvarts → Shaxmat."),
            "ru": ("До турнира 10 минут!", "Шахматный турнир начнётся в 21:00. Зайдите прямо сейчас: Хогвартс → Шахматы."),
            "en": ("10 minutes to the tournament!", "The chess tournament starts at 21:00. Come in now: Hogwarts → Chess.")}


_qulf = asyncio.Lock() if hasattr(asyncio, "Lock") else None


async def tick():
    async with _qulf:
        berish, xabarlar, boshla = await asyncio.to_thread(_tick)
        for mid, a, b in boshla:
            try:
                for u in (a, b):
                    await hpchess._after(await asyncio.to_thread(_boshqa_oyinlar, u))
                res, changed = await asyncio.to_thread(hpchess._match, a, b, {}, BASE, INC)
                await hpchess._after(changed)
                if res.get("ok"):
                    await asyncio.to_thread(_oyin_yoz, mid, res["game_id"])
                else:
                    logging.error("Shaxmat turniri: o'yin ochilmadi (%s): %s", mid, res)
            except Exception as e:
                logging.error("Shaxmat turniri: o'yin ochishda xato (%s): %s", mid, e)
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
                logging.error("Shaxmat turniri xati yuborilmadi (%s): %s", uid, e)
    return len(berish), len(xabarlar), len(boshla)


async def _elon_yubor():
    try:
        n = await _cfg["elon"](xat_matni("elon"))
        logging.info("Shaxmat turniri e'loni yuborildi: %s kishi", n)
    except Exception as e:
        logging.error("Shaxmat turniri e'loni yuborilmadi: %s", e)


async def kuzatuvchi(interval=15):
    """Fon aylanasi: hech kim so'ramasa ham to'r tuziladi, o'yinlar ochiladi va yopiladi."""
    while True:
        try:
            await tick()
        except Exception as e:
            logging.error("Shaxmat turniri kuzatuvchisi: %s", e)
        try:
            T0 = _turnir_vaqti(_hafta())
            tez = T0 - 2 * YOPILISH <= _ep() <= T0 + TUGASH
        except Exception:
            tez = False
        await asyncio.sleep(3 if tez else interval)


def _odamlar(conn, uidlar):
    uidlar = [u for u in set(uidlar) if u is not None and u > 0]
    if not uidlar:
        return {}
    q = conn.execute("SELECT user_id, COALESCE(first_name, 'Sehrgar') AS name, house FROM users WHERE user_id IN (%s)" % ",".join("?" * len(uidlar)), uidlar)
    return {r["user_id"]: {"name": hpdars._ism(r["name"]), "house": r["house"]} for r in q}


def _kim(od, uid):
    if uid is None:
        return None
    o = od.get(uid, {"name": "Sehrgar", "house": None})
    return {"uid": uid, "name": o["name"], "house": o["house"]}


def _yozil(uid, on):
    uid, hafta = int(uid), _hafta()
    if _ep() >= _turnir_vaqti(hafta) - YOPILISH:
        return False
    conn = hpcup._connect()
    try:
        if on:
            conn.execute("INSERT OR IGNORE INTO sh_qatnash (hafta, user_id, vaqt) VALUES (?,?,?)", (hafta, uid, hpcup._utc_iso(_now())))
        else:
            conn.execute("DELETE FROM sh_qatnash WHERE hafta=? AND user_id=?", (hafta, uid))
        conn.commit()
        return True
    finally:
        conn.close()


def _holat(uid):
    uid, hafta, now = int(uid), _hafta(), _ep()
    T0 = _turnir_vaqti(hafta)
    conn = hpcup._connect()
    try:
        qat = _qatnashchilar(conn, hafta)
        tr = conn.execute("SELECT hajm FROM sh_turnir WHERE hafta=?", (hafta,)).fetchone()
        javob = {
            "ok": True, "now": now,
            "tour": {"ts": T0, "now": now, "open": now < T0 - YOPILISH, "joined": any(r["user_id"] == uid for r in qat), "n": len(qat), "close": YOPILISH,
                     # ro'yxatda REYTING YO'Q (egasi: turnirda reyting ko'rinmasin) - faqat ism va fakultet
                     "players": [{"uid": r["user_id"], "name": hpdars._ism(r["name"]), "house": r["house"], "me": r["user_id"] == uid} for r in qat]},
            "rules": {"base": BASE, "gap": ORALIQ, "first": hpchess.FIRST_MOVE, "points": {str(k): v for k, v in BOSQICH_BALL.items()}},
            "cup": {"size": None},
        }
        if not tr:
            return javob
        if not tr["hajm"]:
            javob["cup"] = {"size": 0}
            return javob
        ms = conn.execute("SELECT * FROM sh_match WHERE hafta=? ORDER BY bosqich DESC, joy", (hafta,)).fetchall()
        od = _odamlar(conn, [x for m in ms for x in (m["a"], m["b"])])
        bosq, my, n = {}, None, 0
        for m in ms:
            bosq.setdefault(m["bosqich"], []).append({
                "id": m["id"], "a": _kim(od, m["a"]), "b": _kim(od, m["b"]), "winner": m["golib"], "state": m["holat"], "why": m["sabab"],
                "game": m["game"], "ts": m["bosh"]})
            if my is None and m["holat"] != "tugadi" and uid in (m["a"], m["b"]):
                my = {"id": m["id"], "stage": m["bosqich"], "game": m["game"], "state": m["holat"], "ts": m["bosh"],
                      "ready": m["a"] is not None and m["b"] is not None, "white": m["a"] == uid}
        stages = []
        for s in sorted(bosq, reverse=True):
            stages.append({"stage": s, "ts": T0 + n * BOSQICH_T, "points": BOSQICH_BALL.get(s, 0), "matches": bosq[s]})
            n += 1
        javob["cup"] = {"size": tr["hajm"], "now": now, "my": my, "stages": stages}
        return javob
    finally:
        conn.close()


async def api_turnir(request):
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
    try:
        await tick()
    except Exception as e:
        logging.error("Shaxmat turniri tick: %s", e)
    qosh = {}
    if body.get("join") is not None:
        qosh["join_ok"] = await asyncio.to_thread(_yozil, uid, bool(body.get("join")))
        if _cfg.get("log"):
            try:
                await _cfg["log"](user, "shaxmat_turnir_" + ("yozildi" if body.get("join") else "chiqdi"))
            except Exception:
                pass
    javob = await asyncio.to_thread(_holat, uid)
    javob.update(qosh)
    return cors(web.json_response(javob))


def register(app, cfg):
    """cfg: verify_init_data, cors, log, xat. hpchess va hpdars DAN KEYIN ulanadi."""
    global _qulf
    _cfg.update(cfg)
    _qulf = asyncio.Lock()
    _init()
    app.router.add_route("*", "/api/chess/turnir", api_turnir)
    logging.info("Shaxmat turniri ulandi")
