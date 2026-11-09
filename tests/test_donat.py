# -*- coding: utf-8 -*-
"""Donat (hpdonat): havola, homiy nishoni (yashirin), panel, rahmat xati.

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
TMP = tempfile.mkdtemp(prefix="hp-donat-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["HP_DONAT_PATH"] = os.path.join(TMP, "donat.json")
os.environ["BOT_TOKEN"] = "123456:TEST-token"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpnishon, hpdonat as D   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


asyncio.run(hpcup.init())
hpnishon._init()
c = hpcup._connect()
c.execute("INSERT INTO users (user_id, first_name, username, house, created_at) VALUES (7, 'Malika', 'Malika_HP', 'gryffindor', '2026-11-01')")
c.execute("INSERT INTO users (user_id, first_name, created_at) VALUES (8, 'Jasur', '2026-11-01')")
c.commit(); c.close()

check("havola yo'q", D.havola() is None)
check("noto'g'ri havola rad", not D._togri("http://taps.uz/x") and not D._togri("javascript:alert(1)") and not D._togri("https://"))
check("to'g'ri havola", D._togri("https://taps.uz/garripotter"))
D._saqla("https://taps.uz/garripotter")
check("havola saqlandi", D.havola() == "https://taps.uz/garripotter")
check("havola fayli", json.load(open(os.environ["HP_DONAT_PATH"]))["havola"] == "https://taps.uz/garripotter")
check("hozircha faqat adminga", D.havola_kimga(False) is None and D.havola_kimga(True) == "https://taps.uz/garripotter")
D.HAMMAGA = True
check("hammaga ochilsa - hammaga", D.havola_kimga(False) == "https://taps.uz/garripotter")
D.HAMMAGA = False
D._saqla(None)
check("havola o'chirildi", D.havola() is None)

check("username bilan topish (@, katta-kichik)", D.top("@malika_hp") == (7, "Malika", "Malika_HP"))
check("id bilan topish", D.top("8")[0] == 8)
check("yo'q odam", D.top("@nobody_here") is None and D.top("<script>") is None)

kodlar = lambda uid: [x["code"] for x in hpnishon._royxat(uid)["list"]]
check("homiy nishoni olinmagan bo'lib ko'rinadi", any(b["code"] == "homiy" and not b["got"] for b in hpnishon._royxat(7)["list"]))
tot0 = hpnishon._royxat(7)["total"]
check("yangi homiy", D.ber(7, "taps 50 000") is True)
check("takror berilmaydi", D.ber(7) is False)
r = hpnishon._royxat(7)
check("homiy nishoni olindi", any(x["code"] == "homiy" and x["got"] for x in r["list"]) and "homiy" in r["new"])
check("jami o'zgarmadi", r["total"] == tot0)
rw = D.royxat()
check("ro'yxatda", len(rw) == 1 and rw[0]["username"] == "Malika_HP" and rw[0]["izoh"] == "taps 50 000")
check("olib tashlash", D.olib_tashla(7) and D.royxat() == [] and not any(b["code"] == "homiy" and b["got"] for b in hpnishon._royxat(7)["list"]))

# panel: token, berish va rahmat xati
xatlar = []
async def xat(uid, matnlar, botga):
    xatlar.append((uid, matnlar["uz"][0], botga))
D._cfg.update({"cors": lambda r: r, "dash_ok": lambda req: req.headers.get("X-Dash-Token") == "t", "xat": xat})
class Req:
    def __init__(self, body, tok="t"):
        self.method = "POST"; self.headers = {"X-Dash-Token": tok}; self._b = body
    async def json(self): return self._b
def panel(body, tok="t"):
    r = asyncio.run(D.api_panel(Req(body, tok)))
    return r.status, json.loads(r.body)
st, j = panel({}, "yomon")
check("token yo'q - 403", st == 403)
st, j = panel({"kim": "@Malika_HP", "izoh": "1-donat"})
check("paneldan berildi", j["ok"] and j["yangi"] and j["berildi"]["uid"] == 7 and len(j["rows"]) == 1)
check("rahmat xati ketdi", xatlar == [(7, "Dambldordan rahmat", True)])
st, j = panel({"kim": "@Malika_HP"})
check("ikkinchi marta xat ketmaydi", j["yangi"] is False and len(xatlar) == 1)
st, j = panel({"kim": "@yoq_odam"})
check("topilmadi", j["ok"] is False and j["error"] == "topilmadi")

print("=" * 40)
print("hpdonat: %d ta to'g'ri, %d ta xato" % (ok, fail))
sys.exit(1 if fail else 0)
