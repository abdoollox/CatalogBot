"""Toshchalar (Gobstones) - SESHANBA turniri (egasi, 2026-10-14). Darslarda yo'q, o'ziga xos o'yin: nishonga olish va kuch.

O'YIN (ikki kishi): doira (sehrli maydon) o'rtasida TOSH_SONI ta toshcha turadi. Navbat bilan har kim o'z otuvchi toshini doira
chetidan (pastki yoydan, joyini o'zi tanlaydi) barmoq bilan tortib otadi: yo'nalish va kuch - o'yinchining mahorati.
Otuvchi tosh toshchalarni uradi; doiradan chiqib ketgan har bir toshcha - otgan o'yinchiga bitta ochko. Otuvchi tosh zarbadan keyin olinadi.
Har kimga ZARBA ta zarba (navbat bilan). Toshchalar tugasa - o'yin tugaydi. Teng bo'lsa - qo'shimcha juft zarbalar (QOSHIMCHA tagacha),
baribir teng bo'lsa: turnirda to'rda yuqori turgan o'tadi, mashqda durang. Yutqazganga - asardagidek - «sassiq suyuqlik» sepiladi (ilovada).
FIZIKA SERVERDA: zarba (joy, yo'nalish, kuch) serverga yuboriladi, server toshlar harakatini hisoblaydi va kadrlarini qaytaradi -
ikkala o'yinchi (va tomoshabinlar) bir xil manzarani ko'radi, natijani faqat server belgilaydi.
Navbat NAVBAT_T soniya; ulgurmasa zarba o'tkazib yuboriladi; ikki marta ketma-ket o'tkazib yuborgan va ko'rinmagan o'yinchi yutqazadi (kelmadi).

MASHQ: kompyuter raqiblar (3 daraja) bilan, istalgan payt, ballsiz.
TURNIR: seshanba 22:00 (shaxmat/duel turnirlari qolipida): «Qatnashaman» bosgan har bir saralangan o'quvchi; to'r eng yaqin 2 ning
darajasiga to'ldiriladi (mashqda ko'p yutganlar birinchi bosqichni o'tkazib yuboradi); ball: g'alaba uchun 1/8 +5, chorak +10, yarim final +20,
final +30. Keyingi bosqich o'yini ikkala raqib aniqlangach ORALIQ soniyadan keyin. Adminga «Sinov o'yini» (kompyuter bilan, turnir oqimi).

So'rovlar - POST /api/tosh: {} holat, {join: 1|0}, {mashq: 1|2|3}, {oyin: id, seen: n} o'yin holati (seen - oxirgi ko'rilgan zarba raqami),
{oyin: id, shot: {s, a, p}} zarba (s - doiradagi joy burchagi, a - yo'nalish burchagi, p - kuch 0..1), {sinov: 1}.
"""

import asyncio
import hashlib
import json
import logging
import math
import random
from datetime import datetime, timedelta

from aiohttp import web

import hpcup
import hpdars
import hpgolib

BOSH_HAFTA = "2026-10-19"     # birinchi turnir shu haftada (seshanba 20-oktabr)
TURNIR_KUN = 1                # seshanba
SOAT = 22
YOPILISH = 300                # yozilish turnirdan shuncha soniya oldin yopiladi, to'r tuziladi
ORALIQ = 45                   # ikkala raqib aniqlangach keyingi o'yin shuncha soniyadan keyin
TUGASH = 3 * 3600
BOSQICH_BALL = {16: 5, 8: 10, 4: 20, 2: 30}
BOSQICH_T = 6 * 60            # bosqichning taxminiy davomiyligi (to'rda ko'rsatish uchun)

# ---------- o'yin qoidasi ----------
ZARBA = 5                     # har o'yinchiga zarbalar
QOSHIMCHA = 3                 # teng bo'lsa qo'shimcha juft zarbalar (eng ko'pi)
NAVBAT_T = 30                 # navbat vaqti
KELMADI_SKIP = 2              # ketma-ket shuncha o'tkazib yuborgan va ko'rinmagan - yutqazadi
KORINDI_T = 45                # oxirgi so'rovdan shuncha soniya o'tmagan bo'lsa - o'yinda
PAUZA = 1.2                   # zarba manzarasi tugagach keyingi navbatgacha qo'shimcha kutish

# ---------- fizika ----------
R = 1.0                       # doira radiusi
TR = 0.058                    # toshcha radiusi
OR_ = 0.068                   # otuvchi tosh radiusi
OM = 1.45                     # otuvchi tosh massasi (toshcha - 1)
ISHQ = 1.2                    # ishqalanish (tezlik har soniyada shuncha kamayadi)
QAYT = 0.9                    # urilishdagi tiklanish
V_MIN, V_MAX = 0.6, 2.6       # kuch 0..1 -> boshlang'ich tezlik (sozlangan: kuchli zarba 1-3 toshcha, o'rtacha 0-1)
DT = 1.0 / 120
KADR = 3                      # har shuncha qadamda bitta kadr (40 kadr/s)
MAX_T = 7.0
JOY_MIN, JOY_MAX = -150.0, -30.0   # otuvchi tosh joyi: pastki yoy (gradus; 0 - o'ngda, -90 - pastda)
TOSH_SONI = 9

DOST_MUDDAT = 1800            # do'stga taklif (Telegram yoki ilova) shuncha soniya kutadi
BOT_UID0 = -9300              # kompyuter raqiblar: BOT_UID0 - daraja
BOTLAR = {1: ("Nevill", "gryffindor"), 2: ("Ron", "gryffindor"), 3: ("Jorj Uizli", "gryffindor")}
BOT_NOMZOD = {1: 1, 2: 4, 3: 12}                  # nechta zarbani o'ylab ko'radi (zarba boshiga o'rtacha 0,4 / 0,6 / 0,85 toshcha)
BOT_SHOVQIN = {1: 0.12, 2: 0.06, 3: 0.02}         # nishonga olishdagi xato (radian)

_cfg = {}


def _now():
    return hpcup.now_tk()


def _ep():
    return _now().timestamp()


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS tosh_match ("
                     " id INTEGER PRIMARY KEY AUTOINCREMENT, tur TEXT NOT NULL, hafta TEXT, bosqich INTEGER, joy INTEGER,"
                     " a INTEGER, b INTEGER, a_seed INTEGER, b_seed INTEGER, daraja INTEGER, bosh REAL,"
                     " holat TEXT NOT NULL DEFAULT 'kutmoqda', golib INTEGER, sabab TEXT,"
                     " toshlar TEXT, navbat TEXT, zarba INTEGER NOT NULL DEFAULT 0, a_ball INTEGER NOT NULL DEFAULT 0, b_ball INTEGER NOT NULL DEFAULT 0,"
                     " a_skip INTEGER NOT NULL DEFAULT 0, b_skip INTEGER NOT NULL DEFAULT 0, navbat_bosh REAL, oxirgi TEXT,"
                     " a_seen REAL, b_seen REAL, vaqt TEXT)")
        conn.execute("CREATE INDEX IF NOT EXISTS tosh_match_hafta ON tosh_match (hafta, bosqich, joy)")
        conn.execute("CREATE TABLE IF NOT EXISTS tosh_turnir (hafta TEXT PRIMARY KEY, hajm INTEGER NOT NULL DEFAULT 0, vaqt TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS tosh_qatnash (hafta TEXT NOT NULL, user_id INTEGER NOT NULL, vaqt TEXT NOT NULL, PRIMARY KEY (hafta, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS tosh_eslatma (hafta TEXT NOT NULL, tur TEXT NOT NULL, PRIMARY KEY (hafta, tur))")
        conn.commit()
    finally:
        conn.close()


# =====================================================================  FIZIKA

def boshlangich():
    """O'yin boshidagi toshchalar: 3x3 to'r, o'rtada."""
    q = 0.165
    return [[round(x * q, 4), round(y * q, 4)] for y in (1, 0, -1) for x in (-1, 0, 1)]


def otish_joyi(s_grad):
    s = math.radians(max(JOY_MIN, min(JOY_MAX, float(s_grad))))
    return [math.cos(s) * (R - OR_ * 1.2), math.sin(s) * (R - OR_ * 1.2)]


def simulyatsiya(toshlar, s_grad, a_grad, kuch, kadrlar=True):
    """Bitta zarba. toshlar - [[x, y], ...] (doiradagi toshchalar). Qaytaradi: (qolgan toshlar, chiqqanlar soni, kadrlar).
    Kadr - har bir jism [x, y] (toshchalar tartibida, oxirida otuvchi); chiqib ketgan jism kadrlarda o'z joyida qoladi, `chiqdi` da qachon chiqqani."""
    sx, sy = otish_joyi(s_grad)
    a = math.radians(float(a_grad))
    v = V_MIN + (V_MAX - V_MIN) * max(0.0, min(1.0, float(kuch)))
    n = len(toshlar)
    px = [t[0] for t in toshlar] + [sx]
    py = [t[1] for t in toshlar] + [sy]
    vx = [0.0] * n + [math.cos(a) * v]
    vy = [0.0] * n + [math.sin(a) * v]
    rad = [TR] * n + [OR_]
    mass = [1.0] * n + [OM]
    tirik = [True] * (n + 1)
    chiqdi = [None] * (n + 1)
    out, qadam = [], 0
    kad = [[[round(px[i], 3), round(py[i], 3)] for i in range(n + 1)]] if kadrlar else []
    while qadam * DT < MAX_T:
        qadam += 1
        harakat = False
        for i in range(n + 1):
            if not tirik[i]:
                continue
            sp = math.hypot(vx[i], vy[i])
            if sp > 0:
                yangi = max(0.0, sp - ISHQ * DT)
                k = yangi / sp
                vx[i] *= k
                vy[i] *= k
                px[i] += vx[i] * DT
                py[i] += vy[i] * DT
                if yangi > 0.004:
                    harakat = True
        # urilishlar (faqat doiradagi jismlar)
        for i in range(n + 1):
            if not tirik[i]:
                continue
            for j in range(i + 1, n + 1):
                if not tirik[j]:
                    continue
                dx, dy = px[j] - px[i], py[j] - py[i]
                ms = rad[i] + rad[j]
                d2 = dx * dx + dy * dy
                if d2 >= ms * ms or d2 == 0:
                    continue
                d = math.sqrt(d2)
                nx, ny = dx / d, dy / d
                rv = (vx[i] - vx[j]) * nx + (vy[i] - vy[j]) * ny
                ust = (ms - d) / 2.0
                px[i] -= nx * ust
                py[i] -= ny * ust
                px[j] += nx * ust
                py[j] += ny * ust
                if rv <= 0:
                    continue
                imp = (1 + QAYT) * rv / (1 / mass[i] + 1 / mass[j])
                vx[i] -= imp / mass[i] * nx
                vy[i] -= imp / mass[i] * ny
                vx[j] += imp / mass[j] * nx
                vy[j] += imp / mass[j] * ny
                harakat = True
        # doiradan chiqish (markazi doira chetidan o'tdi). Otuvchi tosh ham chiqsa - zarba tugaydi.
        for i in range(n + 1):
            if tirik[i] and math.hypot(px[i], py[i]) > R:
                if i == n and qadam * DT < 0.15:
                    continue                      # otuvchi tosh chetdan boshlanadi - darhol chiqmasin
                tirik[i] = False
                chiqdi[i] = len(kad)
                if i < n:
                    out.append(i)
        if kadrlar and qadam % KADR == 0:
            kad.append([[round(px[i], 3), round(py[i], 3)] for i in range(n + 1)])
        if not harakat:
            break
    if kadrlar and (qadam % KADR):
        kad.append([[round(px[i], 3), round(py[i], 3)] for i in range(n + 1)])
    qoldi = [[round(px[i], 4), round(py[i], 4)] for i in range(n) if tirik[i]]
    return qoldi, len(out), {"f": kad, "out": [chiqdi[i] for i in range(n + 1)], "start": [round(sx, 3), round(sy, 3)]}


def kompyuter_zarbasi(toshlar, daraja, rnd=random):
    """Kompyuter raqib: bir nechta zarbani o'ylab ko'radi (shovqin bilan), eng ko'p toshcha chiqaradiganini tanlaydi."""
    if not toshlar:
        return {"s": -90, "a": 90, "p": 0.5}
    eng, eng_ball = None, -1
    for _ in range(BOT_NOMZOD.get(daraja, 8)):
        s = rnd.uniform(JOY_MIN + 8, JOY_MAX - 8)
        sx, sy = otish_joyi(s)
        t = rnd.choice(toshlar)
        a = math.degrees(math.atan2(t[1] - sy, t[0] - sx)) + rnd.gauss(0, 7)
        p = rnd.uniform(0.55, 1.0)
        _, ball, _ = simulyatsiya(toshlar, s, a, p, kadrlar=False)
        if ball + rnd.random() * 0.4 > eng_ball:
            eng, eng_ball = (s, a, p), ball + rnd.random() * 0.4
    s, a, p = eng
    return {"s": s, "a": a + math.degrees(rnd.gauss(0, BOT_SHOVQIN.get(daraja, 0.05))), "p": max(0.05, min(1.0, p + rnd.gauss(0, 0.04)))}


# =====================================================================  O'YIN

def _bot(uid):
    return uid is not None and uid < 0


def _yangi_oyin(conn, tur, a, b, bosh, **qosh):
    cur = conn.execute("INSERT INTO tosh_match (tur, a, b, bosh, holat, toshlar, navbat, navbat_bosh, vaqt, hafta, bosqich, joy, a_seed, b_seed, daraja) "
                       "VALUES (?,?,?,?,'ketmoqda',?,'a',?,?,?,?,?,?,?,?)",
                       (tur, a, b, bosh, json.dumps(boshlangich()), bosh, hpcup._utc_iso(_now()), qosh.get("hafta"), qosh.get("bosqich"),
                        qosh.get("joy"), qosh.get("a_seed"), qosh.get("b_seed"), qosh.get("daraja")))
    return cur.lastrowid


def _tugashi_kerakmi(m, toshlar, zarba, ab, bb):
    """(tugadimi, g'olib yoni 'a'|'b'|None)."""
    if not toshlar:
        return True, ("a" if ab > bb else "b" if bb > ab else None)
    asosiy = ZARBA * 2
    if zarba < asosiy:
        return False, None
    if zarba % 2:                                 # juftlik tugamagan (b hali otmagan)
        return False, None
    if ab != bb:
        return True, ("a" if ab > bb else "b")
    if zarba >= asosiy + QOSHIMCHA * 2:
        return True, None
    return False, None


def _yakunla(conn, m, golib_yon, sabab, berish, now):
    golib = m[golib_yon] if golib_yon else None
    if golib is None and m["tur"] in ("turnir", "sinov"):
        # teng: to'rda yuqori turgan (kichik seed) o'tadi
        golib = m["a"] if (m["a_seed"] or 99) <= (m["b_seed"] or 99) else m["b"]
        sabab = "teng"
    conn.execute("UPDATE tosh_match SET holat='tugadi', golib=?, sabab=?, navbat=NULL WHERE id=?", (golib, sabab, m["id"]))
    if m["tur"] == "turnir":
        _tor_keyingi(conn, dict(m), golib, sabab, berish, now)


def _zarba_ber(conn, m, yon, shot, berish, now):
    """Zarbani bajaradi (yoki o'tkazib yuboradi - shot None). m - hozirgi qator."""
    toshlar = json.loads(m["toshlar"] or "[]")
    n = m["zarba"] + 1
    if shot is None:
        qoldi, ball, kad = toshlar, 0, None
        oxirgi = {"n": n, "by": yon, "skip": True}
        conn.execute("UPDATE tosh_match SET %s_skip=%s_skip+1 WHERE id=?" % (yon, yon), (m["id"],))
        davom = 0.6
    else:
        try:
            s, a, p = float(shot.get("s")), float(shot.get("a")), float(shot.get("p"))
        except (TypeError, ValueError, AttributeError):
            return False
        if not all(map(math.isfinite, (s, a, p))):
            return False
        qoldi, ball, kad = simulyatsiya(toshlar, s, a, p)
        oxirgi = {"n": n, "by": yon, "ball": ball, "f": kad["f"], "out": kad["out"], "start": kad["start"], "dt": DT * KADR}
        conn.execute("UPDATE tosh_match SET %s_skip=0 WHERE id=?" % yon, (m["id"],))
        davom = len(kad["f"]) * DT * KADR
    ab = m["a_ball"] + (ball if yon == "a" else 0)
    bb = m["b_ball"] + (ball if yon == "b" else 0)
    keyingi = "b" if yon == "a" else "a"
    conn.execute("UPDATE tosh_match SET toshlar=?, zarba=?, a_ball=?, b_ball=?, oxirgi=?, navbat=?, navbat_bosh=? WHERE id=?",
                 (json.dumps(qoldi), n, ab, bb, json.dumps(oxirgi, separators=(",", ":")), keyingi, now + davom + PAUZA, m["id"]))
    tugadi, golib_yon = _tugashi_kerakmi(m, qoldi, n, ab, bb)
    if tugadi:
        conn.execute("UPDATE tosh_match SET navbat_bosh=? WHERE id=?", (now + davom + PAUZA, m["id"]))
        m2 = conn.execute("SELECT * FROM tosh_match WHERE id=?", (m["id"],)).fetchone()
        _yakunla(conn, m2, golib_yon, "oyin", berish, now)
    return True


def _oyin_yur(conn, m, berish, now, rnd=random):
    """O'yinni hozirgi vaqtga keltiradi: kompyuter zarbasi, navbat vaqti tugashi, kelmaganlar."""
    for _ in range(4):
        if m["holat"] != "ketmoqda" or not m["navbat"] or now < (m["navbat_bosh"] or 0):
            return m
        yon = m["navbat"]
        uid = m[yon]
        if _bot(uid):
            _zarba_ber(conn, m, yon, kompyuter_zarbasi(json.loads(m["toshlar"] or "[]"), m["daraja"] or (BOT_UID0 - uid), rnd), berish, now)
        elif now >= (m["navbat_bosh"] or 0) + NAVBAT_T:
            korindi = (m[yon + "_seen"] or 0) >= now - KORINDI_T
            if m[yon + "_skip"] + 1 >= KELMADI_SKIP and not korindi:
                _yakunla(conn, m, "b" if yon == "a" else "a", "kelmadi", berish, now)
            else:
                _zarba_ber(conn, m, yon, None, berish, now - 0.0)
        else:
            return m
        m = conn.execute("SELECT * FROM tosh_match WHERE id=?", (m["id"],)).fetchone()
    return m


# =====================================================================  TURNIR

def _tartib(n):
    t = [1, 2]
    while len(t) < n:
        k = len(t) * 2 + 1
        t = [x for s in t for x in (s, k - s)]
    return t


def _turnir_vaqti(hafta):
    y, m, d = (int(x) for x in hafta.split("-"))
    return (datetime(y, m, d, SOAT, 0, 0, tzinfo=_now().tzinfo) + timedelta(days=TURNIR_KUN)).timestamp()


def _hafta():
    h = max(hpdars._hafta(), BOSH_HAFTA)
    if _ep() >= _turnir_vaqti(h) + TUGASH:
        y, m, d = (int(x) for x in h.split("-"))
        h = (datetime(y, m, d) + timedelta(days=7)).strftime("%Y-%m-%d")
    return h


def _qatnashchilar(conn, hafta):
    """Yozilganlar: mashqda kompyuterni ko'proq yengganlar yuqorida (qiyin daraja ko'proq hisoblanadi), keyin oldin yozilgan."""
    return conn.execute(
        "SELECT q.user_id, q.vaqt, COALESCE(u.first_name, 'Sehrgar') AS name, u.house, "
        " (SELECT COALESCE(SUM(m.daraja), 0) FROM tosh_match m WHERE m.tur='mashq' AND m.golib=q.user_id) AS kuch "
        "FROM tosh_qatnash q JOIN users u ON u.user_id = q.user_id "
        "WHERE q.hafta=? AND u.house IS NOT NULL AND q.user_id > 0 ORDER BY kuch DESC, q.vaqt ASC", (hafta,)).fetchall()


def _tor_keyingi(conn, m, golib, sabab, berish, now):
    if sabab != "bye" and golib and golib > 0:
        berish.append((golib, "tosh:%s:%d" % (m["hafta"], m["bosqich"]), BOSQICH_BALL.get(m["bosqich"], 0)))
    nb = m["bosqich"] // 2
    if nb < 2:
        return
    yon = "a" if m["joy"] % 2 == 0 else "b"
    seed = m["a_seed"] if golib == m["a"] else m["b_seed"]
    conn.execute("UPDATE tosh_match SET %s=?, %s_seed=? WHERE tur='turnir' AND hafta=? AND bosqich=? AND joy=?" % (yon, yon),
                 (golib, seed, m["hafta"], nb, m["joy"] // 2))
    k = conn.execute("SELECT * FROM tosh_match WHERE tur='turnir' AND hafta=? AND bosqich=? AND joy=?", (m["hafta"], nb, m["joy"] // 2)).fetchone()
    if k["a"] is not None and k["b"] is not None and k["bosh"] is None:
        conn.execute("UPDATE tosh_match SET bosh=? WHERE id=?", (max(_turnir_vaqti(m["hafta"]), now + ORALIQ), k["id"]))


def _tor_tuz(conn, hafta, berish, now):
    if now < _turnir_vaqti(hafta) - YOPILISH:
        return
    if conn.execute("INSERT OR IGNORE INTO tosh_turnir (hafta, hajm, vaqt) VALUES (?,0,?)", (hafta, hpcup._utc_iso(_now()))).rowcount < 1:
        return
    rows = _qatnashchilar(conn, hafta)
    n = len(rows)
    if n < 2:
        return
    hajm = 2
    while hajm < n:
        hajm *= 2
    conn.execute("UPDATE tosh_turnir SET hajm=? WHERE hafta=?", (hajm, hafta))
    s = hajm
    while s >= 2:
        for i in range(s // 2):
            conn.execute("INSERT INTO tosh_match (tur, hafta, bosqich, joy, holat) VALUES ('turnir',?,?,?,'kutmoqda')", (hafta, s, i))
        s //= 2
    t, T0 = _tartib(hajm), _turnir_vaqti(hafta)
    for i in range(hajm // 2):
        a, b = t[2 * i], t[2 * i + 1]
        conn.execute("UPDATE tosh_match SET a=?, a_seed=?, b=?, b_seed=?, bosh=? WHERE tur='turnir' AND hafta=? AND bosqich=? AND joy=?",
                     (rows[a - 1]["user_id"], a, rows[b - 1]["user_id"] if b <= n else None, b if b <= n else None, T0, hafta, hajm, i))
        if b > n:
            m = conn.execute("SELECT * FROM tosh_match WHERE tur='turnir' AND hafta=? AND bosqich=? AND joy=?", (hafta, hajm, i)).fetchone()
            conn.execute("UPDATE tosh_match SET holat='tugadi', golib=?, sabab='bye' WHERE id=?", (m["a"], m["id"]))
            _tor_keyingi(conn, dict(m), m["a"], "bye", berish, now)


def _turnir_boshla(conn, now):
    """Vaqti kelgan turnir uchrashuvlarini boshlaydi (ikkala raqib aniq)."""
    for m in conn.execute("SELECT * FROM tosh_match WHERE tur='turnir' AND holat='kutmoqda' AND a IS NOT NULL AND b IS NOT NULL "
                          "AND bosh IS NOT NULL AND bosh<=?", (now,)).fetchall():
        conn.execute("UPDATE tosh_match SET holat='ketmoqda', toshlar=?, navbat='a', navbat_bosh=?, zarba=0, a_ball=0, b_ball=0 WHERE id=?",
                     (json.dumps(boshlangich()), max(now, m["bosh"]) + 3, m["id"]))


def _eslatmalar(conn, hafta, xabarlar):
    hozir = _now()
    T0 = _turnir_vaqti(hafta)
    if hozir.timestamp() >= T0 or datetime.fromtimestamp(T0, hozir.tzinfo).date() != hozir.date():
        return
    daq = hozir.hour * 60 + hozir.minute
    tur = "on" if SOAT * 60 - 10 <= daq < SOAT * 60 else "ertalab" if 600 <= daq < SOAT * 60 - 10 else None
    if not tur:
        return
    if conn.execute("INSERT OR IGNORE INTO tosh_eslatma (hafta, tur) VALUES (?,?)", (hafta, tur)).rowcount < 1:
        return
    if tur == "ertalab" and hafta == BOSH_HAFTA:
        xabarlar.append((0, "elon"))
        return
    for r in conn.execute("SELECT user_id FROM tosh_qatnash WHERE hafta=?", (hafta,)).fetchall():
        xabarlar.append((r["user_id"], tur))


def _tick(rnd=random):
    berish, xabarlar = [], []
    hafta, now = _hafta(), _ep()
    conn = hpcup._connect()
    try:
        _tor_tuz(conn, hafta, berish, now)
        _turnir_boshla(conn, now)
        for m in conn.execute("SELECT * FROM tosh_match WHERE holat='ketmoqda'").fetchall():
            _oyin_yur(conn, m, berish, now, rnd)
        # muddati o'tgan do'stona takliflar yopiladi
        conn.execute("UPDATE tosh_match SET holat='tugadi', sabab='muddat' WHERE tur='dost' AND holat='kutmoqda' AND bosh < ?", (now,))
        # tashlab ketilgan mashq o'yinlari (1 soatdan eski) yopiladi
        conn.execute("UPDATE tosh_match SET holat='tugadi', sabab='tashlandi' WHERE holat='ketmoqda' AND tur IN ('mashq','sinov','dost') AND bosh < ?", (now - 3600,))
        _eslatmalar(conn, hafta, xabarlar)
        conn.commit()
    finally:
        conn.close()
    return berish, xabarlar


def xat_matni(tur):
    if tur == "elon":
        return {"uz": ("Bugun 22:00 da birinchi Toshchalar turniri!", "Asardagi sehrgarlar o'yini: doiradagi toshchalarni o'z toshingiz bilan urib chiqaring — kim ko'p chiqarsa, o'sha yutadi. Ilovada: Xogvarts → Toshchalar. Hozirdan kompyuter bilan mashq qilib, «Qatnashaman» tugmasini bosing. G'olibga +30 ball."),
                "ru": ("Сегодня в 22:00 первый турнир по плюй-камням!", "Игра волшебников из книги: выбивайте камешки из круга своим камнем — кто выбьет больше, тот победил. В приложении: Хогвартс → Плюй-камни. Потренируйтесь с компьютером и нажмите «Участвую». Победителю +30 очков."),
                "en": ("The first Gobstones tournament is today at 22:00!", "The wizarding game from the books: knock the stones out of the ring with your own — whoever knocks out more wins. In the app: Hogwarts → Gobstones. Practise against the computer and tap “I'm in”. +30 points for the winner.")}
    if tur == "ertalab":
        return {"uz": ("Bugun 22:00 da Toshchalar turniri", "Siz turnirga yozilgansiz. Soat 22:00 da ilovaga kiring: Xogvarts → Toshchalar. Navbatingizda 30 soniyada otmasangiz, zarba yonib ketadi."),
                "ru": ("Сегодня в 22:00 турнир по плюй-камням", "Вы записаны. Зайдите в 22:00: Хогвартс → Плюй-камни. Не успели ударить за 30 секунд — удар сгорает."),
                "en": ("The Gobstones tournament is today at 22:00", "You are signed up. Come in at 22:00: Hogwarts → Gobstones. If you do not shoot within 30 seconds, the shot is lost.")}
    return {"uz": ("Turnirga 10 daqiqa qoldi!", "Toshchalar turniri 22:00 da boshlanadi. Hoziroq ilovaga kiring: Xogvarts → Toshchalar."),
            "ru": ("До турнира 10 минут!", "Турнир по плюй-камням начнётся в 22:00. Зайдите прямо сейчас: Хогвартс → Плюй-камни."),
            "en": ("10 minutes to the tournament!", "The Gobstones tournament starts at 22:00. Come in now: Hogwarts → Gobstones.")}


async def _elon_yubor():
    try:
        n = await _cfg["elon"](xat_matni("elon"))
        logging.info("Toshchalar e'loni yuborildi: %s kishi", n)
    except Exception as e:
        logging.error("Toshchalar e'loni yuborilmadi: %s", e)


async def tick():
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
                logging.error("Toshchalar xati yuborilmadi (%s): %s", uid, e)


async def kuzatuvchi(interval=15):
    while True:
        try:
            await tick()
        except Exception as e:
            logging.error("Toshchalar kuzatuvchisi: %s", e)
        try:
            T0 = _turnir_vaqti(_hafta())
            tez = T0 - 600 <= _ep() <= T0 + 2 * 3600
        except Exception:
            tez = False
        await asyncio.sleep(2 if tez else interval)


# =====================================================================  SO'ROVLAR

def _ism(conn, uid):
    if _bot(uid):
        d = BOT_UID0 - uid
        nom, uy = BOTLAR.get(d, ("Sehrgar", None))
        return {"uid": None, "name": nom, "house": uy, "bot": d}
    r = conn.execute("SELECT COALESCE(first_name, 'Sehrgar') AS name, house FROM users WHERE user_id=?", (uid,)).fetchone()
    return {"uid": uid, "name": hpdars._ism(r["name"]) if r else "Sehrgar", "house": r["house"] if r else None}


def _oyin_holat(conn, m, uid, seen, now):
    """O'yin manzarasi ilova uchun. seen - ilova ko'rgan oxirgi zarba raqami (yangi zarba bo'lsa kadrlari beriladi)."""
    men = "a" if m["a"] == uid else "b" if m["b"] == uid else None
    if men:
        conn.execute("UPDATE tosh_match SET %s_seen=? WHERE id=?" % men, (now, m["id"]))
    javob = {"id": m["id"], "kind": m["tur"], "state": m["holat"], "me": men, "a": _ism(conn, m["a"]) if m["a"] is not None else None,
             "b": _ism(conn, m["b"]) if m["b"] is not None else None, "score": [m["a_ball"], m["b_ball"]], "shots": m["zarba"],
             "per": ZARBA, "extra": QOSHIMCHA, "turn": m["navbat"], "stones": json.loads(m["toshlar"] or "[]"),
             "turn_in": max(0, round((m["navbat_bosh"] or 0) - now, 2)), "turn_left": max(0, round((m["navbat_bosh"] or 0) + NAVBAT_T - now, 2)),
             "winner": ("a" if m["golib"] == m["a"] else "b") if m["golib"] is not None else None, "why": m["sabab"], "stage": m["bosqich"],
             "starts_in": max(0, round((m["bosh"] or 0) - now, 1)) if m["holat"] == "kutmoqda" and m["tur"] != "dost" else 0,
             "expires_in": max(0, round((m["bosh"] or 0) - now)) if m["holat"] == "kutmoqda" and m["tur"] == "dost" else None}
    if m["oxirgi"]:
        ox = json.loads(m["oxirgi"])
        javob["last_n"] = ox.get("n")
        if seen is None or int(seen) < ox.get("n", 0):
            javob["last"] = ox
    return javob


def _holat(uid, oyin=None, seen=None):
    uid, hafta, now = int(uid), _hafta(), _ep()
    conn = hpcup._connect()
    try:
        if oyin is not None:
            m = conn.execute("SELECT * FROM tosh_match WHERE id=?", (int(oyin),)).fetchone()
            if not m:
                return {"ok": False, "error": "yoq"}
            berish = []
            m = _oyin_yur(conn, m, berish, now)
            _berish_keyin.extend(berish)              # turnir uchrashuvi shu so'rovda tugasa - ball api_tosh da beriladi
            g = _oyin_holat(conn, m, uid, seen, now)
            conn.commit()
            return {"ok": True, "game": g}
        T0 = _turnir_vaqti(hafta)
        qat = _qatnashchilar(conn, hafta)
        tr = conn.execute("SELECT hajm FROM tosh_turnir WHERE hafta=?", (hafta,)).fetchone()
        javob = {"ok": True, "now": now,
                 "tour": {"ts": T0, "now": now, "open": now < T0 - YOPILISH, "joined": any(r["user_id"] == uid for r in qat), "n": len(qat), "close": YOPILISH,
                          "players": [{"uid": r["user_id"], "name": hpdars._ism(r["name"]), "house": r["house"], "me": r["user_id"] == uid} for r in qat]},
                 "rules": {"shots": ZARBA, "extra": QOSHIMCHA, "turn": NAVBAT_T, "stones": TOSH_SONI, "gap": ORALIQ,
                           "points": {str(k): v for k, v in BOSQICH_BALL.items()}, "bots": {str(k): v[0] for k, v in BOTLAR.items()}},
                 "champs": hpgolib.tor(conn, "tosh_match", hafta, "tosh", uid, "SELECT COUNT(*) FROM tosh_qatnash WHERE hafta=?", _turnir_vaqti),
                 "admin": uid in (_cfg.get("admin_ids") or ()),
                 "stats": dict(zip(("played", "won"), conn.execute("SELECT COUNT(*), COALESCE(SUM(golib=?), 0) FROM tosh_match WHERE (a=? OR b=?) AND holat='tugadi'",
                                                                   (uid, uid, uid)).fetchone())),
                 "cup": {"size": tr["hajm"] if tr else None}}
        faol = conn.execute("SELECT id, tur FROM tosh_match WHERE holat IN ('ketmoqda','kutmoqda') AND (a=? OR b=?) AND tur IN ('mashq','sinov','turnir') "
                            "AND (tur != 'turnir' OR (bosh IS NOT NULL AND bosh <= ?)) ORDER BY id DESC LIMIT 1", (uid, uid, now + ORALIQ + 5)).fetchone()
        if faol:
            javob["active"] = {"id": faol["id"], "kind": faol["tur"]}
        if tr and tr["hajm"]:
            ms = conn.execute("SELECT * FROM tosh_match WHERE tur='turnir' AND hafta=? ORDER BY bosqich DESC, joy", (hafta,)).fetchall()
            stages = {}
            for m in ms:
                stages.setdefault(m["bosqich"], []).append({
                    "id": m["id"], "a": _ism(conn, m["a"]) if m["a"] else None, "b": _ism(conn, m["b"]) if m["b"] else None,
                    "score": [m["a_ball"], m["b_ball"]], "state": m["holat"], "winner": m["golib"], "why": m["sabab"],
                    "mine": uid in (m["a"], m["b"]), "ts": m["bosh"]})
            javob["cup"]["stages"] = [{"stage": s, "points": BOSQICH_BALL.get(s, 0), "matches": stages[s]} for s in sorted(stages, reverse=True)]
        conn.commit()
        return javob
    finally:
        conn.close()


def _mashq(uid, daraja):
    daraja = max(1, min(3, int(daraja)))
    now = _ep()
    conn = hpcup._connect()
    try:
        conn.execute("UPDATE tosh_match SET holat='tugadi', sabab='tashlandi' WHERE holat='ketmoqda' AND tur IN ('mashq','sinov') AND a=?", (uid,))
        mid = _yangi_oyin(conn, "mashq", uid, BOT_UID0 - daraja, now, daraja=daraja)
        conn.commit()
        return mid
    finally:
        conn.close()


def _sinov(uid):
    """Admin: turnir o'yini oqimi kompyuter (2-daraja) bilan, ballsiz."""
    now = _ep()
    conn = hpcup._connect()
    try:
        conn.execute("UPDATE tosh_match SET holat='tugadi', sabab='tashlandi' WHERE holat='ketmoqda' AND tur IN ('mashq','sinov') AND a=?", (uid,))
        mid = _yangi_oyin(conn, "sinov", uid, BOT_UID0 - 2, now + 5, daraja=2, a_seed=1, b_seed=2, bosqich=2)
        conn.commit()
        return mid
    finally:
        conn.close()


def _dost(uid):
    """Do'stga taklif: a = chaqiruvchi, b bo'sh, `bosh` - taklif muddati. Oldingi ochiq taklifi bekor bo'ladi."""
    now = _ep()
    conn = hpcup._connect()
    try:
        conn.execute("UPDATE tosh_match SET holat='tugadi', sabab='bekor' WHERE tur='dost' AND holat='kutmoqda' AND a=?", (uid,))
        cur = conn.execute("INSERT INTO tosh_match (tur, a, a_seed, b_seed, bosh, holat, vaqt) VALUES ('dost',?,1,2,?,'kutmoqda',?)",
                           (uid, now + DOST_MUDDAT, hpcup._utc_iso(_now())))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _qabul(uid, mid):
    """Taklifni qabul qilish. (id | None, xato)."""
    now = _ep()
    conn = hpcup._connect()
    try:
        m = conn.execute("SELECT * FROM tosh_match WHERE id=? AND tur='dost'", (int(mid),)).fetchone()
        if not m:
            return None, "yoq"
        if uid in (m["a"], m["b"]):
            return m["id"], None
        if m["b"] is not None:
            return None, "band"
        if m["holat"] != "kutmoqda" or now >= (m["bosh"] or 0):
            return None, "muddat"
        cur = conn.execute("UPDATE tosh_match SET b=?, holat='ketmoqda', bosh=?, toshlar=?, navbat='a', navbat_bosh=?, zarba=0, a_ball=0, b_ball=0, b_seen=? "
                           "WHERE id=? AND b IS NULL AND holat='kutmoqda'", (uid, now, json.dumps(boshlangich()), now + 4, now, m["id"]))
        conn.commit()
        return (m["id"], None) if cur.rowcount else (None, "band")
    finally:
        conn.close()


def _bekor(uid, mid):
    conn = hpcup._connect()
    try:
        n = conn.execute("UPDATE tosh_match SET holat='tugadi', sabab='bekor' WHERE id=? AND tur='dost' AND holat='kutmoqda' AND a=?", (int(mid), uid)).rowcount
        conn.commit()
        return n > 0
    finally:
        conn.close()


def taklif_info(mid):
    """Telegram kartasi uchun: ochiq taklif bo'lsa {a, name}, aks holda None."""
    conn = hpcup._connect()
    try:
        m = conn.execute("SELECT * FROM tosh_match WHERE id=? AND tur='dost'", (int(mid),)).fetchone()
        if not m or m["b"] is not None or m["holat"] != "kutmoqda" or _ep() >= (m["bosh"] or 0):
            return None
        r = conn.execute("SELECT first_name FROM users WHERE user_id=?", (m["a"],)).fetchone()
        return {"a": m["a"], "name": (r["first_name"] if r else None) or "Sehrgar"}
    finally:
        conn.close()


def _otish(uid, oyin, shot):
    now = _ep()
    conn = hpcup._connect()
    try:
        m = conn.execute("SELECT * FROM tosh_match WHERE id=?", (int(oyin),)).fetchone()
        if not m or m["holat"] != "ketmoqda":
            return False
        berish = []
        m = _oyin_yur(conn, m, berish, now)
        yon = "a" if m["a"] == uid else "b" if m["b"] == uid else None
        if not yon or m["navbat"] != yon or now < (m["navbat_bosh"] or 0) - 0.5 or now > (m["navbat_bosh"] or 0) + NAVBAT_T + 2:
            conn.commit()
            return False
        ok = _zarba_ber(conn, m, yon, shot, berish, now)
        conn.commit()
        _berish_keyin.extend(berish)
        return ok
    finally:
        conn.close()


_berish_keyin = []


def _yozil(uid, on):
    uid, hafta = int(uid), _hafta()
    if _ep() >= _turnir_vaqti(hafta) - YOPILISH:
        return False
    conn = hpcup._connect()
    try:
        if on:
            conn.execute("INSERT OR IGNORE INTO tosh_qatnash (hafta, user_id, vaqt) VALUES (?,?,?)", (hafta, uid, hpcup._utc_iso(_now())))
        else:
            conn.execute("DELETE FROM tosh_qatnash WHERE hafta=? AND user_id=?", (hafta, uid))
        conn.commit()
        return True
    finally:
        conn.close()


async def api_tosh(request):
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
    # do'stona o'yin (Telegram taklifi bilan kelgan yangi o'quvchi ham) - saralanmagan bo'lsa ham o'ynaydi
    dostona = body.get("qabul") is not None or body.get("oyin") is not None
    if not hpcup._get_house(uid) and not dostona:
        return cors(web.json_response({"ok": False, "error": "no_house"}))
    qosh = {}
    try:
        if body.get("dost"):
            body = {"oyin": await asyncio.to_thread(_dost, uid)}
            if _cfg.get("log"):
                try:
                    await _cfg["log"](user, "tosh_dost_taklif")
                except Exception:
                    pass
        elif body.get("qabul") is not None:
            mid, xato = await asyncio.to_thread(_qabul, uid, int(body.get("qabul")))
            if xato:
                return cors(web.json_response({"ok": False, "error": xato}))
            body = {"oyin": mid}
        elif body.get("bekor") is not None:
            qosh["bekor_ok"] = await asyncio.to_thread(_bekor, uid, int(body.get("bekor")))
        elif body.get("shot") is not None and body.get("oyin") is not None:
            qosh["shot_ok"] = await asyncio.to_thread(_otish, uid, int(body.get("oyin")), body.get("shot") if isinstance(body.get("shot"), dict) else {})
            while _berish_keyin:
                u, ref, pts = _berish_keyin.pop()
                if pts > 0 and u and u > 0:
                    await asyncio.to_thread(hpcup._award, u, "dars", ref, pts)
        elif body.get("mashq") is not None:
            daraja = body.get("mashq")
            mid = await asyncio.to_thread(_mashq, uid, daraja)
            body = {"oyin": mid}
            if _cfg.get("log"):
                try:
                    await _cfg["log"](user, "tosh_mashq_%s" % daraja)
                except Exception:
                    pass
        elif body.get("sinov") and uid in (_cfg.get("admin_ids") or ()):
            body = {"oyin": await asyncio.to_thread(_sinov, uid)}
        elif body.get("join") is not None:
            qosh["join_ok"] = await asyncio.to_thread(_yozil, uid, bool(body.get("join")))
    except (TypeError, ValueError):
        return cors(web.json_response({"ok": False, "error": "bad"}, status=400))
    javob = await asyncio.to_thread(_holat, uid, body.get("oyin"), body.get("seen"))
    while _berish_keyin:
        u, ref, pts = _berish_keyin.pop()
        if pts > 0 and u and u > 0:
            await asyncio.to_thread(hpcup._award, u, "dars", ref, pts)
    javob.update(qosh)
    return cors(web.json_response(javob))


def register(app, cfg):
    """cfg: verify_init_data, cors, log, xat, elon, admin_ids."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/tosh", api_tosh)
    logging.info("Toshchalar ulandi")
