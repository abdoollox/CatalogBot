# -*- coding: utf-8 -*-
"""Maxluqlar jangi: kartalar kuchi, daraja, unsur, to'plam, mashq (kompyuter), raund vaqti, kelmadi, turnir, do'st bilan.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import json
import os
import random
import sqlite3
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-mjang-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars, hpqoriq, hpmjang as P   # noqa: E402
KOD_REJIM = P.YANGI_QOIDA
P.YANGI_QOIDA = "admin"         # eski qoida sinovlari - oddiy o'yinchilar 5 karta bilan

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
    r = await P.api_mjang(Req(body, init=str(kim)))
    return json.loads(r.body)


def db(sql, args=()):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        r = c.execute(sql, args).fetchall()
        c.commit()
        return r
    finally:
        c.close()


def oyna(A, B, da, db_, rnd):
    """Ikki kompyuter o'rtasida bitta o'yin (sinov uchun): g'olib 'a' | 'b' | None."""
    tarix, wa, wb, nav = [], 0, 0, rnd.choice("ab")
    while len(tarix) < P.QOL and wa < P.YUTISH and wb < P.YUTISH:
        dl, dr = (da, db_) if nav == "a" else (db_, da)
        i, s = P.kompyuter_hujum(A, B, tarix, nav, wa, wb, dl, rnd)
        jy = "b" if nav == "a" else "a"
        j = P.kompyuter_javob(A, B, tarix, jy, wa, wb, {"i": i, "s": s}, dr, rnd)
        ia, ib = (i, j) if nav == "a" else (j, i)
        va, vb = P.kuch(A[ia], s, B[ib]), P.kuch(B[ib], s, A[ia])
        tarix.append({"a": {"i": ia}, "b": {"i": ib}})
        wa += va > vb; wb += vb > va
        nav = "a" if va > vb else "b" if vb > va else jy
    return "a" if wa > wb else "b" if wb > wa else None


async def oyna_api(uid, oid, ilgari, P, ask):
    """O'yinchi oddiy o'ynaydi: hujumda birinchi qolgan kartasining eng kuchli tomoni, javobda birinchi qolgan karta."""
    for _ in range(30):
        g = (await ask(uid, oyin=oid))["game"]
        if g["state"] != "ketmoqda":
            return g
        ilgari(max(0, g["in"]) + 0.1)
        g = (await ask(uid, oyin=oid))["game"]
        men = g["me"]
        used = [h[men]["i"] for h in g["hist"]]
        bor = [i for i in range(5) if i not in used]
        if g["phase"] == "attack" and g["turn"] == men:
            await ask(uid, oyin=oid, hujum={"i": bor[0], "s": P.eng_kuchli(g["hand"][men][bor[0]]["k"])})
        elif g["phase"] == "answer" and g["turn"] != men:
            await ask(uid, oyin=oid, javob=bor[0])
        else:
            ilgari(1.5)
    return (await ask(uid, oyin=oid))["game"]


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    app = types.SimpleNamespace(router=types.SimpleNamespace(add_route=lambda *a, **k: None))
    cfg = {"cors": lambda r: r, "verify_init_data": lambda s: {"id": int(s)} if s.lstrip("-").isdigit() else None}
    hpdars.register(app, cfg)
    hpqoriq.register(app, cfg)
    xatlar, elonlar = [], []
    async def xat(uid, matnlar):
        xatlar.append((uid, matnlar["uz"][0]))
    async def elon(matnlar):
        elonlar.append(matnlar["uz"][0])
        return 0
    P.register(app, dict(cfg, xat=xat, elon=elon, admin_ids={42}))
    soat = [datetime(2026, 10, 14, 12, 0, tzinfo=TZ)]
    P._now = lambda: soat[0]
    hpdars._hafta = lambda: (soat[0].date() - timedelta(days=soat[0].weekday())).strftime("%Y-%m-%d")
    hpcup.now_tk = lambda: soat[0]
    def vaqt(kun, s, d=0, sek=0):
        soat[0] = datetime(2026, 10, kun, s, d, sek, tzinfo=TZ)
    def ilgari(sek):
        soat[0] = soat[0] + timedelta(seconds=sek)
    def ball(u):
        return db("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_ref LIKE 'mjang:%'", (u,))[0][0]
    for u in list(range(1, 8)) + [42]:
        db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (u, "U%d" % u, "gryffindor", "2026-10-01T00:00:00Z"))
    db("INSERT OR IGNORE INTO users (user_id, first_name, created_at) VALUES (30,'Uysiz','2026-10-01T00:00:00Z')")

    # ---------- kartalar ----------
    check("12 maxluq - Qo'riqxonadagi bilan bir xil, kuchlar yig'indisi hammada 15", set(P.KARTALAR) == set(hpqoriq.MAXLUQLAR)
          and all(sum(v[1:]) == 15 for v in P.KARTALAR.values()))
    check("har unsurda 4 tadan maxluq", all(sum(1 for v in P.KARTALAR.values() if v[0] == u) == 4 for u in ("olov", "suv", "havo")))
    aj, gp, kl = {"k": "ajdar"}, {"k": "gippo"}, {"k": "kalmar"}
    check("unsur ustunligi: olov havoni yengadi (+2), havo olovga qarshi qo'shimchasiz", P.kuch(aj, "k", gp) == 9 + 2 and P.kuch(gp, "k", aj) == 7)
    check("suv olovni yengadi", P.kuch(kl, "h", aj) == 6 + 2 and P.kuch(aj, "h", kl) == 4)
    check("o'stirilgan maxluq: faqat eng kuchli tomoniga qo'shimcha", P.kuch({"k": "ajdar", "o": 1}, "k") == 10 and P.kuch({"k": "ajdar", "o": 1}, "h") == 4
          and P.eng_kuchli("boyogli") == "c")
    check("o'smir +0,5 - teng bo'lsa yutadi", P.kuch({"k": "kalmar", "o": 0.5}, "k") > P.kuch({"k": "kalmar"}, "k"))

    # ---------- kompyuter ----------
    rnd = random.Random(7)
    def kuchlilik(d1, d2, n=120):
        w = 0
        for _ in range(n):
            kod = rnd.sample(list(P.KARTALAR), 10)
            A, B = [{"k": k, "o": 0} for k in kod[:5]], [{"k": k, "o": 0} for k in kod[5:]]
            r = oyna(A, B, d1, d2, rnd)
            w += 1 if r == "a" else 0.5 if r is None else 0
        return w / n
    k31, k21 = kuchlilik(3, 1), kuchlilik(2, 1)
    k32 = kuchlilik(3, 2)
    check("hisob-kitob hal qiladi: qiyin kompyuter o'rtachani, o'rtacha osonni ko'p yengadi (%.2f, %.2f, %.2f)" % (k32, k21, k31),
          k32 > 0.65 and k21 > 0.75 and k31 > 0.8)

    # ---------- kartalar holati ----------
    d = await ask(1)
    check("holat: 12 karta, o'quvchida maxluq yo'q", d["ok"] and len(d["cards"]) == 12 and all(c["st"] == -1 and c["o"] == 0 for c in d["cards"]))
    db("INSERT INTO qoriq (user_id, kod, olgan, boqildi) VALUES (1,'testral','2026-10-01',10)")
    db("INSERT INTO qoriq (user_id, kod, olgan, boqildi) VALUES (1,'flobber','2026-10-01',3)")
    db("INSERT INTO qoriq (user_id, kod, olgan, boqildi) VALUES (1,'gippo','2026-10-01',1)")
    kt = {c["k"]: c for c in (await ask(1))["cards"]}
    check("o'z maxluqi: katta +1, o'smir +0,5, bola 0", kt["testral"]["o"] == 1 and kt["flobber"]["o"] == 0.5 and kt["gippo"]["o"] == 0 and kt["gippo"]["st"] == 0)

    # ---------- mashq ----------
    check("saralanmagan mashq ocha olmaydi", (await ask(30, mashq=1)).get("error") == "no_house")
    d = await ask(1, mashq=1)
    g = d["game"]
    qa, qb = [c["k"] for c in g["hand"]["a"]], [c["k"] for c in g["hand"]["b"]]
    check("mashq ochildi: raqib Luna, 5 tadan karta, takrorsiz, ikkala qo'l ochiq", g["kind"] == "mashq" and g["b"]["name"] == "Luna Lavgud"
          and len(qa) == 5 and len(qb) == 5 and len(set(qa + qb)) == 10 and g["phase"] == "wait")
    ka = {c["k"]: c for c in g["hand"]["a"]}
    check("qo'ldagi o'z maxluqi qo'shimchasi bilan keladi", all(ka[k]["o"] == {"testral": 1, "flobber": 0.5}.get(k, 0) for k in ka))
    oid = g["id"]
    ilgari(g["in"] + 0.1)
    g = (await ask(1, oyin=oid))["game"]
    if g["turn"] == "b":
        ilgari(2)
        g = (await ask(1, oyin=oid))["game"]
        check("kompyuter hujum qildi: kartasi va kuchi ochiq, endi javob navbati", g["phase"] == "answer" and g["attack"] and g["attack"]["s"] in "khc")
        check("hujum navbati bo'lmaganda hujum qabul qilinmaydi", (await ask(1, oyin=oid, hujum={"i": 0, "s": "k"}))["move_ok"] is False)
        d = await ask(1, oyin=oid, javob=0)
    else:
        check("hujum navbati sizda: tanlash fazasi", g["phase"] == "attack")
        check("javob navbati bo'lmaganda javob qabul qilinmaydi", (await ask(1, oyin=oid, javob=0))["move_ok"] is False)
        d = await ask(1, oyin=oid, hujum={"i": 0, "s": "k"})
        ilgari(2)
        d = await ask(1, oyin=oid)
        check("kompyuter javob berdi: raund ochildi", len(d["game"]["hist"]) == 1)
    g = d["game"]
    h = g["hist"][0]
    check("raund natijasi: ikkala karta, kuchlar, g'olib to'g'ri", h["a"]["k"] == g["hand"]["a"][h["a"]["i"]]["k"]
          and h["w"] == ("a" if h["a"]["v"] > h["b"]["v"] else "b" if h["b"]["v"] > h["a"]["v"] else None))
    check("yutgan keyingi raundda hujum qiladi (teng bo'lsa navbat almashadi)", g["turn"] == (h["w"] or ("b" if h["by"] == "a" else "a")))
    ilgari(P.PAUZA + 0.1)
    g = await oyna_api(1, oid, ilgari, P, ask)
    check("o'yin tugadi: kimdir 3 ta yutdi yoki 5 raund o'ynaldi", g["state"] == "tugadi" and (max(g["wins"]) >= 3 or len(g["hist"]) == 5))
    check("har karta bir marta ishlatildi", len({x["a"]["i"] for x in g["hist"]}) == len(g["hist"]))
    check("mashqda ball yo'q", ball(1) == 0)
    h = (await ask(1, history=1))["history"]
    check("o'yinlar tarixi: tugagan mashq o'yini, raqib - kompyuter, hisob va natija", len(h) >= 1 and h[0]["id"] == oid and h[0]["kind"] == "mashq"
          and h[0]["opp"] and h[0]["opp"].get("bot") and h[0]["res"] in ("g", "m", "d") and len(h[0]["score"]) == 2)

    # vaqtida tanlamasa - karta o'zi qo'yiladi
    d = await ask(2, mashq=2)
    oid = d["game"]["id"]
    ilgari(d["game"]["in"] + 2 * P.RAUND_T + 3)
    g = (await ask(2, oyin=oid))["game"]
    check("vaqt tugadi: o'yinchi o'rniga karta qo'yildi, o'yin davom etadi", len(g["hist"]) >= 1 and g["state"] == "ketmoqda")

    # ---------- turnir: 3 kishi ----------
    vaqt(14, 12)
    d = await ask(3, join=1)
    check("yozilish: navbatdagi turnir - shanba 24-oktabr 22:00", d["join_ok"] and d["tour"]["joined"]
          and datetime.fromtimestamp(d["tour"]["ts"], TZ).strftime("%Y-%m-%d %H:%M") == "2026-10-24 22:00")
    await ask(4, join=1); await ask(5, join=1)
    vaqt(17, 10, 1)
    await P.tick()
    check("shanba bo'lsa ham boshqa hafta - e'lon ketmaydi", not elonlar)
    vaqt(24, 10, 1)
    await P.tick(); await asyncio.sleep(0.05)
    check("birinchi turnir kuni ertalab hammaga e'lon (bir marta)", len(elonlar) == 1)
    await P.tick(); await asyncio.sleep(0.05)
    check("e'lon takrorlanmaydi", len(elonlar) == 1)
    vaqt(24, 21, 56)
    await P.tick()
    d = await ask(3)
    check("to'r tuzildi: 4 talik, bittasi o'tkazib yuboradi", d["cup"]["size"] == 4 and any(m["why"] == "bye" for m in d["cup"]["stages"][0]["matches"]))
    check("yozilish yopildi", (await ask(6, join=1))["join_ok"] is False)
    vaqt(24, 22, 0, 1)
    await P.tick()
    yarim = [m for m in d["cup"]["stages"][0]["matches"] if m["why"] != "bye"][0]
    a_uid, b_uid = yarim["a"]["uid"], yarim["b"]["uid"]
    d = await ask(a_uid)
    act = d.get("active")
    check("o'yin boshlandi va o'yinchiga ko'rinadi", act and act["kind"] == "turnir")
    mid = act["id"]
    # «a» o'ynaydi, «b» umuman kelmaydi
    for _ in range(14):
        g = (await ask(a_uid, oyin=mid))["game"]
        if g["state"] != "ketmoqda":
            break
        ilgari(max(0, g["in"]) + 0.1)
        g = (await ask(a_uid, oyin=mid))["game"]
        used = [h["a"]["i"] for h in g["hist"]]
        bor = [i for i in range(5) if i not in used]
        if g["phase"] == "attack" and g["turn"] == "a":
            await ask(a_uid, oyin=mid, hujum={"i": bor[0], "s": "k"})
        elif g["phase"] == "answer" and g["turn"] == "b":
            await ask(a_uid, oyin=mid, javob=bor[0])
        else:
            ilgari(P.RAUND_T + 1)
            await P.tick()
    g = (await ask(a_uid, oyin=mid))["game"]
    check("raqib kelmadi - yutqazdi", g["state"] == "tugadi" and g["winner"] == "a" and g["why"] == "kelmadi")
    check("g'alaba uchun ball (yarim final +20)", ball(a_uid) == 20 and ball(b_uid) == 0)
    vaqt(24, 22, 30)
    await P.tick()
    d = await ask(3)
    fin = d["cup"]["stages"][1]["matches"][0]
    check("final juftligi aniqlandi va boshlandi", fin["a"] and fin["b"] and fin["state"] == "ketmoqda")
    # finalni oxirigacha: ikkalasi o'ynaydi
    fid = fin["id"]
    for _ in range(30):
        g = (await ask(fin["a"]["uid"], oyin=fid))["game"]
        if g["state"] != "ketmoqda":
            break
        ilgari(max(0, g["in"]) + 0.1)
        g = (await ask(fin["a"]["uid"], oyin=fid))["game"]
        nav = g["turn"]
        kim = nav if g["phase"] == "attack" else ("b" if nav == "a" else "a")
        used = [h[kim]["i"] for h in g["hist"]]
        bor = [i for i in range(5) if i not in used]
        if g["phase"] == "attack":
            await ask(fin[kim]["uid"], oyin=fid, hujum={"i": bor[0], "s": "h"})
        elif g["phase"] == "answer":
            await ask(fin[kim]["uid"], oyin=fid, javob=bor[-1])
    g = (await ask(fin["a"]["uid"], oyin=fid))["game"]
    check("final tugadi, g'olib bor (teng bo'lsa to'rda yuqori turgan)", g["state"] == "tugadi" and g["winner"] in ("a", "b"))
    gol = fin[g["winner"]]["uid"]
    check("final g'olibiga +30", ball(gol) >= 30)
    vaqt(25, 12)
    d = await ask(6)
    check("«So'nggi g'oliblar» kartasi: 1-o'rin final g'olibi", d["champs"] and d["champs"]["top"][0]["uid"] == gol and d["champs"]["top"][0]["place"] == 1)

    # ---------- sinov o'yini (admin) ----------
    d = await ask(42, sinov=1)
    check("admin sinov o'yini: kompyuter bilan", d["game"]["kind"] == "sinov" and d["game"]["b"]["name"] == "Charli Uizli")
    check("oddiy o'quvchi sinov ochmaydi", "game" not in (await ask(6, sinov=1)))

    # ---------- do'st bilan (Telegram taklifi) ----------
    d = await ask(1, dost=1)
    tid = d["game"]["id"]
    check("do'stga taklif: kutmoqda, muddati bor", d["game"]["kind"] == "dost" and d["game"]["state"] == "kutmoqda" and d["game"]["expires_in"] > 1000)
    # Xogvarts chatidagi taklif kartasi (o'quvchilar taklifi): ochiq -> ketmoqda, holati o'zgarsa karta yangilanadi
    msg = await hpcup.post_chat_message("global", 1, "taklif", None, mjang=tid)
    check("chat kartasi: ochiq taklif", msg.get("mjang") and msg["mjang"]["status"] == "waiting" and msg["mjang"]["b"] is None and msg["mjang"]["a"]["uid"] == 1)
    check("taklif ma'lumoti (karta uchun)", P.taklif_info(tid) == {"a": 1, "name": "U1"})
    db("INSERT OR IGNORE INTO users (user_id, first_name, created_at) VALUES (31,'Yangi','2026-10-01T00:00:00Z')")
    d = await ask(31, qabul=tid)
    g = d["game"]
    check("saralanmagan (yangi) do'st qabul qildi: jang boshlandi, unga ham 5 karta", d["ok"] and g["state"] == "ketmoqda" and g["me"] == "b"
          and len(g["hand"]["b"]) == 5 and all(c["o"] == 0 for c in g["hand"]["b"]))
    await P._dost_xabar()
    rooms = await hpcup.chat_bump_oyin("mjang", tid)
    _c = hpcup._connect()
    try:
        msg2 = hpcup._chat_one(_c, msg["id"], 1)
    finally:
        _c.close()
    check("chat kartasi: raqib qabul qildi - o'yin ketmoqda, xona yangilanadi", rooms == ["global"] and msg2["mjang"]["status"] == "active" and msg2["mjang"]["b"]["uid"] == 31)
    check("qabul qilingan taklif yopiq", P.taklif_info(tid) is None)
    check("ikkinchi odam qabul qila olmaydi", (await ask(2, qabul=tid)).get("error") == "band")
    check("saralanmagan turnirga yozila olmaydi", (await ask(31, join=1)).get("error") == "no_house")
    t2 = (await ask(2, dost=1))["game"]["id"]
    check("taklifni bekor qilish", (await ask(2, bekor=t2)).get("bekor_ok") and P.taklif_info(t2) is None)
    t3 = (await ask(3, dost=1))["game"]["id"]
    ilgari(P.DOST_MUDDAT + 5)
    await P.tick()
    check("muddati o'tgan taklif yopiladi", P.taklif_info(t3) is None and (await ask(4, qabul=t3)).get("error") == "muddat")

    # 2-qoida - navbatli hujum (2026-10-25): hozircha faqat admin o'yinlarida
    import random as _r
    db("INSERT OR IGNORE INTO users (user_id, first_name, house, created_at) VALUES (42,'Admin','ravenclaw','2026-10-01T00:00:00Z')")
    _c = hpcup._connect()
    try:
        now = P._ep()
        m1 = P._yangi_oyin(_c, "dost", 1, 2, now - 100, _r.Random(3))
        m2 = P._yangi_oyin(_c, "dost", 42, 2, now - 100, _r.Random(3))
        m3 = P._yangi_oyin(_c, "turnir", 42, 2, now - 100, _r.Random(3), a_seed=1, b_seed=2)
        hand = lambda mid: len(json.loads(_c.execute("SELECT a_qol FROM mj_match WHERE id=?", (mid,)).fetchone()[0]))
        check("2-qoida faqat admin o'yinida (6 karta); oddiy va turnir - 5", hand(m1) == 5 and hand(m2) == 6 and hand(m3) == 5)
        for _ in range(12):                      # 6 raundgacha qo'lda o'ynaymiz
            m = _c.execute("SELECT * FROM mj_match WHERE id=?", (m2,)).fetchone()
            if m["holat"] != "ketmoqda":
                break
            nav = m["navbat"]
            if m["hujum"] is None:
                qol = json.loads(m[nav + "_qol"])
                P._hujum_qoy(_c, m, min(P._qolgan(qol, json.loads(m["tarix"]), nav)), "k", now)
            else:
                jy = "b" if nav == "a" else "a"
                qol = json.loads(m[jy + "_qol"])
                P._javob_qoy(_c, m, max(P._qolgan(qol, json.loads(m["tarix"]), jy)), [], now)
        m = _c.execute("SELECT * FROM mj_match WHERE id=?", (m2,)).fetchone()
        tr = json.loads(m["tarix"])
        f = tr[0]["by"]; o = "b" if f == "a" else "a"
        kutilgan = [f, o, o, f, f, o][:len(tr)]
        check("2-qoida: hujum navbati A-B-B-A-A-B, natijaga qaramay", [r["by"] for r in tr] == kutilgan)
        check("2-qoida: 4 raund yutgan yoki 6 raunddan keyin tugaydi", m["holat"] == "tugadi"
              and (max(m["a_win"], m["b_win"]) >= 4 or len(tr) == 6))
        g = P._oyin_holat(_c, m, 42, now)
        check("o'yin holatida qoida, kerakli g'alaba, raundlar", g["rule"] == 2 and g["need"] == 4 and g["rounds"] == 6)
        # kompyuter 6 kartali o'yinda xatosiz yuradi
        A, B = P.tarqat(_c, 42, 2, _r.Random(5), 6)
        i, s_ = P.kompyuter_hujum(A, B, [], "a", 0, 0, 3, _r.Random(1))
        j = P.kompyuter_javob(A, B, [], "b", 0, 0, {"i": i, "s": s_}, 3, _r.Random(1))
        check("kompyuter 2-qoidada ham yuradi", 0 <= i < 6 and s_ in P.KUCHLAR and 0 <= j < 6)
    finally:
        _c.close()
    P.YANGI_QOIDA = "hamma"
    _c = hpcup._connect()
    try:
        m4 = P._yangi_oyin(_c, "turnir", 1, 2, P._ep(), _r.Random(3), a_seed=1, b_seed=2)
        check("hammaga ochilganda turnir ham 2-qoidada", len(json.loads(_c.execute("SELECT a_qol FROM mj_match WHERE id=?", (m4,)).fetchone()[0])) == 6)
    finally:
        _c.close()
    P.YANGI_QOIDA = KOD_REJIM
    check("kodda hozircha faqat admin rejimi (egasi sinab ko'radi)", KOD_REJIM == "admin")

    print("Maxluqlar jangi: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(amain())
