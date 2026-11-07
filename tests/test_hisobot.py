# -*- coding: utf-8 -*-
"""Kunlik hisobot (hphisobot): kecha vs oldingi 7 kun, kanal takrorlari, matn, AI kaliti.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import os
import sys
import tempfile
import types
from datetime import date, datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-hisobot-")
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

import hpcup, hpevents, hpgoya, hphisobot as H   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


asyncio.run(hpcup.init())
hpevents._init("/yoq.json")
hpgoya._init()
BUGUN = date(2026, 11, 7)

def yoz(uid, payload, kun, soat=12):
    # Toshkent soat 12 -> UTC 07:00
    t = datetime.combine(kun, datetime.min.time()) + timedelta(hours=soat - 5)
    hpevents._log(uid, "N", None, payload, t.strftime("%Y-%m-%d %H:%M:%S"))

# Oldingi 7 kun: har kuni 2 tadan kanalga qo'shilish va 2 ta chiqish, 20 ta film
uid = 1000
for i in range(2, 9):
    kun = BUGUN - timedelta(days=i)
    for j in range(2):
        uid += 1; yoz(uid, "subscribed", kun); yoz(uid, "left", kun, 13)
    for j in range(20):
        yoz(5, "hp1_uz" if j % 2 else "web_hp1_uz@hd", kun)
    yoz(5, "pleyer_hp1_uz@hd", kun)           # pleyer sanalmaydi
# Kecha: 15 kishi chiqdi (+ takroriy «left» yozuvlari sanalmasin), filmlar 4 ta
kecha = BUGUN - timedelta(days=1)
for j in range(15):
    uid += 1; yoz(uid, "subscribed", kecha, 9); yoz(uid, "left", kecha, 10); yoz(uid, "left", kecha, 11)
for j in range(4):
    yoz(5, "web_hp1_uz@hd", kecha)

h = H.hisob(BUGUN)
N = {m["k"]: m for m in h["natija"]}
check("kecha sanasi", h["kecha"] == kecha)
check("chiqqanlar 15 (takror sanalmadi)", N["kchiq"]["y"] == 15)
check("chiqqanlar odatda 2", abs(N["kchiq"]["mu"] - 2) < 1e-9)
check("chiqqanlar belgilandi, yomon", N["kchiq"]["belgi"] and not N["kchiq"]["yaxshi"])
check("filmlar 4, odatda 20, belgilandi, yomon", N["film"]["y"] == 4 and N["film"]["mu"] == 20 and N["film"]["belgi"] and not N["film"]["yaxshi"])
check("qo'shilganlar ko'paydi - yaxshi", N["kqosh"]["belgi"] and N["kqosh"]["yaxshi"])
check("bloklaganlar o'zgarmadi", not N["blok"]["belgi"])
t = H.matn(h)
check("matnda sarlavha", "Kuzatuv: kecha, 6-noyabr" in t)
check("matnda chiqqanlar qizil", "🔴 Kanaldan chiqqanlar: <b>15</b>" in t)
check("matnda foiz", "+650%" in t)
check("g'oya yo'q - qator yo'q", "g'oyalar" not in t)

# G'oya kutayotgan bo'lsa qator chiqadi
conn = hpcup._connect()
conn.execute("INSERT INTO goya (user_id, nom, holat, vaqt) VALUES (7, 'X', 'yangi', ?)", ((datetime.utcnow() - timedelta(days=3)).strftime("%Y-%m-%dT%H:%M:%SZ"),))
conn.commit(); conn.close()
t = H.matn(H.hisob(BUGUN))
check("g'oya qatori va eskiligi", "Javob kutayotgan g'oyalar: <b>1</b> (eng eskisi 3 kunlik)" in t)

# AI izohi: matn oxirida, HTML belgilar xavfsiz; kalit yo'q bo'lsa izoh so'ralmaydi
t3 = H.matn(H.hisob(BUGUN), "• Kanaldan chiqish <ko'paydi> & tekshiring")
check("AI izohi qo'shildi va xavfsiz", "AI izohi" in t3 and "&lt;ko'paydi&gt; &amp; tekshiring" in t3)
check("kalitsiz AI izohi yo'q", asyncio.run(H.ai_izoh(H.hisob(BUGUN))) is None)
check("kechagi ommaviy xabarlar maydoni bor", isinstance(H.hisob(BUGUN)["xabarlar"], list))

# Bo'sh kun: hammasi odatdagidek
t2 = H.matn(H.hisob(date(2026, 12, 20)))
check("o'zgarish yo'q bo'lsa xabar", "hammasi odatdagidek" in t2)

# AI kaliti
check("kalit hali yo'q", H.ai_kalit() is None)
H._ai_saqla("AIzaTEST0123456789abcdefghijklmnopq")
check("kalit saqlandi va o'qiladi", H.ai_kalit() == "AIzaTEST0123456789abcdefghijklmnopq")

# Kunlik belgi
check("hali yuborilmagan", H._oxirgi() is None)
H._belgila("2026-11-07")
check("belgi yozildi", H._oxirgi() == "2026-11-07")

print("O'tdi: %d, xato: %d" % (ok, fail))
sys.exit(1 if fail else 0)
