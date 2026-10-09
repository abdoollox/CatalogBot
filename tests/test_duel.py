# -*- coding: utf-8 -*-
"""Duel: raund qoidasi, kompyuter raqib, saralash bali va jadvali.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-duel-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars, hpduel   # noqa: E402

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
    r = await hpduel.api_duel(Req(body, init=str(kim)))
    return r.status, json.loads(r.body)


def db(sql, args=()):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


class Rnd:
    """Oldindan belgilangan raqib yurishlari."""
    def __init__(self, tur, acc): self.tur, self.acc = tur, acc
    def choice(self, seq): return self.tur
    def random(self): return 1.0
    def gauss(self, a, b): return self.acc


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    loglar = []
    async def log(user, payload):
        loglar.append(payload)
    app = types.SimpleNamespace(router=types.SimpleNamespace(add_route=lambda *a, **k: None))
    cfg = {"cors": lambda r: r, "log": log, "verify_init_data": lambda s: {"id": int(s)} if s.lstrip("-").isdigit() else None}
    hpdars.register(app, cfg)
    hpduel.register(app, cfg)
    for uid, h in ((1, "gryffindor"), (2, "slytherin"), (3, None)):
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (uid, "S%d" % uid, h, "2026-10-01T00:00:00Z"))

    H = hpduel.hal_qil
    check("uchburchak: hujum > hiyla > himoya > hujum", H("hujum", 80, "hiyla", 80) == 1 and H("hiyla", 80, "himoya", 80) == 1
          and H("himoya", 80, "hujum", 80) == 1 and H("hiyla", 80, "hujum", 80) == -1)
    check("aniqlik hal qiladi: a'lo chizilgan afsun noqulay turda ham yutadi; o'rtachasi - yo'q", H("hiyla", 95, "hujum", 60) == 1 and H("hiyla", 80, "hujum", 60) == -1
          and H("hujum", 60, "hiyla", 95) == -1 and H("hujum", 72, "hiyla", 95) == 0 and hpduel.kuch("hujum", 60, "hiyla") == 85 and hpduel.kuch("hujum", 30, "hiyla") == 0)
    check("bir xil tur: aniqrog'i yutadi, farq kichik bo'lsa durang", H("hujum", 80, "hujum", 60) == 1 and H("hujum", 60, "hujum", 80) == -1 and H("hujum", 80, "hujum", 78) == 0)
    check("afsun chiqmasa (aniqlik past) - raqib uradi; ikkalasi chiqmasa durang", H("hujum", 20, "hiyla", 50) == -1 and H("hiyla", 50, "hujum", 20) == 1 and H("hujum", 10, "hiyla", 10) == 0)

    st, d = await ask("x")
    check("imzosiz 403", st == 403)
    st, d = await ask(3)
    check("saralanmagan o'ynay olmaydi", d == {"ok": False, "error": "no_house"})
    st, d = await ask(1)
    check("boshida bo'sh holat", d["ok"] and d["mine"]["total"] == 0 and d["top"] == [] and d["place"] is None and d["rules"]["lives"] == 5)
    st, d = await ask(1, start=7)
    check("noma'lum raqib 404", st == 404)
    st, d = await ask(1, start=2)
    g = d["game"]
    check("duel boshlandi", g["level"] == 2 and g["lives"] == 5 and g["rlives"] == 5 and g["round"] == 0)
    st, d = await ask(1, game=g["id"], move="sehr", acc=90)
    check("noma'lum tur 404", st == 404)

    # Uch raundda g'alaba: raqib hiyla qiladi, men hujum
    r = None
    for i in range(5):
        r = hpduel._yur(1, g["id"], "hujum", 90, Rnd("hiyla", 70))
    check("besh raundda yutdi, ball = 200 + 5 jon + aniqlik", r["game"]["over"] and r["game"]["won"] and r["game"]["rlives"] == 0 and r["game"]["lives"] == 5
          and r["game"]["score"] == 200 + 100 + 45 and r["round"]["win"] == 1)
    check("tugagan duelga yurish yo'q", hpduel._yur(1, g["id"], "hujum", 90) is None)
    st, d = await ask(1)
    check("saralash jadvalida", d["mine"]["2"] == 345 and d["mine"]["total"] == 345 and d["place"] == 1 and d["top"][0]["me"] and d["top"][0]["score"] == 345)

    # Yomonroq g'alaba eng yaxshi natijani pasaytirmaydi; boshqa daraja qo'shiladi
    g2 = hpduel._boshla(1, 2)
    hpduel._yur(1, g2["id"], "hujum", 90, Rnd("himoya", 70))
    for i in range(5):
        r = hpduel._yur(1, g2["id"], "hujum", 60, Rnd("hiyla", 70))
    check("pastroq natija saqlanmaydi", r["game"]["won"] and r["game"]["score"] < 345 and (await ask(1))[1]["mine"]["2"] == 345)
    g3 = hpduel._boshla(1, 1)
    for i in range(5):
        r = hpduel._yur(1, g3["id"], "himoya", 80, Rnd("hujum", 70))
    st, d = await ask(1)
    check("darajalar yig'iladi", d["mine"]["1"] == 100 + 100 + 40 and d["mine"]["total"] == 585)

    # Mag'lubiyat va ikkinchi o'yinchi
    g4 = hpduel._boshla(2, 3)
    for i in range(5):
        r = hpduel._yur(2, g4["id"], "hujum", 90, Rnd("himoya", 70))
    check("yutqazdi: ball yo'q", r["game"]["over"] and not r["game"]["won"] and r["game"]["score"] == 0 and r["game"]["lives"] == 0)
    g5 = hpduel._boshla(2, 1)
    for i in range(5):
        hpduel._yur(2, g5["id"], "hujum", 100, Rnd("hiyla", 70))
    st, d = await ask(2)
    check("jadval: ikki kishi, o'rin", d["n"] == 2 and d["place"] == 2 and [x["score"] for x in d["top"]] == [585, 250])

    # Yangi duel eskisini tashlaydi; API orqali to'liq duel
    a = hpduel._boshla(1, 1); b = hpduel._boshla(1, 1)
    check("yangi duel boshlansa eskisi tashlanadi", hpduel._yur(1, a["id"], "hujum", 90) is None)
    over = False
    for i in range(30):
        st, d = await ask(1, game=b["id"], move="hujum", acc=95)
        if d.get("game", {}).get("over"):
            over = True
            break
    check("API orqali duel tugaydi (20 raunddan oshmaydi)", over and d["game"]["round"] <= 20 and "round" in d)
    db("UPDATE duel_saral SET hafta='2000-01-03'")
    st, d = await ask(1)
    check("yangi haftada jadval yangidan", d["mine"]["total"] == 0 and d["top"] == [])
    check("log", any(x.startswith("duel_1_") for x in loglar))

    # ================= PLEY-OFF =================
    from datetime import datetime, timedelta
    TZ = hpcup.TASHKENT
    soat = [datetime(2026, 10, 14, 23, 0, tzinfo=TZ)]          # chorshanba kechasi
    hpduel._now = lambda: soat[0]
    hpdars._hafta = lambda: "2026-10-12"
    hpduel._cfg["admin_ids"] = {42}
    xatlar = []
    async def xat(uid, matnlar):
        xatlar.append((uid, matnlar["uz"][0]))
    hpduel._cfg["xat"] = xat
    def vaqt(kun, s, d=0, sek=0):
        soat[0] = datetime(2026, 10, kun, s, d, sek, tzinfo=TZ)
    def ilgari(sek):
        soat[0] = soat[0] + timedelta(seconds=sek)
    def ball(u):
        return db("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_ref LIKE 'duel:%'", (u,))[0][0]
    for u in range(11, 20):                                     # 9 duelchi: 11 eng kuchli ... 19 eng kuchsiz
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (u, "D%d" % u, "ravenclaw", "2026-10-01T00:00:00Z"))
        db("INSERT INTO duel_saral (user_id, hafta, daraja, ball, vaqt) VALUES (?,?,1,?,?)", (u, "2026-10-12", 400 - u, "2026-10-13T00:00:%02dZ" % u))
    check("to'r tartibi", hpduel._tartib(8) == [1, 8, 4, 5, 2, 7, 3, 6] and hpduel._tartib(16)[:4] == [1, 16, 8, 9])
    await hpduel.tick()
    st, d = await ask(11)
    check("chorshanba: to'r hali yo'q", d["cup"]["size"] is None and ball(11) == 0)
    vaqt(15, 0, 30)
    await hpduel.tick(); await hpduel.tick()
    st, d = await ask(11)
    C = d["cup"]
    q = C["stages"][0]["matches"]
    check("payshanba: 9 kishidan 8 talik to'r, 1-8, 4-5, 2-7, 3-6", C["size"] == 8 and [x["stage"] for x in C["stages"]] == [8, 4, 2]
          and [(m["a"]["uid"], m["b"]["uid"]) for m in q] == [(11, 18), (14, 15), (12, 17), (13, 16)] and len(C["stages"][1]["matches"]) == 2)
    check("kirish bali +5, bir marta; to'qqizinchi kirmadi; o'z uchrashuvi", ball(11) == 5 and ball(18) == 5 and ball(19) == 0 and C["my"]["stage"] == 8 and xatlar == [])
    vaqt(15, 10, 5)
    await hpduel.tick(); await hpduel.tick()
    check("payshanba 10:00: «pley-offga chiqdingiz» xati, 8 kishiga bir marta", len(xatlar) == 8 and "chiqdingiz" in xatlar[0][1])
    vaqt(16, 10, 5); await hpduel.tick()
    vaqt(16, 20, 51); await hpduel.tick(); await hpduel.tick()
    check("juma: ertalab va 10 daqiqa oldin eslatma", len(xatlar) == 24 and "21:00" in xatlar[8][1] and "10 daqiqa" in xatlar[-1][1])

    async def ar(u, mid, **kw):
        st, d = await ask(u, arena=mid, **kw)
        return d.get("arena")
    m1, m2, m3, m4 = [m["id"] for m in q]
    vaqt(16, 20, 55)
    A = await ar(11, m1)
    check("vaqtidan oldin: kutish", A["phase"] == "early" and A["starts_in"] == 300 and A["opp"]["name"] == "D18")
    check("begona odam arenaga kira olmaydi", (await ask(12, arena=m1))[1].get("error") == "no_match")
    vaqt(16, 21, 0, 5)
    A = await ar(11, m1)
    check("raqib kelmagan: kutmoqda", A["phase"] == "wait" and not A["opp"]["here"])
    B = await ar(18, m1)
    check("ikkalasi keldi: duel boshlandi", B["phase"] == "pick" and B["round"] == 1 and B["lives"] == 5 and B["deadline_in"] == 30)
    A = await ar(11, m1, move="hujum", acc=90)
    check("yurish yozildi, raqib kutilmoqda", A["phase"] == "pick" and A["moved"])
    B = await ar(18, m1, move="hiyla", acc=80)
    check("raund hal bo'ldi: natija ikkalasiga o'z tomonidan", B["phase"] == "reveal" and B["last"]["win"] == -1 and B["lives"] == 4 and B["last"]["mine"] == "hiyla" and B["last"]["racc"] == 90)
    A = await ar(11, m1)
    check("g'olib tomonda", A["last"]["win"] == 1 and A["rlives"] == 4 and A["phase"] == "reveal")
    for i in range(4):
        ilgari(7)
        await ar(11, m1); await ar(18, m1)
        await ar(11, m1, move="hujum", acc=90)
        B = await ar(18, m1, move="hiyla", acc=80)
    A = await ar(11, m1)
    check("besh raundda g'alaba: +15 ball darhol, yarim finalga o'tdi", A["over"] and A["won"] and B["over"] and not B["won"] and ball(11) == 20 and ball(18) == 5)
    # Raund vaqti tugadi
    vaqt(16, 21, 1, 0)
    await ar(13, m4); await ar(16, m4)
    A = await ar(13, m4, move="himoya", acc=70)
    ilgari(14); await ar(13, m4); await ar(16, m4)
    ilgari(14); await ar(13, m4); await ar(16, m4)
    ilgari(4)
    A = await ar(13, m4)
    check("yurmagan duelchining afsuni chiqmaydi", A["phase"] == "reveal" and A["last"]["win"] == 1 and A["last"]["racc"] == 0 and A["rlives"] == 4)
    # Kelmagan raqib
    vaqt(16, 21, 0, 20)
    await ar(14, m2)
    vaqt(16, 21, 5, 2)
    A = await ar(14, m2)
    check("raqib 5 daqiqada kelmadi: g'alaba", A["over"] and A["won"] and A["why"] == "kelmadi" and ball(14) == 20)
    # Hech kim kelmadi: yuqori o'rindagi o'tadi (fon aylanasi)
    vaqt(16, 21, 5, 30)
    await hpduel.tick()
    st, d = await ask(12)
    s8 = d["cup"]["stages"][0]["matches"]; s4 = d["cup"]["stages"][1]["matches"]
    check("ikkalasi kelmadi: saralashda yuqori turgani o'tadi", s8[2]["winner"] == 12 and s8[2]["why"] == "ikkalasi" and ball(12) == 20)
    check("yarim final juftlari to'ldi", (s4[0]["a"]["uid"], s4[0]["b"]["uid"]) == (11, 14) and s4[1]["a"]["uid"] == 12 and d["cup"]["my"]["stage"] == 4)
    # Sinov uchrashuvi (admin): kompyuter raqib, ballsiz
    db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (42,'Admin','gryffindor','2026-10-01T00:00:00Z')")
    st, d = await ask(11, sinov=1)
    check("oddiy odam sinov ocholmaydi", "test_id" not in d)
    st, d = await ask(42, sinov=1)
    tid = d["test_id"]
    A = await ar(42, tid)
    ilgari(13)
    A2 = await ar(42, tid)
    A3 = await ar(42, tid, move="hujum", acc=95)
    ilgari(4)
    A4 = await ar(42, tid)
    check("sinov: kompyuter raqib o'zi keladi va yuradi, ball yo'q", A["phase"] == "early" and A["test"] and A2["phase"] == "pick" and A2["opp"]["here"]
          and A3["moved"] and A4["phase"] == "reveal" and A4["last"]["his"] in hpduel.TURLAR and ball(42) == 0)

    print("Duel: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
