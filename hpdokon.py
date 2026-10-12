"""Do'kon (egasi, 2026-10-12): galleonga JIHOZ va DAMLAMA - o'yinda haqiqiy USTUNLIK beradi.

Egasi qarorlari: xarid albatta kuch berishi kerak («faqat ko'rinish» rad etilgan); lekin MAHORAT HAL QILSIN - ustunlik kichik
(eng yuqori bosqichda ham ~10-15%); shaxmatda jihoz yo'q; hammasi birga chiqadi.

JIHOZLAR (doimiy; har birida 3 bosqich, ketma-ket olinadi, narxi NARX):
  supurgi   - Uchish bellashuvi va Supurgi poygasi: tezlik +4 / +8 / +12 % (ilova qo'llaydi);
  qolqop    - Duel: afsun kuchi +2 / +4 / +6 (SERVER qo'shadi); Afsunlar darsi: sham 10 / 20 / 30 % uzoqroq yonadi (ilova);
  qozon     - Damlamalar darsi: sham 10 / 20 / 30 % sekinroq (ilova);
  mantiya   - Himoya darsi: xavf 8 / 16 / 24 % sekinroq yaqinlashadi (ilova);
  eslatgich - Sehrgarlik tarixi darsi: 1 / 2 / 3 ta savolda bitta noto'g'ri variant o'chadi (ilova).
  qolqop, qozon, mantiya, eslatgich - o'z fanining BELLASHUVIDA har xato jarimasi 3 s emas: 2,6 / 2,2 / 1,8 s (SERVER, hpdars._tugat).
DAMLAMALAR (bir martalik; bor va yoqilgan bo'lsa o'zi ishlaydi):
  feliks - viktorinada bitta xato kechiriladi (har viktorinada bir marta; SERVER, hpviktorina);
  tezlik - poygada startdan katta tezlik (ilova so'raydi: {use: "tezlik"});
  diqqat - bellashuvda birinchi xato jarimasiz (SERVER, hpdars._tugat).

So'rovlar - POST /api/dokon: {} holat, {buy: kod} (jihozning keyingi bosqichi yoki bitta damlama), {toggle: kod, on: 0|1}, {use: "tezlik"}.
"""

import asyncio
import logging

from aiohttp import web

import hpcup

NARX = (15, 35, 80)                         # jihozning 1-, 2-, 3-bosqichi
JIHOZLAR = ("supurgi", "qolqop", "qozon", "mantiya", "eslatgich")
JIHOZ_FAN = {"qolqop": "afsun", "qozon": "iksir", "mantiya": "himoya", "eslatgich": "tarix"}      # bellashuv jarimasini kamaytiradiganlar
DAMLAMALAR = {"feliks": 4, "tezlik": 3, "diqqat": 2}
JARIMA_MS = 3000                            # bellashuvdagi odatdagi jarima (hpdars.XATO_MS bilan bir xil)
JARIMA_KAM = 400                            # har bosqich jarimani shuncha kamaytiradi
DUEL_KUCH = 2                               # qo'lqopning har bosqichi duelda shuncha kuch qo'shadi
TEZLIK = (4, 8, 12)                         # supurgi: tezlik foizi (ilova uchun)
SHAM = (10, 20, 30)                         # qo'lqop / qozon: sham shuncha foiz uzoqroq
XAVF = (8, 16, 24)                          # mantiya: xavf shuncha foiz sekinroq

_cfg = {}


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS dokon_jihoz (user_id INTEGER NOT NULL, tur TEXT NOT NULL, daraja INTEGER NOT NULL DEFAULT 0, vaqt TEXT,"
                     " PRIMARY KEY (user_id, tur))")
        conn.execute("CREATE TABLE IF NOT EXISTS dokon_damlama (user_id INTEGER NOT NULL, kod TEXT NOT NULL, soni INTEGER NOT NULL DEFAULT 0,"
                     " faol INTEGER NOT NULL DEFAULT 1, PRIMARY KEY (user_id, kod))")
        # bir martalik ishlatish izlari (masalan, feliks - har viktorinada bir marta): ref takrorlanmaydi
        conn.execute("CREATE TABLE IF NOT EXISTS dokon_ishlatildi (user_id INTEGER NOT NULL, kod TEXT NOT NULL, ref TEXT NOT NULL, vaqt TEXT,"
                     " PRIMARY KEY (user_id, kod, ref))")
        conn.commit()
    finally:
        conn.close()


# ---------- boshqa modullar uchun (o'z ulanishi bilan chaqiriladi) ----------

def daraja(conn, uid, tur):
    """Jihoz bosqichi (0 - yo'q)."""
    if not uid or uid <= 0:
        return 0
    try:
        r = conn.execute("SELECT daraja FROM dokon_jihoz WHERE user_id=? AND tur=?", (int(uid), tur)).fetchone()
        return int(r["daraja"]) if r else 0
    except Exception:
        return 0


def jarima_ms(conn, uid, dars):
    """Shu fan bellashuvidagi bitta xato jarimasi (jihoz kamaytiradi)."""
    for tur, fan in JIHOZ_FAN.items():
        if fan == dars:
            return JARIMA_MS - JARIMA_KAM * daraja(conn, uid, tur)
    return JARIMA_MS


def duel_kuch(conn, uid):
    return DUEL_KUCH * daraja(conn, uid, "qolqop")


def damlama_ishlat(conn, uid, kod, ref=None):
    """Bitta damlamani sarflaydi (bor va yoqilgan bo'lsa). ref berilsa - shu ref uchun faqat bir marta. True - ishladi."""
    if not uid or uid <= 0:
        return False
    try:
        if ref is not None and conn.execute("SELECT 1 FROM dokon_ishlatildi WHERE user_id=? AND kod=? AND ref=?", (int(uid), kod, ref)).fetchone():
            return False
        cur = conn.execute("UPDATE dokon_damlama SET soni = soni - 1 WHERE user_id=? AND kod=? AND soni > 0 AND faol = 1", (int(uid), kod))
        if cur.rowcount < 1:
            return False
        if ref is not None:
            conn.execute("INSERT OR IGNORE INTO dokon_ishlatildi (user_id, kod, ref, vaqt) VALUES (?,?,?,?)",
                         (int(uid), kod, ref, hpcup._utc_iso(hpcup.now_tk())))
        return True
    except Exception as e:
        logging.error("Damlama ishlatilmadi (%s, %s): %s", uid, kod, e)
        return False


def ishlatilgan(conn, uid, kod, ref):
    try:
        return conn.execute("SELECT 1 FROM dokon_ishlatildi WHERE user_id=? AND kod=? AND ref=?", (int(uid), kod, ref)).fetchone() is not None
    except Exception:
        return False


# ---------- do'kon ----------

def _holat(uid):
    conn = hpcup._connect()
    try:
        g = conn.execute("SELECT galleons FROM users WHERE user_id=?", (uid,)).fetchone()
        jih = {r["tur"]: int(r["daraja"]) for r in conn.execute("SELECT tur, daraja FROM dokon_jihoz WHERE user_id=?", (uid,))}
        dam = {r["kod"]: (int(r["soni"]), bool(r["faol"])) for r in conn.execute("SELECT kod, soni, faol FROM dokon_damlama WHERE user_id=?", (uid,))}
        return {"ok": True, "galleons": int(g["galleons"] or 0) if g else 0,
                "gear": [{"k": k, "level": jih.get(k, 0), "max": len(NARX), "price": NARX[jih.get(k, 0)] if jih.get(k, 0) < len(NARX) else None} for k in JIHOZLAR],
                "potions": [{"k": k, "n": dam.get(k, (0, True))[0], "on": dam.get(k, (0, True))[1], "price": p} for k, p in DAMLAMALAR.items()],
                "rules": {"prices": list(NARX), "speed": list(TEZLIK), "candle": list(SHAM), "danger": list(XAVF), "duel": DUEL_KUCH,
                          "penalty": [(JARIMA_MS - JARIMA_KAM * (i + 1)) / 1000.0 for i in range(len(NARX))]}}
    finally:
        conn.close()


def _sotib_ol(uid, kod):
    """'ok' | 'pul' (galleon yetmaydi) | 'toliq' (eng yuqori bosqich) | 'yoq' (bunday mol yo'q). Qo'shimcha: jihoz bo'lsa yangi bosqich."""
    conn = hpcup._connect()
    try:
        if kod in JIHOZLAR:
            hozir = daraja(conn, uid, kod)
            if hozir >= len(NARX):
                return "toliq", hozir
            narx = NARX[hozir]
            # Bitta so'rovda tekshirib yechamiz: ikki marta bosilsa ham pul ortiqcha ketmaydi
            if conn.execute("UPDATE users SET galleons = galleons - ? WHERE user_id = ? AND galleons >= ?", (narx, uid, narx)).rowcount < 1:
                conn.rollback()
                return "pul", hozir
            conn.execute("INSERT INTO dokon_jihoz (user_id, tur, daraja, vaqt) VALUES (?,?,?,?) "
                         "ON CONFLICT(user_id, tur) DO UPDATE SET daraja=excluded.daraja, vaqt=excluded.vaqt",
                         (uid, kod, hozir + 1, hpcup._utc_iso(hpcup.now_tk())))
            conn.commit()
            return "ok", hozir + 1
        if kod in DAMLAMALAR:
            narx = DAMLAMALAR[kod]
            if conn.execute("UPDATE users SET galleons = galleons - ? WHERE user_id = ? AND galleons >= ?", (narx, uid, narx)).rowcount < 1:
                conn.rollback()
                return "pul", 0
            conn.execute("INSERT INTO dokon_damlama (user_id, kod, soni) VALUES (?,?,1) ON CONFLICT(user_id, kod) DO UPDATE SET soni = soni + 1", (uid, kod))
            conn.commit()
            return "ok", 0
        return "yoq", 0
    finally:
        conn.close()


def _yoq_ochir(uid, kod, on):
    if kod not in DAMLAMALAR:
        return False
    conn = hpcup._connect()
    try:
        conn.execute("INSERT INTO dokon_damlama (user_id, kod, soni, faol) VALUES (?,?,0,?) ON CONFLICT(user_id, kod) DO UPDATE SET faol=excluded.faol",
                     (uid, kod, 1 if on else 0))
        conn.commit()
        return True
    finally:
        conn.close()


def _ishlat(uid, kod):
    conn = hpcup._connect()
    try:
        ok = damlama_ishlat(conn, uid, kod)
        conn.commit()
        return ok
    finally:
        conn.close()


async def api_dokon(request):
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
    if body.get("buy"):
        kod = str(body.get("buy"))
        natija, bosqich = await asyncio.to_thread(_sotib_ol, uid, kod)
        qosh["buy"] = natija
        if natija == "ok" and _cfg.get("log"):
            try:
                await _cfg["log"](user, "dokon_%s%s" % (kod, "_%d" % bosqich if bosqich else ""))
            except Exception:
                pass
    elif body.get("toggle"):
        qosh["toggle_ok"] = await asyncio.to_thread(_yoq_ochir, uid, str(body.get("toggle")), bool(body.get("on")))
    elif body.get("use") == "tezlik":            # faqat ilova o'zi qo'llaydigan damlama; qolganlarini server o'zi sarflaydi
        qosh["used"] = await asyncio.to_thread(_ishlat, uid, "tezlik")
    javob = await asyncio.to_thread(_holat, uid)
    javob.update(qosh)
    return cors(web.json_response(javob))


def register(app, cfg):
    """cfg: verify_init_data, cors, log."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/dokon", api_dokon)
    logging.info("Do'kon ulandi")
