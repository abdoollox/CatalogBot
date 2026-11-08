# -*- coding: utf-8 -*-
"""Qo'llanma videolar ketma-ketligi (hpqollanma): kim, qachon, qaysi video.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-qollanma-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["HP_QOLLANMA_BOSH"] = "2026-11-08 12:00:00"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpevents, hppochta, hpgoya, hpqollanma as Q   # noqa: E402

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
hppochta._ulan().close()
hpgoya._init()

def yoz(uid, payload, t):
    hpevents._log(uid, "N", None, payload, t.strftime("%Y-%m-%d %H:%M:%S"))

def lang(uid, l):
    c = hpcup._connect(); c.execute("INSERT OR REPLACE INTO users (user_id, lang, created_at) VALUES (?,?,?)", (uid, l, "2026-11-08T00:00:00Z")); c.commit(); c.close()

F = datetime(2026, 11, 8, 13, 0)          # birinchi film (UTC)
for u in (1, 2, 3, 4, 5, 6):
    lang(u, "uz"); yoz(u, "start", F - timedelta(minutes=5)); yoz(u, "hp1_uz", F)
lang(3, "ru")                              # rus tilida ham oladi (egasi)
yoz(4, "hp2_uz", datetime(2026, 11, 1))    # eski odam (BOSH dan oldin film)
yoz(5, "blocked", F + timedelta(hours=2))  # bloklagan
c = hpcup._connect(); c.execute("INSERT INTO onb_qadam (user_id, qadam, vaqt) VALUES (6,'letter','x')"); c.commit(); c.close()

N = lambda t: {u: v[0] for u, v in Q.nomzodlar(t)}
check("1 kun o'tmagan - hech kim", N(F + timedelta(hours=20)) == {})
n = N(F + timedelta(hours=25))
check("1 kundan keyin: 1, 2, 3 va 6", set(n) == {1, 2, 3, 6})
check("xat videosi birinchi", n.get(1) == "x")
check("xatni ochgan - xat videosi o'tkazib yuboriladi", n.get(6) == "tw")
check("rus tilidagi ham oladi", n.get(3) == "x")
check("eski odam olmaydi", 4 not in n)
check("bloklagan olmaydi", 5 not in n)

T1 = F + timedelta(hours=25)
Q._belgila(1, "x", "yuborildi", T1)
check("kuniga bittadan", 1 not in N(T1 + timedelta(hours=10)))
check("ertasiga keyingisi", N(T1 + timedelta(hours=25)).get(1) == "tw")
c = hpcup._connect(); c.execute("UPDATE users SET house='gryffindor' WHERE user_id=1"); c.execute("INSERT INTO onb_qadam (user_id, qadam, vaqt) VALUES (1,'wand','x')"); c.commit(); c.close()
check("tayoqcha va fakultet bor - pleyer videosi", N(T1 + timedelta(hours=25)).get(1) == "p")
Q._belgila(1, "p", "bloklagan", T1 + timedelta(hours=25))
check("yuborishda bloklagan bo'lsa to'xtaydi", 1 not in N(T1 + timedelta(days=3)))

# yana start bossa (blokdan chiqqan) - davom etadi; bot xabarini o'chirgan - olmaydi
yoz(5, "start", F + timedelta(hours=3))
check("blokdan chiqqan yana oladi", N(T1).get(5) == "x")
hppochta._sozla(5, False)
check("bot xabarlarini o'chirgan olmaydi", 5 not in N(T1))

# hammasi tugasa - boshqa video yo'q
for v in Q.KETMA:
    Q._belgila(2, v[0], "yuborildi", F)
check("ketma-ketlik tugagan", 2 not in N(T1 + timedelta(days=30)))

# rejim: "admin" bo'lsa aylana hech kimga yubormaydi
class Bot:
    n = 0
    async def copy_message(self, **k): Bot.n += 1
Q.YOQIQ = "admin"
check("admin rejimida avtomatik yuborilmaydi", asyncio.run(Q.aylana(Bot())) == 0 and Bot.n == 0)
check("holat matni", "Olganlar" in Q.holat())

print("=" * 40)
print("hpqollanma: %d ta to'g'ri, %d ta xato" % (ok, fail))
sys.exit(1 if fail else 0)
