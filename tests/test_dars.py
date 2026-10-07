"""Darslar: kun mavzusi, holat, ball (kuniga bir marta), faqat saralanganlarga.

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
TMP = tempfile.mkdtemp(prefix="hp-dars-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars   # noqa: E402

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
    r = await hpdars.api_dars(Req(body, init=str(kim)))
    return r.status, json.loads(r.body)


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    loglar = []
    async def log(user, payload):
        loglar.append(payload)
    app = types.SimpleNamespace(router=types.SimpleNamespace(add_route=lambda *a, **k: None))
    hpdars.register(app, {"cors": lambda r: r, "log": log,
                          "verify_init_data": lambda s: {"id": int(s)} if s.lstrip("-").isdigit() else None})

    k = hpdars.kun_mavzusi
    check("kun mavzusi: birinchi kun birinchi afsun, aylanadi", k("afsun", "2026-10-07") == "lumos"
          and k("afsun", "2026-10-08") == "leviosa" and k("afsun", "2026-10-19") == "lumos"
          and k("iksir", "2026-10-07") == "boils" and k("iksir", "2026-10-17") == "boils")
    check("kubok: 'dars' manbasi va chegaralar", hpcup.SOURCE_GROUP["dars"] == "lesson" and "lesson" in hpcup.SOURCE_KEYS
          and hpcup.SOURCE_CAPS["lesson"] == 70 and hpcup.MAX_POINTS == 300)

    check("imzosiz - 403", (await ask(""))[0] == 403)
    await hpcup.touch_user(1, "Garri")
    st, d = await ask(1)
    check("saralanmaganga yo'q", d == {"ok": False, "error": "no_house"})
    await hpcup.set_house(1, "gryffindor")
    st, d = await ask(1)
    check("holat: uch fan, hech biri bajarilmagan", d["ok"] and set(d["lessons"]) == {"tarix", "afsun", "iksir"}
          and not any(x["done"] for x in d["lessons"].values()) and d["lessons"]["afsun"]["pts"] == 5
          and d["lessons"]["afsun"]["item"] in hpdars.DARSLAR["afsun"]["items"] and d["lessons"]["tarix"]["pts"] == 10)
    st, d = await ask(1, done="afsun")
    check("afsun bajarildi: +5 ball", d["new"] is True and d["pts"] == 5 and d["lessons"]["afsun"]["done"]
          and not d["lessons"]["iksir"]["done"])
    st, d = await ask(1, done="afsun")
    check("ikkinchi marta ball yo'q", d["new"] is False and d["pts"] == 0 and d["lessons"]["afsun"]["done"])
    st, d = await ask(1, done="iksir")
    check("iksir alohida ballanadi", d["new"] is True and d["lessons"]["iksir"]["done"])
    st, d = await ask(1, done="uchish")
    check("noma'lum fan", d == {"ok": False, "error": "unknown"})
    season = await hpcup.current_season()
    stats = await hpcup.user_stats(1, season["id"])
    check("kubokda 'lesson' manbasi 10 ball", stats["by"].get("lesson") == 10)
    check("log: fan va mavzu", len(loglar) == 2 and loglar[0].startswith("dars_afsun_") and loglar[1].startswith("dars_iksir_"))
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    ddl = c.execute("SELECT sql FROM sqlite_master WHERE name='points'").fetchone()[0]
    c.close()
    check("jadval cheklovida 'dars' bor", "'dars'" in ddl)

    print("Darslar: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(amain())
