# -*- coding: utf-8 -*-
"""G'oyalar AI tahlili (hpgoyaai): javobni tekshirish, saqlash, qoralama saqlanishi, panel manzili.
Gemini chaqirilmaydi - o'rniga soxta javob.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-goyaai-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["HP_AI_PATH"] = os.path.join(TMP, "ai.json")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpgoya, hphisobot, hpgoyaai as AI   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


asyncio.run(hpcup.init())
hpgoya._init()
AI._init()
conn = hpcup._connect()
for i, (nom, til, holat, javob) in enumerate([("Kitoblarni ovozli qiling", "uz", "yangi", ""), ("Audio kitoblar", "uz", "yangi", ""),
                                              ("Shaxmatda vaqt ko'proq", "ru", "yangi", ""), ("Fon rasmlari", "uz", "qabul", "Rahmat")], 1):
    conn.execute("INSERT INTO goya (user_id, nom, til, holat, javob, vaqt) VALUES (?,?,?,?,?,?)", (100 + i, nom, til, holat, javob, "2026-11-0%dT10:00:00Z" % i))
conn.commit(); conn.close()

goy = AI._goyalar()
check("4 g'oya o'qildi", len(goy) == 4)

# Tekshiruv: noma'lum mavzu -> Boshqa; noto'g'ri asosiy (o'zi, kattaroq id, yo'q id) -> null; zanjir
xom = {"mavzular": [{"nom": "Audio kitoblar"}, {"nom": "O'yinlar"}],
       "goyalar": [{"id": 1, "mavzu": "Audio kitoblar", "asosiy": None, "qoralama": "Rahmat, ko'rib chiqamiz."},
                   {"id": 2, "mavzu": "Audio kitoblar", "asosiy": 1, "qoralama": "Q2"},
                   {"id": 3, "mavzu": "Nomalum", "asosiy": 3, "qoralama": "Спасибо"},
                   {"id": 4, "mavzu": "O'yinlar", "asosiy": 99, "qoralama": None},
                   {"id": 77, "mavzu": "O'yinlar"}]}
mz, ch = AI.tozala(xom, goy)
check("noma'lum mavzu Boshqa", ch[3]["mavzu"] == "Boshqa" and "Boshqa" in [m["nom"] for m in mz])
check("takror bog'landi", ch[2]["asosiy"] == 1)
check("o'ziga bog'lanmaydi", ch[3]["asosiy"] is None)
check("yo'q id ga bog'lanmaydi", ch[4]["asosiy"] is None)
check("begona id tashlandi", 77 not in ch)

# To'liq tahlil soxta Gemini bilan
async def soxta(matn):
    soxta.kirish = json.loads(matn.split("G'oyalar (JSON):\n", 1)[1])
    return xom
AI._gemini = soxta
check("tahlil o'tdi", asyncio.run(AI.tahlil()))
kir = {g["id"]: g for g in soxta.kirish}
check("AI ga ism/id yuborilmaydi", all(set(g) == {"id", "nom", "batafsil", "til", "holat", "qoralama_kerak"} for g in soxta.kirish))
check("javobli g'oyaga qoralama so'ralmaydi", kir[4]["qoralama_kerak"] is False and kir[1]["qoralama_kerak"] is True)
n = AI.natija()
check("natija saqlandi", n["goyalar"]["2"]["asosiy"] == 1 and n["goyalar"]["1"]["qoralama"].startswith("Rahmat") and n["vaqt"])
check("mavzular saqlandi", [m["nom"] for m in n["mavzular"]][:2] == ["Audio kitoblar", "O'yinlar"])

# Ikkinchi tahlil: qoralamasi bor g'oyaga qayta so'ralmaydi, eski qoralama yo'qolmaydi
xom["goyalar"][0]["qoralama"] = None
asyncio.run(AI.tahlil())
kir = {g["id"]: g for g in soxta.kirish}
check("qoralamasi borga qayta so'ralmaydi", kir[1]["qoralama_kerak"] is False)
check("eski qoralama saqlanib qoldi", AI.natija()["goyalar"]["1"]["qoralama"].startswith("Rahmat"))
check("tahlil qilinmagan g'oya yo'q", AI._yangi_bormi() is False)

# Panel manzili
class Req:
    def __init__(self, body, tok="t"):
        self.method = "POST"; self._b = body; self.headers = {"X-Dash-Token": tok}
    async def json(self): return self._b
AI._cfg.update({"cors": lambda r: r, "dash_ok": lambda r: r.headers.get("X-Dash-Token") == "t"})
r = asyncio.run(AI.api(Req({}, "yomon")))
check("kalitsiz panel 403", r.status == 403)
r = asyncio.run(AI.api(Req({})))
d = json.loads(r.body)
check("panel natijani oladi, AI kaliti yo'q", d["ok"] and d["kalit"] is False and d["goyalar"]["2"]["asosiy"] == 1)

print("O'tdi: %d, xato: %d" % (ok, fail))
sys.exit(1 if fail else 0)
