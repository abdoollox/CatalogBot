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
    hpdars._kesh.clear()               # sinovda har so'rov yangidan hisoblansin
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
          and k("iksir", "2026-10-07") == "boils" and k("iksir", "2026-10-19") == "boils" and k("tarix", "2026-10-07") == "savol")
    check("kubok: 'dars' manbasi, mashq ballsiz", hpcup.SOURCE_GROUP["dars"] == "lesson" and "lesson" in hpcup.SOURCE_KEYS
          and hpcup.MAX_POINTS == 230)
    check("jadvaldagi ism: belgidan iborat ism o'rniga Sehrgar", hpdars._ism(".") == "Sehrgar" and hpdars._ism("") == "Sehrgar"
          and hpdars._ism("Garri Potter") == "Garri" and hpdars._ism("ز") == "ز")
    check("sovrinlar", [hpdars.sovrin(i) for i in (1, 2, 3, 4, 10, 11)] == [15, 10, 7, 3, 3, 0])
    check("tarix savollari: 96 ta = 24 dars x 4", len(hpdars.savollar()) == 96 and hpdars.DARS_SONI * hpdars.TARIX_DARS == 96
          and len(hpdars.tarix_dars(24, "uz")) == 4 and "c" in hpdars.tarix_dars(1, "ru")[0]
          and hpdars.tarix_bell("2026-10-08") == hpdars.tarix_bell("2026-10-08") and len(set(hpdars.tarix_bell("2026-10-08"))) == 5)

    check("imzosiz - 403", (await ask(""))[0] == 403)
    await hpcup.touch_user(1, "Garri Potter")
    st, d = await ask(1)
    check("saralanmaganga yo'q", d == {"ok": False, "error": "no_house"})
    await hpcup.set_house(1, "gryffindor")
    st, d = await ask(1)
    L = d["lessons"]
    check("holat: uch fan, 24 dars, bosqich 0", d["ok"] and set(L) == {"tarix", "afsun", "iksir"}
          and all(x["level"] == 0 and x["total"] == 24 for x in L.values()) and "daily" not in L["tarix"]
          and "contest" in L["tarix"])
    st, d = await ask(1, done="afsun", level=1)
    check("1-dars o'tildi: bosqich 1, ball yo'q", d["new"] is True and d["pts"] == 0 and d["lessons"]["afsun"]["level"] == 1)
    st, d = await ask(1, done="afsun", level=1)
    check("o'tilgan darsni qayta o'ynash bosqichni oshirmaydi", d["new"] is False and d["lessons"]["afsun"]["level"] == 1)
    st, d = await ask(1, done="afsun", level=5)
    check("darsni sakrab o'tib bo'lmaydi", d["new"] is False and d["lessons"]["afsun"]["level"] == 1)
    for n in (2, 3, 4):
        st, d = await ask(1, done="afsun", level=n)
    check("bir kunda xohlagancha dars", d["new"] is True and d["lessons"]["afsun"]["level"] == 4
          and d["lessons"]["iksir"]["level"] == 0)
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute("UPDATE dars_daraja SET daraja=24 WHERE user_id=1 AND dars='afsun'")
    c.commit(); c.close()
    st, d = await ask(1, done="afsun", level=25)
    check("oxirgi darsdan keyin dars yo'q", d["new"] is False and d["lessons"]["afsun"]["level"] == 24)
    st, d = await ask(1, done="uchish", level=1)
    check("noma'lum fan", d == {"ok": False, "error": "unknown"})

    st, d = await ask(1, quiz=1, lang="en")
    check("tarix 1-dars savollari (inglizcha, javobi bilan)", d["ok"] and d["level"] == 1 and len(d["questions"]) == 4
          and d["need"] == 3 and len(d["questions"][0]["a"]) == 4 and "platform" in d["questions"][0]["q"].lower()
          and d["questions"][0]["c"] == 1)
    st, d = await ask(1, quiz=2)
    check("navbatdagi darsdan keyingisi yopiq", d == {"ok": False, "error": "locked"})
    st, d = await ask(1, done="tarix", level=1)
    st, d = await ask(1, quiz=2)
    check("1-dars o'tilgach 2-dars ochiladi", d["ok"] and d["questions"][0]["q"] != hpdars.tarix_dars(1, "uz")[0]["q"])

    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    ball = c.execute("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=1").fetchone()[0]
    c.close()
    check("mashqlar uchun ball yozilmadi", ball == 0)
    check("log: fan va bosqich", "dars_afsun_1" in loglar and "dars_afsun_4" in loglar and "dars_tarix_1" in loglar)

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

    # Tarix bellashuvi: savollar javobsiz keladi, xatoni server sanaydi
    st, d = await ask(2, start="tarix", lang="ru")
    idx = hpdars.tarix_bell(kun)
    check("tarix: 5 savol, to'g'ri javob yuborilmaydi", d["started"] and len(d["questions"]) == 5
          and all("c" not in q for q in d["questions"]) and d["questions"][0]["q"] == hpdars.savollar()[idx[0]]["ru"]["q"])
    togri = [hpdars.savollar()[i]["correct"] for i in idx]
    xato2 = togri[:3] + [(togri[3] + 1) % 4, (togri[4] + 1) % 4]
    st, d = await ask(2, finish="tarix", answers=xato2)
    check("tarix: 2 xato = +6 soniya", d["ok"] and d["wrong"] == 2 and d["ms"] == hpdars.ENG_KAM_MS + 6000)
    st, d = await ask(2, start="tarix"); st, d = await ask(2, finish="tarix", answers=togri)
    check("tarix: hammasi to'g'ri", d["wrong"] == 0 and d["best"] == hpdars.ENG_KAM_MS
          and d["lessons"]["tarix"]["contest"]["place"] == 1)
    st, d = await ask(2, start="tarix"); st, d = await ask(2, finish="tarix")
    check("tarix: javobsiz - hammasi xato", d["wrong"] == 5)
    import hpsandiq
    c = hpcup._connect()
    check("qurbaqa topshirig'i: tarix bellashuvida qatnashgan - bajarilgan", hpsandiq._daily_bajarildi(c, 2, kun) is True
          and hpsandiq._daily_bajarildi(c, 4, kun) is False)
    c.close()
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute("DELETE FROM dars_bellashuv WHERE dars='tarix'")
    c.commit(); c.close()

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
    season = await hpcup.current_season()
    stats = await hpcup.user_stats(1, season["id"])
    # 2-o'rin uchun +10 ikki marta: sinovda bitta natija ikki xil sanaga ko'chirilgan (ikki kun yakunlandi)
    check("kubokda bellashuv bali 'lesson' manbasida", stats["by"].get("lesson") == 20)
    # Holat keshi: ketma-ket so'rovlar bazani qayta hisoblamaydi
    hpdars._kesh.clear()
    sanoq = {"n": 0}
    asl = hpdars._ish
    def sanab(uid, body):
        sanoq["n"] += 1
        return asl(uid, body)
    hpdars._ish = sanab
    for _ in range(5):
        await hpdars.api_dars(Req({}, init="1"))
    await hpdars.api_dars(Req({"done": "iksir", "level": 1}, init="1"))
    await hpdars.api_dars(Req({}, init="1"))
    hpdars._ish = asl
    check("holat so'rovi keshlanadi, amal - yo'q", sanoq["n"] == 3)

    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    ddl = c.execute("SELECT sql FROM sqlite_master WHERE name='points'").fetchone()[0]
    c.close()
    check("jadval cheklovida 'dars' bor", "'dars'" in ddl)

    print("Darslar: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(amain())
