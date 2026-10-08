# -*- coding: utf-8 -*-
"""Qo'riqxona: maxluq olish (darslar, bellashuv), yemish sotib olish, boqish, o'sish, sovg'a, profil, nishonlar.

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
TMP = tempfile.mkdtemp(prefix="hp-qoriq-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars, hpqoriq, hpnishon   # noqa: E402

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
    r = await hpqoriq.api_qoriq(Req(body, init=str(kim)))
    return r.status, json.loads(r.body)


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
    loglar = []
    async def log(user, payload):
        loglar.append(payload)
    app = types.SimpleNamespace(router=types.SimpleNamespace(add_route=lambda *a, **k: None))
    cfg = {"cors": lambda r: r, "log": log, "verify_init_data": lambda s: {"id": int(s)} if s.lstrip("-").isdigit() else None}
    hpdars.register(app, cfg)
    hpqoriq.register(app, cfg)
    for uid in (1, 2):
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (uid, "S%d" % uid, "gryffindor", "2026-10-01T00:00:00Z"))
    db("UPDATE users SET galleons = 3 WHERE user_id = 1")

    st, d = await ask("x")
    check("imzosiz 403", st == 403)
    st, d = await ask(1)
    L = {x["kod"]: x for x in d["list"]}
    check("boshida maxluq yo'q, 12 ta ro'yxatda", d["ok"] and len(d["list"]) == 12 and not any(x["got"] for x in d["list"])
          and d["gal"] == 3 and L["gippo"]["need"] == 3 and L["kalamush"]["need"] == 33 and L["ajdar"]["need"] == 0)
    st, d = await ask(1, buy="gippo")
    check("yo'q maxluqqa yemish olinmaydi", d["ok"] is False and d["error"] == "yoq" and d["gal"] == 3)

    db("INSERT INTO dars_daraja (user_id, dars, daraja, kun) VALUES (1, 'maxluq', 7, NULL)")
    st, d = await ask(1)
    check("7-dars: ikki maxluq (har uch darsda bitta)", [x["kod"] for x in d["list"] if x["got"]] == ["gippo", "boyogli"])
    st, d = await ask(1, feed="gippo")
    check("yemishsiz boqilmaydi", d["error"] == "yemish")
    st, d = await ask(1, buy="gippo")
    L = {x["kod"]: x for x in d["list"]}
    check("1 galleon = 5 porsiya", d["ok"] and d["gal"] == 2 and L["gippo"]["food"] == 5 and L["boyogli"]["food"] == 0)
    st, d = await ask(1, feed="gippo")
    L = {x["kod"]: x for x in d["list"]}
    check("boqildi: porsiya kamaydi, bugun belgilandi", d["ok"] and d["fed"] == "gippo" and d["grew"] is None and d["gift"] == 0
          and L["gippo"]["food"] == 4 and L["gippo"]["fed"] == 1 and L["gippo"]["today"] and L["gippo"]["next"] == 2)
    st, d = await ask(1, feed="gippo")
    check("kuniga bir marta", d["error"] == "bugun" and {x["kod"]: x for x in d["list"]}["gippo"]["food"] == 4)

    def kecha():
        db("UPDATE qoriq SET oxirgi = '2000-01-01' WHERE user_id = 1")
    kecha(); await ask(1, feed="gippo"); kecha()
    st, d = await ask(1, feed="gippo")
    check("3 marta boqilsa o'smir", d["grew"] == 1 and {x["kod"]: x for x in d["list"]}["gippo"]["stage"] == 1)
    db("UPDATE qoriq SET boqildi = 9, yemish = 20 WHERE user_id = 1 AND kod = 'gippo'"); kecha()
    st, d = await ask(1, feed="gippo")
    L = {x["kod"]: x for x in d["list"]}
    check("10 marta - katta; gippogrif sovg'a keltirmaydi (u darsda yordam beradi)", d["grew"] == 2 and L["gippo"]["stage"] == 2 and L["gippo"]["gift"] == 0 and d["gift"] == 0)
    db("UPDATE qoriq SET boqildi = 16 WHERE user_id = 1 AND kod = 'gippo'"); kecha()
    st, d = await ask(1, feed="gippo")
    check("gippogrif 7-boqishda ham galleon bermaydi", d["gift"] == 0 and d["gal"] == 2)
    # Boyo'g'li: har 7-boqishda boshqa maxluqlarga 3 porsiya yemish
    db("UPDATE qoriq SET boqildi = 16, yemish = 5 WHERE user_id = 1 AND kod = 'boyogli'")
    oldin = db("SELECT yemish FROM qoriq WHERE user_id = 1 AND kod = 'gippo'")[0][0]; kecha()
    st, d = await ask(1, feed="boyogli")
    L = {x["kod"]: x for x in d["list"]}
    check("boyo'g'li boshqa maxluqqa 3 porsiya keltiradi", d["gift"] == {"type": "food", "n": 3} and L["gippo"]["food"] == oldin + 3
          and L["boyogli"]["food"] == 4 and L["boyogli"]["gift"] == 7 and d["gal"] == 2)
    # Niffler: 1 galleon
    db("INSERT INTO qoriq (user_id, kod, olgan, boqildi, yemish) VALUES (1, 'niffler', 'x', 16, 3)")
    st, d = await ask(1, feed="niffler")
    check("niffler har 7-boqishda 1 galleon topadi", d["gift"] == {"type": "gal", "n": 1} and d["gal"] == 3)
    kecha(); st, d = await ask(1, feed="niffler")
    check("keyingi boqishda sovg'a yo'q", d["gift"] == 0 and d["gal"] == 3)
    db("DELETE FROM qoriq WHERE user_id = 1 AND kod = 'niffler'")

    db("UPDATE users SET galleons = 0 WHERE user_id = 1")
    st, d = await ask(1, buy="boyogli")
    check("galleon yetmasa", d["error"] == "pul" and d["gal"] == 0)
    st, d = await ask(1, buy="tovuq")
    check("noma'lum maxluq 404", st == 404)

    # Noyob maxluq: bellashuvda birinchi uchlik (sovrin 7 balldan)
    st, d = await ask(2)
    check("bellashuvsiz ajdar yo'q", not {x["kod"]: x for x in d["list"]}["ajdar"]["got"])
    hpcup._award(2, "dars", "m:maxluq:2026-10-08", 7)
    hpcup._award(2, "dars", "m:afsun:2026-10-08", 15)
    st, d = await ask(2)
    check("maxluq bellashuvida uchlikka kirgan - ajdar bolasi", [x["kod"] for x in d["list"] if x["got"]] == ["ajdar"])
    hpcup._award(1, "dars", "m:maxluq:2026-10-09", 3)
    st, d = await ask(1)
    check("4-10-o'rin (3 ball) ajdar bermaydi", not {x["kod"]: x for x in d["list"]}["ajdar"]["got"])

    check("profilda: olinish tartibida, bosqichi bilan", hpqoriq.korinish(1) == [{"kod": "gippo", "stage": 2}, {"kod": "boyogli", "stage": 2}]
          and hpqoriq.korinish(999) == [])
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.row_factory = sqlite3.Row
    h = hpnishon.hisob(c, 1)
    c.close()
    check("nishonlar: birinchi maxluq, katta maxluq, 12 tadan 2 tasi", h["maxluq_1"] == (1, 1) and h["maxluq_katta"] == (1, 1) and h["maxluq_12"] == (2, 12))
    check("log", "qoriq_yemish_gippo" in loglar and "qoriq_boq_gippo" in loglar)

    print("Qo'riqxona: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
