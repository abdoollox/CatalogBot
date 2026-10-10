# -*- coding: utf-8 -*-
"""Duel: raund qoidasi, kompyuter raqib, saralash bali va jadvali.

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
TMP = tempfile.mkdtemp(prefix="hp-duel-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars, hpduel   # noqa: E402

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
    r = await hpduel.api_duel(Req(body, init=str(kim)))
    return r.status, json.loads(r.body)


def db(sql, args=()):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


class Rnd:
    """Oldindan belgilangan raqib yurishlari."""
    def __init__(self, tur, acc): self.tur, self.acc = tur, acc
    def choice(self, seq): return self.tur
    def random(self): return 1.0
    def gauss(self, a, b): return self.acc


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    loglar = []
    async def log(user, payload):
        loglar.append(payload)
    app = types.SimpleNamespace(router=types.SimpleNamespace(add_route=lambda *a, **k: None))
    cfg = {"cors": lambda r: r, "log": log, "verify_init_data": lambda s: {"id": int(s)} if s.lstrip("-").isdigit() else None}
    hpdars.register(app, cfg)
    hpduel.register(app, cfg)
    for uid, h in ((1, "gryffindor"), (2, "slytherin"), (3, None)):
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (uid, "S%d" % uid, h, "2026-10-01T00:00:00Z"))

    H = hpduel.hal_qil
    check("uchburchak: hujum > hiyla > himoya > hujum", H("hujum", 80, "hiyla", 80) == 1 and H("hiyla", 80, "himoya", 80) == 1
          and H("himoya", 80, "hujum", 80) == 1 and H("hiyla", 80, "hujum", 80) == -1)
    check("aniqlik hal qiladi: a'lo chizilgan afsun noqulay turda ham yutadi; o'rtachasi - yo'q", H("hiyla", 95, "hujum", 60) == 1 and H("hiyla", 80, "hujum", 60) == -1
          and H("hujum", 60, "hiyla", 95) == -1 and H("hujum", 72, "hiyla", 95) == 0 and hpduel.kuch("hujum", 60, "hiyla") == 85 and hpduel.kuch("hujum", 30, "hiyla") == 0)
    check("bir xil tur: aniqrog'i yutadi, farq kichik bo'lsa durang", H("hujum", 80, "hujum", 60) == 1 and H("hujum", 60, "hujum", 80) == -1 and H("hujum", 80, "hujum", 78) == 0)
    check("afsun chiqmasa (aniqlik past) - raqib uradi; ikkalasi chiqmasa durang", H("hujum", 20, "hiyla", 50) == -1 and H("hiyla", 50, "hujum", 20) == 1 and H("hujum", 10, "hiyla", 10) == 0)

    st, d = await ask("x")
    check("imzosiz 403", st == 403)
    st, d = await ask(3)
    check("saralanmagan o'ynay olmaydi", d == {"ok": False, "error": "no_house"})
    st, d = await ask(1)
    check("boshida bo'sh holat", d["ok"] and d["mine"]["total"] == 0 and d["top"] == [] and d["place"] is None and d["rules"]["lives"] == 5)
    st, d = await ask(1, start=7)
    check("noma'lum raqib 404", st == 404)
    st, d = await ask(1, start=2)
    g = d["game"]
    check("duel boshlandi", g["level"] == 2 and g["lives"] == 5 and g["rlives"] == 5 and g["round"] == 0)
    st, d = await ask(1, game=g["id"], move="sehr", acc=90)
    check("noma'lum tur 404", st == 404)

    # Uch raundda g'alaba: raqib hiyla qiladi, men hujum
    r = None
    for i in range(5):
        r = hpduel._yur(1, g["id"], "hujum", 90, Rnd("hiyla", 70))
    check("besh raundda yutdi, ball = 200 + 5 jon + aniqlik", r["game"]["over"] and r["game"]["won"] and r["game"]["rlives"] == 0 and r["game"]["lives"] == 5
          and r["game"]["score"] == 200 + 100 + 45 and r["round"]["win"] == 1)
    check("tugagan duelga yurish yo'q", hpduel._yur(1, g["id"], "hujum", 90) is None)
    st, d = await ask(1)
    check("g'alabadan keyin: eng yaxshi natija va REYTING (1000 dan oshdi), jadvalda birinchi", d["mine"]["2"] == 345 and d["rating"]["r"] > 1000 and d["rating"]["games"] == 1
          and d["rating"]["wins"] == 1 and d["place"] == 1 and d["top"][0]["me"] and d["top"][0]["score"] == d["rating"]["r"] and r["game"]["delta"] > 0)

    # TARIX: har raund yozilgan, duelni raund-raund qayta ko'rsa bo'ladi; begona ko'ra olmaydi
    st, d = await ask(1, history=1)
    h = d["history"]
    check("tarix: tugagan duel ro'yxatda", len(h) == 1 and h[0]["k"] == "o" and h[0]["won"] and h[0]["rounds"] == 5 and h[0]["saved"] and h[0]["lives"] == [5, 0])
    st, d = await ask(1, replay={"k": "o", "id": g["id"]})
    rp = d["replay"]
    check("qayta ko'rish: besh raund, har birida ikki tomonning turi va aniqligi", len(rp["rounds"]) == 5 and rp["rounds"][0] == {"mine": "hujum", "acc": 90, "his": "hiyla", "racc": 70, "win": 1}
          and rp["start"] == 5 and rp["won"])
    st, d = await ask(2, replay={"k": "o", "id": g["id"]})
    check("mashq duelini begona ko'ra olmaydi; yo'q duel - xato", d == {"ok": False, "error": "no_duel"}
          and (await ask(1, replay={"k": "o", "id": 99999}))[1]["error"] == "no_duel")
    st, d = await ask(1)
    check("holatda turnir ma'lumoti", d["tour"]["ts"] > 0 and d["tour"]["n"] == 0 and d["tour"]["joined"] is False and d["now"] > 0 and d["rules"]["match"] == 300)

    # Yomonroq g'alaba eng yaxshi natijani pasaytirmaydi; boshqa daraja qo'shiladi
    g2 = hpduel._boshla(1, 2)
    hpduel._yur(1, g2["id"], "hujum", 90, Rnd("himoya", 70))
    for i in range(5):
        r = hpduel._yur(1, g2["id"], "hujum", 60, Rnd("hiyla", 70))
    check("pastroq natija saqlanmaydi", r["game"]["won"] and r["game"]["score"] < 345 and (await ask(1))[1]["mine"]["2"] == 345)
    g3 = hpduel._boshla(1, 1)
    for i in range(5):
        r = hpduel._yur(1, g3["id"], "himoya", 80, Rnd("hujum", 70))
    st, d = await ask(1)
    check("darajalar yig'iladi", d["mine"]["1"] == 100 + 100 + 40 and d["mine"]["total"] == 585)

    # Mag'lubiyat va ikkinchi o'yinchi
    g4 = hpduel._boshla(2, 3)
    for i in range(5):
        r = hpduel._yur(2, g4["id"], "hujum", 90, Rnd("himoya", 70))
    check("yutqazdi: ball yo'q", r["game"]["over"] and not r["game"]["won"] and r["game"]["score"] == 0 and r["game"]["lives"] == 0)
    g5 = hpduel._boshla(2, 1)
    for i in range(5):
        hpduel._yur(2, g5["id"], "hujum", 100, Rnd("hiyla", 70))
    st, d = await ask(2)
    check("reyting jadvali: ikki kishi; kuchli raqibga yutqazib, kuchsizni yengan - reytingi pastroq", d["n"] == 2 and d["place"] == 2 and d["top"][0]["uid"] == 1
          and d["top"][0]["score"] > d["top"][1]["score"] and d["rating"]["games"] == 2 and d["rating"]["wins"] == 1)
    r1 = hpduel._kutilgan(1000, 850); r2 = hpduel._kutilgan(1000, 1250)
    check("Elo: kuchsiz raqibni yengish oz, kuchlini yengish ko'p beradi", 16 * (1 - r1) < 5 < 16 * (1 - r2) and abs(hpduel._kutilgan(1000, 1000) - 0.5) < 1e-9)

    # Yangi duel eskisini tashlaydi; API orqali to'liq duel
    a = hpduel._boshla(1, 1); b = hpduel._boshla(1, 1)
    check("yangi duel boshlansa eskisi tashlanadi", hpduel._yur(1, a["id"], "hujum", 90) is None)
    over = False
    for i in range(30):
        st, d = await ask(1, game=b["id"], move="hujum", acc=95)
        if d.get("game", {}).get("over"):
            over = True
            break
    check("API orqali duel tugaydi (20 raunddan oshmaydi)", over and d["game"]["round"] <= 20 and "round" in d)
    db("UPDATE duel_saral SET hafta='2000-01-03'")
    st, d = await ask(1)
    check("yangi haftada haftalik natija noldan, reyting esa saqlanadi", d["mine"]["total"] == 0 and len(d["top"]) == 2 and d["rating"]["games"] > 0)
    check("log", any(x.startswith("duel_1_") for x in loglar))

    # ================= TURNIR: yozilish, reyting bo'yicha to'r, bir oqshomda =================
    from datetime import datetime, timedelta
    TZ = hpcup.TASHKENT
    soat = [datetime(2026, 10, 17, 12, 0, tzinfo=TZ)]          # shanba, turnir - yakshanba 18-oktabr 21:00
    hpduel._now = lambda: soat[0]
    hpdars._hafta = lambda: "2026-10-12"
    hpduel._cfg["admin_ids"] = {42}
    xatlar = []
    async def xat(uid, matnlar):
        xatlar.append((uid, matnlar["uz"][0]))
    hpduel._cfg["xat"] = xat
    def vaqt(kun, s, d=0, sek=0):
        soat[0] = datetime(2026, 10, kun, s, d, sek, tzinfo=TZ)
    def ilgari(sek):
        soat[0] = soat[0] + timedelta(seconds=sek)
    def ball(u):
        return db("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_ref LIKE 'duel:%'", (u,))[0][0]
    def rey(u):
        return db("SELECT reyting FROM duel_reyting WHERE user_id=?", (u,))[0][0]
    for u in range(11, 21):                                     # 11 eng kuchli ... 19 eng kuchsiz; 20 - yozilmaydi
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (u, "D%d" % u, "ravenclaw", "2026-10-01T00:00:00Z"))
        db("INSERT INTO duel_reyting (user_id, reyting, oyin, galaba) VALUES (?,?,5,3)", (u, 1400 - u * 10))
    check("to'r tartibi", hpduel._tartib(8) == [1, 8, 4, 5, 2, 7, 3, 6] and hpduel._tartib(16)[:4] == [1, 16, 8, 9])
    for u in range(11, 20):
        st, d = await ask(u, join=1)
    check("yozilish: 9 kishi, o'zi yozilgan, ro'yxat reyting bo'yicha", d["join_ok"] and d["tour"]["n"] == 9 and d["tour"]["joined"] and d["tour"]["open"]
          and [p["uid"] for p in d["tour"]["players"]][:3] == [11, 12, 13] and d["tour"]["players"][-1]["me"])
    st, d = await ask(12, join=0)
    check("chiqish va qayta yozilish", d["tour"]["n"] == 8 and not d["tour"]["joined"] and (await ask(12, join=1))[1]["tour"]["n"] == 9)
    await hpduel.tick()
    st, d = await ask(11)
    check("turnirdan oldin: to'r yo'q, ball yo'q", d["cup"]["size"] is None and ball(11) == 0)
    vaqt(18, 10, 5)
    await hpduel.tick(); await hpduel.tick()
    check("turnir kuni 10:00: yozilgan 9 kishiga eslatma, bir marta", len(xatlar) == 9 and "21:00" in xatlar[0][1])
    vaqt(18, 20, 51); await hpduel.tick(); await hpduel.tick()
    check("10 daqiqa qolganda yana eslatma", len(xatlar) == 18 and "10 daqiqa" in xatlar[-1][1])
    st, d = await ask(11)
    check("20:51: yozilish hali ochiq, to'r yo'q", d["tour"]["open"] and d["cup"]["size"] is None)
    vaqt(18, 20, 56)
    await hpduel.tick(); await hpduel.tick()
    st, d = await ask(20, join=1)
    check("20:55 dan keyin yozilish yopiq", d["join_ok"] is False and not d["tour"]["open"] and not d["tour"]["joined"])
    st, d = await ask(11)
    C = d["cup"]
    q = C["stages"][0]["matches"]
    haqiqiy = [m for m in q if m["why"] != "bye"]
    check("9 kishi: 16 talik to'r, 7 kuchli birinchi bosqichni o'tkazib yuboradi, 8- va 9-o'rin o'ynaydi", C["size"] == 16 and [x["stage"] for x in C["stages"]] == [16, 8, 4, 2]
          and len(q) == 8 and len(haqiqiy) == 1 and (haqiqiy[0]["a"]["uid"], haqiqiy[0]["b"]["uid"]) == (18, 19)
          and sum(1 for m in q if m["why"] == "bye" and m["winner"] == m["a"]["uid"] and m["b"] is None) == 7)
    s8 = C["stages"][1]["matches"]
    check("chorak final: kutganlar joyida, birinchi juftlik g'olibni kutmoqda; o'tkazib yuborganga ball yo'q", s8[0]["a"]["uid"] == 11 and s8[0]["b"] is None
          and [(m["a"]["uid"], m["b"]["uid"]) for m in s8[1:]] == [(14, 15), (12, 17), (13, 16)] and ball(11) == 0 and C["my"]["stage"] == 8)
    check("bosqichlar 6 daqiqadan: 21:00, 21:06, 21:12, 21:18", [int(x["ts"] - C["stages"][0]["ts"]) for x in C["stages"]] == [0, 360, 720, 1080]
          and [x["points"] for x in C["stages"]] == [5, 10, 20, 30])

    async def ar(u, mid, **kw):
        st, d = await ask(u, arena=mid, **kw)
        return d.get("arena")
    m1 = haqiqiy[0]["id"]
    vaqt(18, 20, 58)
    A = await ar(18, m1)
    check("vaqtidan oldin: kutish", A["phase"] == "early" and A["starts_in"] == 120 and A["opp"]["name"] == "D19")
    check("begona odam arenaga kira olmaydi", (await ask(12, arena=m1))[1].get("error") == "no_match")
    vaqt(18, 21, 0, 5)
    A = await ar(18, m1)
    check("raqib kelmagan: kutmoqda", A["phase"] == "wait" and not A["opp"]["here"])
    B = await ar(19, m1)
    check("ikkalasi keldi: duel boshlandi, raundga 20 soniya", B["phase"] == "pick" and B["round"] == 1 and B["lives"] == 5 and B["deadline_in"] == 20)
    A = await ar(18, m1, move="hujum", acc=90)
    check("yurish yozildi, raqib kutilmoqda", A["phase"] == "pick" and A["moved"])
    B = await ar(19, m1, move="hiyla", acc=80)
    check("raund hal bo'ldi: natija ikkalasiga o'z tomonidan", B["phase"] == "reveal" and B["last"]["win"] == -1 and B["lives"] == 4 and B["last"]["mine"] == "hiyla" and B["last"]["racc"] == 90)
    r18, r19 = rey(18), rey(19)
    for i in range(4):
        ilgari(6)
        await ar(18, m1); await ar(19, m1)
        await ar(18, m1, move="hujum", acc=90)
        B = await ar(19, m1, move="hiyla", acc=80)
    A = await ar(18, m1)
    check("besh raundda g'alaba: 1/8 uchun +5 ball darhol, reyting o'zgardi", A["over"] and A["won"] and B["over"] and not B["won"] and ball(18) == 5 and ball(19) == 0
          and rey(18) > r18 and rey(19) < r19 and abs((rey(18) - r18) + (rey(19) - r19)) < 1e-6)
    check("g'olibga keyingi dueli aytiladi (chorak final, 21:06)", A["next"] and A["next"]["id"] == s8[0]["id"] and 300 < A["next"]["in"] <= 360 and B["next"] is None)
    # Duelni raund-raund qayta ko'rish: o'ynaganlar o'z tomonidan, boshqalar - 1-tomondan
    rp = (await ask(18, replay={"k": "m", "id": m1}))[1]["replay"]
    check("turnir dueli tarixi: g'olib tomonidan", len(rp["rounds"]) == 5 and rp["rounds"][0] == {"mine": "hujum", "acc": 90, "his": "hiyla", "racc": 80, "win": 1}
          and rp["me"] and rp["won"] and rp["p1"]["uid"] == 18 and rp["p2"]["uid"] == 19 and rp["lives"] == [5, 0] and rp["stage"] == 16)
    rp = (await ask(19, replay={"k": "m", "id": m1}))[1]["replay"]
    check("turnir dueli tarixi: yutqazgan tomonidan", rp["rounds"][0]["mine"] == "hiyla" and rp["rounds"][0]["win"] == -1 and not rp["won"] and rp["p1"]["uid"] == 19)
    rp = (await ask(12, replay={"k": "m", "id": m1}))[1]["replay"]
    check("turnir dueli tarixi: tomoshabin ham ko'ra oladi", not rp["me"] and rp["p1"]["uid"] == 18 and len(rp["rounds"]) == 5 and rp["won"])
    check("tugamagan uchrashuvni ko'rib bo'lmaydi", (await ask(12, replay={"k": "m", "id": s8[1]["id"]}))[1].get("error") == "no_duel")
    h = (await ask(18, history=1))[1]["history"]
    check("tarix ro'yxatida turnir dueli", any(x["k"] == "m" and x["id"] == m1 and x["won"] and x["rounds"] == 5 and x["stage"] == 16 and x["opp"]["uid"] == 19 for x in h))
    d = (await ask(11))[1]
    check("to'rda raundlar soni; chorak finalda g'olib joyiga tushdi", [m for st_ in d["cup"]["stages"] for m in st_["matches"] if m["id"] == m1][0]["rounds"] == 5
          and d["cup"]["stages"][1]["matches"][0]["b"]["uid"] == 18)

    # ----- chorak final (21:06): to'liq duel, kelmagan raqib, ikkalasi kelmadi, vaqt tugadi -----
    k1, k2, k3, k4 = [m["id"] for m in d["cup"]["stages"][1]["matches"]]
    # (vaqt faqat oldinga yuradi: har so'rov butun turnirni hozirgi vaqtga keltiradi)
    vaqt(18, 21, 6, 2)
    await ar(14, k2)                                  # 14 keldi, raqibi (15) kelmaydi
    await ar(13, k4); await ar(16, k4)                # 13 va 16: bitta raund o'ynab, keyin yurmay qo'yishadi
    await ar(13, k4, move="hujum", acc=90)
    await ar(16, k4, move="hiyla", acc=80)
    await ar(11, k1); await ar(18, k1)                # 11 va 18: to'liq duel
    for i in range(5):
        await ar(11, k1, move="hujum", acc=90)
        await ar(18, k1, move="hiyla", acc=80)
        ilgari(6)
        await ar(11, k1); await ar(18, k1)
    A = await ar(11, k1)
    check("chorak finalda g'alaba: +10", A["over"] and A["won"] and ball(11) == 10 and ball(18) == 5)
    vaqt(18, 21, 7, 2)
    A = await ar(14, k2)
    check("raqib 1 daqiqada kelmadi: g'alaba, reyting o'zgarmaydi", A["over"] and A["won"] and A["why"] == "kelmadi" and ball(14) == 10 and rey(14) == 1400 - 140 and rey(15) == 1400 - 150)
    vaqt(18, 21, 11, 1)
    await hpduel.tick()
    st, d = await ask(12)
    s8 = d["cup"]["stages"][1]["matches"]; s4 = d["cup"]["stages"][2]["matches"]
    check("ikkalasi kelmadi: reytingi yuqori o'tadi", s8[2]["winner"] == 12 and s8[2]["why"] == "ikkalasi" and ball(12) == 10)
    check("duelga 5 daqiqa: vaqt tugadi - joni ko'p yutadi", s8[3]["winner"] == 13 and s8[3]["why"] == "vaqt" and s8[3]["lives"] == [5, 4] and ball(13) == 10 and rey(13) > 1400 - 130)
    check("yarim final juftlari to'ldi (21:12)", (s4[0]["a"]["uid"], s4[0]["b"]["uid"]) == (11, 14) and (s4[1]["a"]["uid"], s4[1]["b"]["uid"]) == (12, 13) and d["cup"]["my"]["stage"] == 4)
    # yarim final va final: hech kim kelmaydi - reytingi yuqorilar o'tadi, turnir shu oqshom tugaydi
    vaqt(18, 21, 13, 5); await hpduel.tick()
    vaqt(18, 21, 19, 5); await hpduel.tick()
    st, d = await ask(11)
    fin = d["cup"]["stages"][3]["matches"][0]
    check("turnir bir oqshomda tugadi: final g'olibi aniqlandi, ballar 5/10/20/30 bo'yicha", fin["winner"] == 11 and fin["state"] == "tugadi" and d["cup"]["my"] is None
          and ball(11) == 10 + 20 + 30 and ball(12) == 10 + 20 and ball(14) == 10)
    # Sinov uchrashuvi (admin): kompyuter raqib, ballsiz
    db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (42,'Admin','gryffindor','2026-10-01T00:00:00Z')")
    st, d = await ask(11, sinov=1)
    check("oddiy odam sinov ocholmaydi", "test_id" not in d)
    st, d = await ask(42, sinov=1)
    tid = d["test_id"]
    A = await ar(42, tid)
    ilgari(13)
    A2 = await ar(42, tid)
    A3 = await ar(42, tid, move="hujum", acc=95)
    ilgari(4)
    A4 = await ar(42, tid)
    check("sinov: kompyuter raqib o'zi keladi va yuradi, ball yo'q", A["phase"] == "early" and A["test"] and A2["phase"] == "pick" and A2["opp"]["here"]
          and A3["moved"] and A4["phase"] == "reveal" and A4["last"]["his"] in hpduel.TURLAR and ball(42) == 0)

    # ---------- do'stona duel (chatdagi taklif) ----------
    rey = lambda u: (db("SELECT reyting FROM duel_reyting WHERE user_id=?", (u,)) or [(None,)])[0][0]
    r11, r12, b11, b12 = rey(11), rey(12), ball(11), ball(12)
    mid = await hpduel.dost_yarat(11)
    A = await ar(11, mid)
    check("do'stona: taklif ochiq, chaqiruvchi kutadi", A["phase"] == "open" and A["friend"] and A["expires_in"] > 0)
    check("do'stona: begona odam arenaga kira olmaydi", (await ask(13, arena=mid))[1].get("error") == "no_match")
    st, d = await ask(12, accept=mid)
    check("do'stona: qabul qilindi", d.get("friend_id") == mid)
    st, d = await ask(13, accept=mid)
    check("do'stona: ikkinchi odam qabul qila olmaydi", d.get("error") == "taken")
    ilgari(hpduel.DOST_BOSH + 1)
    await ar(11, mid); B = await ar(12, mid); A = await ar(11, mid)
    check("do'stona: ikkalasi kelgach duel boshlanadi", A["phase"] == "pick" and B["opp"]["uid"] == 11 and A["opp"]["uid"] == 12)
    for i in range(hpduel.JON):
        await ar(11, mid, move="hujum", acc=95)
        await ar(12, mid, move="hiyla", acc=40)
        ilgari(hpduel.PAUZA + 1)
        A = await ar(11, mid)
    check("do'stona: duel tugadi, 11 yutdi", A["over"] and A["won"] and A["why"] == "duel" and A["next"] is None)
    check("do'stona: ball ham, reyting ham o'zgarmadi", ball(11) == b11 and ball(12) == b12 and rey(11) == r11 and rey(12) == r12)
    st, d = await ask(12, history=1)
    check("do'stona: tarixda «friend» belgisi bilan", any(h.get("friend") and h["id"] == mid and not h["won"] for h in d["history"]))
    m2 = await hpduel.dost_yarat(11)
    m3 = await hpduel.dost_yarat(11)
    check("do'stona: yangi taklif eskisini bekor qiladi", (await ar(11, m2))["phase"] == "over" and (await ar(11, m3))["phase"] == "open")
    st, d = await ask(11, cancel=m3)
    check("do'stona: bekor qilish", d.get("cancel_ok") and (await ask(12, accept=m3))[1].get("error") == "expired")
    m4 = await hpduel.dost_yarat(11)
    ilgari(hpduel.DOST_MUDDAT + 1)
    check("do'stona: muddati o'tgan taklif qabul qilinmaydi", (await ask(12, accept=m4))[1].get("error") == "expired" and (await ar(11, m4))["over"])
    # chat kartasi
    msg = await hpcup.post_chat_message("global", 11, "duel", None, duel=mid)
    check("chat kartasi: tugagan duel, g'olib bilan", msg.get("duel") and msg["duel"]["status"] == "finished" and msg["duel"]["winner"] == 11 and msg["duel"]["b"]["uid"] == 12)
    m5 = await hpduel.dost_yarat(13)
    msg = await hpcup.post_chat_message("global", 13, "duel", None, duel=m5)
    check("chat kartasi: ochiq taklif", msg["duel"]["status"] == "waiting" and msg["duel"]["b"] is None)
    rooms = await hpcup.chat_bump_duel(m5)
    check("chat kartasi: xona yangilanadi", rooms == ["global"])

    print("Duel: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
