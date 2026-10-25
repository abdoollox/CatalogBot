# -*- coding: utf-8 -*-
"""Chat: yangi o'yin taklifi tashlanganda shu odamning shu xonadagi qabul qilinmay qolgan eski kartalari o'chadi.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-chattaklif-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hptosh   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


def ochirilgan(mid):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        return c.execute("SELECT deleted FROM chat_messages WHERE id=?", (mid,)).fetchone()[0] == 1
    finally:
        c.close()


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    hptosh._init() if hasattr(hptosh, "_init") else None
    for uid, nom in ((1, "Garri"), (2, "Ron"), (3, "Germiona")):
        await hpcup.touch_user(uid, nom)
        await hpcup.set_house(uid, "gryffindor")
    T = "🔮 Toshchalar o'yiniga chaqiraman!"
    # 1) Garri taklif tashlaydi, hech kim qabul qilmaydi
    t1 = hptosh._dost(1)
    m1 = await hpcup.post_chat_message("global", 1, T, None, tosh=t1)
    # 2) yana taklif - birinchisi o'zi bekor bo'ladi; karta o'chishi kerak
    t2 = hptosh._dost(1)
    m2 = await hpcup.post_chat_message("global", 1, T, None, tosh=t2)
    n = await hpcup.eski_takliflarni_ochir("global", 1, m2["id"])
    check("qabul qilinmagan eski karta o'chdi", n == 1 and ochirilgan(m1["id"]) and not ochirilgan(m2["id"]))
    # 3) Ron ikkinchisini qabul qiladi - o'ynalgan o'yin kartasi keyingi taklifda o'chmaydi
    gid, xato = hptosh._qabul(2, t2)
    check("qabul qilindi", gid == t2 and not xato)
    t3 = hptosh._dost(1)
    m3 = await hpcup.post_chat_message("global", 1, T, None, tosh=t3)
    await hpcup.eski_takliflarni_ochir("global", 1, m3["id"])
    check("qabul qilingan o'yin kartasi qoladi", not ochirilgan(m2["id"]) and not ochirilgan(m3["id"]))
    # 4) boshqa odamning va boshqa xonaning kartasiga tegilmaydi
    t4 = hptosh._dost(3)
    m4 = await hpcup.post_chat_message("global", 3, T, None, tosh=t4)
    t5 = hptosh._dost(1)
    m5 = await hpcup.post_chat_message("gryffindor", 1, T, None, tosh=t5)
    await hpcup.eski_takliflarni_ochir("gryffindor", 1, m5["id"])
    check("boshqa odamning kartasi qoladi", not ochirilgan(m4["id"]))
    check("boshqa xonadagi eski karta qoladi (o'z xonasidagi kutayotgan taklif ham)", not ochirilgan(m3["id"]))
    # 5) oddiy xabar o'chmaydi
    m6 = await hpcup.post_chat_message("global", 1, "Salom!", None)
    t7 = hptosh._dost(1)
    m7 = await hpcup.post_chat_message("global", 1, T, None, tosh=t7)
    await hpcup.eski_takliflarni_ochir("global", 1, m7["id"])
    check("oddiy xabar o'chmaydi; muddati o'tgan taklif o'chadi", not ochirilgan(m6["id"]) and ochirilgan(m3["id"]))
    print("Chat takliflari: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
