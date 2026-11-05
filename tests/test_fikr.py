# -*- coding: utf-8 -*-
"""So'rovnoma (hpanketa) va g'oyalar qutisi (hpgoya): javobni tekshirish, bir marta yozish, panel sanog'i, holat va xat.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-fikr-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpanketa as A, hpgoya as G   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


asyncio.run(hpcup.init())
A._init()
G._init()
c = hpcup._connect()
for u, h in [(1, "slytherin"), (2, None), (42, "direktor")]:
    c.execute("INSERT OR REPLACE INTO users (user_id, first_name, house, created_at) VALUES (?,?,?,?)", (u, "U%d" % u, h, "2026-10-01T00:00:00Z"))
c.commit()
c.close()

# --- so'rovnoma (2-nusxa: o'tgan voqealar, 20 galleon)
def gal(u):
    c = hpcup._connect()
    try:
        return c.execute("SELECT galleons FROM users WHERE user_id=?", (u,)).fetchone()[0]
    finally:
        c.close()

ASOS = {"qayerdan": "dost", "oldin": "tv", "maqsad": "film_korish", "oxirgi": ["film"], "aytdimi": "yoq"}
toza = A.tekshir(dict(ASOS, oxirgi=["chat", "yolgon", "film"], aytdimi="ha", aytdi_matn="  Hamma film o'zbekchada bor  ", yosh="99"))
check("noto'g'ri variant tashlanadi, tartib ro'yxatdagidek",
      toza == dict(ASOS, oxirgi=["film", "chat"], aytdimi="ha", aytdi_matn="Hamma film o'zbekchada bor"))
check("majburiy savolsiz rad", A.tekshir({"qayerdan": "dost", "oldin": "tv"}) is None)
check("noto'g'ri bitta tanlov rad", A.tekshir(dict(ASOS, qayerdan="x")) is None)
check("lug'at emas - rad", A.tekshir("salom") is None)
check("matn chegarasi", len(A.tekshir(dict(ASOS, qayerdan_kim="a" * 900))["qayerdan_kim"]) == A.MATN_MAX)
check("sovg'a: mazmunli javob", A.sovga_mi(toza))
check("sovg'a: matn juda qisqa - yo'q", not A.sovga_mi(dict(ASOS, qayerdan_kim="aa")))
check("sovg'a: belgilar harf emas - yo'q", not A.sovga_mi(dict(ASOS, qayerdan_kim="...!!")))
check("sovg'a: «aytdim» deb, nima deganini yozmasa - yo'q", not A.sovga_mi(dict(ASOS, aytdimi="ha")))
check("sovg'a: matnsiz oddiy javob - bor", A.sovga_mi(ASOS))

g0 = gal(1)
check("birinchi javob yoziladi, 20 galleon", A._yoz(1, toza, "uz") == (True, A.SOVGA) and gal(1) == g0 + A.SOVGA)
check("ikkinchi javob yozilmaydi, galleon yo'q", A._yoz(1, dict(ASOS, qayerdan="tiktok"), "uz") == (False, 0) and gal(1) == g0 + A.SOVGA)
check("javob berilgan", A._bormi(1) and not A._bormi(2))
g2 = gal(2)
check("qisqa yozma javob: yoziladi, galleon yo'q", A._yoz(2, dict(ASOS, oxirgi=["chat", "film"], qayerdan_kim="x"), "ru") == (True, 0) and gal(2) == g2)
A._yoz(42, dict(ASOS, qayerdan="tg_qidiruv"), "uz")
p = A.panel((42,))
check("panel: admin sanalmaydi", p["n"] == 2 and p["son"]["qayerdan"]["tg_qidiruv"] == 0)
check("panel: sanoq", p["son"]["qayerdan"]["dost"] == 2 and p["son"]["oldin"]["tv"] == 2 and p["son"]["oxirgi"]["film"] == 2)
check("panel: saralangan va sovg'a olgan soni", p["saralangan"] == 1 and p["sovga_olgan"] == 1)
check("panel: yozma javob, odam idsiz", {"k": "aytdi_matn", "t": "Hamma film o'zbekchada bor", "til": "uz", "vaqt": p["matn"][-1]["vaqt"],
                                         "qayerdan": "dost", "yosh": None, "sar": 1} in p["matn"] and all("uid" not in m for m in p["matn"]))

check("instagram endi yo'q variant", A.tekshir(dict(ASOS, qayerdan="instagram")) is None)
g1 = gal(1)
check("admin sinovi: javob o'chadi, sovg'a qaytariladi", A.qaytadan(1) and not A._bormi(1) and gal(1) == g1 - A.SOVGA)
check("admin sinovi: javobsiz - hech narsa", A.qaytadan(1) is False)
check("qaytadan javob berish mumkin", A._yoz(1, ASOS, "uz") == (True, A.SOVGA))

# --- g'oyalar
check("qisqa nom rad", G.yangi(2, "ab", "", "filmlar", "uz") == (False, "nom"))
check("yangi g'oya", G.yangi(2, "Serial uchun alohida bo'lim", "batafsil", "noma'lum", "ru") == (True, None))
m = G.meniki(2)
check("o'z ro'yxati", len(m) == 1 and m[0]["holat"] == "yangi" and m[0]["bolim"] == "boshqa")
for i in range(G.KUNIGA - 1):
    G.yangi(2, "G'oya %d" % i, "", "xogvarts", "ru")
check("kunlik chegara", G.yangi(2, "Yana bitta", "", "filmlar", "ru") == (False, "kop"))
check("boshqa odamga chegara yo'q", G.yangi(1, "Mening g'oyam", "", "filmlar", "uz")[0])

gid = m[0]["id"]
r = G.ozgartir(gid, holat="qabul")
check("holat o'zgardi - xat kerak", r and r["xat"] and r["holat"] == "qabul" and r["uid"] == 2)
r = G.ozgartir(gid, holat="qabul")
check("o'sha holat - xat yo'q", r and not r["xat"])
r = G.ozgartir(gid, javob="Rahmat, dekabrda qo'shamiz")
check("javob yozildi - xat kerak", r["xat"] and G.meniki(2)[-1]["javob"] == "Rahmat, dekabrda qo'shamiz")
check("noto'g'ri holat rad", G.ozgartir(gid, holat="zo'r") is None)
check("yo'q g'oya", G.ozgartir(99999, holat="rad") is None)
x = G.xat_matni("Serial", "qabul", "Rahmat")
check("xat uch tilda, javob bilan", set(x) == {"uz", "ru", "en"} and "qabul qilindi" in x["uz"][1] and "Rahmat" in x["ru"][1])
rows = G.panel_royxat((42,))
check("panel ro'yxati: ism va fakultet", len(rows) == G.KUNIGA + 1 and rows[-1]["ism"] == "U2" and rows[0]["uid"] == 1)

print("So'rovnoma va g'oyalar: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
sys.exit(1 if fail else 0)
