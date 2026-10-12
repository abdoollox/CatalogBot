"""Testni qayta topshirish (2026-10-12): 19-sentabrgacha saralanganlarga bir marta, muddat ichida.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
import types
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-qayta-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hppochta   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


def sql(q, a=()):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    # 1 - eski (avgust, bo'sh joyli yozuv), 2 - eski (ISO), 3 - 19-sentabrdan keyin, 4 - saralanmagan, -5 - sinov
    for uid, uy in ((1, "hufflepuff"), (2, "gryffindor"), (3, "slytherin"), (-5, "hufflepuff")):
        await hpcup.touch_user(uid, "Sehrgar %d" % uid)
        await hpcup.set_house(uid, uy)
    await hpcup.touch_user(4, "Sehrgar 4")
    sql("UPDATE users SET sorted_at='2026-08-16 13:36:20' WHERE user_id IN (1, -5)")
    sql("UPDATE users SET sorted_at='2026-09-19T14:16:28Z' WHERE user_id=2")
    sql("UPDATE users SET sorted_at='2026-09-19T14:16:29Z' WHERE user_id=3")

    check("eski (bo'sh joyli sana) - mumkin", hpcup.qayta_mumkin(1))
    check("eski (chegaradan 1 s oldin) - mumkin", hpcup.qayta_mumkin(2))
    check("19-sentabrdan keyin - mumkin emas", not hpcup.qayta_mumkin(3))
    check("saralanmagan - qayta test emas", not hpcup.qayta_mumkin(4))
    check("sinov o'quvchisi - yo'q", not hpcup.qayta_mumkin(-5))
    a, u = await hpcup.can_resort(1)
    check("can_resort eskiga ochiq, muddati bilan", a and u == hpcup.QAYTA_GACHA)
    a3, _ = await hpcup.can_resort(3)
    check("can_resort yangiga yopiq", not a3)
    kech = datetime(2026, 10, 20, tzinfo=timezone.utc)
    c = hpcup._connect()
    check("muddat o'tgach - yopiq", not hpcup._qayta_mumkin(c, 1, kech))
    c.close()

    # Pochta: kimga «qayta_test» - faqat 1 va 2
    check("xat oluvchilar - 19-sentabrgacha saralanganlar", hppochta._kimlar({"tur": "qayta_test"}) == [1, 2])

    # Tarix muhrlanadi: yopilgan haftada 1-o'quvchining 50 bali Xaffelpaffda qolishi kerak
    s = await hpcup.current_season()
    await hpcup.award(1, "daily", "q1", 50)
    await hpcup.close_season(s["id"])
    hpcup._history_cache.clear()

    r = await hpcup.set_house(1, "ravenclaw")
    check("qayta topshirish qabul qilindi, fakultet o'zgardi", r and r.get("changed") and r.get("qayta"))
    check("fakultet yangilandi, sana o'zgarmadi",
          sql("SELECT house, sorted_at FROM users WHERE user_id=1") == [("ravenclaw", "2026-08-16 13:36:20")])
    check("bir marta: ikkinchisiga ruxsat yo'q", not hpcup.qayta_mumkin(1) and await hpcup.set_house(1, "slytherin") is False)
    check("yozuv saqlandi", sql("SELECT eski, yangi FROM qayta_test WHERE user_id=1") == [("hufflepuff", "ravenclaw")])
    check("xat oluvchilardan chiqdi", hppochta._kimlar({"tur": "qayta_test"}) == [2])

    hpcup._history_cache.clear()
    tarix = (await hpcup.cup_history())["seasons"]
    yopiq = [x for x in tarix if x["id"] == s["id"]][0]
    uylar = {x["house"]: x["total_points"] for x in yopiq["houses"]}
    check("tarixda ball eski fakultetda qoldi", uylar.get("hufflepuff") == 50 and not uylar.get("ravenclaw"))
    check("tarixda uchlikdagi fakultet ham eski", yopiq["top"] and yopiq["top"][0]["house"] == "hufflepuff")

    # Bir xil fakultet chiqsa ham urinish sarflanadi
    r2 = await hpcup.set_house(2, "gryffindor")
    check("o'sha fakultet chiqdi - o'zgarish yo'q, lekin sarflandi", r2 and not r2.get("changed") and not hpcup.qayta_mumkin(2))

    print("Qayta test: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    return fail == 0


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(amain()) else 1)
