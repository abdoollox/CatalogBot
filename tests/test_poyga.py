# -*- coding: utf-8 -*-
"""Supurgi poygasi (dushanba 21:00): zal, bosqichlar, saralab qolish, vaqtni tekshirish, o'rinlar va ballar.

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
TMP = tempfile.mkdtemp(prefix="hp-poyga-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars, hppoyga as P   # noqa: E402

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
    r = await P.api_poyga(Req(body, init=str(kim)))
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
    hpdars.register(app, cfg)
    xatlar, elonlar = [], []
    async def xat(uid, matnlar):
        xatlar.append((uid, matnlar["uz"][0]))
    async def elon(matnlar):
        elonlar.append(matnlar["uz"][0])
        return 0
    P.register(app, dict(cfg, xat=xat, elon=elon, admin_ids={42}))
    soat = [datetime(2026, 10, 14, 12, 0, tzinfo=TZ)]          # chorshanba; birinchi poyga - dushanba 19-oktabr 21:00
    P._now = lambda: soat[0]
    hpdars._hafta = lambda: (soat[0].date() - timedelta(days=soat[0].weekday())).strftime("%Y-%m-%d")
    hpcup.now_tk = lambda: soat[0]
    def vaqt(kun, s, d=0, sek=0):
        soat[0] = datetime(2026, 10, kun, s, d, sek, tzinfo=TZ)
    def ilgari(sek):
        soat[0] = soat[0] + timedelta(seconds=sek)
    def ball(u):
        return db("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_ref LIKE 'poyga:%'", (u,))[0][0]
    for u in range(1, 13):
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (u, "U%d" % u, "gryffindor", "2026-10-01T00:00:00Z"))
    db("INSERT OR IGNORE INTO users (user_id, first_name, created_at) VALUES (30,'Uysiz','2026-10-01T00:00:00Z')")

    check("bosqichlar soni: 4 gacha bitta, 8 gacha ikkita, ko'pi uchta", [P.bosqichlar_soni(n) for n in (2, 4, 5, 8, 9, 30)] == [1, 1, 2, 2, 3, 3])
    check("saralab qolish: yarmi, lekin kamida uch kishi", [P.otadiganlar(n) for n in (2, 3, 5, 9, 10, 21)] == [2, 3, 3, 5, 5, 11])
    check("yo'l urug'i: bosqich va hafta sayin boshqa, takror so'ralsa o'sha", P._urug("2026-10-19", 0) == P._urug("2026-10-19", 0)
          and len({P._urug("2026-10-19", 0), P._urug("2026-10-19", 1), P._urug("2026-10-26", 0)}) == 3)
    check("saralanmagan qatnasha olmaydi", (await ask(30)).get("error") == "no_house")
    d = await ask(1, join=1)
    check("chorshanbada: navbatdagi poyga - dushanba 19-oktabr, yozilish ochiq", d["join_ok"] and d["tour"]["joined"] and d["phase"] == "kutish"
          and datetime.fromtimestamp(d["tour"]["ts"], TZ).strftime("%Y-%m-%d %H:%M") == "2026-10-19 21:00")
    vaqt(19, 10, 1)
    await P.tick(); await asyncio.sleep(0.05)
    vaqt(19, 20, 51)
    await P.tick()
    check("birinchi poyga: ertalab hammaga e'lon, 20:50 da yozilganlarga eslatma", len(elonlar) == 1 and xatlar == [(1, "Poygaga 10 daqiqa qoldi!")])

    # ---------- 9 kishi: uch bosqich (9 -> 5 -> 3) ----------
    vaqt(19, 20, 58, 30)
    for u in range(1, 10):
        d = await ask(u)
    check("zal: 2 daqiqa oldin ochiladi, kelganlar sanaladi", d["phase"] == "zal" and d["total"] == 9 and d["me"]["in"] and d["starts_in"] == 90)
    vaqt(19, 21, 0, 1)
    d = await ask(1)
    check("21:00 - birinchi bosqich: sanoq, urug' keladi, uch bosqich", d["phase"] == "poyga" and d["heats"] == 3 and d["heat"]["n"] == 0
          and d["heat"]["seed"] == P._urug("2026-10-19", 0) and 4.5 < d["heat"]["start_in"] <= 5 and d["heat"]["keep"] == 5 and not d["heat"]["final"])
    d = await ask(10)
    check("kechikkan - tomoshabin", d["phase"] == "poyga" and not d["me"]["in"] and d["total"] == 9)
    check("sanoq paytida natija qabul qilinmaydi", (await ask(1, heat=0, ms=20000, xato=0))["heat_ok"] is False)

    vaqt(19, 21, 0, 6)                                         # uchish boshlandi (bosh + SANOQ)
    ilgari(20)
    d = await ask(1, heat=0, ms=5000, xato=0)
    check("ilova juda kam vaqt aytsa - server o'lchaganidan ko'pi bilan 2,5 s kam olinadi", d["heat_ok"] and d["heat"]["mine"]["ms"] == 17500)
    check("ikkinchi marta yuborib bo'lmaydi", (await ask(1, heat=0, ms=12000, xato=0))["heat_ok"] is False)
    ilgari(2)                                                  # 22 s
    d = await ask(2, heat=0, ms=21800, xato=1)
    check("jarima: har xato +3 s", d["heat_ok"] and d["heat"]["mine"] == {"ms": 24800, "xato": 1})
    check("uchib bo'lganga jadval ko'rinadi", [r["uid"] for r in d["results"]] == [1, 2] and d["results"][1]["me"])
    for i, u in enumerate((3, 4, 5, 6, 7)):                    # 23..27 s
        ilgari(1)
        await ask(u, heat=0, ms=(23 + i) * 1000, xato=0)
    check("boshqa bosqich raqami bilan yuborilgan natija rad etiladi", (await ask(8, heat=1, ms=25000, xato=0))["heat_ok"] is False)
    ilgari(1)                                                  # 28 s
    d = await ask(8, heat=0, ms=27900, xato=4)                 # 27,9 + 12 = 39,9 s
    check("hali bitta uchuvchi qolgan - bosqich yopilmaydi", d["phase"] == "poyga" and d["heat"]["done"] == 8)
    # 9-o'quvchi ulgurmaydi: bosqich 100 soniyada o'zi yopiladi
    vaqt(19, 21, 1, 41)
    d = await ask(1)
    check("vaqt tugadi - bosqich yopildi: natija, tezroq beshtasi o'tdi", d["phase"] == "natija" and d["alive"] == 5 and d["me"]["alive"]
          and [r["uid"] for r in d["results"]] == [1, 3, 4, 2, 5, 6, 7, 8, 9] and [r["through"] for r in d["results"]] == [True] * 5 + [False] * 4
          and d["results"][8]["ms"] is None and d["next_in"] >= 13 and not d["next_final"])
    d = await ask(6)
    check("chiqqan o'quvchi: tirik emas, qaysi bosqichda chiqqani ma'lum", not d["me"]["alive"] and d["me"]["out"] == 0)

    ilgari(15)                                                 # ikkinchi bosqich sanog'i
    d = await ask(1)
    check("ikkinchi bosqich: boshqa urug', besh kishidan uchtasi qoladi", d["phase"] == "poyga" and d["heat"]["n"] == 1 and d["heat"]["keep"] == 3
          and d["heat"]["seed"] == P._urug("2026-10-19", 1) and d["heat"]["seed"] != P._urug("2026-10-19", 0))
    check("chiqqan o'quvchi natija yubora olmaydi", (await ask(6, heat=1, ms=20000, xato=0))["heat_ok"] is False)
    ilgari(P.SANOQ + 19)
    for i, u in enumerate((5, 4, 3, 2, 1)):                    # endi teskari tartib: 5 eng tez
        ilgari(1)
        d = await ask(u, heat=1, ms=(20 + i) * 1000, xato=0)
    check("hamma uchib bo'ldi - bosqich darhol yopilmaydi (2 s kutadi)", d["phase"] == "poyga")
    ilgari(3)
    d = await ask(1)
    check("hamma uchib bo'lgach bosqich vaqtidan oldin yopiladi", d["phase"] == "natija" and d["alive"] == 3 and not d["me"]["alive"]
          and [r["uid"] for r in d["results"]] == [5, 4, 3, 2, 1] and d["next_final"])

    ilgari(P.NATIJA_T + P.SANOQ + 25)
    d = await ask(5)
    check("final: uch kishi", d["phase"] == "poyga" and d["heat"]["final"] and d["heat"]["n"] == 2 and d["alive"] == 3 and d["heat"]["keep"] is None)
    await ask(4, heat=2, ms=24000, xato=0)
    ilgari(1)
    await ask(3, heat=2, ms=25000, xato=0)
    ilgari(1)
    await ask(5, heat=2, ms=26000, xato=2)                     # 26 + 6 = 32 s - uchinchi
    ilgari(3)
    d = await ask(4, log_end=1)
    await asyncio.sleep(0.05)
    check("poyga tugadi: o'rinlar - finalchilar, keyin kechroq chiqqanlar", d["phase"] == "tugadi" and d["played"]
          and [r["uid"] for r in d["top"]] == [4, 3, 5, 2, 1, 6, 7, 8, 9] and d["me"]["place"] == 1 and d["me"]["points"] == 30 and d["top"][0]["ms"])
    check("ballar: 30 / 20 / 10, finalga chiqmaganlarga yo'q", [ball(u) for u in (4, 3, 5, 2, 1, 9, 10)] == [30, 20, 10, 0, 0, 0, 0])
    await P.tick(); await P.tick()
    check("ball ikki marta berilmaydi", ball(4) == 30)
    d = await ask(2)
    check("chiqqan o'quvchi yakunda o'z o'rnini ko'radi", d["me"]["place"] == 4 and d["me"]["points"] == 0)

    # ---------- keyingi hafta: 6 kishi - ikki bosqich; final 3 kishi, to'rtinchi finalchi yo'q ----------
    vaqt(20, 0, 30)
    d = await ask(1)
    check("poygadan 3 soat o'tgach keyingi dushanbaga yozilish ochiladi, o'tgan g'olib ko'rinadi", d["phase"] == "kutish" and d["last"]["uid"] == 4 and d["last"]["n"] == 9
          and datetime.fromtimestamp(d["tour"]["ts"], TZ).strftime("%Y-%m-%d") == "2026-10-26")
    await ask(2, join=1)
    vaqt(26, 10, 1)
    await P.tick()
    check("keyingi haftalarda e'lon yo'q - faqat yozilganlarga eslatma", len(elonlar) == 1 and xatlar[-1] == (2, "Bugun 21:00 da supurgi poygasi"))
    vaqt(26, 20, 59)
    for u in range(1, 7):
        await ask(u)
    vaqt(26, 21, 0, P.SANOQ + 30)
    d = await ask(1)
    check("6 kishi - ikki bosqich", d["heats"] == 2 and d["heat"]["keep"] == 3)
    for u in (1, 2, 3, 4):
        await ask(u, heat=0, ms=28000 + u * 100, xato=0)
        ilgari(0.2)
    vaqt(26, 21, 1, 41)                                        # 5 va 6 ulgurmadi
    d = await ask(5)
    check("ulgurmagan o'tmaydi", d["phase"] == "natija" and not d["me"]["alive"] and d["alive"] == 3)
    ilgari(P.NATIJA_T + P.SANOQ + 20)
    await ask(1, heat=1, ms=19000, xato=0)
    vaqt(26, 21, 4, 0)                                         # 2 va 3 finalda uchmadi
    d = await ask(1)
    check("finalda bitta odam uchib bo'ldi - u g'olib, uchmaganlarga ball yo'q", d["phase"] == "tugadi" and d["me"]["place"] == 1 and d["me"]["points"] == 30
          and [ball(u) for u in (1, 2, 3)] == [30, 0, 20])          # 3-o'quvchining 20 bali - birinchi poygadan

    # ---------- bir kishi bilan poyga bo'lmaydi ----------
    vaqt(27, 3, 0)
    vaqt(11, 0, 0)
    soat[0] = datetime(2026, 11, 2, 20, 59, tzinfo=TZ)
    await ask(7)
    soat[0] = datetime(2026, 11, 2, 21, 0, 10, tzinfo=TZ)
    d = await ask(7)
    check("bir kishi kelsa poyga o'tmaydi", d["phase"] == "tugadi" and d["played"] is False and ball(7) == 0)

    # ---------- sinov poygasi (faqat admin): kompyuter uchuvchilar bilan, ballsiz ----------
    db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (42,'Admin','ravenclaw','2026-10-01T00:00:00Z')")
    soat[0] = datetime(2026, 11, 4, 12, 0, tzinfo=TZ)
    d = await ask(1, sinov=1)
    check("oddiy o'quvchi sinov poygasini boshlay olmaydi", "sinov_ok" not in d and not d["test"] and not d["can_test"] and d["phase"] == "kutish")
    d = await ask(42)
    check("adminga sinov tugmasi ko'rinadi", d["can_test"] and not d["test"])
    d = await ask(42, sinov=1)
    check("sinov: start chizig'i, 10 uchuvchi", d.get("sinov_ok") and d["test"] and d["phase"] == "zal" and d["total"] == 10 and 0 < d["starts_in"] <= P.SINOV_KUT)
    check("sinov boshqalarga ko'rinmaydi", (await ask(1))["phase"] == "kutish")
    ilgari(P.SINOV_KUT + 1)
    d = await ask(42)
    check("sinov: uch bosqich, birinchisi boshlandi", d["phase"] == "poyga" and d["heats"] == 3 and d["heat"]["n"] == 0 and d["me"]["alive"])
    bosqichlar = 0
    for _ in range(3):
        k = d["heat"]["n"]
        ilgari(P.SANOQ + 25)
        d = await ask(42, heat=k, ms=25000, xato=0)
        check("sinov: %d-bosqich natijasi qabul qilindi" % (k + 1), d.get("heat_ok") and 25000 <= d["heat"]["mine"]["ms"] <= 29000)
        for _q in range(40):                     # qolganlar uchib bo'lguncha
            ilgari(2)
            d = await ask(42)
            if d["phase"] != "poyga":
                break
        bosqichlar += 1
        if d["phase"] == "tugadi":
            break
        men = [r for r in d["results"] if r["me"]][0]
        check("sinov: %d-bosqichdan o'tdi, raqiblar ismli" % (k + 1), d["phase"] == "natija" and men["through"] and any(r["name"] == "Viktor" for r in d["results"]))
        ilgari(d["next_in"])
        d = await ask(42)
    check("sinov: uch bosqichdan keyin tugadi, o'rin bor, ball YO'Q", bosqichlar == 3 and d["phase"] == "tugadi" and d["played"] and d["me"]["place"] in (1, 2, 3)
          and ball(42) == 0 and len(d["top"]) == 10)
    d = await ask(42, sinov=0)
    check("sinov to'xtatildi: yana haqiqiy poyga holati, izlar tozalandi", d.get("sinov_ok") and not d["test"] and d["phase"] == "kutish"
          and db("SELECT COUNT(*) FROM pg_oyinchi WHERE hafta LIKE 'sinov:%'")[0][0] == 0)

    print("Poyga: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(amain())
