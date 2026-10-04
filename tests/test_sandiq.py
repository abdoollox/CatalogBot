"""Kunlik sandiq: topshiriqlar, bosqichli ball, ochish, ketma-ketlik, katta sandiq.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import json
import os
import sqlite3
import sys
import tempfile
import types
from datetime import datetime, timedelta

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-sandiq-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpsandiq   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


class Req:
    def __init__(self, body=None, init="", method="POST"):
        self._b, self.method = body or {}, method
        self.headers = {"X-Telegram-Init-Data": init}
        self.query = {}
    async def json(self):
        return self._b


def sql(q, a=()):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    try:
        r = c.execute(q, a).fetchall()
        c.commit()
        return r
    finally:
        c.close()


async def ask(kim, **body):
    r = await hpsandiq.api_sandiq(Req(body, init=str(kim)))
    return json.loads(r.body)


def ball(uid):
    return sql("SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_type='sandiq'", (uid,))[0][0]


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    app = types.SimpleNamespace(router=types.SimpleNamespace(add_route=lambda *a, **k: None))
    hpsandiq.register(app, {"cors": lambda r: r,
                            "verify_init_data": lambda s: {"id": int(s)} if s.lstrip("-").isdigit() else None})

    check("imzosiz rad etiladi", (await hpsandiq.api_sandiq(Req({}, init=""))).status == 403)
    t = hpsandiq.kun_topshiriqlari("2026-10-05")
    check("kuniga 6 ta topshiriq, kunlik savol doim bor, takrorsiz",
          len(t) == 6 and t[0] == "daily" and len(set(t)) == 6 and t == hpsandiq.kun_topshiriqlari("2026-10-05"))
    check("kunlar bir-biridan farq qiladi",
          len({tuple(hpsandiq.kun_topshiriqlari("2026-10-%02d" % d)) for d in range(1, 15)}) > 3)

    await hpcup.touch_user(1, "Garri")
    check("saralanmaganga sandiq yo'q", (await ask(1)).get("error") == "no_house")
    await hpcup.set_house(1, "gryffindor")
    d = await ask(1)
    kun = d["kun"]
    kodlar = [x["code"] for x in d["tasks"]]
    check("boshida 0 / 6, ochib bo'lmaydi", d["ok"] and d["n"] == 0 and d["total"] == 6 and not d["can_open"] and d["streak"] == 0)

    boshqa = [k for k in kodlar if k != "daily"]
    yoq = [k for k in hpsandiq.HAVZA if k not in kodlar]
    d = await ask(1, task=yoq[0])
    check("bugungi ro'yxatda yo'q topshiriq sanalmaydi", d["n"] == 0)
    d = await ask(1, task="daily")
    check("kunlik savolni ilova aytgani bilan sanalmaydi (server tekshiradi)", d["n"] == 0)

    d = await ask(1, task=boshqa[0])
    check("1 ta - hali mukofot yo'q", d["n"] == 1 and not d["reward"] and ball(1) == 0)
    d = await ask(1, task=boshqa[0])
    check("takror sanalmaydi", d["n"] == 1)
    d = await ask(1, task=boshqa[1])
    check("2 ta - oraliq mukofot yo'q", d["n"] == 2 and not d["reward"] and ball(1) == 0)
    d = await ask(1, task=boshqa[2])
    d = await ask(1, task=boshqa[3])
    check("4 ta - hali ham ball yo'q", d["n"] == 4 and not d["reward"] and ball(1) == 0)
    d = await ask(1, task=boshqa[4])
    check("5 ta - ochib bo'lmaydi", d["n"] == 5 and not d["can_open"])
    d = await ask(1, open=True)
    check("5 ta bilan ochilmaydi", not d["opened"] and ball(1) == 0)

    # Kunlik savolga javob: server o'zi ko'radi
    q = sql("SELECT id FROM questions WHERE kind='daily' LIMIT 1")[0][0]
    season = await hpcup.current_season()
    sql("INSERT INTO answers (user_id, season_id, question_id, is_correct, answered_at) VALUES (1,?,?,0,?)",
        (season["id"], q, hpcup._utc_iso(hpcup.now_tk())))
    d = await ask(1)
    check("kunlik savol javobi bazadan ko'rindi - 6 / 6", d["n"] == 6 and d["can_open"])
    gal0 = sql("SELECT galleons FROM users WHERE user_id=1")[0][0]
    d = await ask(1, open=True)
    gal1 = sql("SELECT galleons FROM users WHERE user_id=1")[0][0]
    check("sandiq ochildi: +10 ball, +1 galleon, ketma-ketlik 1",
          d["opened"] and d["reward"]["ball"] == 10 and d["reward"]["gal"] == 1 and d["streak"] == 1
          and ball(1) == 10 and gal1 - gal0 == 1)
    check("kartochka berildi: bugungisi, yangi", d["reward"]["card"] == hpsandiq.kun_kartasi(kun) and d["reward"]["card_new"] is True
          and d["cards"] == {hpsandiq.kun_kartasi(kun): 1} and d["cards_total"] == 24 and d["card"] == hpsandiq.kun_kartasi(kun))
    d = await ask(1, open=True)
    check("ikkinchi marta ochilmaydi", ball(1) == 10 and sql("SELECT galleons FROM users WHERE user_id=1")[0][0] == gal1)
    check("kubokda 'chest' manbasi", (await hpcup.user_stats(1, season["id"]))["by"].get("chest") == 10)

    # Ketma-ketlik: oldingi 6 kun ochilgan, bugun 7-kun -> katta sandiq
    await hpcup.touch_user(2, "Ron")
    await hpcup.set_house(2, "gryffindor")
    bugun = datetime.strptime(kun, "%Y-%m-%d")
    for i in range(1, 7):
        sql("INSERT INTO sandiq (user_id, kun, done, bosqich, ochildi) VALUES (2, ?, '[]', 2, 'x')",
            ((bugun - timedelta(days=i)).strftime("%Y-%m-%d"),))
    d = await ask(2)
    check("6 kunlik ketma-ketlik, bugun katta sandiq", d["streak"] == 6 and d["big"] is True)
    sql("UPDATE sandiq SET done=? WHERE user_id=2 AND kun=?", (json.dumps(kodlar), kun))
    sql("INSERT OR IGNORE INTO sandiq (user_id, kun, done) VALUES (2, ?, ?)", (kun, json.dumps(kodlar)))
    g0 = sql("SELECT galleons FROM users WHERE user_id=2")[0][0]
    d = await ask(2, open=True)
    check("7-kun: +1 va +3 galleon", d["reward"]["gal"] == 4 and d["reward"]["big"] and d["streak"] == 7
          and sql("SELECT galleons FROM users WHERE user_id=2")[0][0] - g0 == 4)

    aylana = [hpsandiq.kun_kartasi((datetime(2026, 10, 5) + timedelta(days=i)).strftime("%Y-%m-%d")) for i in range(48)]
    check("24 kunda 24 xil kartochka, keyingi aylanada yana hammasi",
          len(set(aylana[:24])) == 24 and len(set(aylana[24:])) == 24 and set(aylana[:24]) == set(hpsandiq.KARTALAR))

    # Kun o'tkazib yuborilsa - noldan
    await hpcup.touch_user(3, "Nevill")
    await hpcup.set_house(3, "gryffindor")
    for i in (2, 3, 4):
        sql("INSERT INTO sandiq (user_id, kun, done, bosqich, ochildi) VALUES (3, ?, '[]', 2, 'x')",
            ((bugun - timedelta(days=i)).strftime("%Y-%m-%d"),))
    check("kecha o'tkazib yuborilgan - ketma-ketlik 0", (await ask(3))["streak"] == 0)


asyncio.run(amain())
print("O'tdi: %d, xato: %d" % (ok, fail))
sys.exit(1 if fail else 0)
