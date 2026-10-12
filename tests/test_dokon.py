# -*- coding: utf-8 -*-
"""Do'kon: jihoz bosqichlari va narxi, damlamalar, bellashuv jarimasi, duel kuchi, bir martalik ishlatish.

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
TMP = tempfile.mkdtemp(prefix="hp-dokon-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import time
import hpcup, hpdars, hpduel, hpdokon as P   # noqa: E402

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
    r = await P.api_dokon(Req(body, init=str(kim)))
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
    P.register(app, cfg)
    for u in (1, 2):
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at, galleons) VALUES (?,?,?,?,?)", (u, "U%d" % u, "gryffindor", "2026-10-01T00:00:00Z", 0))
    db("INSERT OR IGNORE INTO users (user_id, first_name, created_at) VALUES (30,'Uysiz','2026-10-01T00:00:00Z')")
    def gal(u):
        return db("SELECT galleons FROM users WHERE user_id=?", (u,))[0][0]

    check("saralanmagan do'konga kira olmaydi", (await ask(30)).get("error") == "no_house")
    d = await ask(1)
    check("boshida: beshta jihoz 0-bosqichda, uchta damlama yo'q", [g["k"] for g in d["gear"]] == list(P.JIHOZLAR) and all(g["level"] == 0 and g["price"] == 15 for g in d["gear"])
          and [(p["k"], p["n"], p["on"]) for p in d["potions"]] == [("feliks", 0, True), ("tezlik", 0, True), ("diqqat", 0, True)])
    d = await ask(1, buy="supurgi")
    check("galleon yetmasa sotilmaydi", d["buy"] == "pul" and d["gear"][0]["level"] == 0 and gal(1) == 0)
    db("UPDATE users SET galleons=140 WHERE user_id=1")
    d = await ask(1, buy="supurgi")
    check("1-bosqich: 15 galleon", d["buy"] == "ok" and d["gear"][0]["level"] == 1 and d["gear"][0]["price"] == 35 and d["galleons"] == 125)
    d = await ask(1, buy="supurgi"); d = await ask(1, buy="supurgi")
    check("2- va 3-bosqich: 35 va 80; keyin narx yo'q", d["buy"] == "ok" and d["gear"][0]["level"] == 3 and d["gear"][0]["price"] is None and d["galleons"] == 10)
    d = await ask(1, buy="supurgi")
    check("eng yuqori bosqichdan keyin sotilmaydi, pul ketmaydi", d["buy"] == "toliq" and d["galleons"] == 10)
    check("noma'lum mol", (await ask(1, buy="ajdar"))["buy"] == "yoq" and gal(1) == 10)
    d = await ask(1, buy="diqqat"); d = await ask(1, buy="diqqat"); d = await ask(1, buy="feliks")
    check("damlamalar: 2 + 2 + 4 galleon, soni oshadi", d["galleons"] == 2 and [(p["k"], p["n"]) for p in d["potions"]] == [("feliks", 1), ("tezlik", 0), ("diqqat", 2)])
    d = await ask(1, buy="tezlik")
    check("damlamaga ham galleon yetishi kerak", d["buy"] == "pul" and d["galleons"] == 2)
    d = await ask(1, use="tezlik")
    check("yo'q damlama ishlatilmaydi", d["used"] is False)

    # ---------- bellashuv: jihoz jarimani kamaytiradi, «diqqat» birinchi xatoni kechiradi ----------
    db("UPDATE users SET galleons=200 WHERE user_id=2")
    await ask(2, buy="qozon"); await ask(2, buy="qozon")
    c = hpcup._connect()
    check("jarima: jihozsiz 3 s, qozonning 2-bosqichida 2,2 s (faqat o'z fanida)", P.jarima_ms(c, 1, "iksir") == 3000 and P.jarima_ms(c, 2, "iksir") == 2200
          and P.jarima_ms(c, 2, "afsun") == 3000 and P.jarima_ms(c, 2, "uchish") == 3000)
    c.close()
    kun = hpdars._kun() if hasattr(hpdars, "_kun") else hpcup.now_tk().strftime("%Y-%m-%d")
    def boshla(u, dars):
        db("INSERT OR REPLACE INTO dars_bellashuv (kun, dars, user_id, ms, boshladi, urinish) VALUES (?,?,?,NULL,?,1)", (kun, dars, u, time.time() - 20))
    boshla(2, "iksir")
    ms, _ = hpdars._tugat(2, "iksir", kun, 2)
    check("qozonli o'quvchi: 2 xato = 2 x 2,2 s", 20000 + 4400 <= ms <= 20000 + 4400 + 600 and hpdars._tugat.oxirgi == {"penalty": 2200, "forgiven": False})
    boshla(1, "iksir")
    ms, _ = hpdars._tugat(1, "iksir", kun, 2)
    check("«diqqat» damlamasi: birinchi xato jarimasiz, bittasi sarflandi", 20000 + 3000 <= ms <= 20000 + 3000 + 600 and hpdars._tugat.oxirgi["forgiven"]
          and db("SELECT soni FROM dokon_damlama WHERE user_id=1 AND kod='diqqat'")[0][0] == 1)
    boshla(1, "afsun")
    hpdars._tugat(1, "afsun", kun, 0)
    check("xato bo'lmasa damlama sarflanmaydi", db("SELECT soni FROM dokon_damlama WHERE user_id=1 AND kod='diqqat'")[0][0] == 1)
    await ask(1, toggle="diqqat", on=0)
    boshla(1, "himoya")
    ms, _ = hpdars._tugat(1, "himoya", kun, 1)
    check("o'chirib qo'yilgan damlama ishlamaydi", ms >= 23000 and db("SELECT soni, faol FROM dokon_damlama WHERE user_id=1 AND kod='diqqat'")[0] == (1, 0))

    # ---------- duel: qo'lqop kuch qo'shadi, lekin chiqmagan afsunga yordam bermaydi ----------
    check("duel: 60 ga qarshi 66 - yutqazadi; qo'lqop (+6) bilan durang", hpduel.hal_qil("hujum", 60, "hujum", 66) == -1 and hpduel.hal_qil("hujum", 60, "hujum", 66, 6, 0) == 0)
    check("duel: 62 ga qarshi 61 - durang; qo'lqop (+6) bilan yutadi", hpduel.hal_qil("hujum", 62, "hujum", 61) == 0 and hpduel.hal_qil("hujum", 62, "hujum", 61, 6, 0) == 1)
    check("duel: afsun chiqmasa (aniqlik past) qo'lqop yordam bermaydi", hpduel.kuch("hujum", hpduel.KAM - 1, "hiyla", 6) == 0)
    await ask(2, buy="qolqop")
    c = hpcup._connect()
    check("duel kuchi: 1-bosqich qo'lqop +2, jihozsiz 0, kompyuter raqibga 0", P.duel_kuch(c, 2) == 2 and P.duel_kuch(c, 1) == 0 and P.duel_kuch(c, -999) == 0 and P.duel_kuch(c, None) == 0)
    # ---------- bir martalik ishlatish (feliks - har viktorinada bir marta) ----------
    db("UPDATE dokon_damlama SET soni=3 WHERE user_id=1 AND kod='feliks'")
    a = P.damlama_ishlat(c, 1, "feliks", "vik:2026-10-12"); b = P.damlama_ishlat(c, 1, "feliks", "vik:2026-10-12"); c.commit()
    d2 = P.damlama_ishlat(c, 1, "feliks", "vik:2026-10-19"); c.commit(); c.close()
    check("feliks: bitta viktorinada bir marta, keyingisida yana ishlaydi", a and not b and d2 and db("SELECT soni FROM dokon_damlama WHERE user_id=1 AND kod='feliks'")[0][0] == 1)

    print("Do'kon: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(amain())
