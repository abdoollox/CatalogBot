"""Kitoblar: nomdan kitob/til/format tanish, sinov rejimi, galleonga ochish, yuborish, o'qish fayli.

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
TMP = tempfile.mkdtemp(prefix="hp-kitob-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["BOT_TOKEN"] = "123456:TEST-token"

import hpmusic   # noqa: E402
import hpkitob   # noqa: E402

hpkitob.STORE = os.path.join(TMP, "kitob.json")
hpkitob.FILE_DIR = os.path.join(TMP, "fayl")
hpkitob.DB_PATH = hpmusic.DB_PATH = os.environ["HP_DB_PATH"]

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


class Req:
    def __init__(self, body=None, init="", method="POST", query=None, match=None):
        self._b, self.method = body or {}, method
        self.headers = {"X-Telegram-Init-Data": init}
        self.query, self.match_info = query or {}, match or {}
    async def json(self):
        return self._b


class FakeBot:
    def __init__(self):
        self.sent, self.copied, self.yuklandi = [], [], []
    async def send_message(self, uid, text, **kw):
        self.sent.append((uid, text))
    async def download(self, fid, destination=None):
        self.yuklandi.append(fid)
        with open(destination, "wb") as f:
            f.write(b"%PDF-" + fid.encode())
    async def copy_message(self, **kw):
        self.copied.append(kw)
        return types.SimpleNamespace(message_id=777)


class Msg:
    """Guruhdagi fayl xabar (mavzuda)."""
    def __init__(self, mid, thread, name="", cap="", size=1000, mime="application/pdf"):
        self.message_id, self.message_thread_id, self.is_topic_message = mid, thread, True
        self.chat = types.SimpleNamespace(id=-100, type="supergroup")
        self.document = types.SimpleNamespace(file_name=name, file_size=size, file_id="f%d" % mid, mime_type=mime)
        self.caption, self.photo, self.video = cap, None, None


def sql(q, a=()):
    c = sqlite3.connect(os.environ["HP_DB_PATH"])
    c.execute(q, a)
    c.commit()
    c.close()


async def main():
    b, l, f = hpkitob.book_of, hpkitob.lang_of, hpkitob.fmt_of
    check("inglizcha nomlar", [b(x) for x in (
        "Harry Potter and the Philosopher's Stone.pdf", "Harry_Potter_and_the_Sorcerers_Stone.pdf",
        "HP and the Chamber of Secrets", "Prisoner of Azkaban", "Goblet of Fire", "Order of the Phoenix",
        "Half-Blood Prince", "Harry Potter and the Deathly Hallows (2007).epub")]
        == ["kt1", "kt1", "kt2", "kt3", "kt4", "kt5", "kt6", "kt7"])
    check("ruscha nomlar", [b(x) for x in ("Гарри Поттер и философский камень", "Тайная комната", "Узник Азкабана",
                                            "Кубок огня", "Орден Феникса", "Принц-полукровка", "Дары Смерти")]
          == ["kt%d" % i for i in range(1, 8)])
    check("o'zbekcha nomlar", b("Garri Potter va afsonaviy tosh") == "kt1" and b("Garri Potter va maxfiy xona") == "kt2"
          and b("Feniks ordeni") == "kt5" and b("Chala qonli shahzoda") == "kt6" and b("Ajal tuhfalari") == "kt7")
    check("film uslubidagi o'zbekcha nomlar", [b(x) for x in ("Garri Potter va Hikmatlar Toshi", "Maxfiy Hujra", "Alanga Kubogi",
          "Feniks Jamiyati", "Tilsim Shaxzodasi", "Ajal Tuhfasi")] == ["kt1", "kt2", "kt4", "kt5", "kt6", "kt7"])
    check("raqam bilan", b("Harry Potter Book 3.pdf") == "kt3" and b("4-kitob") == "kt4" and b("Книга 5") == "kt5"
          and b("02 - Harry Potter.pdf") == "kt2" and b("HP6.pdf") == "kt6")
    check("yil kitob raqami emas", b("Harry Potter 2007.pdf") is None and b("") is None and b(None) is None)
    check("til nomdan", l("HP1 eng.pdf") == "en" and l("Garri Potter uz.pdf") == "uz"
          and l("Гарри Поттер и философский камень") == "ru" and l("Harry Potter.pdf") is None)
    check("format", f("a.PDF") == "pdf" and f("a.epub") == "epub" and f("kitob", "application/pdf") == "pdf"
          and f("rasm.jpg", "image/jpeg") is None)
    check("kalit", hpkitob.parse_key("KT3_en") == ("kt3", "en") and hpkitob.parse_key("hp1_uz") is None)

    bot = FakeBot()
    async def sub(chat):
        return True
    hpmusic._cfg.update({"token": "123456:TEST-token"})
    hpkitob._cfg.update({"bot": bot, "admin_ids": {42}, "cors": lambda r: r,
                         "verify_init_data": lambda d: {"id": int(d)} if d.lstrip("-").isdigit() else None,
                         "is_subscribed": sub, "tg_chat_id": lambda u: u,
                         "webapp_url": lambda lg: "https://x.test/?lang=" + lg})
    hpkitob._init()
    sql("CREATE TABLE users (user_id INTEGER PRIMARY KEY, galleons INTEGER)")
    sql("INSERT INTO users VALUES (5, 4), (6, 1), (42, 0)")
    hpkitob._data.update({"group": -100, "topics": {"7": "en", "9": ""}})

    await hpkitob.on_group_doc(Msg(50, 7, name="Harry Potter and the Philosopher's Stone.pdf"))
    check("bog'landi, o'qish uchun yuklandi, adminga aytildi", hpkitob.source("kt1", "en", "pdf") == (-100, 50)
          and hpkitob.can_read("kt1", "en") and bot.yuklandi == ["f50"] and "sinov" in bot.sent[-1][1])
    check("sinovda oddiy odam ko'rmaydi, admin ko'radi", hpkitob.public_list(5) == []
          and [x["id"] for x in hpkitob.public_list(42)] == ["kt1"])
    r = await hpkitob.api_send(Req({"book": "kt1", "lang": "en"}, init="5"))
    check("sinovda oddiy odamga yuborilmaydi", json.loads(r.body)["error"] == "not_ready" and not bot.copied)

    await hpkitob.on_group_doc(Msg(51, 7, name="scan0001.pdf"))
    check("tanilmagan fayl - qo'lda buyruq", "/kitobfayl kt1_en pdf 51" in bot.sent[-1][1])
    await hpkitob.on_group_doc(Msg(52, 9, name="Chamber of Secrets.pdf"))
    check("tilsiz mavzuda til aniqlanmasa - so'raladi", "Tili aniqlanmadi" in bot.sent[-1][1]
          and hpkitob.source("kt2", "en", "pdf") is None)
    await hpkitob.on_group_doc(Msg(53, 9, name="Гарри Поттер и Тайная комната.epub", mime="application/epub+zip"))
    check("tilsiz mavzuda til nomdan (ru), epub", hpkitob.source("kt2", "ru", "epub") == (-100, 53)
          and not hpkitob.can_read("kt2", "ru"))
    n = len(bot.sent)
    rasm = Msg(54, 7, name="muqova.jpg", mime="image/jpeg")
    await hpkitob.on_group_doc(rasm)
    check("kitob bo'lmagan fayl jim o'tkaziladi", len(bot.sent) == n)
    await hpkitob.on_group_doc(Msg(55, 7, name="Chamber of Secrets.pdf", size=30 * 1024 * 1024))
    check("katta PDF: bog'lanadi, lekin o'qilmaydi", hpkitob.source("kt2", "en", "pdf") == (-100, 55)
          and not hpkitob.can_read("kt2", "en") and "20 MB" in bot.sent[-1][1] and "f55" not in bot.yuklandi)

    hpkitob._data["ochiq"] = True
    d = json.loads((await hpkitob.api_list(Req(init="5", method="GET"))).body)
    kt = {x["id"]: x for x in d["books"]}
    check("ro'yxat: birinchi kitob bepul va ochiq, ikkinchisi qulf", d["price"] == 3 and d["gal"] == 4 and d["key"]
          and kt["kt1"]["open"] and kt["kt1"]["free"] and kt["kt1"]["files"]["en"]["pdf"]["read"]
          and not kt["kt2"]["open"] and set(kt["kt2"]["files"]) == {"ru", "en"})
    d = json.loads((await hpkitob.api_list(Req(init="", method="GET"))).body)
    check("imzosiz ro'yxat: kalit yo'q", "key" not in d and len(d["books"]) == 2)

    r = await hpkitob.api_send(Req({"book": "kt2", "lang": "en"}, init="5"))
    check("qulflangan kitob yuborilmaydi", json.loads(r.body)["error"] == "locked")
    r = await hpkitob.api_buy(Req({"book": "kt2"}, init="6"))
    check("galleon yetmasa - pul", json.loads(r.body) == {"ok": False, "error": "pul", "gal": 1, "price": 3})
    r = await hpkitob.api_buy(Req({"book": "kt2"}, init="5"))
    check("ochildi, 3 galleon yechildi", json.loads(r.body) == {"ok": True, "gal": 1})
    r = await hpkitob.api_buy(Req({"book": "kt2"}, init="5"))
    check("ikkinchi marta pul yechilmaydi", json.loads(r.body) == {"ok": True, "gal": 1})
    r = await hpkitob.api_buy(Req({"book": "kt5"}, init="5"))
    check("fayli yo'q kitob sotilmaydi", r.status == 404)

    r = await hpkitob.api_send(Req({"book": "kt2", "lang": "en", "fmt": "pdf", "ui": "uz"}, init="5"))
    k = bot.copied[-1]
    check("kitob yuborildi (himoyasiz, o'zbekcha karta)", json.loads(r.body)["ok"] and k["message_id"] == 55
          and k["protect_content"] is False and "Maxfiy Hujra" in k["caption"] and "2-kitob" in k["caption"]
          and "English" in k["caption"] and "PDF" in k["caption"] and "1998" in k["caption"])
    check("o'qib bo'lmaydigan kitobda faqat kutubxona tugmasi", len(k["reply_markup"].inline_keyboard[0]) == 1)
    r = await hpkitob.api_send(Req({"book": "kt2", "lang": "en"}, init="5"))
    check("ketma-ket bosish - slow", json.loads(r.body)["error"] == "slow")
    hpkitob._oxirgi.clear()
    r = await hpkitob.api_send(Req({"book": "kt1", "lang": "en", "ui": "ru"}, init="6"))
    k = bot.copied[-1]
    check("bepul kitob hammaga, o'qish tugmasi bilan", json.loads(r.body)["ok"] and "Философский Камень" in k["caption"]
          and k["reply_markup"].inline_keyboard[0][0].web_app.url.endswith("&kitob=kt1"))
    r = await hpkitob.api_send(Req({"book": "kt1", "lang": "uz"}, init="6"))
    check("yo'q til - not_ready", json.loads(r.body)["error"] == "not_ready")
    r = await hpkitob.api_send(Req({"book": "kt1", "lang": "en", "action": "read"}, init="6"))
    check("o'qish belgisi: fayl yuborilmaydi", json.loads(r.body)["ok"] and len(bot.copied) == 2)
    r = await hpkitob.api_send(Req({"book": "kt1", "lang": "en"}, init="yolgon"))
    check("imzosiz - 403", r.status == 403)

    # O'qish fayli: kalit bilan, faqat ochiq kitob
    key5, key6 = hpmusic.make_key(5), hpmusic.make_key(6)
    r = await hpkitob.api_file(Req(method="GET", query={"k": "yolgon"}, match={"key": "kt1_en"}))
    check("fayl: kalitsiz 403", r.status == 403)
    r = await hpkitob.api_file(Req(method="GET", query={"k": key6}, match={"key": "kt1_en"}))
    check("fayl: bepul kitob beriladi", r.status == 200 and str(r._path).endswith("kt1_en.pdf")
          and "Content-Range" in r.headers["Access-Control-Expose-Headers"])
    r = await hpkitob.api_file(Req(method="GET", query={"k": key5}, match={"key": "kt2_en"}))
    check("fayl: katta PDF o'qilmaydi", r.status == 404)
    await hpkitob.on_group_doc(Msg(60, 7, name="Prisoner of Azkaban.pdf"))
    r = await hpkitob.api_file(Req(method="GET", query={"k": key6}, match={"key": "kt3_en"}))
    check("fayl: qulflangan kitob berilmaydi", r.status == 404)
    r = await hpkitob.api_file(Req(method="OPTIONS", match={"key": "kt1_en"}))
    check("fayl: bo'laklab o'qishga ruxsat", r.status == 204 and r.headers["Access-Control-Allow-Headers"] == "Range")

    # Yengil PDF qayta tashlansa o'qish ochiladi
    await hpkitob.on_group_doc(Msg(61, 7, name="Chamber of Secrets.pdf", size=5 * 1024 * 1024))
    check("qayta tashlansa yangilanadi", hpkitob.source("kt2", "en", "pdf") == (-100, 61) and hpkitob.can_read("kt2", "en"))

    # Saqlash va qayta o'qish
    hpkitob._data = {"group": None, "topics": {}, "books": {}, "ochiq": False}
    hpkitob.load()
    check("saqlangan holat qaytadi", hpkitob.source("kt1", "en", "pdf") == (-100, 50) and hpkitob._data["ochiq"] is True)
    check("holat matni", "1-kitob: en·pdf (o'qish ✓)" in hpkitob.table_text() and "5-kitob: —" in hpkitob.table_text())

    print("Kitoblar: %d ta tekshiruv o'tdi, %d ta xato" % (ok, fail))
    sys.exit(1 if fail else 0)


asyncio.run(main())
