"""Admin hisobi - Xogvarts direktori «Albus Dambldor» (egasi, 2026-10-24): ismi saqlanadi,
hamma joyda ko'rinadi, lekin bali hech bir fakultetga, uchlikka va galleonga qo'shilmaydi.

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
TMP = tempfile.mkdtemp(prefix="hp-direktor-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "7"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hppochta, hpdars   # noqa: E402

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
    for uid, uy in ((1, "gryffindor"), (2, "slytherin"), (7, "ravenclaw")):
        await hpcup.touch_user(uid, "Sehrgar %d" % uid)
        await hpcup.set_house(uid, uy)
    check("direktor qilindi", hpcup.direktor_qil(7) == 1)
    await hpcup.touch_user(7, "Abdulloh", "abdulloh")
    check("Telegram ismi direktor ismini almashtirmaydi",
          bir("SELECT first_name, house FROM users WHERE user_id=7") == ("Albus Dambldor", "direktor"))
    await hpcup.touch_user(1, "Garri Potter")
    check("oddiy o'quvchi ismi yangilanadi", bir("SELECT first_name FROM users WHERE user_id=1")[0] == "Garri")
    check("qisqa ism: direktor to'liq, boshqalar birinchi so'z",
          hpcup.ism("Albus Dambldor") == "Albus Dambldor" and hpcup.ism("Garri Potter") == "Garri"
          and hpdars._ism("Albus Dambldor") == "Albus Dambldor" and hpdars._ism("Ron Uizli") == "Ron")

    season = await hpcup.current_season()
    for uid, n in ((1, 5), (2, 3), (7, 30)):
        for i in range(n):
            await hpcup.award(uid, "daily", "k%d" % i, 10)
    jadval = await hpcup.leaderboard(season["id"])
    uylar = {x["house"]: x["total_points"] for x in jadval}
    check("jadvalda faqat to'rt fakultet", sorted(uylar) == sorted(hpcup.HOUSES))
    check("direktor bali hech bir fakultetga tushmaydi", uylar["ravenclaw"] == 0 and uylar["gryffindor"] == 50
          and sum(uylar.values()) == 80)

    a = await hpcup.chat_members(None, season["id"], 7)
    check("Katta zal a'zolari ro'yxatida direktor bor", any(m.get("uid", m.get("user_id")) == 7 for m in a)
          or "Albus Dambldor" in json.dumps(a, ensure_ascii=False))

    st = await hpcup.user_stats(7, season["id"])
    check("direktor «saralangan» hisoblanadi (hamma joyga kiradi)", st.get("house") == "direktor")

    res = await hpcup.close_season(season["id"])
    check("g'olib - Grifindor (direktorning 300 bali hisobga olinmadi)", res["winner_house"] == "gryffindor")
    check("direktorga galleon berilmaydi", 7 not in res["galleons"] and 1 in res["galleons"])
    tarix = await hpcup.cup_history()
    s = next(x for x in tarix["seasons"] if x["id"] == season["id"])
    check("haftaning eng yaxshi uchligida direktor yo'q", all(t["uid"] != 7 for t in s.get("top") or []))

    hppochta._cfg.update({"admin_ids": {7}})
    n = hppochta._kubok_yoz(season["id"])
    check("kubok xati faqat fakultet o'quvchilariga", n == 2
          and bir("SELECT COUNT(*) FROM pochta WHERE user_id=7 AND tur='kubok'")[0] == 0)

    print("=" * 40)
    print("Direktor: %d ta o'tdi, %d ta xato" % (ok, fail))
    return fail


sys.exit(1 if asyncio.run(amain()) else 0)
