"""Darslar: kun mavzusi, holat, ball (kuniga bir marta), faqat saralanganlarga.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import time
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
          and k("afsun", "2026-10-08") == "leviosa" and k("afsun", "2026-10-19") == "petrificus" and k("afsun", "2026-10-31") == "lumos"
          and k("iksir", "2026-10-07") == "boils" and k("iksir", "2026-10-19") == "boils"
          and k("tarix", "2026-10-07") == "5" and k("tarix", "2026-10-08") == "10")
    check("kubok: 'dars' manbasi, mashq ballsiz", hpcup.SOURCE_GROUP["dars"] == "lesson" and "lesson" in hpcup.SOURCE_KEYS
          and hpcup.MAX_POINTS == 230)
    check("jadvaldagi ism: belgidan iborat ism o'rniga Sehrgar", hpdars._ism(".") == "Sehrgar" and hpdars._ism("") == "Sehrgar"
          and hpdars._ism("Garri Potter") == "Garri" and hpdars._ism("ز") == "ز")
    B = hpdars.bell_savollar()
    check("bellashuv havzasi: kino + kunlik + yangi savollar, uch tilda", len(B) == 96 + 120 + 61 and len(hpdars.savollar()) == 96
          and all(len(q[l]["a"]) == 4 and q[l]["q"] and 0 <= q["correct"] < 4 for q in B for l in ("uz", "ru", "en"))
          and len({q["key"] for q in B}) == len(B) and max(hpdars.tarix_bell("2026-10-20")) < len(B)
          and max(hpdars.tarix_bell("2026-10-08")) < 96)
    check("sovrinlar", [hpdars.sovrin(i) for i in (1, 2, 3, 4, 10, 11)] == [15, 10, 7, 3, 3, 0])
    d1, d2, d46 = hpdars.tarix_dars(1, "uz"), hpdars.tarix_dars(2, "uz"), hpdars.tarix_dars(46, "uz")
    birinchi6 = {q["uz"]["q"] for q in hpdars.bell_savollar()[:6]}
    check("tarix darslari: 46 ta; 1-darsda 6 savol, keyin 6 yangi + 2 takror", hpdars.dars_soni("tarix") == 46
          and hpdars.dars_soni("afsun") == 48 and hpdars.dars_soni("iksir") == 36 and len(d1) == 6 and len(d2) == 8 and len(d46) == 8
          and {q["q"] for q in d1} == birinchi6 and len({q["q"] for q in d2} & birinchi6) == 2
          and len({q["q"] for q in d2}) == 8 and [q["q"] for q in hpdars.tarix_dars(2, "uz")] == [q["q"] for q in d2] and "c" in hpdars.tarix_dars(1, "ru")[0]
          and hpdars.tarix_bell("2026-10-08") == hpdars.tarix_bell("2026-10-08") and len(set(hpdars.tarix_bell("2026-10-08"))) == 10
          and len(hpdars.tarix_bell("2026-10-07")) == 5)

    check("imzosiz - 403", (await ask(""))[0] == 403)
    await hpcup.touch_user(1, "Garri Potter")
    st, d = await ask(1)
    check("saralanmaganga yo'q", d == {"ok": False, "error": "no_house"})
    await hpcup.set_house(1, "gryffindor")
    st, d = await ask(1)
    L = d["lessons"]
    check("holat: uch fan, 24 dars, bosqich 0", d["ok"] and set(L) == {"tarix", "afsun", "iksir", "himoya", "uchish", "maxluq", "astro", "osimlik", "trans"} and L["trans"]["total"] == 36 and L["astro"]["total"] == 36 and L["osimlik"]["total"] == 36 and L["maxluq"]["total"] == 36 and L["uchish"]["total"] == 36 and L["himoya"]["total"] == 36 and L["himoya"]["contest"]["item"] in hpdars.DARSLAR["himoya"]["items"]
          and all(x["level"] == 0 for x in L.values()) and L["afsun"]["total"] == 48 and L["iksir"]["total"] == 36 and L["tarix"]["total"] == 46
          and "daily" not in L["tarix"]
          and "contest" in L["tarix"])
    st, d = await ask(1, done="afsun", level=1)
    check("1-dars o'tildi: bosqich 1, ball yo'q", d["new"] is True and d["pts"] == 0 and d["lessons"]["afsun"]["level"] == 1)
    st, d = await ask(1, done="afsun", level=1)
    check("o'tilgan darsni qayta o'ynash bosqichni oshirmaydi", d["new"] is False and d["lessons"]["afsun"]["level"] == 1)
    st, d = await ask(1, done="afsun", level=5)
    check("darsni sakrab o'tib bo'lmaydi", d["new"] is False and d["lessons"]["afsun"]["level"] == 1)
    # Baholar (qobiliyatlar uchun): faqat o'tilgan dars, 3-5, eng yaxshisi qoladi
    st, d = await ask(1, done="afsun", level=1, grade=4)
    A = d["lessons"]["afsun"]
    check("baho yozildi", A["gs"] == 4 and A["gn"] == 1)
    st, d = await ask(1, done="afsun", level=1, grade=3)
    check("pastroq baho eng yaxshisini o'zgartirmaydi", d["lessons"]["afsun"]["gs"] == 4)
    st, d = await ask(1, done="afsun", level=1, grade=5)
    st, d = await ask(1, done="afsun", level=9, grade=5)
    st, d = await ask(1, done="afsun", level=1, grade=9)
    check("yuqoriroq baho yangilanadi; o'tilmagan dars va noto'g'ri baho yozilmaydi", d["lessons"]["afsun"]["gs"] == 5 and d["lessons"]["afsun"]["gn"] == 1)
    st, d = await ask(1, grades={"afsun": {"1": 4, "7": 5}, "runlar": {"1": 5}, "iksir": {"1": 5}})
    check("eski baholarni ko'chirish: faqat o'tilganlari", d["synced"] == 1 and d["lessons"]["afsun"]["gs"] == 5 and d["lessons"]["iksir"]["gn"] == 0)
    # Rekord («kim uzoqqa boradi»): haftalik eng yaxshi natija, jadval
    st, d = await ask(1, record="afsun", score=7)
    check("boshlanmagan urinish rekordga yozilmaydi", d["records"]["afsun"]["all"] == 0)
    st, d = await ask(1, rek_start="afsun")
    st, d = await ask(1, record="afsun", score=50)
    check("vaqtga sig'magan natija yozilmaydi", d["ok"] and d["records"]["afsun"]["all"] == 0)
    def bosh(u):
        hpdars._rek_bosh[(u, "afsun")] = time.time() - 100000
    bosh(1)
    st, d = await ask(1, record="afsun", score=7)
    R = d["records"]["afsun"]
    check("rekord yozildi", d["ok"] and R["week"] == 7 and R["all"] == 7 and R["place"] == 1 and R["top"][0]["score"] == 7 and R["top"][0]["me"])
    bosh(1)
    st, d = await ask(1, record="afsun", score=4)
    check("pastroq natija rekordni o'zgartirmaydi", d["records"]["afsun"]["week"] == 7)
    await hpcup.set_house(2, "ravenclaw")
    bosh(2)
    st, d = await ask(2, record="afsun", score=12)
    bosh(1)
    st, d = await ask(1, record="afsun", score=99999)
    check("buzuq son yozilmaydi", d["records"]["afsun"]["all"] == hpdars.REKORD_MAX)
    st, d = await ask(2, records=1)
    check("hamma fan rekordlari: 2-o'rin, boshqa fanlar bo'sh", set(d["records"]) == set(hpdars.DARSLAR) and d["records"]["afsun"]["place"] == 2 and d["records"]["afsun"]["week"] == 12
          and d["records"]["afsun"]["n"] == 2 and d["records"]["trans"]["top"] == [] and d["records"]["trans"]["all"] == 0)
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute("UPDATE dars_rekord SET hafta='2000-01-03' WHERE user_id=1"); c.commit(); c.close()
    st, d = await ask(1, records=1)
    check("jadval doimiy: eski hafta natijasi ham jadvalda", d["records"]["afsun"]["week"] == 0 and d["records"]["afsun"]["all"] == hpdars.REKORD_MAX and d["records"]["afsun"]["n"] == 2 and d["records"]["afsun"]["place"] == 1)
    # Kunlik rekord sovg'asi: jadvaldagi birinchi uchlikka ball, bir kunda bir marta
    def ball(u):
        c = sqlite3.connect(os.environ["HP_DB_PATH"])
        n = c.execute("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_ref LIKE 'r:afsun:%'", (u,)).fetchone()[0]
        c.close(); return n
    c = sqlite3.connect(os.environ["HP_DB_PATH"]); c.execute("DELETE FROM dars_yakun WHERE dars LIKE 'rek:%'"); c.commit(); c.close()
    n1 = hpdars.rekord_yakunla(hpcup.today_tk())
    n2 = hpdars.rekord_yakunla(hpcup.today_tk())
    check("rekord sovg'asi: 1-o'rin +5, 2-o'rin +3, takror berilmaydi", n1 == 2 and n2 == 0 and ball(1) == 5 and ball(2) == 3)
    c = sqlite3.connect(os.environ["HP_DB_PATH"]); c.execute("DELETE FROM points WHERE source_ref LIKE 'r:%'"); c.commit(); c.close()
    st, d = await ask(1, quiz_rek=1, lang="uz")
    check("tarix rekordi: hamma savollar, javobi bilan", len(d["questions"]) == len(hpdars.bell_savollar()) and "c" in d["questions"][0])
    # Natija teng bo'lsa oxirgi yetgan yuqorida (2026-11-01)
    hpdars._rekord_yoz(1, "himoya", 30)
    hpdars._rekord_yoz(2, "himoya", 30)
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute("UPDATE dars_rekord SET vaqt='2000-01-02T00:00:00Z' WHERE dars='himoya' AND user_id=1")
    c.execute("UPDATE dars_rekord SET vaqt='2000-01-03T00:00:00Z' WHERE dars='himoya' AND user_id=2")
    c.commit(); c.close()
    def rek_tartib():
        conn = hpcup._connect()
        try:
            return [r["user_id"] for r in hpdars._rek_top(conn, "himoya")]
        finally:
            conn.close()
    check("teng natijada oxirgi yetgan yuqorida", rek_tartib() == [2, 1])
    hpdars._rekord_yoz(1, "himoya", 30)
    check("o'sha natijani qayta qilgan yana oxirgi yetgan", rek_tartib() == [1, 2])
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute("INSERT INTO dars_rekord (user_id, dars, hafta, ball, vaqt) VALUES (2, 'himoya', '2000-01-03', 10, '2030-01-01T00:00:00Z')")
    c.commit(); c.close()
    check("pastroq yangi natija o'rinni o'zgartirmaydi", rek_tartib() == [1, 2])
    c = sqlite3.connect(os.environ["HP_DB_PATH"]); c.execute("DELETE FROM dars_rekord WHERE dars='himoya'"); c.commit(); c.close()
    st, d = await ask(1, record="runlar", score=5)
    check("noma'lum fanga rekord yo'q", d == {"ok": False, "error": "unknown"})
    q = {x["id"]: x["score"] for x in hpdars.qobiliyat(1)}
    check("qobiliyat: 8 soha, afsun 1/48 a'lo bahoda ~2, qolgani 0", len(q) == 8 and q["aniqlik"] == 2 and q["mantiq"] == 0 and hpdars.qobiliyat(999)[0]["score"] == 0)
    for n in (2, 3, 4):
        st, d = await ask(1, done="afsun", level=n)
    check("bir kunda xohlagancha dars", d["new"] is True and d["lessons"]["afsun"]["level"] == 4
          and d["lessons"]["iksir"]["level"] == 0)
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute("UPDATE dars_daraja SET daraja=48 WHERE user_id=1 AND dars='afsun'")
    c.commit(); c.close()
    st, d = await ask(1, done="afsun", level=49)
    check("oxirgi darsdan keyin dars yo'q", d["new"] is False and d["lessons"]["afsun"]["level"] == 48)
    st, d = await ask(1, done="runlar", level=1)
    check("noma'lum fan", d == {"ok": False, "error": "unknown"})

    st, d = await ask(1, quiz=1, lang="en")
    check("tarix 1-dars savollari (inglizcha, javobi bilan): hammasi to'g'ri bo'lishi shart", d["ok"] and d["level"] == 1
          and len(d["questions"]) == 6 and d["need"] == 6 and all(len(q["a"]) == 4 and 0 <= q["c"] < 4 for q in d["questions"])
          and any("platform" in q["q"].lower() for q in d["questions"]))
    st, d = await ask(1, quiz=2)
    check("navbatdagi darsdan keyingisi yopiq", d == {"ok": False, "error": "locked"})
    st, d = await ask(1, done="tarix", level=1)
    st, d = await ask(1, quiz=2)
    check("1-dars o'tilgach 2-dars ochiladi (8 savol, hammasi shart)", d["ok"] and len(d["questions"]) == 8 and d["need"] == 8)
    # Bir martalik ko'chirish: eski 24-dars (4 savoldan) -> yangi 16-dars
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute("DELETE FROM dars_yakun WHERE kun='migr'")
    c.execute("INSERT OR REPLACE INTO dars_daraja (user_id, dars, daraja, kun) VALUES (77, 'tarix', 24, NULL), (78, 'tarix', 5, NULL), (77, 'afsun', 24, NULL), (78, 'afsun', 7, NULL), (77, 'iksir', 24, NULL)")
    c.commit(); c.close()
    hpdars._init(); hpdars._init()
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    kochdi = dict(((u, f), d) for u, f, d in c.execute("SELECT user_id, dars, daraja FROM dars_daraja WHERE user_id IN (77, 78)"))
    c.close()
    check("ko'chirish: tarix 24 -> 16, 5 -> 3; afsun 24 -> 12, 7 qoladi; bir marta; iksir tegilmaydi",
          kochdi == {(77, "tarix"): 16, (78, "tarix"): 3, (77, "afsun"): 12, (78, "afsun"): 7, (77, "iksir"): 24})

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
    # Ilova o'z vaqtini (cms) yuboradi: internet kechikishi uchun KECHIKISH_MS gacha kamaytiriladi, undan ko'p emas
    for uid in (5, 6, 7):
        await hpcup.touch_user(uid, "Sinov%d" % uid)
        await hpcup.set_house(uid, "ravenclaw")
    def boshladi_h(uid, soniya):
        c = sqlite3.connect(os.environ["HP_DB_PATH"])
        c.execute("UPDATE dars_bellashuv SET boshladi = boshladi - ? WHERE user_id=? AND dars='himoya' AND kun=?", (soniya, uid, kun))
        c.commit(); c.close()
    st, d = await ask(5, start="himoya"); boshladi_h(5, 10); st, d = await ask(5, finish="himoya", cms=9000)
    check("ilova vaqti kechikish chegarasida qabul qilinadi", 9000 <= d["ms"] < 9100)
    st, d = await ask(6, start="himoya"); boshladi_h(6, 10); st, d = await ask(6, finish="himoya", cms=3000)
    check("ilova vaqti juda kam bo'lsa - server vaqti minus chegara", 8000 <= d["ms"] < 8100)
    st, d = await ask(7, start="himoya"); boshladi_h(7, 10); st, d = await ask(7, finish="himoya", cms=60000)
    check("ilova vaqti server vaqtidan ko'p bo'lsa - server vaqti", 10000 <= d["ms"] < 10200)
    st, d = await ask(7, finish="himoya", cms=60000)
    check("ikkinchi marta yuborilgan natija - not_started (qayta yozilmaydi)", d["ok"] is False and d["error"] == "not_started")
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute("DELETE FROM dars_bellashuv WHERE dars='himoya'")
    c.commit(); c.close()

    # Tarix bellashuvi: savollar javobsiz keladi, xatoni server sanaydi
    st, d = await ask(2, start="tarix", lang="ru")
    idx = hpdars.tarix_bell(kun)
    N = hpdars.tarix_soni(kun)
    B_ = hpdars.bell_savollar()
    asl = {B_[i]["ru"]["q"]: B_[i] for i in idx}
    check("tarix: savollar soni, to'g'ri javob yuborilmaydi", d["started"] and len(d["questions"]) == N
          and all("c" not in q for q in d["questions"]) and {q["q"] for q in d["questions"]} == set(asl))
    check("tarix: variantlar aralashgan, lekin o'sha to'rttasi", all(sorted(q["a"]) == sorted(asl[q["q"]]["ru"]["a"]) for q in d["questions"])
          and any(q["a"] != asl[q["q"]]["ru"]["a"] for q in d["questions"]))

    def javoblar(qs, til, xato=0):
        """Ilova ko'rgan tartibda to'g'ri javoblar; oxirgi `xato` tasi ataylab noto'g'ri."""
        m_ = {B_[i][til]["q"]: B_[i] for i in idx}
        out = [q["a"].index(m_[q["q"]][til]["a"][m_[q["q"]]["correct"]]) for q in qs]
        for z in range(xato):
            out[-1 - z] = (out[-1 - z] + 1) % 4
        return out
    birinchi = [q["q"] for q in d["questions"]]
    st, d = await ask(2, finish="tarix", answers=javoblar(d["questions"], "ru", 2))
    jx = hpdars.TARIX_XATO_MS if kun >= hpdars.TARIX_XATO_DAN else 3000      # 2026-10-24 dan tarixda xato 10 s
    check("tarix: 2 xato = 2 x jarima", d["ok"] and d["wrong"] == 2 and d["ms"] == hpdars.ENG_KAM_MS + 2 * jx)
    check("tarix: jarima holatda ko'rinadi", d["lessons"]["tarix"]["contest"]["penalty"] == jx
          and d["lessons"]["afsun"]["contest"]["penalty"] == 3000)
    c_ = hpcup._connect()
    check("tarix: 24-oktabrdan xato 10 s, undan oldin 3 s", hpdars._jarima(c_, 2, "tarix", "2026-10-24") == 10000
          and hpdars._jarima(c_, 2, "tarix", "2026-10-23") == 3000 and hpdars._jarima(c_, 2, "afsun", "2026-10-30") == 3000)
    c_.close()
    st, d = await ask(2, start="tarix")
    ikkinchi = [B_[i]["ru"]["q"] for q in d["questions"] for i in idx if B_[i]["uz"]["q"] == q["q"]]
    check("tarix: qayta urinishda savollar tartibi boshqa", sorted(ikkinchi) == sorted(birinchi) and ikkinchi != birinchi)
    qs2 = d["questions"]
    st, d = await ask(2, finish="tarix", answers=javoblar(qs2, "uz"))
    check("tarix: hammasi to'g'ri", d["wrong"] == 0 and d["best"] == hpdars.ENG_KAM_MS
          and d["lessons"]["tarix"]["contest"]["place"] == 1)
    st, d = await ask(2, start="tarix"); st, d = await ask(2, finish="tarix")
    check("tarix: javobsiz - hammasi xato", d["wrong"] == N)
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

    # ---------- KURSLAR: bo'limlar bosqichma-bosqich ochiladi ----------
    def q(sql_, a_=()):
        c_ = sqlite3.connect(os.environ["HP_DB_PATH"]); r_ = c_.execute(sql_, a_).fetchall(); c_.commit(); c_.close(); return r_
    await hpcup.touch_user(77, "Yangi")
    await hpcup.set_house(77, "hufflepuff")
    q("UPDATE users SET sorted_at='2026-10-12T05:00:00Z' WHERE user_id=77")
    q("DELETE FROM dars_daraja WHERE user_id=77"); q("DELETE FROM dars_bellashuv WHERE user_id=77")
    check("kurs: yangi saralangan - 1-kurs", hpdars.kurs(77)["n"] == 1 and hpdars.kurs(77)["need2"] == 3 and hpdars.kurs(77)["fans"] == 9)
    FANLAR = list(hpdars.DARSLAR)
    def qoy(n, fanlar=None):
        for f in (fanlar or FANLAR):
            q("INSERT OR REPLACE INTO dars_daraja (user_id, dars, daraja, kun) VALUES (77,?,?,'2026-10-12')", (f, n))
    qoy(12, ["afsun"]); qoy(3, FANLAR[1:8] if FANLAR[0] == "afsun" else [f for f in FANLAR if f != "afsun"][:7])
    k_ = hpdars.kurs(77)
    check("kurs: bitta fanda darsi yo'q - hali 1-kurs (8 / 9 fan)", k_["n"] == 1 and k_["fan2"] == 8)
    qoy(3, [f for f in FANLAR if f != "afsun"])
    check("kurs: HAR fandan 3 tadan - 2-kurs", hpdars.kurs(77)["n"] == 2 and hpdars.kurs(77)["fan2"] == 9)
    qoy(9); qoy(8, ["iksir"])
    check("kurs: bitta fanda 9 ga yetmagan - 2-kursda qoladi", hpdars.kurs(77)["n"] == 2 and hpdars.kurs(77)["fan3"] == 8)
    qoy(9)
    check("kurs: har fandan 9 tadan, lekin qurbaqa va bellashuv yo'q - 2-kursda qoladi", hpdars.kurs(77)["n"] == 2 and hpdars.kurs(77)["fan3"] == 9)
    q("CREATE TABLE IF NOT EXISTS qurbaqa (user_id INTEGER NOT NULL, card TEXT NOT NULL, soni INTEGER NOT NULL DEFAULT 1, vaqt TEXT NOT NULL, PRIMARY KEY (user_id, card))")
    q("INSERT OR REPLACE INTO qurbaqa (user_id, card, vaqt) VALUES (77,'merlin','x')")
    for f_ in FANLAR[:8]:
        q("INSERT OR REPLACE INTO dars_bellashuv (kun, dars, user_id, ms, vaqt) VALUES ('2026-10-12',?,77,9000,'x')", (f_,))
    k_ = hpdars.kurs(77)
    check("kurs: qurbaqa bor, 8 / 9 fan bellashuvi - 2-kursda qoladi", k_["n"] == 2 and k_["qurb"] == 1 and k_["bellf"] == 8)
    q("INSERT OR REPLACE INTO dars_bellashuv (kun, dars, user_id, ms, vaqt) VALUES ('2026-10-12',?,77,NULL,'x')", (FANLAR[8],))
    check("kurs: tugatilmagan bellashuv hisobga olinmaydi", hpdars.kurs(77)["bellf"] == 8)
    q("UPDATE dars_bellashuv SET ms=9000 WHERE user_id=77 AND dars=?", (FANLAR[8],))
    q("DELETE FROM qurbaqa WHERE user_id=77")
    check("kurs: hamma bellashuv bor, qurbaqa yo'q - 2-kursda qoladi", hpdars.kurs(77)["n"] == 2 and hpdars.kurs(77)["bellf"] == 9)
    q("INSERT OR REPLACE INTO qurbaqa (user_id, card, vaqt) VALUES (77,'merlin','x')")
    check("kurs: 9 tadan dars + qurbaqa + to'qqiz bellashuv - 3-kurs", hpdars.kurs(77)["n"] == 3 and hpdars.kurs(77)["bell"])
    qoy(15); qoy(14, ["afsun"])
    check("kurs: bitta fanda 15 ga yetmagan - 3-kurs", hpdars.kurs(77)["n"] == 3 and hpdars.kurs(77)["need4"] == 15)
    qoy(15)
    check("kurs: har fandan 15 tadan - 4-kurs", hpdars.kurs(77)["n"] == 4)
    q("DELETE FROM qurbaqa WHERE user_id=77")
    check("kurs: 15 tadan dars, lekin qurbaqa yo'q - 4-kurs emas (2-kurs)", hpdars.kurs(77)["n"] == 2)
    q("INSERT OR REPLACE INTO qurbaqa (user_id, card, vaqt) VALUES (77,'merlin','x')")
    q("INSERT OR REPLACE INTO dars_bellashuv (kun, dars, user_id, ms, vaqt) VALUES ('2026-10-12','afsun',77,9000,'x')")
    q("UPDATE users SET sorted_at='2026-10-01T05:00:00Z' WHERE user_id=77")
    q("DELETE FROM dars_daraja WHERE user_id=77")
    check("kurs: joriy qilinishidan oldin saralangan - darhol 4-kurs", hpdars.kurs(77)["n"] == 4)
    hpdars._kesh.clear() if hasattr(hpdars, "_kesh") and hasattr(hpdars._kesh, "clear") else None
    st, d = await ask(77)
    check("kurs holat javobida keladi", d.get("kurs", {}).get("n") == 4)

    # ---------- Yangi saralanganlarga eslatma ----------
    import datetime as _d
    q("DELETE FROM dars_eslatma")
    T = hpcup._parse_iso("2026-10-14T08:00:00Z")           # Toshkentda 13:00
    def nom(v): return hpdars._eslatma_nomzodlar(v.astimezone(hpcup.now_tk().tzinfo))
    await hpcup.touch_user(81, "Ilk"); await hpcup.set_house(81, "ravenclaw")
    q("DELETE FROM dars_daraja WHERE user_id IN (77,81)"); q("DELETE FROM dars_bellashuv WHERE user_id IN (77,81)")
    q("UPDATE users SET sorted_at='2026-10-14T05:00:00Z' WHERE user_id=81")
    check("eslatma: saralanganiga 3 soat - hali yo'q", (81, "ilk") not in nom(T))
    q("UPDATE users SET sorted_at='2026-10-13T05:00:00Z' WHERE user_id=81")
    check("eslatma: tunda yuborilmaydi", nom(hpcup._parse_iso("2026-10-14T20:00:00Z")) == [])
    check("eslatma: ertasiga darssiz - «Flitvik kutyapti»", (81, "ilk") in nom(T))
    check("eslatma: ikkinchi marta ketmaydi", (81, "ilk") not in nom(T))
    check("eslatma: eski saralangan (77) olmaydi", not q("SELECT 1 FROM dars_eslatma WHERE user_id=77"))
    for f_ in hpdars.DARSLAR:
        q("INSERT INTO dars_daraja (user_id, dars, daraja, kun) VALUES (81,?,3,'2026-10-14')", (f_,))
    check("eslatma: 2-kursga bugun yetgan - hali yo'q", (81, "bell") not in nom(T))
    q("UPDATE dars_daraja SET kun='2026-10-13' WHERE user_id=81")
    check("eslatma: 2-kurs, ertasiga bellashmagan - bellashuvga chaqiradi", (81, "bell") in nom(T))
    q("DELETE FROM dars_eslatma WHERE tur='bell'")
    q("INSERT INTO dars_bellashuv (kun, dars, user_id, ms, vaqt) VALUES ('2026-10-13','afsun',81,9000,'x')")
    check("eslatma: bellashgan odamga ketmaydi", (81, "bell") not in nom(T))
    check("eslatma matnlari uch tilda", all(set(v) == {"uz", "ru", "en"} for v in hpdars.ESL_MATN.values()))

    # ---------- Sinov o'quvchisi: «Noldan» = saralanish boshi ----------
    await hpcup.touch_user(-5, "Sinov"); await hpcup.set_house(-5, "slytherin")
    q("INSERT OR REPLACE INTO dars_daraja (user_id, dars, daraja, kun) VALUES (-5,'afsun',4,'2026-10-13')")
    await hpcup.test_reset(-5)
    w_ = await hpcup.wallet(-5)
    r_ = q("SELECT house FROM users WHERE user_id=-5")
    check("sinov: darslari o'chdi, fakulteti yo'q", not q("SELECT 1 FROM dars_daraja WHERE user_id=-5") and r_ and r_[0][0] is None)
    check("sinov: Gringotts, tayoqcha, bilet tayyor", bool(w_.get("vault")) and bool(w_.get("wand")) and bool(w_.get("ticket")))
    await hpcup.set_house(-5, "ravenclaw")
    q("INSERT OR REPLACE INTO dars_daraja (user_id, dars, daraja, kun) VALUES (-5,'afsun',20,'2026-10-13')")
    uy_ = await hpcup.test_reset(-5, "kurs1")
    k_ = hpdars.kurs(-5)
    check("sinov «1-kurs tugagan»: fakulteti saqlandi, har fandan 3 tadan dars - 2-kurs",
          uy_ == "ravenclaw" and q("SELECT house FROM users WHERE user_id=-5")[0][0] == "ravenclaw" and k_["n"] == 2 and k_["fan2"] == 9 and k_["fan3"] == 0)
    check("sinov «1-kurs tugagan»: qurbaqa va bellashuv yo'q", k_["qurb"] == 0 and k_["bellf"] == 0)
    q("UPDATE users SET house=NULL WHERE user_id=-5")
    uy_ = await hpcup.test_reset(-5, "kurs1")
    check("sinov «1-kurs tugagan»: fakulteti yo'q bo'lsa - tasodifiy", uy_ in hpcup.HOUSES)
    uy_ = await hpcup.test_reset(-5, "nol")
    w_ = await hpcup.wallet(-5)
    check("sinov «0 dan»: fakultet, darslar, Gringotts, tayoqcha, bilet - hech biri yo'q",
          uy_ is None and q("SELECT house FROM users WHERE user_id=-5")[0][0] is None and not q("SELECT 1 FROM dars_daraja WHERE user_id=-5")
          and not w_.get("vault") and not w_.get("wand") and not w_.get("ticket"))

    r1, r2, r3 = hpdars._bell_aralash(5, "2026-10-12", 1, 10), hpdars._bell_aralash(6, "2026-10-12", 1, 10), hpdars._bell_aralash(5, "2026-10-12", 2, 10)
    check("aralashtirish: bir urinishda doim o'sha, boshqa odam va boshqa urinishda boshqa",
          r1 == hpdars._bell_aralash(5, "2026-10-12", 1, 10) and r1 != r2 and r1 != r3 and sorted(r1[0]) == list(range(10)))
    v_ = [hpdars._savol(B_[0], "uz", True) for _ in range(30)]
    check("dars savoli: variantlar aralashadi, to'g'ri javob o'rni mos", len({tuple(q["a"]) for q in v_}) > 1
          and all(q["a"][q["c"]] == B_[0]["uz"]["a"][B_[0]["correct"]] for q in v_))

    print("Darslar: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(amain())
