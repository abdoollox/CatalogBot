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

# --- so'rovnoma
toza = A.tekshir({"qayerdan": "dost", "nega": ["bepul", "yolgon", "ozbekcha"], "yoqadi": ["filmlar"], "tavsiya": "  zo'r  ", "yosh": "99"})
check("noto'g'ri variant tashlanadi, tartib ro'yxatdagidek", toza == {"qayerdan": "dost", "nega": ["ozbekcha", "bepul"], "yoqadi": ["filmlar"], "tavsiya": "zo'r"})
check("majburiy savolsiz rad", A.tekshir({"qayerdan": "dost", "nega": ["bepul"]}) is None)
check("noto'g'ri bitta tanlov rad", A.tekshir({"qayerdan": "x", "nega": ["bepul"], "yoqadi": ["chat"]}) is None)
check("lug'at emas - rad", A.tekshir("salom") is None)
check("matn chegarasi", len(A.tekshir({"qayerdan": "dost", "nega": ["bepul"], "yoqadi": ["chat"], "tavsiya": "a" * 900})["tavsiya"]) == A.MATN_MAX)

check("birinchi javob yoziladi", A._yoz(1, toza, "uz") is True)
check("ikkinchi javob yozilmaydi", A._yoz(1, {"qayerdan": "tiktok", "nega": ["bepul"], "yoqadi": ["chat"]}, "uz") is False)
check("javob berilgan", A._bormi(1) and not A._bormi(2))
A._yoz(2, {"qayerdan": "dost", "nega": ["bepul"], "yoqadi": ["chat", "filmlar"]}, "ru")
A._yoz(42, {"qayerdan": "youtube", "nega": ["bepul"], "yoqadi": ["chat"]}, "uz")
p = A.panel((42,))
check("panel: admin sanalmaydi", p["n"] == 2 and p["son"]["qayerdan"]["youtube"] == 0)
check("panel: sanoq", p["son"]["qayerdan"]["dost"] == 2 and p["son"]["nega"]["bepul"] == 2 and p["son"]["yoqadi"]["filmlar"] == 2)
check("panel: saralangan soni", p["saralangan"] == 1)
check("panel: yozma javob, odam idsiz", p["matn"] == [{"k": "tavsiya", "t": "zo'r", "til": "uz", "vaqt": p["matn"][0]["vaqt"], "qayerdan": "dost"}])

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
