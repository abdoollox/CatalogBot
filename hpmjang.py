"""Maxluqlar jangi (kartochkalar jangi) - SHANBA turniri (egasi, 2026-10-14). Darslarda yo'q, o'ziga xos o'yin: hisob-kitob.

KARTALAR: Qo'riqxonaning 12 maxluqi. Har birining uchta kuchi bor - Kuch (k), Himoya (h), Chaqqonlik (c) - yig'indisi hammada
bir xil (15), farqi - qaysi kuchi baland. Har maxluqning unsuri: olov / suv / havo. Olov havoni, havo suvni, suv olovni yengadi -
yenggan unsur o'sha raundda +USTUN_BONUS.

O'YIN (ikki kishi): 12 kartadan 10 tasi tasodifan tanlanib, 5 tadan bo'lib beriladi; ikkala qo'l ham ochiq (kim qaysi kartani
ishlatgani ham ko'rinadi). Raundda HUJUM qiluvchi karta va kuchni (k/h/c) tanlaydi - ochiladi; raqib uni ko'rib JAVOB kartasini
tanlaydi; o'sha kuch bo'yicha solishtiriladi (unsur ustunligi bilan), kuchlisi raundni oladi. Raundni yutgan keyingi raundda hujum
qiladi (teng bo'lsa - navbat raqibga o'tadi), birinchi hujum - tasodifiy. Har karta bir marta. 3 raund yutgan - g'olib; 5 raunddan
keyin teng bo'lsa - kuchlar yig'indisi, baribir teng: turnirda to'rda yuqori turgan o'tadi, boshqa o'yinda durang.
NEGA SHUNDAY (hisob bilan tekshirilgan, 2026-10-14): «ikkalasi bir vaqtda, kuch oldindan ma'lum» qoidasida aqlli o'yin oddiysidan
deyarli ustun emas edi (omad o'yini); hujum navbati almashib tursa birinchi hujum qilgan ~80 % yutardi; «yutgan hujum qiladi» -
~55 %. Hozirgi qoidada eng aqlli o'yinchi oddiy (eng kuchli kartani tashlaydigan) o'yinchini ~86 % yutadi.
O'Z MAXLUQI (Qo'riqxona) - kichik, lekin haqiqiy ustunlik: qo'lga tushgan karta o'quvchining o'z maxluqi bo'lsa, ENG KUCHLI tomoniga
o'smir +0,5 (teng bo'lsa yutadi), katta +1 (`OSIRISH`). Hamma maxluqi katta raqibga qarshi maxluqsiz, lekin aqlli o'yinchi ~25 %,
oddiy o'ynaydigan «katta»lar egasini ~53 % yutadi - ya'ni o'stirish yordam beradi, lekin g'alabani hisob-kitob hal qiladi
(egasi: «mahorat hal qilsin»). Maxluqi yo'q o'quvchi ham to'liq o'ynaydi.
Vaqt: har tanlovga RAUND_T soniya; ulgurmagan o'yinchiga tasodifiy karta (hujumda - eng kuchli tomoni bilan); ikki marta ketma-ket
ulgurmagan va ko'rinmagan o'yinchi yutqazadi (kelmadi).

MASHQ: kompyuter raqiblar (3 daraja), ballsiz. DO'ST BILAN: taklif (Telegram chatiga karta - main.py /api/taklif), ballsiz.
TURNIR: shanba 22:00 (toshchalar/shaxmat qolipida), ball: g'alaba uchun 1/8 +5, chorak +10, yarim final +20, final +30.

So'rovlar - POST /api/mjang: {} holat, {join: 1|0}, {mashq: 1|2|3}, {oyin: id} o'yin holati,
{oyin: id, hujum: {i, s}} hujum, {oyin: id, javob: j} javob, {sinov: 1} (admin), {dost: 1}, {qabul: id}, {bekor: id}.
"""

import asyncio
import json
import logging
import random
from datetime import datetime, timedelta
from functools import lru_cache

from aiohttp import web

import hpcup
import hpdars
import hpgolib
import hpqoriq

BOSH_HAFTA = "2026-10-19"     # birinchi turnir shu haftada (shanba 24-oktabr)
TURNIR_KUN = 5                # shanba
SOAT = 22
YOPILISH = 300                # yozilish turnirdan shuncha soniya oldin yopiladi, to'r tuziladi
ORALIQ = 45                   # ikkala raqib aniqlangach keyingi o'yin shuncha soniyadan keyin
TUGASH = 3 * 3600
BOSQICH_BALL = {16: 5, 8: 10, 4: 20, 2: 30}

QOL = 5                       # har kimga karta
YUTISH = 3                    # shuncha raund yutgan - g'olib
RAUND_T = 30                  # har tanlovga (egasi 2026-10-14 sinab ko'rdi: 20 soniya o'ylashga yetmadi - karta o'zi qo'yilib qolardi)
PAUZA = 4.5                   # raund natijasi ko'rsatiladi, keyin keyingi raund
BOSH_KUT = 3                  # o'yin boshlanishidan oldin
KELMADI_SKIP = 2
KORINDI_T = 45
DOST_MUDDAT = 1800
USTUN_BONUS = 2
OSIRISH = {0: 0, 1: 0.5, 2: 1}  # Qo'riqxonadagi bosqich (bola / o'smir / katta) -> eng kuchli tomoniga qo'shimcha
KUCHLAR = ("k", "h", "c")

# kod: (unsur, kuch, himoya, chaqqonlik) - yig'indisi 15
KARTALAR = {
    "gippo":      ("havo", 7, 3, 5),
    "boyogli":    ("havo", 2, 4, 9),
    "niffler":    ("olov", 3, 4, 8),
    "flobber":    ("suv", 1, 9, 5),
    "testral":    ("havo", 6, 5, 4),
    "qurbaqa":    ("suv", 3, 5, 7),
    "kalmar":     ("suv", 8, 6, 1),
    "boutrakl":   ("suv", 4, 8, 3),
    "salamandra": ("olov", 6, 6, 3),
    "mushuk":     ("havo", 5, 2, 8),
    "kalamush":   ("olov", 2, 5, 8),
    "ajdar":      ("olov", 9, 4, 2),
}
USTUN = {"olov": "havo", "havo": "suv", "suv": "olov"}      # kalit qiymatni yengadi

BOT_UID0 = -9400              # kompyuter raqiblar: BOT_UID0 - daraja
BOTLAR = {1: ("Luna Lavgud", "ravenclaw"), 2: ("Charli Uizli", "gryffindor"), 3: ("Nyut Skamander", "hufflepuff")}
BOT_XATO = 0.15               # qiyin kompyuter ham ba'zan oddiy yuradi
BOT_FIKR = 1.5                # kompyuter shuncha soniya «o'ylaydi»

_cfg = {}
_ozgargan = set()             # holati o'zgargan do'stona o'yinlar - chatdagi taklif kartasi yangilanadi (_dost_xabar)


def _now():
    return hpcup.now_tk()


def _ep():
    return _now().timestamp()


def _init():
    conn = hpcup._connect()
    try:
        conn.execute(hpcup.MJ_MATCH_DDL)            # DDL hpcup da - chat kartasi so'rovi shu jadvalga ulanadi
        conn.execute("CREATE INDEX IF NOT EXISTS mj_match_hafta ON mj_match (hafta, bosqich, joy)")
        conn.execute("CREATE TABLE IF NOT EXISTS mj_turnir (hafta TEXT PRIMARY KEY, hajm INTEGER NOT NULL DEFAULT 0, vaqt TEXT)")
        conn.execute("CREATE TABLE IF NOT EXISTS mj_qatnash (hafta TEXT NOT NULL, user_id INTEGER NOT NULL, vaqt TEXT NOT NULL, PRIMARY KEY (hafta, user_id))")
        conn.execute("CREATE TABLE IF NOT EXISTS mj_eslatma (hafta TEXT NOT NULL, tur TEXT NOT NULL, PRIMARY KEY (hafta, tur))")
        conn.commit()
    finally:
        conn.close()


# =====================================================================  KARTALAR

def eng_kuchli(kod):
    u, k, h, c = KARTALAR[kod]
    return max(KUCHLAR, key=lambda s: {"k": k, "h": h, "c": c}[s])


def kuch(karta, stat, raqib=None):
    """Kartaning kuchi: o'sha tomoni + o'stirish qo'shimchasi (eng kuchli tomoniga) + unsur ustunligi. karta: {k, o}."""
    u, k, h, c = KARTALAR[karta["k"]]
    v = {"k": k, "h": h, "c": c}[stat]
    if karta.get("o") and stat == eng_kuchli(karta["k"]):
        v += karta["o"]
    if raqib and USTUN[u] == KARTALAR[raqib["k"]][0]:
        v += USTUN_BONUS
    return v


def _bosqichlar(conn, uid):
    """{kod: bosqich} - o'quvchining o'z maxluqlari (0 bola, 1 o'smir, 2 katta)."""
    if uid is None or uid < 0:
        return {}
    try:
        hpqoriq._yangila(conn, uid)
    except Exception:
        pass
    return {r["kod"]: hpqoriq.bosqich(r["boqildi"]) for r in conn.execute("SELECT kod, boqildi FROM qoriq WHERE user_id=?", (uid,))}


def tarqat(conn, a, b, rnd=random):
    """10 ta tasodifiy karta, 5 tadan. Har karta: {k, o (o'stirish qo'shimchasi), st (Qo'riqxonadagi bosqich yoki -1)}."""
    kod = rnd.sample(list(KARTALAR), QOL * 2)
    out = []
    for uid, qism in ((a, kod[:QOL]), (b, kod[QOL:])):
        bq = _bosqichlar(conn, uid)
        out.append([{"k": k, "o": OSIRISH.get(bq.get(k, 0), 0) if k in bq else 0, "st": bq.get(k, -1)} for k in qism])
    return out


# =====================================================================  HISOB (kompyuter uchun)

def _keyingi(nav, lw, rw):
    """Raundni yutgan keyingi raundda hujum qiladi; teng bo'lsa - navbat raqibga."""
    return nav if lw else ("b" if nav == "a" else "a")


def _yechim(A, B):
    """Ochiq o'yin: V(ra, rb, wa, wb, nav) - 'a' uchun kutilgan natija (1 g'alaba, 0 mag'lubiyat, 0,5 durang), ikkalasi aqlli o'ynasa."""
    @lru_cache(None)
    def V(ra, rb, wa, wb, nav):
        if wa >= YUTISH:
            return 1.0
        if wb >= YUTISH:
            return 0.0
        if not ra or not rb:
            return 1.0 if wa > wb else 0.0 if wb > wa else 0.5
        L, R = (ra, rb) if nav == "a" else (rb, ra)
        LD, RD = (A, B) if nav == "a" else (B, A)
        eng = None
        for i in L:
            for s in KUCHLAR:
                yomon = None
                for j in R:
                    vl, vr = kuch(LD[i], s, RD[j]), kuch(RD[j], s, LD[i])
                    lw, rw = vl > vr, vr > vl
                    nl = _keyingi(nav, lw, rw) if lw or rw else ("b" if nav == "a" else "a")
                    if nav == "a":
                        v = V(ra - {i}, rb - {j}, wa + lw, wb + rw, nl)
                        yomon = v if yomon is None else min(yomon, v)
                    else:
                        v = V(ra - {j}, rb - {i}, wa + rw, wb + lw, nl)
                        yomon = v if yomon is None else max(yomon, v)
                eng = yomon if eng is None else (max(eng, yomon) if nav == "a" else min(eng, yomon))
        return eng
    return V


def _qolgan(qol, tarix, yon):
    ish = {r[yon]["i"] for r in tarix}
    return frozenset(i for i in range(len(qol)) if i not in ish)


def kompyuter_hujum(A, B, tarix, yon, wa, wb, d, rnd=random):
    """yon ('a'|'b') hujum qiladi: (karta indeksi, kuch)."""
    men, u = (A, B) if yon == "a" else (B, A)
    bor = sorted(_qolgan(men, tarix, yon))
    if d <= 1:
        i = rnd.choice(bor)
        return i, rnd.choice(KUCHLAR)
    if d == 2 or rnd.random() < BOT_XATO:
        return max(((i, s) for i in bor for s in KUCHLAR), key=lambda p: (kuch(men[p[0]], p[1]), rnd.random()))
    V = _yechim(A, B)
    ra, rb = _qolgan(A, tarix, "a"), _qolgan(B, tarix, "b")
    raq = rb if yon == "a" else ra
    eng, tan = None, None
    for i in bor:
        for s in KUCHLAR:
            yomon = None
            for j in raq:
                vl, vr = kuch(men[i], s, u[j]), kuch(u[j], s, men[i])
                lw, rw = vl > vr, vr > vl
                nl = yon if lw else ("b" if yon == "a" else "a")
                if yon == "a":
                    v = V(ra - {i}, rb - {j}, wa + lw, wb + rw, nl)
                else:
                    v = 1 - V(ra - {j}, rb - {i}, wa + rw, wb + lw, nl)
                yomon = v if yomon is None else min(yomon, v)
            q = yomon + rnd.random() * 1e-6
            if eng is None or q > eng:
                eng, tan = q, (i, s)
    return tan


def kompyuter_javob(A, B, tarix, yon, wa, wb, hujum, d, rnd=random):
    """yon javob beradi: karta indeksi. hujum: {i, s} - raqibning ochilgan kartasi."""
    men, u = (A, B) if yon == "a" else (B, A)
    bor = sorted(_qolgan(men, tarix, yon))
    hk, s = u[hujum["i"]], hujum["s"]
    if d <= 1:
        return rnd.choice(bor)
    if d == 2 or rnd.random() < BOT_XATO:
        yutadi = [j for j in bor if kuch(men[j], s, hk) > kuch(hk, s, men[j])]
        if yutadi:
            return min(yutadi, key=lambda j: (kuch(men[j], s, hk), rnd.random()))
        return min(bor, key=lambda j: (max(KARTALAR[men[j]["k"]][1:]), rnd.random()))
    V = _yechim(A, B)
    ra, rb = _qolgan(A, tarix, "a"), _qolgan(B, tarix, "b")
    hy = "b" if yon == "a" else "a"
    eng, tan = None, bor[0]
    for j in bor:
        vl, vr = kuch(hk, s, men[j]), kuch(men[j], s, hk)
        lw, rw = vl > vr, vr > vl
        nl = hy if lw else yon
        if yon == "b":
            v = 1 - V(ra - {hujum["i"]}, rb - {j}, wa + lw, wb + rw, nl)
        else:
            v = V(ra - {j}, rb - {hujum["i"]}, wa + rw, wb + lw, nl)
        q = v + rnd.random() * 1e-6
        if eng is None or q > eng:
            eng, tan = q, j
    return tan


# =====================================================================  O'YIN

def _bot(uid):
    return uid is not None and uid < 0


def _boshlash(conn, mid, a, b, faza_bosh, rnd=random):
    qa, qb = tarqat(conn, a, b, rnd)
    conn.execute("UPDATE mj_match SET holat='ketmoqda', a_qol=?, b_qol=?, navbat=?, hujum=NULL, faza_bosh=?, tarix='[]', a_win=0, b_win=0, "
                 "a_skip=0, b_skip=0 WHERE id=?", (json.dumps(qa), json.dumps(qb), rnd.choice("ab"), faza_bosh, mid))


def _yangi_oyin(conn, tur, a, b, bosh, rnd=random, **qosh):
    cur = conn.execute("INSERT INTO mj_match (tur, a, b, bosh, holat, vaqt, hafta, bosqich, joy, a_seed, b_seed, daraja) "
                       "VALUES (?,?,?,?,'kutmoqda',?,?,?,?,?,?,?)",
                       (tur, a, b, bosh, hpcup._utc_iso(_now()), qosh.get("hafta"), qosh.get("bosqich"), qosh.get("joy"),
                        qosh.get("a_seed"), qosh.get("b_seed"), qosh.get("daraja")))
    _boshlash(conn, cur.lastrowid, a, b, bosh + BOSH_KUT, rnd)
    return cur.lastrowid


def _yakunla(conn, m, golib_yon, sabab, berish, now):
    golib = m[golib_yon] if golib_yon else None
    if golib is None and m["tur"] in ("turnir", "sinov"):
        golib = m["a"] if (m["a_seed"] or 99) <= (m["b_seed"] or 99) else m["b"]
        sabab = "teng"
    conn.execute("UPDATE mj_match SET holat='tugadi', golib=?, sabab=?, navbat=NULL, hujum=NULL WHERE id=?", (golib, sabab, m["id"]))
    if m["tur"] == "turnir":
        _tor_keyingi(conn, dict(m), golib, sabab, berish, now)
    if m["tur"] == "dost":
        _ozgargan.add(m["id"])


def _hujum_qoy(conn, m, i, s, now):
    conn.execute("UPDATE mj_match SET hujum=?, faza_bosh=? WHERE id=?", (json.dumps({"i": int(i), "s": s}), now, m["id"]))


def _javob_qoy(conn, m, j, berish, now):
    """Javob - raund natijasi."""
    tarix = json.loads(m["tarix"] or "[]")
    A, B = json.loads(m["a_qol"]), json.loads(m["b_qol"])
    nav = m["navbat"]
    h = json.loads(m["hujum"])
    s = h["s"]
    ia, ib = (h["i"], j) if nav == "a" else (j, h["i"])
    ka, kb = A[ia], B[ib]
    va, vb = kuch(ka, s, kb), kuch(kb, s, ka)
    w = "a" if va > vb else "b" if vb > va else None
    tarix.append({"r": len(tarix), "by": nav, "s": s, "w": w,
                  "a": {"i": ia, "k": ka["k"], "v": va, "u": USTUN[KARTALAR[ka["k"]][0]] == KARTALAR[kb["k"]][0]},
                  "b": {"i": ib, "k": kb["k"], "v": vb, "u": USTUN[KARTALAR[kb["k"]][0]] == KARTALAR[ka["k"]][0]}})
    aw, bw = m["a_win"] + (w == "a"), m["b_win"] + (w == "b")
    keyingi = w if w else ("b" if nav == "a" else "a")
    conn.execute("UPDATE mj_match SET tarix=?, a_win=?, b_win=?, navbat=?, hujum=NULL, faza_bosh=? WHERE id=?",
                 (json.dumps(tarix, separators=(",", ":")), aw, bw, keyingi, now + PAUZA, m["id"]))
    if aw >= YUTISH or bw >= YUTISH or len(tarix) >= QOL:
        if aw != bw:
            gy = "a" if aw > bw else "b"
        else:
            sa, sb = sum(r["a"]["v"] for r in tarix), sum(r["b"]["v"] for r in tarix)
            gy = "a" if sa > sb else "b" if sb > sa else None
        m2 = conn.execute("SELECT * FROM mj_match WHERE id=?", (m["id"],)).fetchone()
        _yakunla(conn, m2, gy, "oyin", berish, now)


def _ulgurmadi(conn, m, yon, berish, now):
    """Vaqtida tanlamadi: True - o'yin tugadi (kelmadi)."""
    korindi = (m[yon + "_seen"] or 0) >= now - KORINDI_T
    if m[yon + "_skip"] + 1 >= KELMADI_SKIP and not korindi:
        _yakunla(conn, m, "b" if yon == "a" else "a", "kelmadi", berish, now)
        return True
    conn.execute("UPDATE mj_match SET %s_skip=%s_skip+1 WHERE id=?" % (yon, yon), (m["id"],))
    return False


def _oyin_yur(conn, m, berish, now, rnd=random):
    """O'yinni hozirgi vaqtga keltiradi: kompyuter yurishi, vaqt tugashi, kelmaganlar."""
    for _ in range(QOL * 2 + 2):
        if m["holat"] != "ketmoqda" or now < (m["faza_bosh"] or 0):
            return m
        tarix = json.loads(m["tarix"] or "[]")
        A, B = json.loads(m["a_qol"]), json.loads(m["b_qol"])
        nav = m["navbat"]
        javobchi = "b" if nav == "a" else "a"
        kim = javobchi if m["hujum"] else nav
        d = m["daraja"] or (BOT_UID0 - m[kim] if _bot(m[kim]) else 0)
        fb = m["faza_bosh"] or now           # vaqt "o'z paytida" hisoblanadi - kech kelgan so'rov ham o'yinni to'g'ri tiklaydi
        if _bot(m[kim]):
            if m["hujum"]:
                _javob_qoy(conn, m, kompyuter_javob(A, B, tarix, kim, m["a_win"], m["b_win"], json.loads(m["hujum"]), d, rnd), berish, fb + BOT_FIKR)
            else:
                i, s = kompyuter_hujum(A, B, tarix, kim, m["a_win"], m["b_win"], d, rnd)
                _hujum_qoy(conn, m, i, s, fb + BOT_FIKR)
        elif now >= fb + RAUND_T:
            if _ulgurmadi(conn, m, kim, berish, now):
                return conn.execute("SELECT * FROM mj_match WHERE id=?", (m["id"],)).fetchone()
            bor = sorted(_qolgan(A if kim == "a" else B, tarix, kim))
            i = rnd.choice(bor)
            if m["hujum"]:
                _javob_qoy(conn, m, i, berish, fb + RAUND_T)
            else:
                _hujum_qoy(conn, m, i, eng_kuchli((A if kim == "a" else B)[i]["k"]), fb + RAUND_T)
        else:
            return m
        m = conn.execute("SELECT * FROM mj_match WHERE id=?", (m["id"],)).fetchone()
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
    """Yozilganlar: mashqda kompyuterni ko'proq yengganlar yuqorida, keyin oldin yozilgan."""
    return conn.execute(
        "SELECT q.user_id, q.vaqt, COALESCE(u.first_name, 'Sehrgar') AS name, u.house, "
        " (SELECT COALESCE(SUM(m.daraja), 0) FROM mj_match m WHERE m.tur='mashq' AND m.golib=q.user_id) AS kuch "
        "FROM mj_qatnash q JOIN users u ON u.user_id = q.user_id "
        "WHERE q.hafta=? AND u.house IS NOT NULL AND q.user_id > 0 ORDER BY kuch DESC, q.vaqt ASC", (hafta,)).fetchall()


def _tor_keyingi(conn, m, golib, sabab, berish, now):
    if sabab != "bye" and golib and golib > 0:
        berish.append((golib, "mjang:%s:%d" % (m["hafta"], m["bosqich"]), BOSQICH_BALL.get(m["bosqich"], 0)))
    nb = m["bosqich"] // 2
    if nb < 2:
        return
    yon = "a" if m["joy"] % 2 == 0 else "b"
    seed = m["a_seed"] if golib == m["a"] else m["b_seed"]
    conn.execute("UPDATE mj_match SET %s=?, %s_seed=? WHERE tur='turnir' AND hafta=? AND bosqich=? AND joy=?" % (yon, yon),
                 (golib, seed, m["hafta"], nb, m["joy"] // 2))
    k = conn.execute("SELECT * FROM mj_match WHERE tur='turnir' AND hafta=? AND bosqich=? AND joy=?", (m["hafta"], nb, m["joy"] // 2)).fetchone()
    if k["a"] is not None and k["b"] is not None and k["bosh"] is None:
        conn.execute("UPDATE mj_match SET bosh=? WHERE id=?", (max(_turnir_vaqti(m["hafta"]), now + ORALIQ), k["id"]))


def _tor_tuz(conn, hafta, berish, now):
    if now < _turnir_vaqti(hafta) - YOPILISH:
        return
    if conn.execute("INSERT OR IGNORE INTO mj_turnir (hafta, hajm, vaqt) VALUES (?,0,?)", (hafta, hpcup._utc_iso(_now()))).rowcount < 1:
        return
    rows = _qatnashchilar(conn, hafta)
    n = len(rows)
    if n < 2:
        return
    hajm = 2
    while hajm < n:
        hajm *= 2
    conn.execute("UPDATE mj_turnir SET hajm=? WHERE hafta=?", (hajm, hafta))
    s = hajm
    while s >= 2:
        for i in range(s // 2):
            conn.execute("INSERT INTO mj_match (tur, hafta, bosqich, joy, holat) VALUES ('turnir',?,?,?,'kutmoqda')", (hafta, s, i))
        s //= 2
    t, T0 = _tartib(hajm), _turnir_vaqti(hafta)
    for i in range(hajm // 2):
        a, b = t[2 * i], t[2 * i + 1]
        conn.execute("UPDATE mj_match SET a=?, a_seed=?, b=?, b_seed=?, bosh=? WHERE tur='turnir' AND hafta=? AND bosqich=? AND joy=?",
                     (rows[a - 1]["user_id"], a, rows[b - 1]["user_id"] if b <= n else None, b if b <= n else None, T0, hafta, hajm, i))
        if b > n:
            m = conn.execute("SELECT * FROM mj_match WHERE tur='turnir' AND hafta=? AND bosqich=? AND joy=?", (hafta, hajm, i)).fetchone()
            conn.execute("UPDATE mj_match SET holat='tugadi', golib=?, sabab='bye' WHERE id=?", (m["a"], m["id"]))
            _tor_keyingi(conn, dict(m), m["a"], "bye", berish, now)


def _turnir_boshla(conn, now):
    """Vaqti kelgan turnir uchrashuvlarini boshlaydi: to'plamlar shu paytda suratga olinadi."""
    for m in conn.execute("SELECT * FROM mj_match WHERE tur='turnir' AND holat='kutmoqda' AND a IS NOT NULL AND b IS NOT NULL "
                          "AND bosh IS NOT NULL AND bosh<=?", (now,)).fetchall():
        _boshlash(conn, m["id"], m["a"], m["b"], max(now, m["bosh"]) + BOSH_KUT + 3)


def _eslatmalar(conn, hafta, xabarlar):
    hozir = _now()
    T0 = _turnir_vaqti(hafta)
    if hozir.timestamp() >= T0 or datetime.fromtimestamp(T0, hozir.tzinfo).date() != hozir.date():
        return
    daq = hozir.hour * 60 + hozir.minute
    tur = "on" if SOAT * 60 - 10 <= daq < SOAT * 60 else "ertalab" if 600 <= daq < SOAT * 60 - 10 else None
    if not tur:
        return
    if conn.execute("INSERT OR IGNORE INTO mj_eslatma (hafta, tur) VALUES (?,?)", (hafta, tur)).rowcount < 1:
        return
    if tur == "ertalab" and hafta == BOSH_HAFTA:
        xabarlar.append((0, "elon"))
        return
    for r in conn.execute("SELECT user_id FROM mj_qatnash WHERE hafta=?", (hafta,)).fetchall():
        xabarlar.append((r["user_id"], tur))


def _tick(rnd=random):
    berish, xabarlar = [], []
    hafta, now = _hafta(), _ep()
    conn = hpcup._connect()
    try:
        _tor_tuz(conn, hafta, berish, now)
        _turnir_boshla(conn, now)
        for m in conn.execute("SELECT * FROM mj_match WHERE holat='ketmoqda'").fetchall():
            _oyin_yur(conn, m, berish, now, rnd)
        for r in conn.execute("SELECT id FROM mj_match WHERE tur='dost' AND holat='kutmoqda' AND bosh < ?", (now,)).fetchall():
            _ozgargan.add(r["id"])
        conn.execute("UPDATE mj_match SET holat='tugadi', sabab='muddat' WHERE tur='dost' AND holat='kutmoqda' AND bosh < ?", (now,))
        conn.execute("UPDATE mj_match SET holat='tugadi', sabab='tashlandi' WHERE holat='ketmoqda' AND tur IN ('mashq','sinov','dost') AND bosh < ?", (now - 3600,))
        _eslatmalar(conn, hafta, xabarlar)
        conn.commit()
    finally:
        conn.close()
    return berish, xabarlar


def xat_matni(tur):
    if tur == "elon":
        return {"uz": ("Bugun 22:00 da birinchi Maxluqlar jangi!", "Qo'riqxonadagi maxluqlaringiz endi kartochka bo'lib jangga chiqadi: har raundda bitta karta, kim kuchli — o'sha yutadi. Maxluqi yo'q o'quvchilarga maktab kartalari beriladi. Ilovada: Xogvarts → Maxluqlar jangi. Kompyuter bilan mashq qilib, «Qatnashaman»ni bosing. G'olibga +30 ball."),
                "ru": ("Сегодня в 22:00 первая Битва существ!", "Ваши существа из заповедника выходят на бой в виде карточек: в каждом раунде одна карта, побеждает сильнейшая. У кого нет существ — получат школьные карты. В приложении: Хогвартс → Битва существ. Потренируйтесь и нажмите «Участвую». Победителю +30 очков."),
                "en": ("The first Creature Battle is today at 22:00!", "Your creatures from the sanctuary now fight as cards: one card per round, the stronger one wins. No creatures yet? You get school cards. In the app: Hogwarts → Creature Battle. Practise and tap “I'm in”. +30 points for the winner.")}
    if tur == "ertalab":
        return {"uz": ("Bugun 22:00 da Maxluqlar jangi", "Siz turnirga yozilgansiz. Soat 22:00 da ilovaga kiring: Xogvarts → Maxluqlar jangi. Har tanlovga 30 soniya beriladi."),
                "ru": ("Сегодня в 22:00 Битва существ", "Вы записаны. Зайдите в 22:00: Хогвартс → Битва существ. На каждый выбор — 30 секунд."),
                "en": ("The Creature Battle is today at 22:00", "You are signed up. Come in at 22:00: Hogwarts → Creature Battle. You have 30 seconds for each choice.")}
    return {"uz": ("Turnirga 10 daqiqa qoldi!", "Maxluqlar jangi 22:00 da boshlanadi. Hoziroq ilovaga kiring: Xogvarts → Maxluqlar jangi."),
            "ru": ("До турнира 10 минут!", "Битва существ начнётся в 22:00. Зайдите прямо сейчас: Хогвартс → Битва существ."),
            "en": ("10 minutes to the tournament!", "The Creature Battle starts at 22:00. Come in now: Hogwarts → Creature Battle.")}


async def _elon_yubor():
    try:
        n = await _cfg["elon"](xat_matni("elon"))
        logging.info("Maxluqlar jangi e'loni yuborildi: %s kishi", n)
    except Exception as e:
        logging.error("Maxluqlar jangi e'loni yuborilmadi: %s", e)


async def _dost_xabar():
    """Holati o'zgargan do'stona o'yinlarning chatdagi kartalarini yangilaydi (hpbot bergan chaqiruv orqali)."""
    fn = _cfg.get("dost_ozgardi")
    while _ozgargan:
        mid = _ozgargan.pop()
        if fn:
            try:
                await fn(mid)
            except Exception as e:
                logging.error("mjang kartasi yangilanmadi (%s): %s", mid, e)


async def dost_yarat(uid):
    """Chatdan taklif (hpbot): yangi do'stona o'yin, id."""
    mid = await asyncio.to_thread(_dost, int(uid))
    await _dost_xabar()
    return mid


async def tick():
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
                logging.error("Maxluqlar jangi xati yuborilmadi (%s): %s", uid, e)


async def kuzatuvchi(interval=15):
    while True:
        try:
            await tick()
        except Exception as e:
            logging.error("Maxluqlar jangi kuzatuvchisi: %s", e)
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


def _oyin_holat(conn, m, uid, now):
    men = "a" if m["a"] == uid else "b" if m["b"] == uid else None
    if men:
        conn.execute("UPDATE mj_match SET %s_seen=? WHERE id=?" % men, (now, m["id"]))
    tarix = json.loads(m["tarix"] or "[]")
    if m["holat"] != "ketmoqda":
        faza = "over" if m["holat"] == "tugadi" else "wait"
    elif now < (m["faza_bosh"] or 0):
        faza = "wait"
    else:
        faza = "answer" if m["hujum"] else "attack"
    return {"id": m["id"], "kind": m["tur"], "state": m["holat"], "me": men,
            "a": _ism(conn, m["a"]) if m["a"] is not None else None, "b": _ism(conn, m["b"]) if m["b"] is not None else None,
            "hand": {"a": json.loads(m["a_qol"] or "[]"), "b": json.loads(m["b_qol"] or "[]")},
            "turn": m["navbat"], "attack": json.loads(m["hujum"]) if m["hujum"] else None, "phase": faza, "hist": tarix,
            "wins": [m["a_win"], m["b_win"]], "in": max(0, round((m["faza_bosh"] or 0) - now, 2)), "turn_t": RAUND_T,
            "left": max(0, round((m["faza_bosh"] or 0) + RAUND_T - now, 2)),
            "winner": ("a" if m["golib"] == m["a"] else "b") if m["golib"] is not None else None, "why": m["sabab"], "stage": m["bosqich"],
            "starts_in": max(0, round((m["bosh"] or 0) - now, 1)) if m["holat"] == "kutmoqda" and m["tur"] != "dost" else 0,
            "expires_in": max(0, round((m["bosh"] or 0) - now)) if m["holat"] == "kutmoqda" and m["tur"] == "dost" else None}


def _kartalar(conn, uid):
    bq = _bosqichlar(conn, uid)
    out = []
    for k in hpqoriq.MAXLUQLAR:
        u, a, h, c = KARTALAR[k]
        out.append({"k": k, "u": u, "s": [a, h, c], "top": eng_kuchli(k), "st": bq.get(k, -1), "o": OSIRISH.get(bq.get(k, 0), 0) if k in bq else 0})
    return out


def _holat(uid, oyin=None):
    uid, hafta, now = int(uid), _hafta(), _ep()
    conn = hpcup._connect()
    try:
        if oyin is not None:
            m = conn.execute("SELECT * FROM mj_match WHERE id=?", (int(oyin),)).fetchone()
            if not m:
                return {"ok": False, "error": "yoq"}
            berish = []
            m = _oyin_yur(conn, m, berish, now)
            _berish_keyin.extend(berish)
            g = _oyin_holat(conn, m, uid, now)
            conn.commit()
            return {"ok": True, "game": g}
        T0 = _turnir_vaqti(hafta)
        qat = _qatnashchilar(conn, hafta)
        tr = conn.execute("SELECT hajm FROM mj_turnir WHERE hafta=?", (hafta,)).fetchone()
        javob = {"ok": True, "now": now,
                 "tour": {"ts": T0, "now": now, "open": now < T0 - YOPILISH, "joined": any(r["user_id"] == uid for r in qat), "n": len(qat), "close": YOPILISH,
                          "players": [{"uid": r["user_id"], "name": hpdars._ism(r["name"]), "house": r["house"], "me": r["user_id"] == uid} for r in qat]},
                 "rules": {"hand": QOL, "win": YUTISH, "turn": RAUND_T, "edge": USTUN_BONUS, "gap": ORALIQ,
                           "grow": {str(k): v for k, v in OSIRISH.items()},
                           "points": {str(k): v for k, v in BOSQICH_BALL.items()}, "bots": {str(k): v[0] for k, v in BOTLAR.items()}},
                 "cards": _kartalar(conn, uid),
                 "champs": hpgolib.tor(conn, "mj_match", hafta, "mjang", uid, "SELECT COUNT(*) FROM mj_qatnash WHERE hafta=?", _turnir_vaqti),
                 "admin": uid in (_cfg.get("admin_ids") or ()),
                 "stats": dict(zip(("played", "won"), conn.execute("SELECT COUNT(*), COALESCE(SUM(golib=?), 0) FROM mj_match WHERE (a=? OR b=?) AND holat='tugadi' "
                                                                   "AND sabab NOT IN ('bekor','muddat','tashlandi','bye')", (uid, uid, uid)).fetchone())),
                 "cup": {"size": tr["hajm"] if tr else None}}
        faol = conn.execute("SELECT id, tur FROM mj_match WHERE holat IN ('ketmoqda','kutmoqda') AND (a=? OR b=?) AND tur IN ('mashq','sinov','turnir') "
                            "AND (tur != 'turnir' OR (bosh IS NOT NULL AND bosh <= ?)) ORDER BY id DESC LIMIT 1", (uid, uid, now + ORALIQ + 5)).fetchone()
        if faol:
            javob["active"] = {"id": faol["id"], "kind": faol["tur"]}
        if tr and tr["hajm"]:
            ms = conn.execute("SELECT * FROM mj_match WHERE tur='turnir' AND hafta=? ORDER BY bosqich DESC, joy", (hafta,)).fetchall()
            stages = {}
            for m in ms:
                stages.setdefault(m["bosqich"], []).append({
                    "id": m["id"], "a": _ism(conn, m["a"]) if m["a"] else None, "b": _ism(conn, m["b"]) if m["b"] else None,
                    "score": [m["a_win"], m["b_win"]], "state": m["holat"], "winner": m["golib"], "why": m["sabab"],
                    "mine": uid in (m["a"], m["b"]), "ts": m["bosh"]})
            javob["cup"]["stages"] = [{"stage": s, "points": BOSQICH_BALL.get(s, 0), "matches": stages[s]} for s in sorted(stages, reverse=True)]
        conn.commit()
        return javob
    finally:
        conn.close()


def _mashq(uid, d):
    d = max(1, min(3, int(d)))
    now = _ep()
    conn = hpcup._connect()
    try:
        conn.execute("UPDATE mj_match SET holat='tugadi', sabab='tashlandi' WHERE holat='ketmoqda' AND tur IN ('mashq','sinov') AND a=?", (uid,))
        mid = _yangi_oyin(conn, "mashq", uid, BOT_UID0 - d, now, daraja=d)
        conn.commit()
        return mid
    finally:
        conn.close()


def _sinov(uid):
    """Admin: turnir o'yini oqimi kompyuter (2-daraja) bilan, ballsiz."""
    now = _ep()
    conn = hpcup._connect()
    try:
        conn.execute("UPDATE mj_match SET holat='tugadi', sabab='tashlandi' WHERE holat='ketmoqda' AND tur IN ('mashq','sinov') AND a=?", (uid,))
        mid = _yangi_oyin(conn, "sinov", uid, BOT_UID0 - 2, now + 5, daraja=2, a_seed=1, b_seed=2, bosqich=2)
        conn.commit()
        return mid
    finally:
        conn.close()


def _dost(uid):
    now = _ep()
    conn = hpcup._connect()
    try:
        for r in conn.execute("SELECT id FROM mj_match WHERE tur='dost' AND holat='kutmoqda' AND a=?", (uid,)).fetchall():
            _ozgargan.add(r["id"])
        conn.execute("UPDATE mj_match SET holat='tugadi', sabab='bekor' WHERE tur='dost' AND holat='kutmoqda' AND a=?", (uid,))
        cur = conn.execute("INSERT INTO mj_match (tur, a, a_seed, b_seed, bosh, holat, vaqt) VALUES ('dost',?,1,2,?,'kutmoqda',?)",
                           (uid, now + DOST_MUDDAT, hpcup._utc_iso(_now())))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _qabul(uid, mid):
    now = _ep()
    conn = hpcup._connect()
    try:
        m = conn.execute("SELECT * FROM mj_match WHERE id=? AND tur='dost'", (int(mid),)).fetchone()
        if not m:
            return None, "yoq"
        if uid in (m["a"], m["b"]):
            return m["id"], None
        if m["b"] is not None:
            return None, "band"
        if m["holat"] != "kutmoqda" or now >= (m["bosh"] or 0):
            return None, "muddat"
        cur = conn.execute("UPDATE mj_match SET b=?, bosh=?, b_seen=? WHERE id=? AND b IS NULL AND holat='kutmoqda'", (uid, now, now, m["id"]))
        if not cur.rowcount:
            return None, "band"
        _boshlash(conn, m["id"], m["a"], uid, now + BOSH_KUT + 2)
        conn.commit()
        _ozgargan.add(m["id"])
        return m["id"], None
    finally:
        conn.close()


def _bekor(uid, mid):
    conn = hpcup._connect()
    try:
        n = conn.execute("UPDATE mj_match SET holat='tugadi', sabab='bekor' WHERE id=? AND tur='dost' AND holat='kutmoqda' AND a=?", (int(mid), uid)).rowcount
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
        m = conn.execute("SELECT * FROM mj_match WHERE id=? AND tur='dost'", (int(mid),)).fetchone()
        if not m or m["b"] is not None or m["holat"] != "kutmoqda" or _ep() >= (m["bosh"] or 0):
            return None
        r = conn.execute("SELECT first_name FROM users WHERE user_id=?", (m["a"],)).fetchone()
        return {"a": m["a"], "name": (r["first_name"] if r else None) or "Sehrgar"}
    finally:
        conn.close()


def _yurish(uid, oyin, hujum=None, javob=None):
    """O'yinchi yurishi: hujum {i, s} yoki javob j. True - qabul qilindi."""
    now = _ep()
    conn = hpcup._connect()
    try:
        m = conn.execute("SELECT * FROM mj_match WHERE id=?", (int(oyin),)).fetchone()
        if not m or m["holat"] != "ketmoqda":
            return False
        berish = []
        m = _oyin_yur(conn, m, berish, now)
        _berish_keyin.extend(berish)
        yon = "a" if m["a"] == uid else "b" if m["b"] == uid else None
        if not yon or m["holat"] != "ketmoqda" or now < (m["faza_bosh"] or 0) - 0.3 or now > (m["faza_bosh"] or 0) + RAUND_T + 2:
            conn.commit()
            return False
        qol = json.loads(m[yon + "_qol"] or "[]")
        bor = _qolgan(qol, json.loads(m["tarix"] or "[]"), yon)
        if hujum is not None:
            try:
                i, s = int(hujum.get("i")), str(hujum.get("s"))
            except (TypeError, ValueError, AttributeError):
                return False
            if m["navbat"] != yon or m["hujum"] or i not in bor or s not in KUCHLAR:
                conn.commit()
                return False
            _hujum_qoy(conn, m, i, s, now)
        else:
            j = int(javob)
            if m["navbat"] == yon or not m["hujum"] or j not in bor:
                conn.commit()
                return False
            _javob_qoy(conn, m, j, berish, now)
        conn.execute("UPDATE mj_match SET %s_skip=0 WHERE id=?" % yon, (m["id"],))
        m = conn.execute("SELECT * FROM mj_match WHERE id=?", (m["id"],)).fetchone()
        _oyin_yur(conn, m, berish, now)
        conn.commit()
        _berish_keyin.extend(berish)
        return True
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
            conn.execute("INSERT OR IGNORE INTO mj_qatnash (hafta, user_id, vaqt) VALUES (?,?,?)", (hafta, uid, hpcup._utc_iso(_now())))
        else:
            conn.execute("DELETE FROM mj_qatnash WHERE hafta=? AND user_id=?", (hafta, uid))
        conn.commit()
        return True
    finally:
        conn.close()


async def _ball_ber():
    while _berish_keyin:
        u, ref, pts = _berish_keyin.pop()
        if pts > 0 and u and u > 0:
            await asyncio.to_thread(hpcup._award, u, "dars", ref, pts)


async def api_mjang(request):
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
    log = None
    try:
        if body.get("dost"):
            body = {"oyin": await asyncio.to_thread(_dost, uid)}
            log = "mjang_dost_taklif"
        elif body.get("qabul") is not None:
            mid, xato = await asyncio.to_thread(_qabul, uid, int(body.get("qabul")))
            if xato:
                return cors(web.json_response({"ok": False, "error": xato}))
            body = {"oyin": mid}
        elif body.get("bekor") is not None:
            qosh["bekor_ok"] = await asyncio.to_thread(_bekor, uid, int(body.get("bekor")))
        elif body.get("hujum") is not None and body.get("oyin") is not None:
            qosh["move_ok"] = await asyncio.to_thread(_yurish, uid, int(body.get("oyin")), body.get("hujum") if isinstance(body.get("hujum"), dict) else {}, None)
        elif body.get("javob") is not None and body.get("oyin") is not None:
            qosh["move_ok"] = await asyncio.to_thread(_yurish, uid, int(body.get("oyin")), None, int(body.get("javob")))
        elif body.get("mashq") is not None:
            body = {"oyin": await asyncio.to_thread(_mashq, uid, body.get("mashq"))}
            log = "mjang_mashq"
        elif body.get("sinov") and uid in (_cfg.get("admin_ids") or ()):
            body = {"oyin": await asyncio.to_thread(_sinov, uid)}
        elif body.get("join") is not None:
            qosh["join_ok"] = await asyncio.to_thread(_yozil, uid, bool(body.get("join")))
    except (TypeError, ValueError):
        return cors(web.json_response({"ok": False, "error": "bad"}, status=400))
    if log and _cfg.get("log"):
        try:
            await _cfg["log"](user, log)
        except Exception:
            pass
    await _ball_ber()
    javob = await asyncio.to_thread(_holat, uid, body.get("oyin"))
    await _ball_ber()
    javob.update(qosh)
    await _dost_xabar()
    return cors(web.json_response(javob))


def register(app, cfg):
    """cfg: verify_init_data, cors, log, xat, elon, admin_ids. hpqoriq DAN KEYIN ulanadi (qoriq jadvali kerak)."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/mjang", api_mjang)
    logging.info("Maxluqlar jangi ulandi")
