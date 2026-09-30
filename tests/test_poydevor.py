"""2026-09-30 tuzatishlari sinovi: imtihon aldovi, filmlar guruhdan, bosishlar
bazada, zaxira, qorovul, havola grammatikasi va Telegram imzosi.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
Hech qanday tarmoq va haqiqiy baza ishlatilmaydi - hammasi vaqtinchalik papkada.
"""
import asyncio
import glob
import hashlib
import hmac
import json
import os
import sqlite3
import subprocess
import sys
import tempfile
import time
import types
import urllib.parse
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-sinov-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

# Google Sheets tarmoqqa chiqmasin
sheets = types.ModuleType("sheets")
SHEET = []
async def _append(*a, **k): SHEET.append(a)
async def _none(*a, **k): return None
sheets.append_click = _append
sheets.read_csv = _none
sys.modules["sheets"] = sheets

import hpcup, hpevents, hpfilms, main   # noqa: E402

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


def db():
    return sqlite3.connect(os.environ["HP_DB_PATH"])


# ------------------------------------------------------------------ imtihon
async def test_exam():
    await hpcup.init(os.path.join(TMP, "yoq.json"))
    uid = 555
    await hpcup.touch_user(uid, "Sinov")
    season = await hpcup.current_season()
    t = await hpcup.get_user_tasks(uid)
    check("film ochilmagan - faqat kunlik", [x["id"] for x in t["tasks"]] == ["daily"])
    await hpcup.award(uid, "film_open", "1", 5)         # hpbot.award_film_open shunday yozadi
    t = await hpcup.get_user_tasks(uid)
    ids = [x["id"] for x in t["tasks"]]
    check("1-film ochilgach imtihon chiqadi (\"1\" ham tanilsin)", "quiz_hp1" in ids)
    check("to'g'ri javob ilovaga yuborilmaydi",
          not any("correct_index" in q for x in t["tasks"] for q in x["questions"]))
    right = dict(db().execute("SELECT id, correct_index FROM questions"))
    for qid in right:
        for tt in ("film_quiz", "daily", "chess_win"):
            await hpcup.submit_task_answer(uid, tt, qid, right[qid])
    st = await hpcup.user_stats(uid, season["id"])
    check("hamma savolni urinish - faqat qonuniy ball (5+30+10)", st["points"] == 45)
    r = await hpcup.submit_task_answer(uid, "film_quiz", 99999, 0)
    check("yo'q savol rad etiladi", r.get("ok") is False)


# ------------------------------------------------------------------ filmlar
def V(name, cap=""):
    return {"mid": 0, "name": name, "cap": cap, "size": 1, "dur": 1}

def test_films_names():
    cases = [
        ("Harry Potter and the Philosopher's Stone (2001)(1080p)(uz).mp4", "", "hp1", "uz"),
        ("Гарри_Поттер_и_Дары_Смерти_Часть_II_20111080p.mp4", "🇷🇺 Русский", "hp8", "ru"),
        ("Harry Potter and the Deathly Hallows Part 1 (2010)(1080p).mp4", "🇬🇧 English", "hp7", "en"),
        ("Fantastik maxluqlar 2.mp4", "Grindevaldning Jinoyatlari 🇺🇿 O'zbekcha", "fb2", "uz"),
        ("Fantastic_Beasts_The_Secrets_Of_Dumbledore_2022_1080p.mp4", "🇬🇧 English", "fb3", "en"),
    ]
    for name, cap, film, lang in cases:
        f, l, _ = hpfilms._guess(V(name, cap), None)
        check("nom: " + name[:40], (f, l) == (film, lang))
    check("4K qism chetlatiladi", hpfilms._skip(V("Harry_Potter_2160p_4K.mp4", "Philosopher's Stone [2]")))
    check("1080p chetlatilmaydi", not hpfilms._skip(V("Harry Potter (2001)(1080p).mp4")))


async def test_films_scan():
    hpfilms.STORE = os.path.join(TMP, "films.json")
    hpfilms.SCAN_PACE = 0
    hpfilms._data.update({"group": -1, "topics": {}, "map": {}, "seen": {}, "empty": [], "noaniq": []})
    NS = types.SimpleNamespace
    def vid(n, cap=""): return NS(video=NS(file_name=n, file_size=1, duration=1), document=None, caption=cap)
    msgs = {11: vid("Philosopher's Stone (2001).mp4"), 13: vid("Chamber of Secrets (uz).mp4"),
            21: vid("Гарри Поттер и философский камень рус.mkv"), 22: vid("Azkaban.mp4"),
            23: vid("Philosopher's Stone 2160p", "[2] 🇬🇧 English")}
    async def peek(bot, chat, mid, inbox): return msgs.get(mid)
    async def inbox(bot, note=None): return 1, 2
    old = (hpfilms.hpmusic._peek, hpfilms.hpmusic._inbox)
    hpfilms.hpmusic._peek, hpfilms.hpmusic._inbox = peek, inbox
    class Bot:
        async def delete_message(self, *a): pass
    hpfilms._cfg["bot"] = Bot()
    try:
        await hpfilms.scan(-1, 11, 24, "uz")
        _, tanilmagan = await hpfilms.scan(-1, 20, 24, "ru")
    finally:
        hpfilms.hpmusic._peek, hpfilms.hpmusic._inbox = old
    m = hpfilms._data["map"]
    check("tili nomida - ishonchli", m.get("hp2_uz", {}).get("by") == "nom" and m.get("hp1_ru", {}).get("mid") == 21)
    check("ikki mavzu oralig'idagi tilsiz video hech qayerga bog'lanmaydi",
          "hp3_uz" not in m and "hp3_ru" not in m and 22 in [x["mid"] for x in tanilmagan])
    check("4K qism bog'lanmaydi", "hp1_en" not in m)
    check("source guruhdan", hpfilms.source("hp2", "uz") == (-1, 13))
    hpfilms.rebuild()
    check("rebuild natijani saqlaydi", hpfilms.source("hp2", "uz") == (-1, 13) and "hp1_en" not in hpfilms._data["map"])


async def test_send_film_without_source():
    hpfilms._data["map"].pop("fb1_ru", None)
    check("guruhda yo'q film tayyor emas", main.film_ready("fb1", "ru") is False)
    try:
        await main.send_film(1, "fb1", "ru")
        check("bog'lanmagan film yuborilmasligi kerak", False)
    except Exception as e:
        check("xato matnida 'not found' (ilova film_missing ko'rsatadi)", "not found" in str(e))


# ------------------------------------------------------------------ bosishlar
async def test_events():
    users = os.path.join(TMP, "users_db.json")
    with open(users, "w", encoding="utf-8") as f:
        json.dump({"101": {"nickname": "Ali", "username": "@ali",
                           "clicks": {"start": ["2026-08-01 10:00:00"], "house_gryffindor": ["2026-08-02 11:00:00"]}}}, f)
    await hpevents.init(os.path.join(TMP, "topilmaydi.json"))
    check("fayl yo'q bo'lsa ko'chirildi deb belgilanmaydi", not hpevents.imported())
    await hpcup.init(users)
    await hpevents.init(users)
    await hpevents.init(users)
    check("tarix bir marta ko'chadi", db().execute("SELECT COUNT(*) FROM events").fetchone()[0] == 2)
    check("eski odam taniladi", await hpevents.known(101))
    check("yangi odam yangi", not await hpevents.known(999))
    await main.log_user_action(types.SimpleNamespace(id=999, full_name="Yangi", username=None), "hp2_uz", "web_hp2_uz")
    check("bosish bazaga yozildi", await hpevents.known(999))
    check("Sheets ga ham ketdi", SHEET and SHEET[-1][3] == "web_hp2_uz")
    c = db()
    c.execute("UPDATE users SET house='slytherin' WHERE user_id=101")
    c.commit()
    await hpcup.init(users)
    check("ko'chirishdan keyin JSON fakultetni qaytarmaydi", await hpcup.get_house(101) == "slytherin")


# ------------------------------------------------------------------ zaxira
def test_backup():
    base = os.path.join(TMP, "bk")
    os.makedirs(os.path.join(base, "data"))
    os.makedirs(os.path.join(base, "backups", "daily"))
    import shutil
    shutil.copy(os.path.join(ROOT, "backup_hp.py"), base)
    shutil.copy(os.environ["HP_DB_PATH"], os.path.join(base, "data", "hp.db"))
    with open(os.path.join(base, "data", "users_db.json"), "w") as f:
        f.write("{}")
    for i in range(8):
        p = os.path.join(base, "backups", "hp-before-x%d.db" % i)
        open(p, "w").close()
        os.utime(p, (time.time() - 40 * 86400,) * 2)
    for d in range(1, 17):
        open(os.path.join(base, "backups", "daily", "hp-2026-01-%02d.zip" % d), "w").close()
    subprocess.run([sys.executable, "backup_hp.py", "--test"], cwd=base, capture_output=True)
    daily = sorted(os.listdir(os.path.join(base, "backups", "daily")))
    today = "hp-%s.zip" % time.strftime("%Y-%m-%d")
    check("bugungi zaxira O'CHMAYDI (eski xato)", today in daily)
    check("kundalik 14 ta qoladi", len(daily) == 14)
    check("qo'lda olinganlardan eng yangi 5 tasi qoladi",
          len(glob.glob(os.path.join(base, "backups", "hp-before-*.db"))) == 5)
    with zipfile.ZipFile(os.path.join(base, "backups", "daily", today)) as z:
        check("arxivda baza va users_db.json", {"hp.db", "users_db.json"} <= set(z.namelist()))


# ------------------------------------------------------------------ qorovul
def test_watchdog():
    wd = os.path.join(TMP, "wd.json")
    code = ("import sys,types;sys.path.insert(0,%r);m=types.ModuleType('sheets');sys.modules['sheets']=m;"
            "import main;main.WATCHDOG_FILE=%r;main._watchdog(59998,grace=0,every=0.2,limit=3)" % (ROOT, wd))
    r = subprocess.run([sys.executable, "-c", code], capture_output=True, env=os.environ, timeout=60)
    check("javob yo'q - jarayon to'xtaydi (Docker qayta yoqadi)", r.returncode == 1)
    check("sababi yoziladi", os.path.exists(wd) and "veb-server" in open(wd).read())


# ------------------------------------------------------------------ havolalar va imzo
def test_links_and_auth():
    check("film havolasi", main.parse_payload("watch_hp3_uz-r12-skanal") == ("watch_hp3_uz", 12, "kanal"))
    check("reklama havolasi", main.parse_payload("src_marvel") == ("", None, "marvel"))
    check("film va til", main.film_va_til("web_hp1_en") == ("hp1", "en"))
    check("noto'g'ri film", main.film_va_til("hp9_uz") == (None, None))
    tok = os.environ["BOT_TOKEN"]
    data = {"auth_date": str(int(time.time())), "user": json.dumps({"id": 7, "first_name": "A"})}
    chk = "\n".join("%s=%s" % (k, data[k]) for k in sorted(data))
    secret = hmac.new(b"WebAppData", tok.encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, chk.encode(), hashlib.sha256).hexdigest()
    good = urllib.parse.urlencode(data)
    check("to'g'ri imzo", (main.verify_init_data(good) or {}).get("id") == 7)
    data["hash"] = "0" * 64
    check("soxta imzo rad etiladi", main.verify_init_data(urllib.parse.urlencode(data)) is None)


async def amain():
    await test_exam()
    test_films_names()
    await test_films_scan()
    await test_send_film_without_source()
    await test_events()


if __name__ == "__main__":
    asyncio.run(amain())
    test_backup()
    test_watchdog()
    test_links_and_auth()
    print("O'tdi: %d, xato: %d" % (ok, fail))
    sys.exit(1 if fail else 0)
