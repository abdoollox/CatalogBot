# -*- coding: utf-8 -*-
"""Kundalik Xabarnoma: kechagi natijalardan tuziladi, kun ichida o'zgarmaydi, eski turnir g'olibi yozilmaydi.

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
TMP = tempfile.mkdtemp(prefix="hp-gazeta-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars, hpgazeta as G, hpmjang   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


asyncio.run(hpcup.init())
hpdars._init()
hpmjang._init()
G._init()
KECHA, KUN = "2026-10-31", "2026-11-01"          # shanba, yakshanba
hpdars.yakunla = lambda kun: None
c = hpcup._connect()
for u, ism, h in [(1, "Farangiz Aliyeva", "slytherin"), (2, "Bekzod", "slytherin"), (3, "Dilnoza", "hufflepuff"), (4, "Ali", "gryffindor")]:
    c.execute("INSERT OR REPLACE INTO users (user_id, first_name, house, created_at, sorted_at) VALUES (?,?,?,?,?)",
              (u, ism, h, "2026-10-01T00:00:00Z", "2026-10-31T10:00:00Z" if u == 4 else "2026-10-01T00:00:00Z"))
c.execute("INSERT OR REPLACE INTO seasons (id, starts_at, ends_at, status) VALUES (11, '2026-10-25T19:00:00Z', '2026-11-01T18:59:00Z', 'active')")
for u, ref, p in [(1, "m:afsun:" + KECHA, 15), (2, "m:afsun:" + KECHA, 10), (1, "m:tarix:" + KECHA, 15), (3, "m:trans:" + KECHA, 15),
                  (1, "m:uchish:2026-10-30", 15), (2, "r:afsun:" + KECHA, 5)]:
    c.execute("INSERT INTO points (user_id, season_id, source_type, source_ref, points, created_at) VALUES (?,11,'dars',?,?,?)", (u, ref, p, "2026-10-31T10:00:00Z"))
c.commit()
c.close()

m = G._son(KUN)
check("son raqami", m["no"] == 1 and m["yesterday"] == KECHA)
check("faqat kechagi birinchi o'rinlar", sorted(b["fan"] for b in m["bell"]) == ["afsun", "tarix", "trans"])
check("ism qisqa", [b["name"] for b in m["bell"] if b["fan"] == "afsun"] == ["Farangiz"])
check("kunning sehrgari", m["star"]["uid"] == 1 and m["star"]["n"] == 2)
check("kubok tartibi", m["cup"]["houses"][0] == {"h": "slytherin", "p": 45 + 5 + 10} and not m["cup"]["closed"])
check("yakshanba: hafta bugun yopiladi", m["cup"]["ends_today"] and m["cup"]["winner"] is None)
check("yangi kelganlar", m["new"] == 1)
check("bugungi turnir: duel", m["today"] == {"kind": "duel", "at": "22:00"})
check("turnir o'tmagan bo'lsa bo'sh", m["tour"] is None)

c = hpcup._connect()
c.execute("UPDATE points SET points=99 WHERE source_ref=?", ("m:trans:" + KECHA,))
c.commit()
c.close()
check("kun ichida son o'zgarmaydi", G._son(KUN) == m)

d = G._son("2026-11-02")                           # dushanba: yakshanbadagi hafta yopilgan
check("dushanba: yopilgan hafta va g'olib", d["cup"]["closed"] and d["cup"]["winner"] == "hufflepuff" and d["no"] == 2)
check("dushanba: poyga", d["today"]["kind"] == "poyga")
p = G._son("2026-10-30")                           # payshanbadan keyingi juma: viktorina, kecha turnir yo'q
check("payshanba turnirsiz", p["tour"] is None and p["today"]["kind"] == "vik")

c = hpcup._connect()
for ref, p in [("duel:2026-10-26:2", 30), ("poyga:2026-10-26", 20), ("dars:2026-10-07", 5)]:
    c.execute("INSERT INTO points (user_id, season_id, source_type, source_ref, points, created_at) VALUES (1,11,'dars',?,?,?)", (ref, p, "2026-10-31T10:00:00Z"))
c.commit()
b = hpcup._by_source(c, 11, "p.user_id", "p.user_id = ?", (1,))[1]
c.close()
check("kubok manbalari: bellashuv, turnir, eski dars alohida", b["bell"] == 45 and b["tur"] == 50 and b["lesson"] == 5 and b["rek"] == 0)
c = hpcup._connect()
b = hpcup._by_source(c, 11, "p.user_id", "p.user_id = ?", (2,))[2]
c.close()
check("kubok manbalari: rekord alohida", b["rek"] == 5 and b["bell"] == 10)

print("Gazeta: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
sys.exit(1 if fail else 0)
