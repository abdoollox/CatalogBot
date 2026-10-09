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
    check("bir xil tur: aniqrog'i yutadi, farq kichik bo'lsa durang", H("hujum", 80, "hujum", 60) == 1 and H("hujum", 60, "hujum", 80) == -1 and H("hujum", 80, "hujum", 78) == 0)
    check("afsun chiqmasa (aniqlik past) - raqib uradi; ikkalasi chiqmasa durang", H("hujum", 20, "hiyla", 50) == -1 and H("hiyla", 50, "hujum", 20) == 1 and H("hujum", 10, "hiyla", 10) == 0)

    st, d = await ask("x")
    check("imzosiz 403", st == 403)
    st, d = await ask(3)
    check("saralanmagan o'ynay olmaydi", d == {"ok": False, "error": "no_house"})
    st, d = await ask(1)
    check("boshida bo'sh holat", d["ok"] and d["mine"]["total"] == 0 and d["top"] == [] and d["place"] is None and d["rules"]["lives"] == 3)
    st, d = await ask(1, start=7)
    check("noma'lum raqib 404", st == 404)
    st, d = await ask(1, start=2)
    g = d["game"]
    check("duel boshlandi", g["level"] == 2 and g["lives"] == 3 and g["rlives"] == 3 and g["round"] == 0)
    st, d = await ask(1, game=g["id"], move="sehr", acc=90)
    check("noma'lum tur 404", st == 404)

    # Uch raundda g'alaba: raqib hiyla qiladi, men hujum
    r = None
    for i in range(3):
        r = hpduel._yur(1, g["id"], "hujum", 90, Rnd("hiyla", 70))
    check("uch raundda yutdi, ball = 200 + 3 jon + aniqlik", r["game"]["over"] and r["game"]["won"] and r["game"]["rlives"] == 0 and r["game"]["lives"] == 3
          and r["game"]["score"] == 200 + 60 + 45 and r["round"]["win"] == 1)
    check("tugagan duelga yurish yo'q", hpduel._yur(1, g["id"], "hujum", 90) is None)
    st, d = await ask(1)
    check("saralash jadvalida", d["mine"]["2"] == 305 and d["mine"]["total"] == 305 and d["place"] == 1 and d["top"][0]["me"] and d["top"][0]["score"] == 305)

    # Yomonroq g'alaba eng yaxshi natijani pasaytirmaydi; boshqa daraja qo'shiladi
    g2 = hpduel._boshla(1, 2)
    hpduel._yur(1, g2["id"], "hujum", 90, Rnd("himoya", 70))
    for i in range(3):
        r = hpduel._yur(1, g2["id"], "hujum", 60, Rnd("hiyla", 70))
    check("pastroq natija saqlanmaydi", r["game"]["won"] and r["game"]["score"] < 305 and (await ask(1))[1]["mine"]["2"] == 305)
    g3 = hpduel._boshla(1, 1)
    for i in range(3):
        r = hpduel._yur(1, g3["id"], "himoya", 80, Rnd("hujum", 70))
    st, d = await ask(1)
    check("darajalar yig'iladi", d["mine"]["1"] == 100 + 60 + 40 and d["mine"]["total"] == 505)

    # Mag'lubiyat va ikkinchi o'yinchi
    g4 = hpduel._boshla(2, 3)
    for i in range(3):
        r = hpduel._yur(2, g4["id"], "hujum", 90, Rnd("himoya", 70))
    check("yutqazdi: ball yo'q", r["game"]["over"] and not r["game"]["won"] and r["game"]["score"] == 0 and r["game"]["lives"] == 0)
    g5 = hpduel._boshla(2, 1)
    for i in range(3):
        hpduel._yur(2, g5["id"], "hujum", 100, Rnd("hiyla", 70))
    st, d = await ask(2)
    check("jadval: ikki kishi, o'rin", d["n"] == 2 and d["place"] == 2 and [x["score"] for x in d["top"]] == [505, 210])

    # Yangi duel eskisini tashlaydi; API orqali to'liq duel
    a = hpduel._boshla(1, 1); b = hpduel._boshla(1, 1)
    check("yangi duel boshlansa eskisi tashlanadi", hpduel._yur(1, a["id"], "hujum", 90) is None)
    over = False
    for i in range(20):
        st, d = await ask(1, game=b["id"], move="hujum", acc=95)
        if d.get("game", {}).get("over"):
            over = True
            break
    check("API orqali duel tugaydi (12 raunddan oshmaydi)", over and d["game"]["round"] <= 12 and "round" in d)
    db("UPDATE duel_saral SET hafta='2000-01-03'")
    st, d = await ask(1)
    check("yangi haftada jadval yangidan", d["mine"]["total"] == 0 and d["top"] == [])
    check("log", any(x.startswith("duel_1_") for x in loglar))

    print("Duel: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
