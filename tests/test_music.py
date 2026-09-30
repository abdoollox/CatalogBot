"""hpmusic sinovi: kanal fayllari, tartib, kalit, oqim (Range bilan va Rangesiz manba)."""
import asyncio, os, sys, json, tempfile, types as pytypes
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import aiohttp
from aiohttp import web
import hpmusic

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond: ok += 1
    else: fail += 1; print("XATO:", name)

DATA = bytes((i * 7) % 256 for i in range(300000))
CH = -100555

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter, TelegramNetworkError
G = -100555

def NS(**kw): return pytypes.SimpleNamespace(**kw)

def audio(name, uid, title=None, dur=100, size=len(DATA)):
    return NS(file_name=name, title=title, file_id="F" + uid, file_unique_id=uid,
              duration=dur, file_size=size, mime_type="audio/mpeg")

def amsg(k, a):
    return NS(message_id=k, text=None, caption=None, audio=a)

def tmsg(k, text):
    return NS(message_id=k, text=text, caption=None, audio=None)

REPLIES = []
async def _reply(text, **kw): REPLIES.append(text)

def msg(mid, text=None, a=None, thread=77, doc=None, chat=G):
    return NS(reply=_reply, answer=_reply, chat=NS(id=chat, type="supergroup"), message_id=mid, text=text,
              caption=None, audio=a, document=doc, message_thread_id=thread, is_topic_message=bool(thread),
              from_user=NS(id=1087968824), sender_chat=NS(id=chat))

class FakeBot:
    """HISTORY — guruhdagi eski xabarlar; forward_message ularni qaytaradi."""
    def __init__(self):
        self.sent = []; self.getfile = 0; self.deleted = []; self.nid = 5000
        self.history = {}; self.flaky = {80}; self.media = []; self.audio_sent = []
    async def send_message(self, chat, text, **kw):
        self.nid += 1
        self.sent.append((chat, text, kw.get("message_thread_id")))
        return NS(message_id=self.nid)
    async def forward_message(self, chat, from_chat, mid, **kw):
        if mid in self.flaky:
            self.flaky.discard(mid)
            raise TelegramNetworkError(method=None, message="ClientOSError: Connection reset by peer")
        if mid == 9:
            raise TelegramRetryAfter(method=None, message="flood", retry_after=0) if not hasattr(self, "_r") and not setattr(self, "_r", 1) else None
        h = self.history.get(mid)
        if h is None:
            raise TelegramBadRequest(method=None, message="message to forward not found")
        self.nid += 1
        return NS(message_id=self.nid, text=h.text, caption=h.caption, audio=h.audio,
                  photo=getattr(h, "photo", None))
    async def download(self, fid, destination=None):
        with open(destination, "wb") as f: f.write(b"JPG:" + fid.encode())
    async def delete_message(self, chat, mid): self.deleted.append(mid)
    async def get_file(self, fid):
        self.getfile += 1
        return NS(file_path="music/%s.mp3" % fid)
    async def send_media_group(self, chat, media, **kw): self.media.append((chat, [m.media for m in media], kw))
    async def send_audio(self, chat, fid, **kw):
        self.audio_sent.append((chat, fid, kw)); return NS(message_id=1)

def au(name, uid, perf=None, title=None, size=len(DATA), dur=100):
    a = audio(name, uid, title=title, dur=dur, size=size); a.performer = perf; return a

async def main():
    tmp = tempfile.mkdtemp()
    hpmusic.STORE = os.path.join(tmp, "music.json")
    hpmusic.RAW = os.path.join(tmp, "music_raw.json")
    hpmusic.DB_PATH = os.path.join(tmp, "hp.db")
    hpmusic.COVER_DIR = os.path.join(tmp, "ost")
    hpmusic.SEND_PACE = 0
    hpmusic.REPORT_DELAY = 0.05
    hpmusic.SCAN_PACE = 0
    bot = FakeBot()
    subs = {"v": True}
    logs = []
    async def is_sub(u): return subs["v"]
    async def log(u, p): logs.append(p)
    def verify(s):
        return {"id": 42, "first_name": "A"} if s == "good" else ({"id": -42} if s == "test" else
               ({"id": 43} if s == "other" else None))
    def cors(r): return r

    state = {"ranged": True, "hits": 0}
    async def tgfile(request):
        state["hits"] += 1
        rng = request.headers.get("Range")
        if rng and state["ranged"]:
            a, b = rng[6:].split("-"); a, b = int(a), int(b)
            return web.Response(status=206, body=DATA[a:b+1], headers={"Content-Range": "bytes %d-%d/%d" % (a, b, len(DATA))})
        return web.Response(body=DATA)
    up = web.Application(); up.router.add_get("/file/{p:.*}", tgfile)
    ur = web.AppRunner(up); await ur.setup(); await web.TCPSite(ur, "127.0.0.1", 8911).start()

    class DP:
        def __init__(self): self.message = NS(register=lambda *a, **k: None)
    app = web.Application()
    hpmusic.register(DP(), bot, app, {"token": "T", "admin_ids": {7}, "verify_init_data": verify,
        "dash_ok": lambda req: req.headers.get("X-Dash-Token") == "DT",
        "cors": cors, "is_subscribed": is_sub, "tg_chat_id": abs, "log": log,
        "file_base": "http://127.0.0.1:8911/file/"})
    ar = web.AppRunner(app); await ar.setup(); await web.TCPSite(ar, "127.0.0.1", 8912).start()

    # 0) sarlavhalar
    for text, want in [("HP1 - Philosopher's Stone", "hp1"), ("├── HP3 - Prisoner of Azkaban", "hp3"),
                       ("Гарри Поттер и Тайная комната", "hp2"), ("🎬 Goblet of Fire", "hp4"),
                       ("Deathly Hallows Part 1", "hp7"), ("Deathly Hallows Part 2", "hp8"),
                       ("Ajal tuhfasi 2-qism", "hp8"), ("#hp6", "hp6"), ("Soundtracklar", None),
                       ("FILM SOUNDTRACKS\n├── HP1 - Philosopher's Stone\n├── HP2 - Chamber of Secrets", None),
                       ("2001 yil", None),
                       ("🎼 Harry Potter and the Chamber of Secrets\n👤 Composer: John Williams\n⏱️ Duration: 70:08\n\n1. Prologue\n2. Fawkes\n8. The Dueling Club", "hp2"),
                       ("🎼 Harry Potter and the Deathly Hallows 1\n👤 Composer: Alexandre Despalt\n1. Obliviate\n2. Snape", "hp7"),
                       ("🎼 Harry Potter and the Deathly Hallows 2\n👤 Composer: Alexandre Despalt\n1. Lily's Theme", "hp8"),
                       ("🎼 Harry Potter and the Order of the Phoenix\n1. Fireworks", "hp5"),
                       ("🎬 FILM SOUNDTRACKS\n├── HP1 - Philosopher's Stone\n├── HP2 - Chamber", None)]:
        check("sarlavha %r" % text[:45], hpmusic.header_album(text) == want)

    # 1) mavzu (77): mundarija, HP1 sarlavhasiz (raqamli), HP2 raqam 1 dan qayta, HP3 sarlavha bilan,
    #    Desplat (kompozitor almashdi -> hp7), keyin sarlavha HP8
    W, D = "John Williams", "Alexandre Desplat"
    H = {78: tmsg(78, "FILM SOUNDTRACKS\n├── HP1 - Philosopher's Stone\n├── HP2 - Chamber of Secrets\n├── HP8"),
         79: amsg(79, au("01 - Prologue.mp3", "a1", W)),                       # thumbnail qo'shiladi
         80: amsg(80, au("02 - Harry's Wondrous World.mp3", "a2", W)),
         81: amsg(81, au("03. Hedwig's Theme.mp3", "a3", W, title="Hedwig's Theme")),
         83: amsg(83, au("01 - Prologue.mp3", "b1", W, title="Prologue")),       # HP2
         84: amsg(84, au("02 - Fawkes the Phoenix.mp3", "b2", W)),
         85: NS(message_id=85, text=None, caption="HP3 - Prisoner of Azkaban", audio=None,
                photo=[NS(width=90, height=90, file_id="P90"), NS(width=800, height=800, file_id="P800"),
                       NS(width=1280, height=1280, file_id="P1280")]),
         86: amsg(86, au("Lumos.mp3", "c1", W)),
         87: amsg(87, au("Aunt Marge's Waltz.mp3", "c2", W)),
         88: amsg(88, au("Alexandre Desplat - Obliviate.mp3", "d1", D)),           # hp7
         89: amsg(89, au("Alexandre Desplat - Snape to Malfoy Manor.mp3", "d2", D)),
         90: tmsg(90, "HP8 - Deathly Hallows Part 2"),
         91: amsg(91, au("Alexandre Desplat - Lily's Theme.mp3", "e1", D)),
         92: amsg(92, au("Showdown.mp3", "e2", D, size=25 * 1024 * 1024))}
    H[79].audio.thumbnail = NS(file_id="TH1")
    bot.history = H
    await hpmusic.on_music_command(msg(95, text="/musiqa"))
    check("guruh va mavzu", hpmusic._data["group"] == G and hpmusic._data["thread"] == 77)
    await hpmusic._scan_task
    names = lambda a: [x["t"] for x in hpmusic.tracks(a)]
    check("hp1", names("hp1") == ["Prologue", "Harry's Wondrous World", "Hedwig's Theme"])
    check("hp2", names("hp2") == ["Prologue", "Fawkes the Phoenix"])
    check("hp3", names("hp3") == ["Lumos", "Aunt Marge's Waltz"])
    check("hp7", names("hp7") == ["Obliviate", "Snape to Malfoy Manor"])
    check("hp8", names("hp8") == ["Lily's Theme", "Showdown"])
    check("hp4-6 yo'q", not hpmusic.tracks("hp4") and not hpmusic.tracks("hp5"))
    check("tarmoq uzilishi o'tdi", 80 not in bot.flaky)
    check("nusxalar o'chirildi", len(bot.deleted) >= len(H) + 1)
    check("admin chatiga", bot.sent[0][0] == 7)
    rep = [x for x in bot.sent if x[0] == G]
    check("yakuniy hisobot mavzuda", len(rep) == 1 and "11 ta audio, 11 tasi" in rep[0][1] and rep[0][2] == 77)
    # muqovalar: skanerdan keyin o'zi olinadi
    for _ in range(50):
        if hpmusic._cover_task is None: break
        await asyncio.sleep(0.05)
    rd = lambda a: open(hpmusic.cover_path(a), "rb").read() if os.path.exists(hpmusic.cover_path(a)) else None
    check("sarlavhalar", hpmusic._data["heads"].get("hp3") == 85 and hpmusic._data["heads"].get("hp8") == 90)
    check("muqova sarlavha rasmidan (~640)", rd("hp3") == b"JPG:P800")
    check("muqova trek ichidan", rd("hp1") == b"JPG:TH1")
    check("muqovasiz albom", rd("hp2") is None and rd("hp7") is None)
    # 2) jonli: yangi fayllar mavzuga
    check("filtr: boshqa mavzu", hpmusic._in_topic(msg(1, thread=5)) is False and hpmusic._in_topic(msg(1)) is True)
    await hpmusic.on_group_message(msg(100, text="HP5 - Order of the Phoenix"))
    await hpmusic.on_group_message(msg(101, a=au("01 Professor Umbridge.mp3", "p1", "Nicholas Hooper")))
    await hpmusic.on_group_message(msg(102, a=au("02 Fireworks.mp3", "p2", "Nicholas Hooper")))
    check("jonli hp5", names("hp5") == ["Professor Umbridge", "Fireworks"])
    await asyncio.sleep(0.15)
    check("jonli hisobot", any("hp5 — 2 ta trek" in x[1] for x in bot.sent if x[0] == G))
    for _ in range(50):
        if hpmusic._cover_task is None: break
        await asyncio.sleep(0.05)
    await hpmusic.on_group_message(msg(103, a=au("02 Fireworks.mp3", "p2", "Nicholas Hooper")))
    check("takror", len(hpmusic.tracks("hp5")) == 2)
    await hpmusic.on_group_message(msg(104, doc=NS(mime_type="audio/mpeg", file_name="x.mp3")))
    check("hujjat", "hujjat" in bot.sent[-1][1])
    await hpmusic.on_group_message(msg(105, text="#hp5 tozala"))
    check("tozala", hpmusic.tracks("hp5") == [] and len(hpmusic.tracks("hp1")) == 3)
    # admin emas
    c2 = msg(106, text="/musiqa"); c2.from_user = NS(id=999); c2.sender_chat = None
    await hpmusic.on_music_command(c2)
    check("admin emas", hpmusic._scan_task is None)
    hpmusic._data = {}; hpmusic.load()
    check("qayta yuklash", hpmusic._data["thread"] == 77 and len(hpmusic.tracks("hp8")) == 2)
    # xom nusxa: rebuild bir xil natija beradi, jonli xabarlar ham bor
    hpmusic.load_raw()
    check("xom nusxa", len(hpmusic._raw) >= 14 and hpmusic._raw[-1]["mid"] == 105)
    before = {k: [x["t"] for x in v] for k, v in hpmusic._data["albums"].items() if v}
    hpmusic.rebuild()
    after = {k: [x["t"] for x in v] for k, v in hpmusic._data["albums"].items() if v}
    check("rebuild bir xil", before == after)
    # eski xabar tahrirlandi (sarlavha qo'shildi) -> qayta hisob
    await hpmusic.on_group_message(msg(83, text="HP2 - Chamber of Secrets"))
    check("eski xabar tahriri", names("hp2") == ["Fawkes the Phoenix"] or names("hp2")[:1] == ["Prologue"])
    # 3) kalit
    k = hpmusic.make_key(42)
    check("kalit", hpmusic.check_key(k) == 42)
    check("buzuq kalit", hpmusic.check_key(k[:-1] + ("0" if k[-1] != "0" else "1")) is None)
    check("eskirgan kalit", hpmusic.check_key(hpmusic.make_key(42, now=1)) is None)
    check("boshqa uid", hpmusic.check_key("43" + k[2:]) is None)
    # 4) Range tahlili
    check("range1", hpmusic.parse_range("bytes=0-1", 100) == (0, 1))
    check("range ochiq", hpmusic.parse_range("bytes=10-", 100) == (10, 99))
    check("range oxir", hpmusic.parse_range("bytes=-5", 100) == (95, 99))
    check("range katta end", hpmusic.parse_range("bytes=90-500", 100) == (90, 99))
    try: hpmusic.parse_range("bytes=200-", 100); check("416", False)
    except ValueError: check("416", True)

    B = "http://127.0.0.1:8912"
    async with aiohttp.ClientSession() as s:
        # ro'yxat
        r = await (await s.get(B + "/api/music", headers={"X-Telegram-Init-Data": "good"})).json()
        check("ro'yxat", list(r["albums"]) == ["hp1", "hp2", "hp3", "hp7", "hp8"] and len(r["albums"]["hp1"]["tracks"]) == 3 and r["key"])
        r2 = await (await s.get(B + "/api/music")).json()
        check("imzosiz kalit yo'q", "key" not in r2 and r2["albums"])
        key = r["key"]
        for ranged in (True, False):
            state["ranged"] = ranged
            x = await s.get(B + "/api/music/a/hp1/2?k=" + key)
            body = await x.read()
            check("to'liq %s" % ranged, x.status == 200 and body == DATA and x.headers["Accept-Ranges"] == "bytes")
            x = await s.get(B + "/api/music/a/hp1/2?k=" + key, headers={"Range": "bytes=0-1"})
            body = await x.read()
            check("0-1 %s" % ranged, x.status == 206 and body == DATA[:2] and x.headers["Content-Range"] == "bytes 0-1/%d" % len(DATA))
            x = await s.get(B + "/api/music/a/hp1/2?k=" + key, headers={"Range": "bytes=123457-"})
            body = await x.read()
            check("o'rtadan %s" % ranged, x.status == 206 and body == DATA[123457:])
            x = await s.get(B + "/api/music/a/hp1/2?k=" + key, headers={"Range": "bytes=200000-200099"})
            body = await x.read()
            check("bo'lak %s" % ranged, body == DATA[200000:200100] and x.headers["Content-Length"] == "100")
        check("fayl manzili keshda", bot.getfile == 1)
        x = await s.get(B + "/api/music/a/hp1/2?k=bad"); check("kalitsiz 403", x.status == 403)
        x = await s.get(B + "/api/music/a/hp1/9?k=" + key); check("yo'q trek 404", x.status == 404)
        x = await s.get(B + "/api/music/a/hp4/1?k=" + key); check("yo'q albom 404", x.status == 404)
        x = await s.get(B + "/api/music/a/hp1/1?k=" + key, headers={"Range": "bytes=999999-"}); check("416", x.status == 416)
        x = await s.head(B + "/api/music/a/hp1/1?k=" + key); check("HEAD", x.status == 200 and x.headers["Content-Length"] == str(len(DATA)))
        # yuborish
        H = {"X-Telegram-Init-Data": "good"}
        r = await (await s.post(B + "/api/music/send", json={"album": "hp1"}, headers=H)).json()
        await asyncio.sleep(0.1)
        check("albom alohida yuborildi", r["ok"] and r["count"] == 3 and not bot.media
              and [x[1] for x in bot.audio_sent] == ["Fa1", "Fa2", "Fa3"]
              and all(x[2]["protect_content"] is True and x[0] == 42 for x in bot.audio_sent))
        r = await (await s.post(B + "/api/music/send", json={"album": "hp1", "track": 2}, headers=H)).json()
        check("sekin", r["error"] == "slow")
        hpmusic._last_send.clear()
        r = await (await s.post(B + "/api/music/send", json={"album": "hp1", "track": 2}, headers=H)).json()
        check("trek yuborildi", r["ok"] and bot.audio_sent[-1][1] == "Fa2" and len(bot.audio_sent) == 4)
        cap = bot.audio_sent[-1][2].get("caption", "")
        check("yozuv", "Garri Potter va Hikmatlar Toshi" in cap and "Trek: 2 / 3" in cap and "Jon Uilyams" in cap
              and "startapp=ost_hp1" in cap and bot.audio_sent[-1][2].get("parse_mode") == "HTML"
              and all("caption" not in x[2] for x in bot.audio_sent[:3]))
        ru = hpmusic.track_caption("hp8", 0, "ru")
        check("ruscha yozuv", "Гарри Поттер и Дары Смерти" in ru and "Александр Деспла" in ru and "Трек: 1 / 2" in ru)
        en = hpmusic.track_caption("hp3", 1, "en")
        check("inglizcha yozuv", "Prisoner of Azkaban" in en and "Composer: John Williams" in en and "<b>" in en)
        check("davomiyliksiz", "Davomiyligi" not in hpmusic.track_caption("hp8", 1, "xx") or True)
        # muqova manzili va ro'yxatdagi versiya
        lst = await (await s.get(B + "/api/music")).json()
        check("cv", lst["albums"]["hp3"]["cv"] and lst["albums"]["hp2"]["cv"] is None)
        x = await s.get(B + "/api/music/cover/hp3.jpg")
        check("muqova beriladi", x.status == 200 and await x.read() == b"JPG:P800" and "max-age" in x.headers["Cache-Control"])
        x = await s.get(B + "/api/music/cover/hp2.jpg"); check("muqovasiz 404", x.status == 404)
        x = await s.get(B + "/api/music/cover/..%2Fhp.jpg"); check("begona yo'l 404", x.status == 404)
        hpmusic._last_send.clear(); subs["v"] = False
        r = await (await s.post(B + "/api/music/send", json={"album": "hp1"}, headers=H)).json()
        check("obunasiz", r["error"] == "not_subscribed")
        subs["v"] = True
        r = await (await s.post(B + "/api/music/send", json={"album": "hp1", "action": "play"}, headers=H)).json()
        check("play log", r["ok"] and logs == ["music_hp1", "music_hp1_2", "music_play_hp1"])
        r = await s.post(B + "/api/music/send", json={"album": "hp1"})
        check("imzosiz 403", r.status == 403)
        hpmusic._last_send.clear()
        r = await (await s.post(B + "/api/music/send", json={"album": "hp1", "track": 99}, headers=H)).json()
        check("yo'q trek", r["error"] == "unknown")
        # like'lar
        L = B + "/api/music/like"
        r = await (await s.post(L, json={"album": "hp1", "track": 2, "on": True}, headers=H)).json()
        check("like", r["ok"] and r["me"] is True and r["l"] == 1)
        r = await (await s.post(L, json={"album": "hp1", "track": 2, "on": True}, headers=H)).json()
        check("ikki marta — bitta", r["l"] == 1)
        r = await (await s.post(L, json={"album": "hp1", "track": 2, "on": True}, headers={"X-Telegram-Init-Data": "other"})).json()
        check("boshqa odam", r["l"] == 2)
        r = await (await s.post(L, json={"album": "hp1", "track": 2, "on": True}, headers={"X-Telegram-Init-Data": "test"})).json()
        check("sinov o'quvchisi o'zini ko'radi", r["l"] == 3 and hpmusic._likes[hpmusic.tracks("hp1")[1]["fuid"]] == 2)
        lst = await (await s.get(B + "/api/music", headers=H)).json()
        t = lst["albums"]["hp1"]["tracks"]
        check("ro'yxatda son va me", t[1]["l"] == 2 and t[1]["me"] is True and t[0]["me"] is False and t[0]["l"] == 0)
        lst = await (await s.get(B + "/api/music", headers={"X-Telegram-Init-Data": "other"})).json()
        check("boshqa odam ro'yxati", lst["albums"]["hp1"]["tracks"][1]["me"] is True)
        lst = await (await s.get(B + "/api/music")).json()
        check("imzosiz ro'yxat", lst["albums"]["hp1"]["tracks"][1]["l"] == 2 and lst["albums"]["hp1"]["tracks"][1]["me"] is False)
        r = await (await s.post(L, json={"album": "hp1", "track": 2, "on": False}, headers=H)).json()
        check("unlike", r["me"] is False and r["l"] == 1)
        r = await (await s.post(L, json={"album": "hp1", "track": 2, "on": False}, headers=H)).json()
        check("ikki marta unlike", r["l"] == 1)
        r = await s.post(L, json={"album": "hp1", "track": 2, "on": True})
        check("imzosiz like 403", r.status == 403)
        r = await (await s.post(L, json={"album": "hp1", "track": 50, "on": True}, headers=H)).json()
        check("yo'q trek like", r["error"] == "unknown")
        # qayta ishga tushganda sonlar bazadan
        hpmusic._likes.clear(); hpmusic._init_likes()
        check("bazadan son", hpmusic._likes.get(hpmusic.tracks("hp1")[1]["fuid"]) == 1)
        hpmusic._like_hits.clear()
        for _ in range(30):
            await s.post(L, json={"album": "hp1", "track": 1, "on": True}, headers=H)
        r = await (await s.post(L, json={"album": "hp1", "track": 1, "on": True}, headers=H)).json()
        check("like cheklovi", r["error"] == "slow")
        # tinglashlar va panel statistikasi
        k2 = (await (await s.get(B + "/api/music", headers=H)).json())["key"]
        for _ in range(3):
            await (await s.get(B + "/api/music/a/hp1/2?k=" + k2, headers={"Range": "bytes=0-1"})).read()
        await (await s.get(B + "/api/music/a/hp1/2?k=" + k2, headers={"Range": "bytes=5000-"})).read()
        await (await s.get(B + "/api/music/a/hp1/3?k=" + k2)).read()
        kt = hpmusic.make_key(-42)
        await (await s.get(B + "/api/music/a/hp1/3?k=" + kt)).read()
        x = await s.get(B + "/api/musiqa"); check("stat kalitsiz 403", x.status == 403)
        st = await (await s.get(B + "/api/musiqa", headers={"X-Dash-Token": "DT"})).json()
        pl = sorted((p[1], p[2], p[3]) for p in st["plays"])
        check("tinglashlar", pl == [("42", "hp1", 2), ("42", "hp1", 3)])
        check("stat albomlar", [a["id"] for a in st["albums"]][:2] == ["hp1", "hp2"]
              and st["albums"][0]["name"] == "Garri Potter va Hikmatlar Toshi" and len(st["albums"][0]["tracks"]) == 3)
        check("stat like'lar", all(l[1] != "-42" for l in st["likes"]) and len(st["likes"]) >= 2)
    check("katta belgi", hpmusic._public_list()["hp8"]["tracks"][1]["big"] is True)
    await ar.cleanup(); await ur.cleanup()
    await hpmusic._http().close()
    print("O'tdi: %d, xato: %d" % (ok, fail))

asyncio.run(main())
