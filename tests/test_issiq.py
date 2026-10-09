# -*- coding: utf-8 -*-
"""Issiqxona: urug' olish (darslar), sug'orish, o'sish, hosil, hosil bilan maxluq boqish.

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
TMP = tempfile.mkdtemp(prefix="hp-issiq-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars, hpqoriq, hpissiq   # noqa: E402

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
    r = await hpissiq.api_issiq(Req(body, init=str(kim)))
    return r.status, json.loads(r.body)


async def qor(kim, **body):
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
    hpissiq.register(app, cfg)
    hpqoriq.register(app, cfg)
    db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (1,'S1','gryffindor','2026-10-01T00:00:00Z')")

    st, d = await ask("x")
    check("imzosiz 403", st == 403)
    st, d = await ask(1)
    L = {x["kod"]: x for x in d["list"]}
    check("boshida o'simlik yo'q, 12 ta ro'yxatda", d["ok"] and len(d["list"]) == 12 and not any(x["got"] for x in d["list"])
          and d["hosil"] == 0 and L["mandragora"]["need"] == 3 and L["tol"]["need"] == 36)
    st, d = await ask(1, water="mandragora")
    check("yo'q o'simlik sug'orilmaydi", d["ok"] and d["watered"] == [])
    st, d = await ask(1, water="lola")
    check("noma'lum o'simlik 404", st == 404)

    db("INSERT INTO dars_daraja (user_id, dars, daraja, kun) VALUES (1, 'osimlik', 7, NULL)")
    st, d = await ask(1)
    check("7-dars: ikki urug'", [x["kod"] for x in d["list"] if x["got"]] == ["mandragora", "bubotuber"])
    st, d = await ask(1, water="mandragora")
    L = {x["kod"]: x for x in d["list"]}
    check("sug'orildi: bugun belgilandi", d["watered"] == ["mandragora"] and d["grew"] == {} and d["crop"] == 0
          and L["mandragora"]["watered"] == 1 and L["mandragora"]["today"] and L["mandragora"]["next"] == 2 and not L["bubotuber"]["today"])
    st, d = await ask(1, water="mandragora")
    check("kuniga bir marta", d["watered"] == [] and {x["kod"]: x for x in d["list"]}["mandragora"]["watered"] == 1)
    st, d = await ask(1, water="all")
    check("hammasini sug'orish: faqat bugun sug'orilmaganlari", d["watered"] == ["bubotuber"])

    db("UPDATE issiq SET sugorildi = 2, oxirgi = '2000-01-01' WHERE user_id=1 AND kod='mandragora'")
    st, d = await ask(1, water="mandragora")
    check("3-sug'orishda o'smir", d["grew"] == {"mandragora": 1} and {x["kod"]: x for x in d["list"]}["mandragora"]["stage"] == 1)
    db("UPDATE issiq SET sugorildi = 9, oxirgi = '2000-01-01' WHERE user_id=1 AND kod='mandragora'")
    st, d = await ask(1, water="mandragora")
    L = {x["kod"]: x for x in d["list"]}
    check("10-sug'orishda yetiladi, hosilgacha 3 ta", d["grew"] == {"mandragora": 2} and d["crop"] == 0 and L["mandragora"]["stage"] == 2 and L["mandragora"]["crop"] == 3)
    db("UPDATE issiq SET sugorildi = 12, oxirgi = '2000-01-01' WHERE user_id=1 AND kod='mandragora'")
    st, d = await ask(1, water="mandragora")
    check("yetilgan o'simlik har 3-sug'orishda hosil beradi", d["crop"] == 1 and d["hosil"] == 1)
    db("UPDATE issiq SET sugorildi = 13, oxirgi = '2000-01-01' WHERE user_id=1 AND kod='mandragora'")
    st, d = await ask(1, water="mandragora")
    check("oraliq sug'orishda hosil yo'q", d["crop"] == 0 and d["hosil"] == 1)

    # Hosil bilan maxluq boqish (Qo'riqxona)
    db("INSERT INTO dars_daraja (user_id, dars, daraja, kun) VALUES (1, 'maxluq', 3, NULL)")
    st, d = await qor(1)
    check("qo'riqxonada hosil ko'rinadi", d["hosil"] == 1 and {x["kod"]: x for x in d["list"]}["gippo"]["got"])
    st, d = await qor(1, feed="gippo", hosil=1)
    L = {x["kod"]: x for x in d["list"]}
    check("hosil bilan boqildi: hosil kamaydi, yemish tegilmadi", d["ok"] and d["fed"] == "gippo" and d["hosil"] == 0 and L["gippo"]["fed"] == 1 and L["gippo"]["food"] == 0)
    db("UPDATE qoriq SET oxirgi = '2000-01-01' WHERE user_id=1")
    st, d = await qor(1, feed="gippo", hosil=1)
    check("hosil tugagan bo'lsa boqilmaydi", d["ok"] is False and d["error"] == "yemish" and {x["kod"]: x for x in d["list"]}["gippo"]["fed"] == 1)
    check("profil uchun ko'rinish", hpissiq.korinish(1)[0] == {"kod": "mandragora", "stage": 2} and len(hpissiq.korinish(1)) == 2)
    check("log", "issiq_suv_mandragora" in loglar and "issiq_suv_hammasi" in loglar and "qoriq_boq_gippo_hosil" in loglar)

    print("Issiqxona: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
