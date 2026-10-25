# -*- coding: utf-8 -*-
"""Shaxmat: taxtada yurish qabul qilinmaganda ilova sababini yuboradi ({diag}) - jurnalga bir marta yoziladi.

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
TMP = tempfile.mkdtemp(prefix="hp-chessdiag-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"

import hpcup, hpchess, hpevents   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


class Req:
    def __init__(self, what, body):
        self.method, self._b = "POST", body
        self.headers = {"X-Telegram-Init-Data": "x"}
        self.query = {}
        self.match_info = {"what": what}
    async def json(self):
        return self._b


class App:
    def __init__(self):
        self.router = self
    def add_route(self, m, path, h):
        self.h = h


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    conn = hpcup._connect(); conn.executescript(hpevents.SCHEMA); conn.close()
    app = App()
    hpchess.asyncio.ensure_future = lambda c: c.close()       # kuzatuvchi sinovda kerak emas
    hpchess.register(app, {"verify_init_data": lambda s: {"id": 7, "first_name": "Garri"},
                           "cors": lambda r: r})
    def yozuvlar():
        c = sqlite3.connect(os.environ["HP_DB_PATH"])
        try:
            return [r[0] for r in c.execute("SELECT payload FROM events WHERE user_id=7 ORDER BY id")]
        finally:
            c.close()
    r = await app.h(Req("diag", {"game_id": "abc123", "why": "stuck"}))
    check("javob ok", json.loads(r.body).get("ok") is True)
    check("sabab jurnalga yozildi", yozuvlar() == ["chess_blok_stuck"])
    await app.h(Req("diag", {"game_id": "abc123", "why": "stuck"}))
    check("bir o'yinda bir sabab bir marta", yozuvlar() == ["chess_blok_stuck"])
    await app.h(Req("diag", {"game_id": "abc123", "why": "cover"}))
    await app.h(Req("diag", {"game_id": "abc123", "why": "<b>xak</b>"}))
    check("faqat ro'yxatdagi sabablar", yozuvlar() == ["chess_blok_stuck", "chess_blok_cover"])
    print("Shaxmat diag: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
