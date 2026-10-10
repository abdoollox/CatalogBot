# -*- coding: utf-8 -*-
"""Shaxmat turniri: yozilish, reyting bo'yicha to'r, o'yinlarni server ochishi, natija va ballar.

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
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-shturnir-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars, hpchess, hpshturnir as T   # noqa: E402

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
    r = await T.api_turnir(Req(body, init=str(kim)))
    return r.status, json.loads(r.body)


def db(sql, args=()):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


OQ_YUTADI = "e2e4 e7e5 d1h5 b8c6 f1c4 g8f6 h5f7".split()
QORA_YUTADI = "f2f3 e7e5 g2g4 d8h4".split()


def oyna(gid, yurishlar):
    """O'yinni berilgan yurishlar bilan o'ynaydi (oxirgisi - mot)."""
    g = db("SELECT white_uid, black_uid FROM chess_games WHERE id=?", (gid,))[0]
    for i, u in enumerate(yurishlar):
        res, _ = hpchess._move(gid, g[i % 2], u, i)
        assert res.get("ok"), res


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    hpchess.migrate()
    app = types.SimpleNamespace(router=types.SimpleNamespace(add_route=lambda *a, **k: None))
    cfg = {"cors": lambda r: r, "verify_init_data": lambda s: {"id": int(s)} if s.lstrip("-").isdigit() else None}
    hpdars.register(app, cfg)
    xatlar = []
    async def xat(uid, matnlar):
        xatlar.append((uid, matnlar["uz"][0]))
    elonlar = []
    async def elon(matnlar):
        elonlar.append(matnlar["uz"][0])
        return 0
    T.register(app, dict(cfg, xat=xat, elon=elon))
    soat = [datetime(2026, 10, 12, 12, 0, tzinfo=TZ)]          # dushanba; turnir - chorshanba 14-oktabr 21:00
    T._now = lambda: soat[0]
    hpdars._hafta = lambda: (soat[0].date() - timedelta(days=soat[0].weekday())).strftime("%Y-%m-%d")
    def vaqt(kun, s, d=0, sek=0):
        soat[0] = datetime(2026, 10, kun, s, d, sek, tzinfo=TZ)
    def ilgari(sek):
        soat[0] = soat[0] + timedelta(seconds=sek)
    def ball(u):
        return db("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_ref LIKE 'shaxmat:%'", (u,))[0][0]
    for u in range(11, 21):                                     # 11 eng kuchli ... 19 eng kuchsiz; 20 yozilmaydi
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (u, "S%d" % u, "ravenclaw", "2026-10-01T00:00:00Z"))
        db("INSERT INTO chess_ratings (user_id, rating, games) VALUES (?,?,5)", (u, 1600 - u * 10))
    db("INSERT OR IGNORE INTO users (user_id, first_name, created_at) VALUES (30,'Uysiz','2026-10-01T00:00:00Z')")

    st, d = await ask(30)
    check("saralanmagan odam qatnasha olmaydi", d.get("error") == "no_house")
    check("hafta: birinchi turnir 12-oktabr haftasida", T._hafta() == "2026-10-12")
    for u in range(11, 20):
        st, d = await ask(u, join=1)
    check("yozilish: 9 kishi, ro'yxat reyting bo'yicha, reyting ko'rsatilmaydi", d["join_ok"] and d["tour"]["n"] == 9 and d["tour"]["joined"] and d["tour"]["open"]
          and d["tour"]["players"][0]["uid"] == 11 and "r" not in d["tour"]["players"][0] and d["cup"]["size"] is None)
    st, d = await ask(19, join=0)
    st, d = await ask(19, join=1)
    check("chiqish va qayta yozilish", d["tour"]["n"] == 9)

    vaqt(14, 10, 5)
    await T.tick()
    vaqt(14, 20, 52)
    await T.tick()
    await asyncio.sleep(0.05)
    check("birinchi turnir: ertalab hammaga BITTA e'lon, 20:50 da faqat yozilganlarga eslatma", len(elonlar) == 1 and len(xatlar) == 9 and not any(u == 20 for u, _ in xatlar))
    vaqt(14, 20, 56)
    st, d = await ask(20, join=1)
    check("yozilish 5 daqiqa oldin yopiladi", not d["join_ok"] and not d["tour"]["open"])
    c = d["cup"]
    s16 = c["stages"][0]["matches"]
    check("to'r: 9 kishi -> 16 talik, 7 ta kuchli kutadi, 8- va 9-o'rin o'ynaydi", c["size"] == 16 and len(c["stages"]) == 4
          and sum(1 for m in s16 if m["why"] == "bye") == 7 and [m for m in s16 if m["why"] != "bye"][0]["a"]["uid"] == 18)
    check("o'yin turnir boshlanguncha ochilmaydi", all(m["game"] is None for st_ in c["stages"] for m in st_["matches"]))

    vaqt(14, 21, 0, 1)
    await T.tick()
    st, d = await ask(18)
    my = d["cup"]["my"]
    g1 = db("SELECT white_uid, black_uid, base, status FROM chess_games WHERE id=?", (my["game"],))[0]
    check("21:00 da o'yin o'zi ochildi: yuqori turgan oq bilan, 5 daqiqa", my["state"] == "ketmoqda" and my["white"] and g1 == (18, 19, 300, "active"))
    oyna(my["game"], QORA_YUTADI)
    await T.tick()
    st, d = await ask(19)
    check("qora yutdi: 1/8 uchun +5 ball, keyingi bosqichga o'tdi", ball(19) == 5 and ball(18) == 0 and d["cup"]["my"]["stage"] == 8 and d["cup"]["my"]["ready"])
    # chorak final: 11-19, 14-15, 12-17, 13-16 (ikkita kutganlar juftligi 21:00 da, 11-19 esa bir daqiqadan keyin)
    await T.tick()
    s8 = (await ask(11))[1]["cup"]["stages"][1]["matches"]
    check("chorak final: kutganlar juftliklari darhol boshlandi, 11-19 hali yo'q", sum(1 for m in s8 if m["game"]) == 3 and s8[0]["game"] is None and s8[0]["b"]["uid"] == 19)
    ilgari(T.ORALIQ + 1)
    await T.tick()
    s8 = (await ask(11))[1]["cup"]["stages"][1]["matches"]
    check("11-19: bir daqiqadan keyin boshlandi", all(m["game"] for m in s8))
    juft = {(m["a"]["uid"], m["b"]["uid"]): m["game"] for m in s8}
    oyna(juft[(11, 19)], OQ_YUTADI)                              # 11 yutdi
    res, _ = hpchess._action(juft[(14, 15)], 15, "abort")        # turnir o'yinini bekor qilib bo'lmaydi: chiqib ketgan (15) yutqazadi
    oyna(juft[(12, 17)], ["e2e4", "e7e5"])
    res, ch = hpchess._action(juft[(12, 17)], 12, "offer_draw")
    res, ch = hpchess._action(juft[(12, 17)], 17, "accept_draw")
    g = db("SELECT status, result FROM chess_games WHERE id=?", (juft[(12, 17)],))[0]
    if g != ("finished", "1/2-1/2"):                            # durang amali boshqacha nomlangan bo'lsa - to'g'ridan-to'g'ri yopamiz
        conn = hpcup._connect(); hpchess._finish(conn, hpchess._row(conn, juft[(12, 17)]), None, "agreed", time.time()); conn.commit(); conn.close()
    conn = hpcup._connect()                                      # 13-16: qora (16) birinchi yurishini qilmadi
    hpchess._move(juft[(13, 16)], 13, "e2e4", 0)
    hpchess._finish(conn, hpchess._row(conn, juft[(13, 16)]), None, "aborted", time.time(), aborted=True); conn.commit(); conn.close()
    await T.tick()
    st, d = await ask(11)
    s8 = d["cup"]["stages"][1]["matches"]
    w = {(m["a"]["uid"], m["b"]["uid"]): (m["winner"], m["why"]) for m in s8}
    check("chorak: mot bilan g'alaba +10", w[(11, 19)] == (11, "oyin") and ball(11) == 10)
    check("chorak: durang -> qora (17) o'tadi", w[(12, 17)] == (17, "durang") and ball(17) == 10)
    check("chorak: qora kelmadi -> oq (13) o'tadi", w[(13, 16)] == (13, "kelmadi") and ball(13) == 10)
    check("chorak: boshida «bekor qilish»ni bosgan (15) yutqazadi", w[(14, 15)] == (14, "oyin") and ball(14) == 10)
    ilgari(T.ORALIQ + 1)
    await T.tick()
    s4 = (await ask(11))[1]["cup"]["stages"][2]["matches"]
    j4 = {(m["a"]["uid"], m["b"]["uid"]): m["game"] for m in s4}
    check("yarim final juftliklari: 11-14 va 17-13", set(j4) == {(11, 14), (17, 13)} and all(j4.values()))
    # oddiy o'yinda band bo'lgan odam: turnir o'yini ochilganda oddiy o'yini bekor qilinadi
    oyna(j4[(11, 14)], OQ_YUTADI)
    oyna(j4[(17, 13)], QORA_YUTADI)
    res, ch = hpchess._match(11, 20, {}, 600, 0)                 # 11 final oldidan boshqa odam bilan o'ynab o'tiribdi
    await T.tick()
    ilgari(T.ORALIQ + 1)
    await T.tick()
    st, d = await ask(11)
    fin = d["cup"]["stages"][3]["matches"][0]
    eski = db("SELECT status FROM chess_games WHERE id=?", (res["game_id"],))[0][0]
    check("final ochildi; 11 ning oddiy o'yini bekor qilindi", fin["game"] and fin["a"]["uid"] == 11 and fin["b"]["uid"] == 13 and eski == "aborted" and ball(11) == 30 and ball(13) == 30)
    oyna(fin["game"], OQ_YUTADI)
    await T.tick()
    st, d = await ask(11)
    fin = d["cup"]["stages"][3]["matches"][0]
    check("turnir tugadi: chempion 11, ballar 10+20+30", fin["winner"] == 11 and d["cup"]["my"] is None and ball(11) == 60 and ball(13) == 30 and ball(19) == 5)
    n_ball = db("SELECT COUNT(*) FROM points WHERE source_ref LIKE 'shaxmat:%'")[0][0]
    await T.tick(); await T.tick()
    check("ball takror berilmaydi", db("SELECT COUNT(*) FROM points WHERE source_ref LIKE 'shaxmat:%'")[0][0] == n_ball)

    vaqt(15, 0, 30)
    st, d = await ask(12, join=1)
    check("turnirdan keyin keyingi haftaga yozilish ochiladi", T._hafta() == "2026-10-19" and d["join_ok"] and d["tour"]["n"] == 1 and d["cup"]["size"] is None)
    # bitta odam bilan turnir bo'lmaydi
    vaqt(21, 20, 57)
    st, d = await ask(12)
    check("ishtirokchi yetmasa turnir o'tmaydi", d["cup"]["size"] == 0)

    print("Shaxmat turniri: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
