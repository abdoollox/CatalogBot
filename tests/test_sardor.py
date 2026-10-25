"""Hafta sardori (egasi, 2026-10-25): har fakultetda yopilgan haftaning eng ko'p ball to'plagan o'quvchisi - keyingi hafta sardori.

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
TMP = tempfile.mkdtemp(prefix="hp-sardor-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "7"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hppochta, hpnishon   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


def bir(sql, args=()):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        return c.execute(sql, args).fetchone()
    finally:
        c.close()


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    hpcup.SARDOR_DAN = "2000-01-01"           # sinovda hafta bugungi sana bilan yopiladi
    odam = ((1, "gryffindor", "Garri Potter", 5), (2, "gryffindor", "Ron", 3), (3, "slytherin", "Draco", 4),
            (4, "slytherin", "Pansy", 4), (5, "ravenclaw", "Luna", 2), (7, "ravenclaw", "Admin", 30))
    for uid, uy, nom, _n in odam:
        await hpcup.touch_user(uid, nom)
        await hpcup.set_house(uid, uy)
    hpcup.direktor_qil(7)
    check("hafta yopilmaguncha sardor yo'q", hpcup._sardorlar(hpcup._connect()) == {})
    season = await hpcup.current_season()
    for uid, uy, nom, n in odam:
        for i in range(n):
            await hpcup.award(uid, "daily", "k%d" % i, 10)
    await hpcup.close_season(season["id"])
    c = hpcup._connect()
    try:
        s = hpcup._sardorlar(c)
    finally:
        c.close()
    check("har fakultetda eng ko'p ball to'plagan", s.get("gryffindor", {}).get("uid") == 1 and s.get("ravenclaw", {}).get("uid") == 5)
    check("teng ballda - oldinroq to'plagan", s.get("slytherin", {}).get("uid") == 3)
    check("ball to'plagan odami yo'q fakultetda sardor yo'q, direktor sardor emas", "hufflepuff" not in s and all(x["uid"] != 7 for x in s.values()))
    check("ism qisqa (birinchi so'z), ball bilan", s["gryffindor"]["name"] == "Garri" and s["gryffindor"]["ball"] == 50)
    hpcup._sardor_kesh["t"] = 0
    check("sardormi", hpcup.sardormi(1) and hpcup.sardormi(3) and not hpcup.sardormi(2) and not hpcup.sardormi(7))
    # keyingi haftada ball o'zgarsa ham shu hafta sardori o'zgarmaydi
    await hpcup.award(2, "daily", "x", 10)
    c = hpcup._connect()
    try:
        check("yozilgan sardor o'zgarmaydi", hpcup._sardorlar(c)["gryffindor"]["uid"] == 1)
        check("jadvalda 3 ta yozuv", c.execute("SELECT COUNT(*) FROM sardor").fetchone()[0] == 3)
    finally:
        c.close()
    # chat xabarida belgi
    m = await hpcup.post_chat_message("gryffindor", 1, "Salom")
    m2 = await hpcup.post_chat_message("gryffindor", 2, "Salom")
    check("chat xabarida sardor belgisi", m.get("sardor") is True and not m2.get("sardor"))
    a = await hpcup.chat_members(None, season["id"] + 1, 1)
    check("a'zolar ro'yxatida belgi", any(x["uid"] == 1 and x["sardor"] for x in a) and any(x["uid"] == 2 and not x["sardor"] for x in a))
    # nishon
    hpnishon._cfg.update({"admin_ids": {7}})
    hpnishon._init()
    d = hpnishon._royxat(1)
    check("«Sardor» nishoni", any(x["code"] == "sardor" and x["got"] for x in d["list"]))
    check("sardor bo'lmaganda nishon yo'q", any(x["code"] == "sardor" and not x["got"] for x in hpnishon._royxat(2)["list"]))
    # kubok xati
    hppochta._cfg.update({"admin_ids": {7}})
    hppochta._kubok_yoz(season["id"])
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        x1 = json.loads(c.execute("SELECT matn FROM pochta WHERE user_id=1 AND tur='kubok'").fetchone()[0])
        x2 = json.loads(c.execute("SELECT matn FROM pochta WHERE user_id=2 AND tur='kubok'").fetchone()[0])
    finally:
        c.close()
    check("kubok xatida: o'zi sardor", x1.get("sar_men") == 1 and "hafta sardorisiz" in hppochta.kubok_matni("uz", x1)[1])
    check("kubok xatida: fakultet sardori", x2.get("sar") == "Garri" and not x2.get("sar_men") and "Garri" in hppochta.kubok_matni("uz", x2)[1])

    hpcup.SARDOR_DAN = "2999-01-01"
    c = hpcup._connect()
    try:
        c.execute("DELETE FROM sardor")
        check("SARDOR_DAN dan oldingi haftaga sardor yo'q", hpcup._sardorlar(c) == {})
    finally:
        c.close()
    print("=" * 40)
    print("Sardor: %d ta o'tdi, %d ta xato" % (ok, fail))
    return fail


sys.exit(1 if asyncio.run(amain()) else 0)
