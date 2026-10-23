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

# Eski (bitta raundli) qoida sinovlari oddiy o'quvchilar uchun "admin" rejimida qoladi; kodda rejim - KOD_REJIM
KOD_REJIM = P.YANGI_QOIDA
P.YANGI_QOIDA = "admin"

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
    h = (await ask(1, history=1))["history"]
    check("o'yinlar tarixi: tugagan mashq o'yini, raqib - kompyuter, hisob va natija", len(h) >= 1 and h[0]["id"] == oid and h[0]["kind"] == "mashq"
          and h[0]["opp"] and h[0]["opp"].get("bot") and h[0]["res"] in ("g", "m", "d") and len(h[0]["score"]) == 2)

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
    # Xogvarts chatidagi taklif kartasi (o'quvchilar taklifi): ochiq -> ketmoqda, holati o'zgarsa karta yangilanadi
    msg = await hpcup.post_chat_message("global", 1, "taklif", None, tosh=tid)
    check("chat kartasi: ochiq taklif", msg.get("tosh") and msg["tosh"]["status"] == "waiting" and msg["tosh"]["b"] is None and msg["tosh"]["a"]["uid"] == 1)
    check("taklif ma'lumoti (karta uchun) - egasi va ismi", P.taklif_info(tid) == {"a": 1, "name": "U1"})
    db("INSERT OR IGNORE INTO users (user_id, first_name, created_at) VALUES (31,'Yangi','2026-10-01T00:00:00Z')")
    d = await ask(31, qabul=tid)
    check("saralanmagan (yangi) do'st ham taklifni qabul qila oladi - o'yin boshlandi", d["ok"] and d["game"]["state"] == "ketmoqda" and d["game"]["me"] == "b")
    await P._dost_xabar()
    rooms = await hpcup.chat_bump_oyin("tosh", tid)
    _c = hpcup._connect()
    try:
        msg2 = hpcup._chat_one(_c, msg["id"], 1)
    finally:
        _c.close()
    check("chat kartasi: raqib qabul qildi - o'yin ketmoqda, xona yangilanadi", rooms == ["global"] and msg2["tosh"]["status"] == "active" and msg2["tosh"]["b"]["uid"] == 31)
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

    # ---- IKKI RAUNDLI QOIDA (2026-10-21; 2026-10-23 dan hammaga): avval sinov rejimi ("admin"), keyin "hamma"
    eski_rejim = P.YANGI_QOIDA
    P.YANGI_QOIDA = "admin"
    m = {"raund": 0, "rz": 0}
    yur = []
    toshlar = P.boshlangich(2)
    for i in range(6):
        t, r, z, nav, tug, g = P._q2_keyin(m, toshlar, 1, 1)
        yur.append(nav); m = {"raund": r, "rz": z}
    check("1-raund: a, b navbat bilan 3 tadan; keyin 2-raundni b boshlaydi", yur == ["b", "a", "b", "a", "b", "b"] and m == {"raund": 1, "rz": 0} and len(t) == 6)
    yur = []
    for i in range(6):
        t, r, z, nav, tug, g = P._q2_keyin(m, toshlar, 3, 3)
        yur.append(nav); m = {"raund": r, "rz": z}
    check("2-raund: b, a navbat bilan; teng - penaltini a boshlaydi", yur == ["a", "b", "a", "b", "a", "a"] and m == {"raund": 2, "rz": 0} and not tug)
    t, r, z, nav, tug, g = P._q2_keyin(m, [], 4, 3)
    check("penalti: a otgach b ham to'liq taxtaga otadi", nav == "b" and len(t) == 6 and not tug)
    t, r, z, nav, tug, g = P._q2_keyin({"raund": 2, "rz": 1}, [], 4, 3)
    check("penalti juftligidan keyin farq bor - o'yin tugaydi", tug and g == "a")
    t, r, z, nav, tug, g = P._q2_keyin({"raund": 0, "rz": 2}, [], 2, 1)
    check("toshchalar tugasa raund erta tugaydi, yangi 6 toshcha", r == 1 and z == 0 and nav == "b" and len(t) == 6 and not tug)
    t, r, z, nav, tug, g = P._q2_keyin({"raund": 1, "rz": 5}, [[0, 0]], 7, 5)
    check("2-raund oxirida farq bor - o'yin tugaydi", tug and g == "a")
    t, r, z, nav, tug, g = P._q2_keyin({"raund": 2, "rz": 5}, [], 6, 6)
    check("3 juft penaltidan keyin ham teng - durang (turnirda to'r o'rni)", tug and g is None)

    d = await ask(1, mashq=2)
    check("oddiy o'quvchi - eski qoida (9 toshcha)", d["game"]["rule"] == 1 and len(d["game"]["stones"]) == 9 and (await ask(1))["rules"]["v2"] is False)
    d0 = await ask(42)
    check("adminga yangi qoida haqida belgi", d0["rules"]["v2"] is True and d0["rules"]["rshots"] == 3 and d0["rules"]["rstones"] == 6)
    d = await ask(42, mashq=2)
    g = d["game"]
    check("admin mashqi - ikki raund, 6 toshcha, 3 tadan zarba", g["rule"] == 2 and len(g["stones"]) == 6 and g["per"] == 3 and g["round"] == 0 and g["taken"] == [0, 0])
    gid, kim_otdi, raundlar = g["id"], [], []
    for _ in range(80):
        g = (await ask(42, oyin=gid))["game"]
        if g["state"] != "ketmoqda":
            break
        ilgari(max(0.1, g["turn_in"]) + 0.05)
        g = (await ask(42, oyin=gid))["game"]
        if g["state"] != "ketmoqda":
            break
        if g["turn"] == "a" and g["turn_in"] <= 0.5:
            kim_otdi.append((g["round"], "a")); raundlar.append(g["round"])
            await ask(42, oyin=gid, shot={"s": -90, "a": 90, "p": 0.9})
        elif g["turn"] == "b":
            kim_otdi.append((g["round"], "b"))
    check("admin mashqi oxirigacha o'ynaldi", g["state"] == "tugadi")
    r1 = [k for r, k in kim_otdi if r == 1]
    check("ikkala raund ham o'ynaldi (2-raundda zarbalar bor)", len(r1) >= 2 and r1.count("a") >= 1)
    check("2-raundning birinchi zarbasini kompyuter (b) beradi", (not r1) or r1[0] == "b")
    check("zarbalar soni: 2 raund x 6 dan oshmaydi (+ penalti)", g["shots"] <= 12 + P.QOSHIMCHA * 2)
    db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (5,'U5','slytherin','2026-10-01T00:00:00Z')")
    d = await ask(42, dost=1)
    d = await ask(5, qabul=d["game"]["id"])
    check("admin bilan do'stona o'yin - yangi qoida", d["game"]["rule"] == 2 and len(d["game"]["stones"]) == 6)
    d = await ask(5, dost=1)
    d = await ask(6, qabul=d["game"]["id"])
    check("adminsiz do'stona o'yin - eski qoida", d["game"]["rule"] == 1 and len(d["game"]["stones"]) == 9)

    P.YANGI_QOIDA = "hamma"
    d = await ask(1, mashq=2)
    check("hammaga ochilgan: oddiy o'quvchi mashqi ham ikki raundli", d["game"]["rule"] == 2 and len(d["game"]["stones"]) == 6 and (await ask(1))["rules"]["v2"] is True)
    check("hammaga ochilgan: turnir o'yini ham yangi qoidada", P._qoida("turnir", 1, 2) == 2)
    P.YANGI_QOIDA = eski_rejim
    check("kodda rejim hammaga ochiq", KOD_REJIM == "hamma")

    print("Toshchalar: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(amain())
