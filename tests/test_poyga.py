# -*- coding: utf-8 -*-
"""Supurgi poygasi (dushanba 21:00): zal, uzluksiz poyga, har 10 halqada oxirgi chiqadi, jonli jadval, o'rinlar va ballar, sinov poygasi.

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
TMP = tempfile.mkdtemp(prefix="hp-poyga-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars, hppoyga as P   # noqa: E402

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
    r = await P.api_poyga(Req(body, init=str(kim)))
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
    P.register(app, dict(cfg, xat=xat, elon=elon, admin_ids={42}))
    soat = [datetime(2026, 10, 14, 12, 0, tzinfo=TZ)]          # chorshanba; birinchi poyga - dushanba 19-oktabr 21:00
    P._now = lambda: soat[0]
    hpdars._hafta = lambda: (soat[0].date() - timedelta(days=soat[0].weekday())).strftime("%Y-%m-%d")
    hpcup.now_tk = lambda: soat[0]
    def vaqt(kun, s, d=0, sek=0):
        soat[0] = datetime(2026, 10, kun, s, d, sek, tzinfo=TZ)
    def ilgari(sek):
        soat[0] = soat[0] + timedelta(seconds=sek)
    def ball(u):
        return db("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_ref LIKE 'poyga:%'", (u,))[0][0]
    for u in range(1, 13):
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (u, "U%d" % u, "gryffindor", "2026-10-01T00:00:00Z"))
    db("INSERT OR IGNORE INTO users (user_id, first_name, created_at) VALUES (30,'Uysiz','2026-10-01T00:00:00Z')")

    P.BOSH_HAFTA = "2026-10-19"                  # sinovlar shu sanaga yozilgan (jonlida birinchi poyga 12-oktabrga ko'chirilgan)
    soat[0] = datetime(2026, 10, 12, 15, 0, tzinfo=TZ)        # dushanba, lekin poyga KEYINGI dushanbada
    await P.tick(); await asyncio.sleep(0.05)
    check("poyga kuni bo'lmagan dushanbada e'lon ketmaydi", elonlar == [] and xatlar == [])
    soat[0] = datetime(2026, 10, 14, 12, 0, tzinfo=TZ)
    check("saralanmagan qatnasha olmaydi", (await ask(30)).get("error") == "no_house")
    d = await ask(1, join=1)
    check("chorshanbada: navbatdagi poyga - dushanba 19-oktabr, yozilish ochiq", d["join_ok"] and d["tour"]["joined"] and d["phase"] == "kutish"
          and datetime.fromtimestamp(d["tour"]["ts"], TZ).strftime("%Y-%m-%d %H:%M") == "2026-10-19 21:00")
    vaqt(19, 10, 1)
    await P.tick(); await asyncio.sleep(0.05)
    vaqt(19, 20, 51)
    await P.tick()
    check("birinchi poyga: ertalab hammaga e'lon, 20:50 da yozilganlarga eslatma", len(elonlar) == 1 and xatlar == [(1, "Poygaga 10 daqiqa qoldi!")])

    # ---------- 5 kishi: uzluksiz poyga, har 10 halqada oxirgi chiqadi ----------
    vaqt(19, 20, 58, 30)
    for u in range(1, 6):
        d = await ask(u)
    check("start chizig'i: kelganlar sanaladi", d["phase"] == "zal" and d["total"] == 5 and d["me"]["in"])
    vaqt(19, 21, 0, 0)
    d = await ask(1)
    check("poyga boshlandi: yo'l (5 - 1) * 10 = 40 halqa, sanoq", d["phase"] == "poyga" and d["race"]["rings"] == 40 and d["race"]["every"] == 10
          and 5 < d["race"]["start_in"] <= 6 and d["alive"] == 5 and len(d["board"]) == 5)
    d9 = await ask(9)
    check("kechikkan - tomoshabin", d9["phase"] == "poyga" and not d9["me"]["in"] and len(d9["board"]) == 5)
    ilgari(P.SANOQ + 2)
    d = await ask(1, pos=2, cps={"0": 1500})
    check("juda erta «nazorat» qabul qilinmaydi", d["light"] and d["ack"] == [] and d["cp"] == 0)
    ilgari(3)
    for u in (1, 2, 3, 4):
        await ask(u, pos=5)
    ilgari(7)                                    # startdan 12 soniya
    await ask(1, pos=10, cps={"0": 11000})
    await ask(2, pos=10, cps={"0": 11400})
    d = await ask(3, pos=10, cps={"0": 2000})
    check("ilova aytgan vaqt server soatidan ko'p kichik bo'la olmaydi", d["ack"] == [0]
          and db("SELECT ms FROM pg_natija WHERE user_id=3 AND bosqich=0 AND hafta='2026-10-19'")[0][0] == 12000 - P.MUHLAT_MS)
    d = await ask(4, pos=7)
    check("jonli jadval: oldindagilar tepada, hamma hali poygada", [r["uid"] for r in d["board"]][:1] in ([1], [2], [3]) and d["board"][3]["uid"] == 4
          and d["board"][4]["uid"] == 5 and d["alive"] == 5 and d["board"][3]["me"])
    ilgari(P.NAZORAT_T + 1)                      # ikki kishi yetib kelmadi - ikkalasi ham chiqadi
    await P.tick()                               # jonli serverda buni fon aylanasi har soniyada qiladi
    d = await ask(4, pos=8)
    check("muddatida nazoratga yetmaganlar chiqadi (uchgani yuqoriroq o'rinda)", d["phase"] == "poyga" and not d["me"]["alive"] and d["me"]["place"] == 4
          and d["alive"] == 3 and d["cp"] == 1 and [r["uid"] for r in d["board"] if r.get("out")] == [4, 5])
    await ask(1, pos=20, cps={"1": 30000})
    await ask(2, pos=20, cps={"1": 31000})
    d = await ask(3, pos=20, cps={"1": 31500})
    check("hamma o'tdi: muhlat tugamaguncha hech kim chiqmaydi", d["alive"] == 3 and d["me"]["alive"])
    ilgari(2)
    await P.tick()                               # jonli serverda buni fon aylanasi har soniyada qiladi
    d = await ask(3, pos=21)
    check("nazoratdan eng oxirida o'tgan chiqadi", not d["me"]["alive"] and d["me"]["place"] == 3 and d["alive"] == 2 and d["cp"] == 2)
    ilgari(8)
    d = await ask(2, pos=30, cps={"2": 40000})
    check("oxirgi ikki kishi: birinchisi o'tdi, muhlat ketmoqda", d["phase"] == "poyga" and d["me"]["alive"])
    ilgari(2)
    await P.tick()                               # jonli serverda buni fon aylanasi har soniyada qiladi
    d = await ask(1, pos=29)
    check("ikkinchisi ulgurmadi - poyga tugadi", d["phase"] == "tugadi" and d["me"]["place"] == 2 and not d["me"]["alive"])
    d = await ask(2)
    check("g'olib va yakuniy jadval", d["phase"] == "tugadi" and d["played"] and d["me"]["place"] == 1 and d["me"]["points"] == 30
          and [(r["uid"], r["place"]) for r in d["board"]] == [(2, 1), (1, 2), (3, 3), (4, 4), (5, 5)])
    await asyncio.sleep(0.05)
    check("ballar: 30 / 20 / 10, uchgan 4-o'ringa +5, umuman uchmaganga yo'q", [ball(u) for u in (2, 1, 3, 4, 5)] == [30, 20, 10, 5, 0])
    d = await ask(5)
    check("uchmagan ishtirokchi: o'rni bor, bali yo'q", d["me"]["place"] == 5 and d["me"]["points"] == 0)
    await P.tick()
    check("ball qayta berilmaydi", ball(2) == 30)

    # ---------- hech kim uchmasa poyga o'zi yopiladi ----------
    soat[0] = datetime(2026, 10, 26, 20, 59, tzinfo=TZ)
    await ask(6); await ask(7)
    d = await ask(6)
    check("keyingi hafta: o'tgan g'olib ko'rinadi", d["phase"] == "zal" and d["last"] and d["last"]["uid"] == 2 and d["last"]["n"] == 5)
    soat[0] = datetime(2026, 10, 26, 21, 0, 30, tzinfo=TZ)
    d = await ask(6)
    check("hech kim uchmayapti: poyga hali ochiq", d["phase"] == "poyga" and d["race"]["rings"] == 10)
    ilgari(P.QISM_T)
    d = await ask(6)
    check("hech kim nazoratga yetmadi - poyga yopildi, g'olib va ball yo'q", d["phase"] == "tugadi" and ball(6) == 0 and ball(7) == 0
          and db("SELECT golib FROM pg_turnir WHERE hafta='2026-10-26'")[0][0] is None)

    # ---------- bir kishi ----------
    soat[0] = datetime(2026, 11, 2, 20, 59, tzinfo=TZ)
    await ask(7)
    soat[0] = datetime(2026, 11, 2, 21, 0, 10, tzinfo=TZ)
    d = await ask(7)
    check("bir kishi kelsa poyga o'tmaydi", d["phase"] == "tugadi" and d["played"] is False and ball(7) == 0)

    # ---------- sinov poygasi (faqat admin): kompyuter uchuvchilar bilan, ballsiz ----------
    db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (42,'Admin','ravenclaw','2026-10-01T00:00:00Z')")
    soat[0] = datetime(2026, 11, 4, 12, 0, tzinfo=TZ)
    d = await ask(1, sinov=1)
    check("oddiy o'quvchi sinov poygasini boshlay olmaydi", "sinov_ok" not in d and not d["test"] and not d["can_test"] and d["phase"] == "kutish")
    d = await ask(42)
    check("adminga sinov tugmasi ko'rinadi", d["can_test"] and not d["test"])
    d = await ask(42, sinov=1)
    check("sinov: start chizig'i, 10 uchuvchi", d.get("sinov_ok") and d["test"] and d["phase"] == "zal" and d["total"] == 10 and 0 < d["starts_in"] <= P.SINOV_KUT)
    check("sinov boshqalarga ko'rinmaydi", (await ask(1))["phase"] == "kutish")
    ilgari(P.SINOV_KUT + 1)
    d = await ask(42)
    check("sinov: poyga boshlandi, yo'l 90 halqa", d["phase"] == "poyga" and d["race"]["rings"] == 90 and d["me"]["alive"]
          and any(r["name"] == "Viktor" for r in d["board"]))
    ilgari(P.SANOQ)
    otdi, yuborilgan, chiqqanlar = 0.0, set(), []
    for _ in range(400):                         # admin har halqaga 0,9 soniya sarflaydi - faqat ikki kompyuter uchuvchi undan tez
        ilgari(1); otdi += 1
        pos = int(max(0, otdi - 1.5) / 0.9)
        cps = {str(k): int((1.5 + (k + 1) * 10 * 0.9) * 1000) for k in range(pos // 10) if k not in yuborilgan}
        d = await ask(42, pos=pos, cps=cps) if cps else await ask(42, pos=pos)
        await P.tick()
        for k in d.get("ack") or []:
            yuborilgan.add(k)
        for r in d["board"]:
            if r.get("out") and r["name"] not in chiqqanlar:
                chiqqanlar.append(r["name"])
        if d["phase"] == "tugadi" or not d["me"]["alive"]:
            break
    check("sinov: birinchi bo'lib eng sekin uchuvchi chiqdi, admin uchinchi bo'ldi", chiqqanlar[:1] == ["Nevill"] and d["me"]["place"] == 3)
    for _ in range(60):
        ilgari(1)
        await P.tick()
    d = await ask(42)
    check("sinov tugadi: g'olib - eng tez uchuvchi, ball YO'Q", d["phase"] == "tugadi" and d["board"][0]["name"] == "Viktor" and d["board"][0]["place"] == 1
          and len(d["board"]) == 10 and d["me"]["points"] == 0 and ball(42) == 0)
    d = await ask(42, sinov=0)
    check("sinov to'xtatildi: yana haqiqiy poyga holati, izlar tozalandi", d.get("sinov_ok") and not d["test"] and d["phase"] == "kutish"
          and db("SELECT COUNT(*) FROM pg_oyinchi WHERE hafta LIKE 'sinov:%'")[0][0] == 0)

    print("Poyga: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(amain())
