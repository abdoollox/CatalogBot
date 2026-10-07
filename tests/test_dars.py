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
    check("bellashuv mavzusi: sana bo'yicha aylanadi", k("afsun", "2026-10-07") == "lumos"
          and k("afsun", "2026-10-08") == "leviosa" and k("afsun", "2026-10-19") == "lumos"
          and k("iksir", "2026-10-07") == "boils" and k("iksir", "2026-10-17") == "boils")
    check("dars mavzusi: bosqich bo'yicha", hpdars.daraja_mavzusi("afsun", 0) == "lumos"
          and hpdars.daraja_mavzusi("afsun", 13) == "leviosa" and hpdars.daraja_mavzusi("iksir", 10) == "boils")
    check("kubok: 'dars' manbasi va chegaralar", hpcup.SOURCE_GROUP["dars"] == "lesson" and "lesson" in hpcup.SOURCE_KEYS
          and hpcup.SOURCE_CAPS["lesson"] == 70 and hpcup.MAX_POINTS == 300)
    check("sovrinlar", [hpdars.sovrin(i) for i in (1, 2, 3, 4, 10, 11)] == [15, 10, 7, 3, 3, 0])

    check("imzosiz - 403", (await ask(""))[0] == 403)
    await hpcup.touch_user(1, "Garri Potter")
    st, d = await ask(1)
    check("saralanmaganga yo'q", d == {"ok": False, "error": "no_house"})
    await hpcup.set_house(1, "gryffindor")
    st, d = await ask(1)
    L = d["lessons"]
    check("holat: uch fan, birinchi dars", d["ok"] and set(L) == {"tarix", "afsun", "iksir"}
          and not any(x["done"] for x in L.values()) and L["afsun"]["pts"] == 5 and L["afsun"]["level"] == 0
          and L["afsun"]["n"] == 1 and L["afsun"]["item"] == "lumos" and L["afsun"]["cycle"] == 0 and L["tarix"]["pts"] == 10)
    st, d = await ask(1, done="afsun")
    L = d["lessons"]
    check("afsun bajarildi: +5 ball, bosqich 1, mashq uchun shu dars", d["new"] is True and d["pts"] == 5
          and L["afsun"]["done"] and L["afsun"]["level"] == 1 and L["afsun"]["n"] == 1 and L["afsun"]["item"] == "lumos"
          and not L["iksir"]["done"])
    st, d = await ask(1, done="afsun")
    check("bugun ikkinchi marta: ball ham, bosqich ham yo'q", d["new"] is False and d["pts"] == 0
          and d["lessons"]["afsun"]["level"] == 1)
    st, d = await ask(1, done="iksir")
    check("iksir alohida bosqich", d["new"] is True and d["lessons"]["iksir"]["level"] == 1)
    st, d = await ask(1, done="uchish")
    check("noma'lum fan", d == {"ok": False, "error": "unknown"})

    # Ertasi kuni: keyingi dars
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute("UPDATE dars_daraja SET kun='2026-01-01', daraja=12 WHERE user_id=1 AND dars='afsun'")
    c.commit(); c.close()
    st, d = await ask(1)
    A = d["lessons"]["afsun"]
    check("yangi kunda keyingi dars, ikkinchi aylana", not A["done"] and A["level"] == 12 and A["n"] == 13
          and A["item"] == "lumos" and A["cycle"] == 1)
    st, d = await ask(1, done="afsun")
    check("13-dars bajarildi", d["new"] and d["lessons"]["afsun"]["level"] == 13)

    season = await hpcup.current_season()
    stats = await hpcup.user_stats(1, season["id"])
    check("kubokda 'lesson' manbasi", stats["by"].get("lesson") == 10)
    check("log: fan va bosqich", loglar[0] == "dars_afsun_1" and "dars_iksir_1" in loglar and "dars_afsun_13" in loglar)

    # --- Bellashuv ---
    for uid, nom in ((2, "Ron"), (3, "Germiona"), (4, "Nevill")):
        await hpcup.touch_user(uid, nom)
        await hpcup.set_house(uid, "gryffindor" if uid != 4 else "hufflepuff")
    st, d = await ask(2, finish="afsun")
    check("boshlamasdan tugatib bo'lmaydi", d["ok"] is False and d["error"] == "not_started")
    kun = hpcup.today_tk()
    def boshladi(uid, soniya):
        c = sqlite3.connect(os.environ["HP_DB_PATH"])
        c.execute("UPDATE dars_bellashuv SET boshladi = boshladi - ? WHERE user_id=? AND dars='afsun' AND kun=?", (soniya, uid, kun))
        c.commit(); c.close()
    for uid, soniya, xato in ((1, 10, 0), (2, 6, 1), (3, 4, 0)):
        st, d = await ask(uid, start="afsun")
        boshladi(uid, soniya)
        st, d = await ask(uid, finish="afsun", xato=xato)
    C = d["lessons"]["afsun"]["contest"]
    check("jadval: tez va xatosiz birinchi; xato +3 soniya", [x["name"] for x in C["top"]] == ["Germiona", "Ron", "Garri"]
          and 4000 <= C["top"][0]["ms"] < 4500 and 9000 <= C["top"][1]["ms"] < 9500 and C["place"] == 1 and C["n"] == 3
          and C["tries"] == 1 and C["max"] == 3 and C["item"] == hpdars.kun_mavzusi("afsun", kun) and C["top"][0]["me"])
    st, d = await ask(1, start="afsun"); boshladi(1, 2); st, d = await ask(1, finish="afsun")
    check("yaxshiroq urinish natijani yangilaydi", d["best"] == d["ms"] and 2000 <= d["ms"] < 2500
          and d["lessons"]["afsun"]["contest"]["place"] == 1)
    st, d = await ask(1, start="afsun"); boshladi(1, 30); st, d = await ask(1, finish="afsun")
    check("yomonroq urinish eng yaxshisini buzmaydi", d["ms"] > d["best"] and 2000 <= d["best"] < 2500)
    st, d = await ask(1, start="afsun")
    check("urinishlar tugadi", d["ok"] is False and d["error"] == "no_tries")
    st, d = await ask(4, start="afsun"); st, d = await ask(4, finish="afsun")
    check("juda tez natija - eng kam vaqt", d["ms"] == hpdars.ENG_KAM_MS)

    # Kun tugadi: sovrinlar
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute("UPDATE dars_bellashuv SET kun='2026-01-02'")
    c.commit(); c.close()
    def ball(uid):
        c = sqlite3.connect(os.environ["HP_DB_PATH"])
        r = c.execute("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_ref LIKE 'm:%'", (uid,)).fetchone()[0]
        c.close()
        return r
    check("yakun: 4 kishiga sovrin", hpdars.yakunla(kun) == 4
          and [ball(u) for u in (4, 1, 3, 2)] == [15, 10, 7, 3])
    check("ikkinchi marta yakunlanmaydi", hpdars.yakunla(kun) == 0 and ball(4) == 15)
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute("UPDATE dars_bellashuv SET kun=?", (hpdars._kecha(kun),))
    c.commit(); c.close()
    st, d = await ask(1)
    Y = d["lessons"]["afsun"]["contest"]["yesterday"]
    check("kechagi g'oliblar va o'z o'rni", [x["name"] for x in Y["top"]] == ["Nevill", "Garri", "Germiona"]
          and Y["place"] == 2 and Y["pts"] == 10 and Y["n"] == 4 and d["lessons"]["afsun"]["contest"]["tries"] == 0)
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    ddl = c.execute("SELECT sql FROM sqlite_master WHERE name='points'").fetchone()[0]
    c.close()
    check("jadval cheklovida 'dars' bor", "'dars'" in ddl)

    print("Darslar: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(amain())
