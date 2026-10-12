"""Hafta yakuni: oxirgi kun (yakshanba) bellashuv va rekord sovrinlari O'SHA hafta kubogiga tushadi (2026-10-12 xatosi).

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import os
import sqlite3
import sys
import tempfile
import types
from datetime import timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-hafta-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpdars   # noqa: E402

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
    hpdars._init()
    check("ilgak ro'yxatda", hpdars._hafta_yopilishi in hpcup.YOPISH_ILGAKLARI)
    for uid, uy in ((1, "gryffindor"), (2, "slytherin")):
        await hpcup.touch_user(uid, "Sehrgar %d" % uid)
        await hpcup.set_house(uid, uy)
    s = await hpcup.current_season()
    oxirgi = hpcup._parse_iso(s["ends_at"]).astimezone(hpcup.TASHKENT).strftime("%Y-%m-%d")     # haftaning yakshanbasi
    # Yakshanba bellashuvi: 1 - birinchi, 2 - ikkinchi; rekord jadvali ham bor
    sql("INSERT INTO dars_bellashuv (kun, dars, user_id, ms, urinish) VALUES (?,?,?,?,1)", (oxirgi, "afsun", 1, 9000))
    sql("INSERT INTO dars_bellashuv (kun, dars, user_id, ms, urinish) VALUES (?,?,?,?,1)", (oxirgi, "afsun", 2, 12000))
    sql("INSERT INTO dars_rekord (user_id, dars, hafta, ball) VALUES (1, 'himoya', '2026-10-05', 30)")

    res = await hpcup.close_season(s["id"])
    pts = dict(sql("SELECT source_ref, season_id FROM points WHERE source_type='dars'"))
    check("bellashuv sovrini yopilgan haftaga", pts.get("m:afsun:%s" % oxirgi) == s["id"])
    check("rekord sovrini yopilgan haftaga", pts.get("r:himoya:%s" % oxirgi) == s["id"])
    check("g'olib shu ballar bilan aniqlandi", res["winner_house"] == "gryffindor")
    check("galleon ham shu ballardan", sql("SELECT ball FROM galleon_mukofot WHERE user_id=1 AND season_id=?", (s["id"],))
          == [(hpdars.SOVRIN[0] + hpdars.REK_SOVRIN[0],)])
    # Ertasiga (yangi haftada) qayta yakunlash - takror ball yo'q, yangi haftaga hech narsa tushmaydi
    ertasi = (hpcup._parse_iso(s["ends_at"]) + timedelta(minutes=1)).astimezone(hpcup.TASHKENT).strftime("%Y-%m-%d")
    hpdars.yakunla(ertasi)
    hpdars.rekord_yakunla(ertasi)
    check("takror berilmadi", sql("SELECT COUNT(*) FROM points WHERE source_type='dars'") == [(3,)])
    check("yangi haftada bu ballar yo'q", sql("SELECT COUNT(*) FROM points WHERE season_id=? AND source_type='dars'", (res["new_season_id"],)) == [(0,)])
    # Kun berilsa - o'sha kun tushgan haftaga (o'tgan, yopilgan hafta bo'lsa ham)
    sql("INSERT INTO seasons (starts_at, ends_at, status, winner_house) VALUES ('2026-01-04T19:00:00Z', '2026-01-11T18:59:00Z', 'closed', NULL)")
    eski = sql("SELECT id FROM seasons WHERE starts_at='2026-01-04T19:00:00Z'")[0][0]
    hpcup._award(2, "dars", "m:test:2026-01-11", 3, kun="2026-01-11")
    check("kun bo'yicha hafta topiladi (yakshanba)", sql("SELECT season_id FROM points WHERE source_ref='m:test:2026-01-11'") == [(eski,)])

    print("Hafta yakuni: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    return fail == 0


if __name__ == "__main__":
    sys.exit(0 if asyncio.run(amain()) else 1)
