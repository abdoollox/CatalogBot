"""Film sifati: Full HD / HD alohida saqlanadi, tanlov tugmalari, yuborish.

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
TMP = tempfile.mkdtemp(prefix="hp-sifat-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpfilms, main   # noqa: E402

hpfilms.STORE = os.path.join(TMP, "films.json")

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


def V(mid, name, size, h=0, cap=""):
    return {"mid": mid, "name": name, "cap": cap, "size": size, "dur": 1, "h": h}


async def amain():
    q = hpfilms.quality_of
    check("nomdan 1080p", q(V(1, "Garri Potter va Hikmatlar Toshi (2001)(1080p).mp4", 1)) == "fhd")
    check("nomdan 720p", q(V(1, "Garri Potter va Hikmatlar Toshi (2001)(720p).mp4", 1)) == "hd")
    check("yil 720 emas", q(V(1, "Film (2007).mp4", 1)) == "fhd")
    check("yopishgan 20111080p - Full HD", q(V(1, "Гарри_Поттер_20111080p.mp4", 1)) == "fhd")
    check("nomsiz: balandlikdan", q(V(1, "film.mp4", 1, h=720)) == "hd" and q(V(1, "film.mp4", 1, h=1080)) == "fhd")
    check("hech narsa ma'lum emas - Full HD", q(V(1, "Fantastik maxluqlar 1.mp4", 1)) == "fhd")

    hpfilms._data.update({"group": -1, "map": {}, "seen": {}, "topics": {"5": "uz"}})
    hpfilms._place(V(10, "Garri Potter va Hikmatlar Toshi (2001)(1080p).mp4", 3 * 1024 ** 3), "hp1", "uz", "nom")
    check("faqat Full HD bor", hpfilms.qualities("hp1", "uz") == {"fhd": 3 * 1024 ** 3})
    hpfilms._place(V(20, "Garri Potter va Hikmatlar Toshi (2001)(720p).mp4", 1288490188), "hp1", "uz", "nom")
    check("720p Full HD o'rnini egallamaydi", hpfilms.source("hp1", "uz", "fhd") == (-1, 10)
          and hpfilms.source("hp1", "uz", "hd") == (-1, 20))
    check("sifat aytilmasa - eng yaxshisi", hpfilms.source("hp1", "uz") == (-1, 10))
    check("ilova ro'yxati", hpfilms.public_map() == {"hp1_uz": {"fhd": 3 * 1024 ** 3, "hd": 1288490188}})
    hpfilms._place(V(30, "Garri Potter va Maxfiy Xujra (2002)(720p).mp4", 5), "hp2", "uz", "nom")
    check("faqat HD bor film ham tayyor", hpfilms.in_group("hp2", "uz") and hpfilms.source("hp2", "uz") == (-1, 30))
    check("jadvalda +HD", "+HD" in hpfilms.table_text())

    check("hajm: GB va MB", main.hajm_matni(3 * 1024 ** 3, "uz") == "3,0 GB" and main.hajm_matni(1288490188, "en") == "1.2 GB"
          and main.hajm_matni(500 * 1024 ** 2, "ru") == "500 MB")
    kb = main.sifat_tugmalari("hp1", "uz", "b").inline_keyboard
    check("ikkala sifat tugmasi", [b[0].text for b in kb] == ["Full HD · 3,0 GB", "HD · 1,2 GB"]
          and kb[1][0].callback_data == "sf:hp1:uz:hd:b")
    kb = main.sifat_tugmalari("hp2", "uz", "w").inline_keyboard
    check("yo'q sifat qulflangan", kb[0][0].text.startswith("🔒 Full HD") and kb[0][0].callback_data.endswith(":x")
          and kb[1][0].callback_data == "sf:hp2:uz:hd:w")
    cap = main.share_caption("hp1", main.catalog.FILMS["hp1"], "uz", 5, "hd")
    check("yuborilgan film ostida aynan o'sha sifat", "Sifat: HD" in main.emoji.strip_tags(cap) and "Full HD" not in cap)
    cap = main.share_caption("hp1", main.catalog.FILMS["hp1"], "uz", 5)
    check("ulashish kartasida mavjud sifatlar", "Full HD · HD" in cap)

    # Yuborish: tanlangan sifatning xabari nusxalanadi
    sent = []
    class FakeBot:
        async def copy_message(self, **kw):
            sent.append(kw)
            return types.SimpleNamespace(message_id=1)
    eski = main.bot
    main.bot = FakeBot()
    try:
        await main.send_film(5, "hp1", "uz", None, "hd")
        await main.send_film(5, "hp1", "uz")
    finally:
        main.bot = eski
    check("HD so'ralsa 720p fayl, so'ralmasa Full HD", [x["message_id"] for x in sent] == [20, 10]
          and "HD" in sent[0]["caption"] and "Full HD" in sent[1]["caption"])

    print("O'tdi: %d, xato: %d" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
