# -*- coding: utf-8 -*-
"""So'rovnoma: faqat saralanganlar, bitta ovoz (o'zgartirsa bo'ladi), natija ovozdan keyin, yopiq holatda faqat adminga.

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
TMP = tempfile.mkdtemp(prefix="hp-sorov-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars, hpsorov as P   # noqa: E402

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
    r = await P.api_sorov(Req(body, init=str(kim)))
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
    P.register(app, dict(cfg, admin_ids={42}))
    soat = [datetime(2026, 10, 13, 12, 0, tzinfo=TZ)]
    hpcup.now_tk = lambda: soat[0]
    for u in (1, 2, 3, 42):
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (u, "U%d" % u, "gryffindor", "2026-10-01T00:00:00Z"))
    db("INSERT OR IGNORE INTO users (user_id, first_name, created_at) VALUES (30,'Uysiz','2026-10-01T00:00:00Z')")

    P.YOQIQ = False
    d = await ask(1)
    check("yopiq so'rovnoma oddiy o'quvchiga ko'rinmaydi", d["ok"] and d["on"] is False and "options" not in d)
    d = await ask(1, vote="22")
    check("yopiq paytda ovoz qabul qilinmaydi", "vote_ok" not in d and db("SELECT COUNT(*) FROM sorov_ovoz")[0][0] == 0)
    d = await ask(42)
    check("admin yopiq so'rovnomani ko'radi (ko'rik)", d["on"] and d["preview"] and [o["k"] for o in d["options"]] == ["20", "21", "22"])
    P.YOQIQ = True
    check("saralanmagan qatnasha olmaydi", (await ask(30)).get("error") == "no_house")
    d = await ask(1)
    check("ovoz bermaguncha natija ko'rinmaydi", d["on"] and d["open"] and d["mine"] is None and "n" not in d["options"][0] and "total" not in d)
    d = await ask(1, vote="19")
    check("ro'yxatda yo'q variant qabul qilinmaydi", d["vote_ok"] is False and d["mine"] is None)
    d = await ask(1, vote="22")
    check("ovoz qabul qilindi, natija ko'rinadi", d["vote_ok"] and d["mine"] == "22" and d["total"] == 1 and [o["n"] for o in d["options"]] == [0, 0, 1])
    await ask(2, vote="21"); await ask(3, vote="22")
    d = await ask(1, vote="21")
    check("ovozni o'zgartirsa bo'ladi - bir odam bitta ovoz", d["mine"] == "21" and d["total"] == 3 and [o["n"] for o in d["options"]] == [0, 2, 1])
    soat[0] = datetime(2026, 10, 19, 0, 1, tzinfo=TZ)
    d = await ask(2, vote="20")
    check("muddat tugagach ovoz qabul qilinmaydi, natija hammaga ko'rinadi", d["vote_ok"] is False and not d["open"] and d["mine"] == "21"
          and (await ask(42))["total"] == 3)

    print("So'rovnoma: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(amain())
