# -*- coding: utf-8 -*-
"""Toshchalar: fizika, mashq (kompyuter bilan), navbat va kelmadi, turnir to'ri, ballar, g'oliblar.

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
TMP = tempfile.mkdtemp(prefix="hp-tosh-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import random
import hpcup, hpdars, hptosh as P   # noqa: E402

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
    r = await P.api_tosh(Req(body, init=str(kim)))
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
    soat = [datetime(2026, 10, 14, 12, 0, tzinfo=TZ)]
    P._now = lambda: soat[0]
    hpdars._hafta = lambda: (soat[0].date() - timedelta(days=soat[0].weekday())).strftime("%Y-%m-%d")
    hpcup.now_tk = lambda: soat[0]
    def vaqt(kun, s, d=0, sek=0):
        soat[0] = datetime(2026, 10, kun, s, d, sek, tzinfo=TZ)
    def ilgari(sek):
        soat[0] = soat[0] + timedelta(seconds=sek)
    def ball(u):
        return db("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_ref LIKE 'tosh:%'", (u,))[0][0]
    for u in list(range(1, 8)) + [42]:
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (u, "U%d" % u, "gryffindor", "2026-10-01T00:00:00Z"))
    db("INSERT OR IGNORE INTO users (user_id, first_name, created_at) VALUES (30,'Uysiz','2026-10-01T00:00:00Z')")

    # ---------- fizika ----------
    st = P.boshlangich()
    q1, b1, k1 = P.simulyatsiya(st, -90, 90, 1.0)
    q2, b2, k2 = P.simulyatsiya(st, -90, 90, 1.0)
    check("fizika bir xil zarbada bir xil natija beradi (adolat)", (q1, b1) == (q2, b2) and k1["f"] == k2["f"])
    check("to'qqiz toshcha; zarba kadrlari bor, har kadrda hamma jism", len(st) == 9 and len(k1["f"]) > 5 and all(len(f) == 10 for f in k1["f"]))
    _, b3, _ = P.simulyatsiya(st, -90, 0, 1.0)
    check("toshchalarga tegmagan zarba hech narsa chiqarmaydi", b3 == 0)
    _, b4, _ = P.simulyatsiya(st, -90, 90, 0.0)
    check("juda kuchsiz zarba ham hech narsa chiqarmaydi", b4 == 0)
    rnd = random.Random(5)
    natija = {}
    for d in (1, 3):
        jami = 0
        for _ in range(6):
            t = P.boshlangich()
            for _ in range(5):
                sh = P.kompyuter_zarbasi(t, d, rnd)
                t, b, _ = P.simulyatsiya(t, sh["s"], sh["a"], sh["p"], False)
                jami += b
        natija[d] = jami
    check("qiyin kompyuter osonidan ko'proq toshcha chiqaradi", natija[3] > natija[1])

    # ---------- mashq ----------
    check("saralanmagan o'ynay olmaydi", (await ask(30, mashq=1)).get("error") == "no_house")
    d = await ask(1, mashq=1)
    g = d["game"]
    check("mashq o'yini ochildi: navbat siznikida, 9 toshcha, raqib - Nevill", d["ok"] and g["me"] == "a" and g["turn"] == "a" and len(g["stones"]) == 9
          and g["b"]["name"] == "Nevill" and g["state"] == "ketmoqda")
    oid = g["id"]
    d = await ask(1, oyin=oid, shot={"s": -90, "a": 90, "p": 1.0})
    check("zarba qabul qilindi: manzara kadrlari keldi, navbat raqibga o'tdi", d["shot_ok"] and d["game"]["last"]["n"] == 1 and d["game"]["turn"] == "b"
          and len(d["game"]["last"]["f"]) > 5)
    d2 = await ask(1, oyin=oid, shot={"s": -90, "a": 90, "p": 1.0})
    check("o'z navbati bo'lmasa zarba qabul qilinmaydi", d2["shot_ok"] is False)
    d3 = await ask(1, oyin=oid, seen=1)
    check("ko'rilgan zarba kadrlari qayta yuborilmaydi", "last" not in d3["game"] and d3["game"]["last_n"] == 1)
    ilgari(d["game"]["turn_in"] + 0.1)
    d = await ask(1, oyin=oid, seen=1)
    check("kompyuter o'z vaqtida otdi, navbat yana sizda", d["game"]["shots"] == 2 and d["game"]["turn"] == "a" and d["game"]["last"]["by"] == "b")
    for _ in range(20):
        g = d["game"]
        if g["state"] != "ketmoqda":
            break
        ilgari(g["turn_in"] + 0.1)
        if g["turn"] == "a":
            d = await ask(1, oyin=oid, shot={"s": random.uniform(-140, -40), "a": random.uniform(60, 120), "p": 0.9})
        else:
            d = await ask(1, oyin=oid)
    g = d["game"]
    check("mashq tugadi: 5 + 5 zarba (yoki toshchalar tugadi), hisob to'g'ri", g["state"] == "tugadi" and (g["shots"] >= 10 or not g["stones"])
          and sum(g["score"]) + len(g["stones"]) == 9)
    check("mashqda ball berilmaydi", ball(1) == 0)

    # navbat vaqti: o'tkazib yuborish va kelmadi
    d = await ask(2, mashq=2)
    oid = d["game"]["id"]
    ilgari(P.NAVBAT_T + 1)
    d = await ask(2, oyin=oid)
    check("navbatida otmasa zarba yonib ketadi (o'yinda ko'rinib turgan bo'lsa ham)", d["game"]["shots"] >= 1 and d["game"]["state"] == "ketmoqda")

    # ---------- turnir: 3 kishi (4 talik to'r: 1-o'rin birinchi bosqichni o'tkazib yuboradi) ----------
    vaqt(14, 12)
    d = await ask(3, join=1)
    check("yozilish: navbatdagi turnir - seshanba 20-oktabr 22:00", d["join_ok"] and d["tour"]["joined"]
          and datetime.fromtimestamp(d["tour"]["ts"], TZ).strftime("%Y-%m-%d %H:%M") == "2026-10-20 22:00")
    await ask(4, join=1); await ask(5, join=1)
    vaqt(20, 10, 1)
    await P.tick(); await asyncio.sleep(0.05)
    check("birinchi turnir kuni ertalab hammaga e'lon", len(elonlar) == 1)
    vaqt(20, 21, 56)
    await P.tick()
    d = await ask(3)
    check("to'r tuzildi: 4 talik, bittasi o'tkazib yuboradi", d["cup"]["size"] == 4 and any(m["why"] == "bye" for m in d["cup"]["stages"][0]["matches"]))
    check("yozilish yopildi", (await ask(6, join=1))["join_ok"] is False)
    vaqt(20, 22, 0, 1)
    await P.tick()
    yarim = [m for m in d["cup"]["stages"][0]["matches"] if m["why"] != "bye"][0]
    d = await ask(yarim["a"]["uid"])
    act = d.get("active")
    check("o'yin boshlandi va o'yinchiga ko'rinadi", act and act["kind"] == "turnir")
    mid = act["id"]
    g = (await ask(yarim["a"]["uid"], oyin=mid))["game"]
    # «a» tomondagi o'yinchi kuchli otadi, «b» tomondagi umuman kelmaydi
    a_uid = g["a"]["uid"]
    for _ in range(12):
        g = (await ask(a_uid, oyin=mid))["game"]
        if g["state"] != "ketmoqda":
            break
        ilgari(max(0, g["turn_in"]) + 0.1)
        if g["turn"] == "a":
            await ask(a_uid, oyin=mid, shot={"s": -90, "a": 90, "p": 1.0})
        else:
            ilgari(P.NAVBAT_T + 1)
            await P.tick()
    g = (await ask(a_uid, oyin=mid))["game"]
    check("raqib kelmadi - yutqazdi (yoki o'yin hisob bilan tugadi)", g["state"] == "tugadi" and g["winner"] == "a")
    check("g'alaba uchun ball (yarim final +20)", ball(a_uid) == 20)
    vaqt(20, 22, 30)
    await P.tick()
    d = await ask(3)
    fin = d["cup"]["stages"][1]["matches"][0]
    check("final juftligi aniqlandi", fin["a"] and fin["b"] and fin["state"] in ("kutmoqda", "ketmoqda"))

    # ---------- sinov o'yini (admin) ----------
    d = await ask(42, sinov=1)
    check("admin sinov o'yini: kompyuter bilan, turnir oqimi", d["game"]["kind"] == "sinov" and d["game"]["b"]["name"] == "Ron")
    check("oddiy o'quvchi sinov ochmaydi", "game" not in (await ask(6, sinov=1)))

    # ---------- do'st bilan (Telegram taklifi) ----------
    vaqt(21, 12)
    d = await ask(1, dost=1)
    tid = d["game"]["id"]
    check("do'stga taklif: o'yin kutmoqda, muddati bor", d["game"]["kind"] == "dost" and d["game"]["state"] == "kutmoqda" and d["game"]["expires_in"] > 1000)
    check("taklif ma'lumoti (karta uchun) - egasi va ismi", P.taklif_info(tid) == {"a": 1, "name": "U1"})
    db("INSERT OR IGNORE INTO users (user_id, first_name, created_at) VALUES (31,'Yangi','2026-10-01T00:00:00Z')")
    d = await ask(31, qabul=tid)
    check("saralanmagan (yangi) do'st ham taklifni qabul qila oladi - o'yin boshlandi", d["ok"] and d["game"]["state"] == "ketmoqda" and d["game"]["me"] == "b")
    check("qabul qilingan taklif yopiq - karta endi chiqmaydi", P.taklif_info(tid) is None)
    check("ikkinchi odam qabul qila olmaydi", (await ask(2, qabul=tid)).get("error") == "band")
    check("saralanmagan odam turnirga yozila olmaydi", (await ask(31, join=1)).get("error") == "no_house")
    d = await ask(2, dost=1)
    t2 = d["game"]["id"]
    d = await ask(2, bekor=t2)
    check("taklifni bekor qilish", d.get("bekor_ok") and P.taklif_info(t2) is None)
    d = await ask(3, dost=1)
    t3 = d["game"]["id"]
    ilgari(P.DOST_MUDDAT + 5)
    await P.tick()
    check("muddati o'tgan taklif yopiladi", P.taklif_info(t3) is None and (await ask(4, qabul=t3)).get("error") == "muddat")

    print("Toshchalar: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(amain())
