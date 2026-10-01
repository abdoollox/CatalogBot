"""Gringotts hamyoni: xona, tayoqcha, bilet. Uy hayvoni 2026-10-01 da olib
tashlandi - endi sotilmaydi, logga yozilmaydi, javobda ham yo'q.

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
TMP = tempfile.mkdtemp(prefix="hp-hamyon-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, main   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    uid = 777
    await hpcup.touch_user(uid, "Sinov")

    w = await hpcup.wallet(uid)
    check("yangi odam: xona yopiq", w["vault"] is False and w["galleons"] == 0)
    check("javobda hayvon yo'q", "pet" not in w and "pets" not in w.get("prices", {}))

    w, xato = await hpcup.buy(uid, "wand")
    check("xonasiz tayoqcha olinmaydi", xato == "vault")

    w, yangi = await hpcup.open_vault(uid)
    check("xona ochildi, 25 galleon", yangi and w["galleons"] == hpcup.START_GALLEONS)
    w, yangi = await hpcup.open_vault(uid)
    check("ikkinchi marta pul berilmaydi", not yangi and w["galleons"] == hpcup.START_GALLEONS)

    for hayvon in ("owl", "cat", "toad", "rat"):
        w, xato = await hpcup.buy(uid, hayvon)
        check("hayvon sotilmaydi: " + hayvon, xato == "yoq")
    check("hayvon uchun pul yechilmadi", w["galleons"] == hpcup.START_GALLEONS)

    w, xato = await hpcup.give_ticket(uid)
    check("tayoqchasiz bilet berilmaydi", xato == "tayoqcha")

    w, xato = await hpcup.buy(uid, "wand")
    check("tayoqcha olindi", xato is None and w["wand"] and
          w["galleons"] == hpcup.START_GALLEONS - hpcup.WAND_PRICE)
    w, xato = await hpcup.buy(uid, "wand")
    check("tayoqcha ikki marta olinmaydi", xato == "bor")

    w, xato = await hpcup.give_ticket(uid)
    check("bilet berildi", xato is None and w["ticket"])

    check("pet_* logga o'tmaydi", main.check_value("pet", "owl") is None)
    check("onb qadami o'tadi", main.check_value("onb", "letter") == "onb_letter")
    check("hpcup da PET_PRICES yo'q", not hasattr(hpcup, "PET_PRICES"))


if __name__ == "__main__":
    asyncio.run(amain())
    print("O'tdi: %d, xato: %d" % (ok, fail))
    sys.exit(1 if fail else 0)
