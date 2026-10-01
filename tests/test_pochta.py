"""Boyo'g'li pochtasi: kim, qachon, necha marta eslatma oladi; bot xabarini
o'chirish; ilova uchun ro'yxat; eski qadamlarni loglardan olish.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import json
import os
import sys
import tempfile
import types
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-pochta-")
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
from aiogram.exceptions import TelegramForbiddenError   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


class FakeBot:
    def __init__(self, blocked=()):
        self.sent = []
        self.blocked = set(blocked)

    async def send_message(self, uid, text, **kw):
        if uid in self.blocked:
            raise TelegramForbiddenError(method=None, message="blocked")
        self.sent.append((uid, text, kw.get("reply_markup")))


def iso(dt):
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def qadam_qoy(uid, qadamlar, qachon):
    for q in qadamlar:
        hppochta._qadam_yoz(uid, q, iso(qachon))


class Req:
    def __init__(self, body, method="POST", headers=None):
        self.method = method
        self._body = body
        self.headers = headers or {}

    async def json(self):
        return self._body


async def amain():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    hppochta._cfg.update({
        "cors": lambda r: r,
        "verify_init_data": lambda s: {"id": int(s)} if s.isdigit() else None,
        "webapp_url": "https://example.test/app/",
        "dash_ok": lambda req: req.headers.get("X-Dash-Token") == "k",
    })
    tush = datetime(2026, 10, 5, 12, 0, tzinfo=hpcup.TASHKENT)   # kunduzi

    for uid in (101, 102, 103, 104, 105, 106, 107):
        await hpcup.touch_user(uid, "Sehrgar %d" % uid)
    await hpcup.set_lang(102, "ru")

    qadam_qoy(101, ["letter"], tush - timedelta(hours=30))                   # 1 kun o'tdi
    qadam_qoy(102, ["letter", "alley", "gringotts"], tush - timedelta(hours=30))
    qadam_qoy(103, ["letter"], tush - timedelta(hours=5))                    # hali erta
    qadam_qoy(104, ["letter"], tush - timedelta(days=40))                    # juda eski
    qadam_qoy(105, YOL_BARI, tush - timedelta(days=2))                       # tugatgan
    qadam_qoy(106, ["letter"], tush - timedelta(hours=30))                   # botni bloklagan
    qadam_qoy(107, ["letter", "alley"], tush - timedelta(hours=30))          # bot xabarini o'chirgan
    hppochta._sozla(107, False)
    qadam_qoy(-5, ["letter"], tush - timedelta(hours=30))                    # sinov o'quvchisi

    bot = FakeBot(blocked={106})
    tun = datetime(2026, 10, 5, 23, 0, tzinfo=hpcup.TASHKENT)
    check("tunda hech narsa yuborilmaydi", await hppochta.aylana(bot, tun) == [] and not bot.sent)

    nat = {u: (q, n, h) for u, q, n, h in await hppochta.aylana(bot, tush)}
    check("101 xiyobon haqida 1-eslatma", nat.get(101) == ("alley", 1, "yuborildi"))
    check("102 tayoqcha haqida", nat.get(102, ("",))[0] == "wand")
    check("103 hali erta", 103 not in nat)
    check("104 juda eski - yozilmaydi", 104 not in nat)
    check("105 tugatgan - yozilmaydi", 105 not in nat)
    check("sinov o'quvchisiga yo'q", -5 not in nat)
    check("106 bloklagan deb yozildi", nat.get(106, ("", 0, ""))[2] == "bloklagan")
    check("107 ilovada xat bor, botdan yo'q", nat.get(107, ("", 0, ""))[2] == "ochirilgan")
    yuborilgan = {u for u, _, _ in bot.sent}
    check("botdan faqat 101 va 102 ga", yuborilgan == {101, 102})
    matn102 = [t for u, t, _ in bot.sent if u == 102][0]
    check("102 ga ruscha matn", "Олливандер" in matn102)
    kb = [k for u, _, k in bot.sent if u == 101][0]
    check("tugmada ilova havolasi va owl=1",
          "owl=1" in kb.inline_keyboard[0][0].web_app.url and kb.inline_keyboard[1][0].callback_data == "owl_off")

    check("darhol qayta - takror yo'q", await hppochta.aylana(bot, tush + timedelta(minutes=15)) == [])
    ikki = {u: n for u, _, n, _ in await hppochta.aylana(bot, tush + timedelta(days=2))}
    check("3 kun jimlikdan keyin 2-eslatma", ikki.get(101) == 2)
    keyin = await hppochta.aylana(bot, tush + timedelta(days=9))
    check("3-eslatma hech qachon yo'q", all(n <= 2 for _, _, n, _ in keyin) and
          not any(u in (101, 102) for u, _, _, _ in keyin))

    # Ilova ro'yxati va o'qish
    r = await hppochta.api_pochta(Req({"initData": "101", "action": "list"}))
    d = json.loads(r.body)
    check("ilovada 2 ta xat, 2 ta o'qilmagan", len(d["items"]) == 2 and d["unread"] == 2 and d["bot"])
    await hppochta.api_pochta(Req({"initData": "101", "action": "came"}))
    r = await hppochta.api_pochta(Req({"initData": "101", "action": "read"}))
    check("o'qildi", json.loads(r.body)["unread"] == 0)
    r = await hppochta.api_pochta(Req({"initData": "101", "action": "bot", "on": False}))
    check("bot xabari o'chirildi", json.loads(r.body)["bot"] is False)
    r = await hppochta.api_pochta(Req({"initData": "abc", "action": "list"}))
    check("imzosiz - 403", r.status == 403)

    # Eslatilgan qadam bajarilsa belgilanadi
    await hppochta.qadam(101, "onb", "alley")
    await hppochta.qadam(101, "onb", "yolgon")          # noma'lum qadam jim o'tadi
    r = await hppochta.api_pochta(Req({"initData": "101"}))
    check("xiyobon eslatmasi bajarildi", all(x["done"] for x in json.loads(r.body)["items"]))

    # Panel
    r = await hppochta.api_pochtapanel(Req({}, "GET", {"X-Dash-Token": "k"}))
    p = json.loads(r.body)
    check("panelda xatlar va o'chirganlar", len(p["xatlar"]) >= 6 and p["ochirgan"] == 2)
    bosilgan = [x for x in p["xatlar"] if x[1] == "101" and x[8]]
    check("bot tugmasi bosilgani yozilgan", len(bosilgan) >= 1)
    r = await hppochta.api_pochtapanel(Req({}, "GET", {}))
    check("panel kalitsiz - 403", r.status == 403)

    # Eski loglardan to'ldirish: xatdan oldingi qadam olinmaydi
    csv_matn = ("User ID,Nickname,Username,Kino ID va Til,Bosilgan Vaqt,Tashkent,\n"
                "900,A,,sort_start,2026-09-09 10:00:00,x,\n"
                "900,A,,onb_letter,2026-09-26 10:00:00,x,\n"
                "900,A,,onb_alley,2026-09-26 10:01:00,x,\n"
                "900,A,,wand_oak_phoenix_rigid,2026-09-26 10:05:00,x,\n"
                "901,B,,house_gryffindor,2026-09-20 10:00:00,x,\n")
    hppochta._toldir(csv_matn)
    conn = hppochta._ulan()
    q900 = {r["qadam"]: r["vaqt"] for r in conn.execute("SELECT * FROM onb_qadam WHERE user_id=900")}
    q901 = conn.execute("SELECT COUNT(*) FROM onb_qadam WHERE user_id=901").fetchone()[0]
    conn.close()
    check("loglardan: xat, xiyobon, tayoqcha", set(q900) == {"letter", "alley", "wand"})
    check("xatsiz odam olinmaydi", q901 == 0)
    check("to'ldirildi belgisi", hppochta._toldirilganmi())


async def test_tarqatma():
    """Qo'lda xat: kimga hisobi, sinov (o'zimga), fakultetga, tarix."""
    bot = FakeBot(blocked={202})
    hppochta._cfg.update({"bot": bot, "admin_ids": {42}})
    for uid, h, til in ((201, "gryffindor", "uz"), (202, "gryffindor", "ru"), (203, "slytherin", "uz"),
                        (204, None, "en"), (42, None, "uz")):
        await hpcup.touch_user(uid, "Odam %d" % uid)
        if h:
            await hpcup.set_house(uid, h, "Odam")
        await hpcup.set_lang(uid, til)
    hppochta._sozla(203, False)

    async def so(body, token="k"):
        r = await hppochta.api_tarqatma(Req(body, "POST", {"X-Dash-Token": token}))
        return r.status, json.loads(r.body)

    check("kalitsiz - 403", (await so({"action": "royxat"}, token=""))[0] == 403)
    _, d = await so({"action": "hisob", "kimga": {"tur": "fakultet", "fakultet": "gryffindor"}})
    check("grifindorda 2 kishi", d.get("soni") == 2)
    _, d = await so({"action": "hisob", "kimga": {"tur": "fakultet", "fakultet": "gryffindor", "til": "ru"}})
    check("grifindor + ruscha = 1", d.get("soni") == 1)
    _, d = await so({"action": "hisob", "kimga": {"tur": "saralanmagan"}})
    s1 = d.get("soni")
    check("saralanmaganlar ichida 204 va admin", s1 is not None and s1 >= 2)
    st, d = await so({"action": "hisob", "kimga": {"tur": "fakultet", "fakultet": "xogvarts"}})
    check("noto'g'ri fakultet - 400", st == 400)
    st, d = await so({"action": "yubor", "sarlavha": "  ", "kimga": {"tur": "men"}})
    check("sarlavhasiz - 400", st == 400)

    st, d = await so({"action": "yubor", "sarlavha": "Sinov <b>", "matn": "Salom & xayr", "kimga": {"tur": "men"}})
    check("o'zimga yuborildi", st == 200 and d["soni"] == 1)
    for _ in range(50):
        if not hppochta._tarqatma_band["id"]:
            break
        await asyncio.sleep(0.05)
    matn = [t for u, t, _ in bot.sent if u == 42]
    check("admin bot xabarini oldi, HTML qochirilgan", matn and "Sinov &lt;b&gt;" in matn[-1] and "&amp;" in matn[-1])

    st, d = await so({"action": "yubor", "sarlavha": "Grifindor, oldindasiz!", "matn": "Kubokda birinchi o'rin.",
                      "kimga": {"tur": "fakultet", "fakultet": "gryffindor"}})
    check("fakultetga yuborish boshlandi", st == 200 and d["soni"] == 2)
    st2, d2 = await so({"action": "yubor", "sarlavha": "Yana", "kimga": {"tur": "men"}})
    check("ikkinchisi kutadi - 409", st2 == 409)
    for _ in range(50):
        if not hppochta._tarqatma_band["id"]:
            break
        await asyncio.sleep(0.05)
    _, d = await so({"action": "royxat"})
    t = d["tarqatmalar"][0]
    check("tarixda: 2 kishi, 1 yetdi, 1 bloklagan, tugagan",
          t["jami"] == 2 and t["yetdi"] == 1 and t["bloklagan"] == 1 and t["tugadi"])
    check("sinov tarixda belgilangan", d["tarqatmalar"][1]["sinov"] is True)

    r = await hppochta.api_pochta(Req({"initData": "201", "action": "list"}))
    x = json.loads(r.body)["items"][0]
    check("ilovada xat matni bilan", x["tur"] == "xabar" and x["title"] == "Grifindor, oldindasiz!" and x["text"])

    # Bot xabarini o'chirgan odamga faqat ilovada
    _, d = await so({"action": "yubor", "sarlavha": "Sliterinlar", "kimga": {"tur": "odam", "uid": 203}})
    for _ in range(50):
        if not hppochta._tarqatma_band["id"]:
            break
        await asyncio.sleep(0.05)
    check("o'chirganga botdan yo'q", not [1 for u, _, _ in bot.sent if u == 203])
    r = await hppochta.api_pochta(Req({"initData": "203", "action": "list"}))
    check("lekin ilovada bor", json.loads(r.body)["unread"] == 1)


async def test_shaxsiy():
    """Shaxsiy xabar: o'qilmasa xat + bot, takrorida son oshadi, o'qisa yopiladi."""
    bot = FakeBot()
    hppochta._cfg.update({"bot": bot})
    for uid in (301, 302, 303):
        await hpcup.touch_user(uid, "Dm %d" % uid)
        await hpcup.set_house(uid, "ravenclaw", "Dm")
    room = "dm:301:302"
    kun = datetime(2026, 10, 5, 14, 0, tzinfo=hpcup.TASHKENT)
    tun = datetime(2026, 10, 5, 23, 30, tzinfo=hpcup.TASHKENT)

    m1 = await hpcup.post_chat_message(room, 301, "Salom, shaxmat o'ynaymizmi?", None)
    r = await hppochta.shaxsiy_ishla(302, 301, "Dm", "Salom, shaxmat o'ynaymizmi?", room, m1["id"], kut=0, hozir=tun)
    check("o'qilmadi - xat va bot xabari", r == "yuborildi")
    t, kw = bot.sent[-1][1], bot.sent[-1][2]
    check("bot xabarida ism va matn", "<b>Dm</b>" in t and "shaxmat" in t)
    kb = bot.sent[-1][2]
    check("tugma suhbatga olib boradi", "dm=301" in kb.inline_keyboard[0][0].web_app.url)

    m2 = await hpcup.post_chat_message(room, 301, "Javob bering", None)
    yuborildi = len(bot.sent)
    r = await hppochta.shaxsiy_ishla(302, 301, "Dm", "Javob bering", room, m2["id"], kut=0, hozir=tun)
    check("ikkinchisida yangi xat yo'q, bot jim", r == "ilovada" and len(bot.sent) == yuborildi)
    res = json.loads((await hppochta.api_pochta(Req({"initData": "302"}))).body)
    x = [i for i in res["items"] if i["tur"] == "dm"]
    check("ilovada bitta xat, 2 ta xabar, oxirgisi", len(x) == 1 and x[0]["n"] == 2 and x[0]["text"] == "Javob bering"
          and x[0]["from"] == 301 and x[0]["name"] == "Dm")

    await hpcup.mark_chat_read(room, 302, m2["id"])
    await hppochta.dm_oqidi(302, 301)
    res = json.loads((await hppochta.api_pochta(Req({"initData": "302"}))).body)
    check("suhbatni ochdi - xat yopildi", res["unread"] == 0)

    m3 = await hpcup.post_chat_message(room, 301, "Rahmat", None)
    await hpcup.mark_chat_read(room, 302, m3["id"])          # chatda turib o'qidi
    check("darhol o'qisa - xat yo'q", await hppochta.shaxsiy_ishla(302, 301, "Dm", "Rahmat", room, m3["id"], kut=0) is None)

    m4 = await hpcup.post_chat_message(room, 301, "Yana", None)
    yuborildi = len(bot.sent)
    r = await hppochta.shaxsiy_ishla(302, 301, "Dm", "Yana", room, m4["id"], kut=0)   # haqiqiy vaqt
    check("bir soat ichida - yangi xat bor, lekin bot yozmaydi", r == "ilovada" and len(bot.sent) == yuborildi)
    check("sinov o'quvchisiga yo'q", await hppochta.shaxsiy_ishla(-302, 301, "Dm", "x", room, 1, kut=0) is None)

    room2 = "dm:302:303"
    m5 = await hpcup.post_chat_message(room2, 303, "♟️ jang", None)
    r = await hppochta.shaxsiy_ishla(302, 303, "Uchinchi", "♟️ jang", room2, m5["id"], chess=True, kut=0, hozir=kun)
    check("shaxmat chaqiruvi alohida xat", r == "yuborildi" and "shaxmat" in bot.sent[-1][1].lower())


YOL_BARI = list(hppochta.YOL)

if __name__ == "__main__":
    asyncio.run(amain())
    asyncio.run(test_tarqatma())
    asyncio.run(test_shaxsiy())
    print("O'tdi: %d, xato: %d" % (ok, fail))
    sys.exit(1 if fail else 0)
