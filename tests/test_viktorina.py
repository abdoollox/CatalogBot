# -*- coding: utf-8 -*-
"""Jonli viktorina «Oxirgi sehrgar»: zal, savollar, chiqib ketish, o'rinlar va ballar.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-vik-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars, hpviktorina as V   # noqa: E402
V.SOAT = 21                                  # sinovlar shu soatga yozilgan (jonlida 22:00)

TZ = timezone(timedelta(hours=5))
ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


class Req:
    def __init__(self, body=None, init="", method="POST"):
        self._b, self.method = body or {}, method
        self.headers = {"X-Telegram-Init-Data": init}
        self.query = {}
    async def json(self):
        return self._b


async def ask(kim, **body):
    r = await V.api_viktorina(Req(body, init=str(kim)))
    return json.loads(r.body)


def db(sql, args=()):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    app = types.SimpleNamespace(router=types.SimpleNamespace(add_route=lambda *a, **k: None))
    cfg = {"cors": lambda r: r, "verify_init_data": lambda s: {"id": int(s)} if s.lstrip("-").isdigit() else None}
    hpdars.register(app, cfg)
    xatlar, elonlar = [], []
    async def xat(uid, matnlar):
        xatlar.append((uid, matnlar["uz"][0]))
    async def elon(matnlar):
        elonlar.append(matnlar["uz"][0])
        return 0
    V.register(app, dict(cfg, xat=xat, elon=elon))
    soat = [datetime(2026, 10, 12, 12, 0, tzinfo=TZ)]          # dushanba; viktorina - juma 16-oktabr 21:00
    V._now = lambda: soat[0]
    hpdars._hafta = lambda: (soat[0].date() - timedelta(days=soat[0].weekday())).strftime("%Y-%m-%d")
    def vaqt(kun, s, d=0, sek=0):
        soat[0] = datetime(2026, 10, kun, s, d, sek, tzinfo=TZ)
    def ilgari(sek):
        soat[0] = soat[0] + timedelta(seconds=sek)
    def ball(u):
        return db("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_ref LIKE 'viktorina:%'", (u,))[0][0]
    for u in range(1, 8):
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (u, "V%d" % u, "ravenclaw", "2026-10-01T00:00:00Z"))
    db("INSERT OR IGNORE INTO users (user_id, first_name, created_at) VALUES (30,'Uysiz','2026-10-01T00:00:00Z')")
    havza = hpdars.bell_savollar()
    tartib = V._savollar("2026-10-12")
    togri = lambda n: havza[tartib[n]]["correct"]
    xato = lambda n: (togri(n) + 1) % 4

    check("saralanmagan qatnasha olmaydi", (await ask(30)).get("error") == "no_house")
    check("savollar: 30 ta, takrorsiz, hafta sayin boshqa", len(tartib) == 30 == len(set(tartib)) and tartib != V._savollar("2026-10-19"))
    d = await ask(1, join=1)
    check("yozilish va kutish holati", d["join_ok"] and d["tour"]["joined"] and d["tour"]["n"] == 1 and d["phase"] == "kutish" and not d["me"]["in"])
    vaqt(16, 10, 1)
    await V.tick(); await asyncio.sleep(0.05)
    vaqt(16, 20, 51)
    await V.tick()
    check("birinchi viktorina: ertalab hammaga e'lon, 20:50 da yozilganlarga eslatma", len(elonlar) == 1 and xatlar == [(1, "Viktorinaga 10 daqiqa qoldi!")])

    vaqt(16, 20, 58, 30)
    for u in range(1, 7):
        d = await ask(u)
    check("zal: 2 daqiqa oldin ochiladi, kelganlar sanaladi", d["phase"] == "zal" and d["total"] == 6 and d["me"]["in"] and d["starts_in"] == 90)
    check("savol boshlanguncha javob qabul qilinmaydi", (await ask(1, q=0, answer=togri(0)))["answer_ok"] is False)

    vaqt(16, 21, 0, 2)
    d = await ask(1)
    check("1-savol: matn va 4 variant bor, to'g'ri javob yuborilmaydi", d["phase"] == "savol" and d["question"]["n"] == 0 and len(d["question"]["a"]) == 4 and "c" not in d["question"] and d["left"] > 10)
    d = await ask(1, q=0, answer=togri(0), lang="ru")
    check("javob qabul qilindi, savol o'z tilida", d["answer_ok"] and d["question"]["mine"] == togri(0) and d["question"]["q"] == havza[tartib[0]]["ru"]["q"])
    check("ikkinchi marta javob o'zgartirib bo'lmaydi", (await ask(1, q=0, answer=xato(0)))["answer_ok"] is False)
    for u in (2, 3, 4):
        await ask(u, q=0, answer=togri(0))
    await ask(5, q=0, answer=xato(0))                            # 5 - xato; 6 - javob bermadi
    ilgari(4)
    d7 = await ask(7)                                            # birinchi savol tugamasdan keldi - ishtirokchi
    check("birinchi savol paytida kelgan ham ishtirokchi", d7["me"]["in"] and d7["total"] == 7)
    await ask(7, q=0, answer=togri(0))
    ilgari(12)                                                   # 21:00:18 - natija
    d = await ask(5)
    check("natija: to'g'ri javob ko'rsatiladi, xato qilgan va javob bermagan chiqdi", d["phase"] == "natija" and d["question"]["c"] == togri(0)
          and not d["me"]["alive"] and d["me"]["out"] == 0 and d["alive"] == 5 and (await ask(6))["me"]["alive"] is False)
    db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (8,'Kech','ravenclaw','2026-10-01T00:00:00Z')")
    d8 = await ask(8)
    check("kechikkan - tomoshabin", not d8["me"]["in"] and d8["total"] == 7)

    ilgari(V.NATIJA_T)                                           # 2-savol
    d = await ask(1)
    check("2-savol ochildi", d["phase"] == "savol" and d["question"]["n"] == 1)
    check("chiqib ketgan javob bera olmaydi", (await ask(5, q=1, answer=togri(1)))["answer_ok"] is False)
    for u in (1, 2, 3, 4, 7):
        await ask(u, q=1, answer=xato(1))                        # hamma xato - savol bekor, hech kim chiqmaydi
    ilgari(V.SAVOL_T)
    d = await ask(1)
    check("hamma xato qilsa hech kim chiqmaydi", d["phase"] == "natija" and d["alive"] == 5 and d["me"]["alive"] and d["me"]["right"] == 1)

    ilgari(V.NATIJA_T)                                           # 3-savol: 1, 2, 3 to'g'ri; 4, 7 chiqadi
    await ask(1, q=2, answer=togri(2))
    ilgari(3)
    await ask(2, q=2, answer=togri(2))
    await ask(3, q=2, answer=togri(2))
    await ask(4, q=2, answer=xato(2))
    ilgari(V.SAVOL_T - 3 + V.NATIJA_T)                           # 4-savol: 1 to'g'ri (tez), 2 to'g'ri (sekin), 3 xato
    await ask(1, q=3, answer=togri(3))
    ilgari(5)
    await ask(2, q=3, answer=togri(3))
    await ask(3, q=3, answer=xato(3))
    ilgari(V.SAVOL_T - 5 + V.NATIJA_T)                           # 5-savol: faqat 1 to'g'ri -> g'olib
    await ask(1, q=4, answer=togri(4))
    await ask(2, q=4, answer=xato(4))
    ilgari(V.SAVOL_T)
    d = await ask(1)
    check("oxirgi sehrgar qoldi - viktorina tugadi", d["phase"] == "tugadi" and d["me"]["place"] == 1 and d["top"][0]["uid"] == 1 and d["asked"] == 5 and d["played"])
    orin = {r[0]: r[1] for r in db("SELECT user_id, orin FROM vk_oyinchi WHERE hafta='2026-10-12'")}
    check("o'rinlar: kech chiqqan yuqori", orin[1] == 1 and orin[2] == 2 and orin[3] == 3 and orin[4] in (4, 5) and orin[7] in (4, 5) and orin[5] in (6, 7) and orin[6] in (6, 7))
    check("ballar: 1-o'rin +30, 2-o'rin +20, 3-o'rin +10, qolganlarga (5 ta to'g'ri bo'lmasa) yo'q", ball(1) == 30 and ball(2) == 20 and ball(3) == 10 and ball(4) == 0 and ball(5) == 0)
    n_ball = db("SELECT COUNT(*) FROM points WHERE source_ref LIKE 'viktorina:%'")[0][0]
    await V.tick(); await V.tick()
    check("ball takror berilmaydi", db("SELECT COUNT(*) FROM points WHERE source_ref LIKE 'viktorina:%'")[0][0] == n_ball)
    check("tugagach javob qabul qilinmaydi", (await ask(2, q=5, answer=0))["answer_ok"] is False)

    vaqt(17, 0, 30)
    d = await ask(2, join=1)
    check("keyingi haftaga yozilish ochiladi, oldingi g'olib ko'rinadi", V._hafta() == "2026-10-19" and d["join_ok"] and d["phase"] == "kutish" and d["last"]["uid"] == 1 and d["last"]["n"] == 7)
    # bir kishi kelsa viktorina bo'lmaydi
    vaqt(23, 20, 59)
    await ask(2)
    vaqt(23, 21, 0, 20)
    d = await ask(2)
    check("bir kishi bilan viktorina o'tmaydi", d["phase"] == "tugadi" and d["played"] is False and ball(2) == 20)

    # tasalli bali: 5 ta to'g'ri javob bergan, lekin uchlikka kirmagan
    V._yakunla.__doc__
    vaqt(24, 1, 0)
    hafta = V._hafta()
    for u, (chiq, t) in {1: (None, 9), 2: (8, 8), 3: (7, 7), 4: (6, 6), 5: (3, 3)}.items():
        db("INSERT INTO vk_oyinchi (hafta, user_id, tirik, chiqdi, togri, ms) VALUES (?,?,?,?,?,1000)", (hafta, u, 1 if chiq is None else 0, chiq, t))
    db("INSERT INTO vk_turnir (hafta, savollar, soni) VALUES (?, '[]', 5)", (hafta,))
    conn = hpcup._connect(); berish = []
    V._yakunla(conn, hafta, berish, V._ep()); conn.commit(); conn.close()
    b = {u: p for u, _, p in berish}
    check("tasalli bali: uchlikdan tashqarida 5+ to'g'ri javobga +5", b == {1: 30, 2: 20, 3: 10, 4: 5})

    print("Viktorina: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
