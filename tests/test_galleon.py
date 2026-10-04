"""Hafta yakunidagi galleon mukofoti va imtihonning kubokdan olib tashlanishi.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-galleon-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hppochta   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


def gal(uid):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        return c.execute("SELECT galleons FROM users WHERE user_id=?", (uid,)).fetchone()[0]
    finally:
        c.close()


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))

    h = hpcup._galleon_hisob
    check("10 ballga 1 galleon, g'olibga ikki baravar, top uchlik",
          h([(1, "gryffindor", 120), (2, "slytherin", 95), (3, "gryffindor", 40), (4, "slytherin", 9)], "gryffindor")
          == [(1, 120, 12, 1, 15, 39), (2, 95, 9, 0, 10, 19), (3, 40, 4, 1, 5, 13)])
    check("g'olib yo'q - hech kimga ikki baravar emas", h([(1, "gryffindor", 50)], None) == [(1, 50, 5, 0, 15, 20)])
    check("imtihon o'chirilgan, eng ko'p ball 160", hpcup.EXAM_ON is False and hpcup.MAX_POINTS == 160
          and "exam" not in hpcup.SOURCE_KEYS)

    # Odamlar: 1,3 - Grifindor; 2 - Sliterin; 5 - saralanmagan; -9 - sinov o'quvchisi
    for uid, uy in ((1, "gryffindor"), (2, "slytherin"), (3, "gryffindor"), (5, None), (-9, "gryffindor")):
        await hpcup.touch_user(uid, "Sehrgar %d" % uid)
        if uy:
            await hpcup.set_house(uid, uy)
    season = await hpcup.current_season()
    for uid, n in ((1, 12), (2, 9), (3, 4), (5, 20), (-9, 30)):
        for i in range(n):
            await hpcup.award(uid, "daily", "k%d" % i, 10)
    await hpcup.award(2, "film_open", "1", 5)

    tasma = await hpcup.feed(limit=3000)
    check("to'liq tasma: saralanganlarning hammasi, sinov o'quvchisisiz",
          sorted(x["house"] for x in tasma) == ["gryffindor", "gryffindor", "slytherin"])
    check("imtihon savoli berilmaydi", await hpcup.film_questions(1, season["id"], 1) == [])
    check("imtihon kutilmaydi", await hpcup.exam_pending(1, season["id"]) == [])

    res = await hpcup.close_season(season["id"])
    check("g'olib - Grifindor", res["winner_house"] == "gryffindor")
    check("1: 12*2 + 15 = 39", gal(1) == 39)
    check("2: 9 + 10 = 19 (95 ball, g'olib emas)", gal(2) == 19)
    check("3: 4*2 + 5 = 13", gal(3) == 13)
    check("saralanmagan va sinov o'quvchisi olmaydi", gal(5) == 0 and gal(-9) == 0)
    check("natijada galleonlar bor", res["galleons"] == {1: 39, 2: 19, 3: 13})

    again = await hpcup.recount_season(season["id"])
    check("qayta hisoblansa ikki marta berilmaydi", gal(1) == 39 and again["galleons"] == {})

    # Kubok xatida galleon qatori
    hppochta._cfg.update({"admin_ids": {42}})
    n = hppochta._kubok_yoz(season["id"])
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    import json
    d1 = json.loads(c.execute("SELECT matn FROM pochta WHERE user_id=1 AND tur='kubok'").fetchone()[0])
    c.close()
    sar, m = hppochta.kubok_matni("uz", d1)
    check("kubok xatida +39 galleon", n == 3 and d1["gal"] == 39 and "+39 galleon" in m)

    # Migratsiya: faol mavsumdagi imtihon ballari arxivga ko'chadi (bir marta)
    yangi = await hpcup.current_season()
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        c.execute("INSERT INTO points (user_id, season_id, source_type, source_ref, points, created_at) "
                  "VALUES (1, ?, 'film_quiz', 'q1', 10, '2026-10-04T00:00:00Z')", (yangi["id"],))
        c.execute("INSERT INTO points (user_id, season_id, source_type, source_ref, points, created_at) "
                  "VALUES (1, ?, 'daily', 'd1', 10, '2026-10-04T00:00:00Z')", (yangi["id"],))
        c.execute("DELETE FROM settings WHERE key='exam_olib_tashlandi'")
        c.commit()
    finally:
        c.close()
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    qoldi = [r[0] for r in c.execute("SELECT source_type FROM points WHERE season_id=? AND user_id=1", (yangi["id"],))]
    arxiv = c.execute("SELECT COUNT(*) FROM points_arxiv WHERE source_type='film_quiz'").fetchone()[0]
    c.close()
    check("imtihon bali o'chdi, kunlik qoldi, arxivda nusxa bor", qoldi == ["daily"] and arxiv == 1)

    # ---- Albomni galleonga ochish
    import hpmusic
    hpmusic.DB_PATH = os.environ["HP_DB_PATH"]
    hpmusic._init_likes()
    hpmusic._data["albums"] = {"hp1": [{"t": "a", "d": 1, "s": 1, "fuid": "f1"}],
                               "hp2": [{"t": "b", "d": 1, "s": 1, "fuid": "f2"}]}
    hpmusic._cfg.update({"cors": lambda r: r, "log": None,
                         "verify_init_data": lambda d: {"id": int(d)} if d.lstrip("-").isdigit() else None})

    class Req:
        def __init__(self, body, init):
            self._b, self.method, self.headers = body, "POST", {"X-Telegram-Init-Data": init}
        async def json(self):
            return self._b

    check("birinchi albom hammaga ochiq, ikkinchisi yopiq", hpmusic.album_open(1, "hp1") and not hpmusic.album_open(1, "hp2"))
    check("sinov o'quvchisiga ham qulf, bepul albom ochiq", not hpmusic.album_open(-9, "hp2") and hpmusic.album_open(-9, "hp1"))
    check("ro'yxatda open belgisi", hpmusic._public_list(1)["hp2"]["open"] is False
          and hpmusic._public_list(1)["hp1"]["open"] is True)
    r = json.loads((await hpmusic.api_buy(Req({"album": "hp2"}, "3"))).body)          # 3 da 13 galleon
    check("galleon yetmasa - pul xatosi, qoldiq o'zgarmaydi", r == {"ok": False, "error": "pul", "gal": 13, "price": 30}
          and gal(3) == 13)
    r = json.loads((await hpmusic.api_buy(Req({"album": "hp2"}, "1"))).body)          # 1 da 39
    check("sotib olindi: 39 - 30 = 9", r == {"ok": True, "gal": 9} and gal(1) == 9 and hpmusic.album_open(1, "hp2"))
    r = json.loads((await hpmusic.api_buy(Req({"album": "hp2"}, "1"))).body)
    check("qayta bosilsa pul ikki marta yechilmaydi", r == {"ok": True, "gal": 9} and gal(1) == 9)
    hpmusic._owned.clear()
    check("qayta ishga tushgandan keyin ham ochiq (bazadan)", hpmusic.album_open(1, "hp2"))
    r = await hpmusic.api_buy(Req({"album": "yoq"}, "1"))
    check("noma'lum albom - 404", r.status == 404)
    r = await hpmusic.api_buy(Req({"album": "hp2"}, "yolgon"))
    check("imzosiz - 403", r.status == 403)

    print("O'tdi: %d, xato: %d" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
