"""Nishonlar: bazadagi izlardan hisoblash, bir marta yozilishi, "yangi" ro'yxati, boshqa odamniki.

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
TMP = tempfile.mkdtemp(prefix="hp-nishon-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpevents, hpnishon, hppatronus   # noqa: E402

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


def sql(q, a=()):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


async def ask(kim, **body):
    r = await hpnishon.api_nishon(Req(body, init=str(kim)))
    return json.loads(r.body)


def got(d):
    return [x["code"] for x in d["list"] if x["got"]]


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.executescript(hpevents.SCHEMA)
    c.close()
    app = types.SimpleNamespace(router=types.SimpleNamespace(add_route=lambda *a, **k: None))
    hpnishon.register(app, {"cors": lambda r: r,
                            "verify_init_data": lambda s: {"id": int(s)} if s.lstrip("-").isdigit() else None})

    check("imzosiz so'rov rad etiladi", (await hpnishon.api_nishon(Req({}, init=""))).status == 403)

    await hpcup.touch_user(1, "Garri")
    await hpcup.touch_user(2, "Ron")
    d = await ask(1)
    check("yangi odamda nishon yo'q, 17 ta ro'yxatda", d["ok"] and d["count"] == 0 and d["total"] == 17
          and len(d["list"]) == 17 and d["new"] == [])

    # Filmlar: botdan, ilovadan (web_ va sifat bilan), 3 tilda
    for p in ("hp1_uz", "web_hp2_uz@hd", "hp3_ru", "hp4_en", "hp1_uz", "fb1_uz", "start", "share_hp1"):
        await hpevents.log(1, "Garri", None, p, "2026-10-04 10:00:00")
    d = await ask(1)
    by = {x["code"]: x for x in d["list"]}
    check("birinchi film va poliglot olindi", got(d) == ["film_1", "poliglot"] and d["new"] == ["film_1", "poliglot"])
    check("8 filmdan 4 tasi, 3 fb dan 1 tasi", (by["film_8"]["have"], by["film_8"]["need"]) == (4, 8)
          and (by["fb_3"]["have"], by["fb_3"]["need"]) == (1, 3))
    check("ko'rilmaguncha yangi bo'lib turadi", (await ask(1))["new"] == ["film_1", "poliglot"])
    await ask(1, seen=True)
    check("ko'rilgach yangi emas", (await ask(1))["new"] == [])

    for p in ("hp5_uz", "hp6_uz", "hp7_uz", "hp8_uz@fhd", "fb2_ru", "web_fb3_en", "sr_s1e1_uz"):
        await hpevents.log(1, "Garri", None, p, "2026-10-04 11:00:00")
    d = await ask(1)
    check("hamma film, fantastik uchlik, serial", d["new"] == ["film_8", "fb_3", "serial_1"])

    # Patronus: saralanmaganga yo'q, bir marta, o'zgarmaydi
    hppatronus.register(app, {"cors": lambda r: r, "verify_init_data": lambda s: {"id": int(s)} if s.lstrip("-").isdigit() else None})
    async def pat(kim, **body):
        r = await hppatronus.api_patronus(Req(body, init=str(kim)))
        return r.status, json.loads(r.body)
    check("patronus: saralanmaganga berilmaydi", (await pat(1, code="stag"))[0] == 409)
    await hpcup.set_house(1, "gryffindor")
    check("patronus: hali yo'q", (await pat(1))[1]["code"] is None)
    check("patronus: noma'lum kod", (await pat(1, code="dragon"))[0] == 400)
    st, d = await pat(1, code="stag")
    check("patronus: yozildi", st == 200 and d["code"] == "stag" and d["new"] is True)
    st, d = await pat(1, code="otter")
    check("patronus: ikkinchi marta o'zgarmaydi", d["code"] == "stag" and d["new"] is False)
    check("patronus: saqlangan", (await pat(1))[1]["code"] == "stag")
    await hpcup.award(1, "daily", "k1", 10)
    await hpcup.award(1, "chess_win", "g1", 10)
    sql("UPDATE users SET wand_at='2026-10-01T00:00:00Z', refs=5 WHERE user_id=1")
    sql("CREATE TABLE IF NOT EXISTS album_egasi (user_id INTEGER, album TEXT, narx INTEGER, vaqt INTEGER)")
    sql("INSERT INTO album_egasi VALUES (1,'hp2',30,1)")
    season = await hpcup.current_season()
    sql("INSERT INTO badges (user_id, code, season_id, earned_at) VALUES (1,'streak_7',?,'x'),(1,'perfect_week',?,'x')",
        (season["id"], season["id"]))
    d = await ask(1, seen=True)
    check("o'quvchi, tayoqcha, ball, hafta, do'stlar, shaxmat, albom",
          set(got(d)) == set(hpnishon.KODLAR) - {"kubok_golib", "top_3"})

    # Hafta yopildi: fakulteti g'olib, o'zi eng ko'p ball to'plagan
    sql("UPDATE seasons SET status='closed', winner_house='gryffindor' WHERE id=?", (season["id"],))
    d = await ask(1)
    check("g'olib fakultet va top-3", d["new"] == ["kubok_golib", "top_3"] and d["count"] == 17)

    # Nishon qaytib olinmaydi
    sql("UPDATE users SET refs=0, wand_at=NULL WHERE user_id=1")
    d = await ask(1)
    check("olingan nishon yo'qolmaydi", d["count"] == 17)

    # Boshqa odam ko'radi: faqat olinganlari
    d = await ask(2, uid=1)
    check("boshqaga faqat olinganlar ko'rinadi", d["count"] == 17 and all(x["got"] for x in d["list"]) and "new" not in d)
    d = await ask(1, uid=2)
    check("nishoni yo'q odam - bo'sh ro'yxat", d["list"] == [] and d["count"] == 0)
    check("yo'q odam - bo'sh ro'yxat", (await ask(1, uid=999))["list"] == [])
    check("noto'g'ri uid", (await hpnishon.api_nishon(Req({"uid": "abc"}, init="1"))).status == 400)


asyncio.run(amain())
print("Nishonlar: %d ta tekshiruv, %d xato" % (ok + fail, fail))
sys.exit(1 if fail else 0)
