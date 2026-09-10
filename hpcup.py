"""Xogvarts kubogi — SQLite qatlami (spetsifikatsiya 2.0).

Haftalik fakultetlar musobaqasi: ball, mavsum, savol, nishon.
Bu modul faqat baza bilan ishlaydi — Telegram yoki HTTP haqida bilmaydi.

sqlite3 bloklovchi kutubxona, aiogram esa async. Shuning uchun har bir
ochiq funksiya `asyncio.to_thread` orqali chaqiriladi (sheets.py kabi).
Sinxron variantlari `_` bilan boshlanadi va faqat shu modul ichida ishlatiladi.

2.0 da o'zgargani:
  - fakultet endi `users` jadvalida va UMRBOD (o'zgarmaydi)
  - `points.house` olib tashlandi — fakultet o'zgarmagani uchun keraksiz
  - faol a'zo = mavsumda kamida 30 ball (avval 1 ball edi)
"""

import os
import json
import random
import sqlite3
import asyncio
import logging
from datetime import datetime, timedelta, timezone

# Docker volume ichida bo'lishi SHART - aks holda konteyner yangilanganda
# barcha ballar yo'qoladi.
DB_PATH = os.getenv("HP_DB_PATH", "/data/hp.db")

TASHKENT = timezone(timedelta(hours=5))

# --- Ball qiymatlari ---
PTS_FILM_OPEN = 5     # har qism uchun mavsumda 1 marta   -> 8 * 5  = 40
PTS_FILM_QUIZ = 10    # har to'g'ri javob                 -> 24 * 10 = 240
PTS_DAILY = 10        # kuniga 1 marta                    -> 7 * 10  = 70

# Shaxmat FAQAT jonli o'yinda (PvP) ballanadi. Bot bilan o'ynash ball
# bermaydi: o'zi bilan o'zi o'ynab cheksiz ball yig'ish mumkin bo'lardi.
PTS_CHESS_WIN = 10    # jonli raqib ustidan g'alaba
PTS_CHESS_DRAW = 5    # durang

# Do'st taklif qilish: taklif qilingan odam kanalga obuna bo'lganda. Mavsum
# chegarasiga (MAX_POINTS) kirmaydi - har bir do'st haqiqiy yangi obunachi,
# uni soxtalashtirish qiyin, shuning uchun cheklanmaydi.
PTS_REFERRAL = 20

# Mavsumda nechta shaxmat natijasi ballanadi. Cheklov SHART: kim yutganini
# server tekshira olmaydi (o'yin brauzerda hisoblanadi), shuning uchun ikki
# do'st bir-biriga ataylab yutqazib cheksiz ball yig'a olardi.
CHESS_MAX_PER_SEASON = 5

FILM_PARTS = 8
QUIZ_PER_FILM = 3
DAILY_PER_WEEK = 7

# Bir mavsumda olish mumkin bo'lgan eng ko'p ball
MAX_POINTS = (PTS_FILM_OPEN * FILM_PARTS
              + PTS_FILM_QUIZ * FILM_PARTS * QUIZ_PER_FILM
              + PTS_DAILY * DAILY_PER_WEEK
              + PTS_CHESS_WIN * CHESS_MAX_PER_SEASON)   # = 400

ACTIVE_MIN_POINTS = 30    # foydalanuvchi "faol" hisoblanishi uchun kerak ball

HOUSES = ("gryffindor", "slytherin", "ravenclaw", "hufflepuff")
BADGE_CODES = ("all_films", "flawless_exam", "perfect_week", "streak_7")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    first_name  TEXT,
    house       TEXT,
    sorted_at   TEXT,
    created_at  TEXT NOT NULL,
    lang        TEXT
);

CREATE TABLE IF NOT EXISTS seasons (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    starts_at    TEXT NOT NULL,
    ends_at      TEXT NOT NULL,
    status       TEXT NOT NULL CHECK (status IN ('active','closed')),
    winner_house TEXT
);

CREATE TABLE IF NOT EXISTS points (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL REFERENCES users(user_id),
    season_id   INTEGER NOT NULL REFERENCES seasons(id),
    source_type TEXT NOT NULL CHECK (source_type IN
                    ('film_open','film_quiz','daily','chess_win','chess_draw',
                     'referral')),
    source_ref  TEXT NOT NULL,
    points      INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (user_id, season_id, source_type, source_ref)
);

CREATE INDEX IF NOT EXISTS idx_points_season_user ON points(season_id, user_id);

CREATE TABLE IF NOT EXISTS questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL CHECK (kind IN ('film','daily')),
    film_part     INTEGER,
    lang          TEXT NOT NULL DEFAULT 'uz',
    body          TEXT NOT NULL,
    options       TEXT NOT NULL,
    correct_index INTEGER NOT NULL,
    is_active     INTEGER NOT NULL DEFAULT 1
);

CREATE TABLE IF NOT EXISTS question_assignments (
    user_id     INTEGER NOT NULL,
    season_id   INTEGER NOT NULL REFERENCES seasons(id),
    film_part   INTEGER NOT NULL,
    question_id INTEGER NOT NULL REFERENCES questions(id),
    PRIMARY KEY (user_id, season_id, film_part, question_id)
);

CREATE TABLE IF NOT EXISTS answers (
    user_id     INTEGER NOT NULL,
    season_id   INTEGER NOT NULL REFERENCES seasons(id),
    question_id INTEGER NOT NULL REFERENCES questions(id),
    is_correct  INTEGER NOT NULL,
    answered_at TEXT NOT NULL,
    PRIMARY KEY (user_id, season_id, question_id)
);

CREATE TABLE IF NOT EXISTS daily_schedule (
    date        TEXT PRIMARY KEY,
    question_id INTEGER NOT NULL REFERENCES questions(id)
);

CREATE TABLE IF NOT EXISTS chat_messages (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    house        TEXT NOT NULL,
    user_id      INTEGER NOT NULL,
    message      TEXT NOT NULL,
    created_at   TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_chat_house_id ON chat_messages(house, id);

-- Chatda bloklanganlar (admin qo'yadi). until NULL - butunlay.
CREATE TABLE IF NOT EXISTS chat_bans (
    user_id   INTEGER PRIMARY KEY,
    banned_by INTEGER,
    banned_at TEXT NOT NULL,
    until     TEXT
);

-- Har odam har xonada qaysi xabargacha o'qigani.
CREATE TABLE IF NOT EXISTS chat_reads (
    user_id INTEGER NOT NULL,
    room    TEXT NOT NULL,
    last_id INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, room)
);

CREATE TABLE IF NOT EXISTS chat_reactions (
    message_id INTEGER NOT NULL,
    user_id    INTEGER NOT NULL,
    emoji      TEXT NOT NULL,
    PRIMARY KEY (message_id, user_id)
);

CREATE TABLE IF NOT EXISTS badges (
    user_id   INTEGER NOT NULL,
    code      TEXT NOT NULL,
    season_id INTEGER REFERENCES seasons(id),
    earned_at TEXT NOT NULL,
    PRIMARY KEY (user_id, code, season_id)
);

-- Spetsifikatsiyada yo'q, lekin kerak: qayta saralanish muhlati shu yerda
-- saqlanadi (xabar yuborilgan kunda yoziladi, 7 kundan keyin tugaydi).
CREATE TABLE IF NOT EXISTS settings (
    key   TEXT PRIMARY KEY,
    value TEXT
);

CREATE TABLE IF NOT EXISTS chess_games (
    id           TEXT PRIMARY KEY,
    white_uid    INTEGER NOT NULL,
    black_uid    INTEGER,
    fen          TEXT NOT NULL,
    turn         TEXT NOT NULL DEFAULT 'w',
    status       TEXT NOT NULL DEFAULT 'waiting',
    winner_uid   INTEGER,
    win_reason   TEXT,
    white_time   INTEGER NOT NULL DEFAULT 300,
    black_time   INTEGER NOT NULL DEFAULT 300,
    last_move_at TEXT,
    created_at   TEXT NOT NULL
);
"""

RESORT_KEY = "resort_until"


# ---------------------------------------------------------------- vaqt

def now_tk():
    """Hozirgi vaqt, Toshkent mintaqasida."""
    return datetime.now(TASHKENT)


def today_tk():
    """Bugungi sana 'YYYY-MM-DD', Toshkent vaqti bo'yicha."""
    return now_tk().strftime("%Y-%m-%d")


def _utc_iso(dt):
    """Mintaqali vaqtni '...Z' ko'rinishidagi UTC ISO matnga o'giradi."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _parse_iso(text):
    try:
        return datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def season_bounds(moment=None):
    """Berilgan payt tushadigan haftaning chegaralari.

    Dushanba 00:00 dan yakshanba 23:59 gacha (Toshkent), UTC ISO matnda.
    """
    moment = (moment or now_tk()).astimezone(TASHKENT)
    monday = (moment - timedelta(days=moment.weekday())).replace(
        hour=0, minute=0, second=0, microsecond=0)
    sunday_end = monday + timedelta(days=6, hours=23, minutes=59)
    return _utc_iso(monday), _utc_iso(sunday_end)


# ---------------------------------------------------------------- ulanish

def _connect():
    folder = os.path.dirname(DB_PATH)
    if folder and not os.path.isdir(folder):
        os.makedirs(folder, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn


# ---------------------------------------------------------------- migratsiya

def _houses_from_json(path):
    """users_db.json dan (user_id, house, sorted_at, first_name) ro'yxatini oladi.

    Fakultet u yerda `clicks` ichida `house_<nom>` hodisasi sifatida yotadi.
    Bir necha marta saralanganlar bor — eng OXIRGISI olinadi.
    """
    out = []
    try:
        with open(path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        return out

    for uid, rec in db.items():
        best_time, best_house = None, None
        for key, stamps in (rec.get("clicks") or {}).items():
            if not key.startswith("house_") or not stamps:
                continue
            name = key[len("house_"):]
            if name not in HOUSES:
                continue
            when = max(stamps)
            if best_time is None or when > best_time:
                best_time, best_house = when, name
        nick = (rec.get("nickname") or "").strip()
        first_name = nick.split()[0] if nick else None
        uname = (rec.get("username") or "").replace("@", "").strip()
        if uname.lower() in ("yo'q", "none", ""):
            uname = None
            
        if best_house:
            try:
                out.append((int(uid), best_house, best_time, first_name, uname))
            except (TypeError, ValueError):
                continue
        elif first_name or uname:
            try:
                out.append((int(uid), None, None, first_name, uname))
            except (TypeError, ValueError):
                continue
    return out


def _migrate(conn, users_json):
    """1.0 -> 2.0/3.0. Bir necha marta chaqirilsa ham xavfsiz."""
    stamp = _utc_iso(now_tk())

    # 0) first_name ustunini users jadvaliga qo'shamiz (agar yo'q bo'lsa)
    user_cols = [r[1] for r in conn.execute("PRAGMA table_info(users)")]
    if "first_name" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN first_name TEXT")
    if "username" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN username TEXT")
    # Botdagi til. Foydalanuvchi /start da bir marta tanlaydi, keyin
    # barcha xabarlar va filmlar shu tilda boradi.
    if "lang" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN lang TEXT")
    # Referal: kim taklif qilgan (bir marta yoziladi), ball qachon berilgan
    # (NULL - hali berilmagan) va shu odam nechta do'st keltirgan.
    if "invited_by" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN invited_by INTEGER")
    if "invited_at" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN invited_at TEXT")
    if "ref_awarded_at" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN ref_awarded_at TEXT")
    if "refs" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN refs INTEGER NOT NULL DEFAULT 0")
    # Reklama manbasi: odamni qaysi kanal/post BIRINCHI olib kelgani.
    if "source" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN source TEXT")
    if "source_at" not in user_cols:
        conn.execute("ALTER TABLE users ADD COLUMN source_at TEXT")

    # Chat: javob, tahrir, o'chirish. `rev` - o'zgarish raqami: yangi xabar,
    # tahrir, o'chirish va reaksiya uni oshiradi; ilova "shu raqamdan keyin
    # nima o'zgardi?" deb so'raydi va hammasini birdaniga oladi.
    chat_cols = [r[1] for r in conn.execute("PRAGMA table_info(chat_messages)")]
    if "reply_to" not in chat_cols:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN reply_to INTEGER")
    if "edited_at" not in chat_cols:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN edited_at TEXT")
    if "deleted" not in chat_cols:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN deleted INTEGER NOT NULL DEFAULT 0")
    if "rev" not in chat_cols:
        conn.execute("ALTER TABLE chat_messages ADD COLUMN rev INTEGER")
        conn.execute("UPDATE chat_messages SET rev = id")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_rev ON chat_messages(rev)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_chat_house_rev ON chat_messages(house, rev)")

    # 1) Eski `points.house` dan foydalanuvchilarni tiklaymiz. Ustun
    #    tushirilgandan keyin bu ma'lumot yo'qoladi, shuning uchun avval.
    cols = [r[1] for r in conn.execute("PRAGMA table_info(points)")]
    if "house" in cols:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, first_name, house, sorted_at, created_at) "
            "SELECT p.user_id, NULL, p.house, NULL, ? FROM points p "
            "WHERE p.house IS NOT NULL AND p.house <> 'none' "
            "GROUP BY p.user_id", (stamp,))

    # 2) users_db.json - fakultet va ismlarning manbai (eng oxirgi saralanish).
    #    Yuqoridagi qadam qo'ygan qiymatni ham to'g'rilaydi.
    for uid, house, when, first_name, uname in _houses_from_json(users_json):
        conn.execute(
            "INSERT INTO users (user_id, first_name, username, house, sorted_at, created_at) VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "house=COALESCE(excluded.house, users.house), "
            "sorted_at=COALESCE(users.sorted_at, excluded.sorted_at), "
            "first_name=COALESCE(excluded.first_name, users.first_name), "
            "username=COALESCE(excluded.username, users.username)",
            (uid, first_name, uname, house, when, stamp))

    # 3) points jadvalini 2.0/3.0 ko'rinishiga keltiramiz: `house` ustuni olib
    #    tashlanadi va users ga tashqi kalit qo'shiladi. Jadval qayta
    #    quriladi - ALTER bilan tashqi kalit qo'shib bo'lmaydi.
    if "house" in cols:
        # Tashqi kalit buzilmasligi uchun har bir user_id users da bo'lsin
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, first_name, house, sorted_at, created_at) "
            "SELECT DISTINCT user_id, NULL, NULL, NULL, ? FROM points", (stamp,))

        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("DROP INDEX IF EXISTS idx_points_season_house")
        conn.execute("""
            CREATE TABLE points_v2 (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(user_id),
                season_id   INTEGER NOT NULL REFERENCES seasons(id),
                source_type TEXT NOT NULL CHECK (source_type IN ('film_open','film_quiz','daily')),
                source_ref  TEXT NOT NULL,
                points      INTEGER NOT NULL,
                created_at  TEXT NOT NULL,
                UNIQUE (user_id, season_id, source_type, source_ref)
            )""")
        conn.execute(
            "INSERT INTO points_v2 (id, user_id, season_id, source_type, "
            "source_ref, points, created_at) "
            "SELECT id, user_id, season_id, source_type, source_ref, points, "
            "created_at FROM points")
        conn.execute("DROP TABLE points")
        conn.execute("ALTER TABLE points_v2 RENAME TO points")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_points_season_user "
                     "ON points(season_id, user_id)")
        conn.execute("PRAGMA foreign_keys = ON")
        logging.info("Kubok migratsiyasi: points.house olib tashlandi")

    # 3) points.source_type cheklovi barcha ball turlarini qabul qilsin
    #    (avval shaxmat, keyin 'referral' qo'shildi). Cheklovda yo'q tur
    #    bazaga tushmay, xato try/except ichida jimgina yo'qolardi. SQLite da
    #    CHECK ni ALTER bilan o'zgartirib bo'lmaydi - jadval qayta quriladi.
    ddl = conn.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='points'"
    ).fetchone()
    if ddl and "'referral'" not in (ddl[0] or ""):
        conn.execute("PRAGMA foreign_keys = OFF")
        conn.execute("""
            CREATE TABLE points_v3 (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id     INTEGER NOT NULL REFERENCES users(user_id),
                season_id   INTEGER NOT NULL REFERENCES seasons(id),
                source_type TEXT NOT NULL CHECK (source_type IN
                                ('film_open','film_quiz','daily',
                                 'chess_win','chess_draw','referral')),
                source_ref  TEXT NOT NULL,
                points      INTEGER NOT NULL,
                created_at  TEXT NOT NULL,
                UNIQUE (user_id, season_id, source_type, source_ref)
            )""")
        conn.execute(
            "INSERT INTO points_v3 (id, user_id, season_id, source_type, "
            "source_ref, points, created_at) "
            "SELECT id, user_id, season_id, source_type, source_ref, points, "
            "created_at FROM points")
        conn.execute("DROP TABLE points")
        conn.execute("ALTER TABLE points_v3 RENAME TO points")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_points_season_user "
                     "ON points(season_id, user_id)")
        conn.execute("PRAGMA foreign_keys = ON")
        logging.info("Kubok migratsiyasi: points cheklovi yangilandi (referral)")


def _seed_questions(questions_dir=None):
    """Bazada faol savollar bo'lmasa, questions/ papkasidan yuklaydi."""
    conn = _connect()
    try:
        count = conn.execute("SELECT COUNT(*) FROM questions WHERE is_active=1").fetchone()[0]
    finally:
        conn.close()

    if count > 0:
        return 0

    if questions_dir is None:
        base_dir = os.path.dirname(os.path.abspath(__file__))
        candidates = [
            os.getenv("HP_QUESTIONS_DIR", "/app/questions"),
            os.path.join(base_dir, "questions"),
            os.path.join(base_dir, "data", "questions"),
        ]
        for c in candidates:
            if os.path.isdir(c):
                questions_dir = c
                break

    if not questions_dir or not os.path.isdir(questions_dir):
        return 0

    total_added = 0
    for filename in sorted(os.listdir(questions_dir)):
        if filename.endswith(".json"):
            filepath = os.path.join(questions_dir, filename)
            try:
                with open(filepath, "r", encoding="utf-8") as f:
                    items = json.load(f)
                    added = _load_questions(items, replace=False)
                    total_added += added
                    logging.info("Savollar yuklandi: %s (%d ta)", filename, added)
            except Exception as e:
                logging.error("Savollarni yuklashda xato (%s): %s", filename, e)

    return total_added


def _init(users_json):
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        _migrate(conn, users_json)
        conn.commit()
        _ensure_season(conn)
    finally:
        conn.close()
    try:
        _seed_questions()
    except Exception as e:
        logging.error("Savollarni avtomatik yuklashda xato: %s", e)


async def init(users_json="/app/users_db.json"):
    """Bazani yaratadi, 1.0 dan ko'chiradi, joriy mavsumni ta'minlaydi."""
    await asyncio.to_thread(_init, users_json)
    logging.info("Xogvarts kubogi bazasi tayyor: %s", DB_PATH)


# ---------------------------------------------------------------- foydalanuvchi

def _touch_user(conn, user_id, first_name=None, username=None):
    stamp = _utc_iso(now_tk())
    clean_name = first_name.strip()[:32].split()[0] if first_name else None
    
    clean_uname = None
    if username:
        clean_uname = username.replace("@", "").strip()
        if clean_uname.lower() in ("yo'q", "none", ""):
            clean_uname = None

    if clean_name or clean_uname:
        conn.execute(
            "INSERT INTO users (user_id, first_name, username, house, sorted_at, created_at) "
            "VALUES (?,?,?,NULL,NULL,?) "
            "ON CONFLICT(user_id) DO UPDATE SET "
            "first_name=COALESCE(excluded.first_name, users.first_name), "
            "username=COALESCE(excluded.username, users.username)",
            (int(user_id), clean_name, clean_uname, stamp))
    else:
        conn.execute(
            "INSERT OR IGNORE INTO users (user_id, first_name, username, house, sorted_at, created_at) "
            "VALUES (?,NULL,NULL,NULL,NULL,?)", (int(user_id), stamp))


async def touch_user(user_id, first_name=None, username=None):
    """Foydalanuvchini ro'yxatga oladi yoki ismini yangilaydi."""
    def _do():
        conn = _connect()
        try:
            _touch_user(conn, user_id, first_name, username)
            conn.commit()
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


def _set_lang(user_id, lang):
    conn = _connect()
    try:
        _touch_user(conn, user_id)
        conn.execute("UPDATE users SET lang=? WHERE user_id=?", (lang, int(user_id)))
        conn.commit()
    finally:
        conn.close()


async def set_lang(user_id, lang):
    """Botdagi tilni saqlaydi."""
    await asyncio.to_thread(_set_lang, user_id, lang)


def _get_lang(user_id):
    conn = _connect()
    try:
        row = conn.execute("SELECT lang FROM users WHERE user_id=?",
                           (int(user_id),)).fetchone()
        return row["lang"] if row and row["lang"] else None
    finally:
        conn.close()


async def get_lang(user_id):
    """Tanlangan til yoki None (hali tanlamagan)."""
    return await asyncio.to_thread(_get_lang, user_id)


def _get_house(user_id):
    conn = _connect()
    try:
        row = conn.execute("SELECT house FROM users WHERE user_id=?",
                           (int(user_id),)).fetchone()
        return row["house"] if row else None
    finally:
        conn.close()


async def get_house(user_id):
    """Foydalanuvchi fakulteti yoki None. Fakultet umrbod — o'zgarmaydi."""
    return await asyncio.to_thread(_get_house, user_id)


# ---------------------------------------------------------------- referal
# Ikki bosqich (Marvel botidagidek):
#   1. Havola bosilganda - faqat KIM taklif qilgani yoziladi, ball yo'q.
#   2. Do'st kanalga obuna bo'lganda - taklif qilganga +1.
# Havolani bosib, obuna bo'lmay ketganlar sanalmaydi - ball qadrsizlanmasin.

def _remember_inviter(user_id, inviter_id):
    user_id, inviter_id = int(user_id), int(inviter_id)
    if user_id == inviter_id:                 # o'zini o'zi taklif qila olmaydi
        return False
    conn = _connect()
    try:
        # Taklif qilgan bazada bo'lishi SHART - aks holda istalgan raqam
        # bilan qalbaki havola yasab, begona id ga ball yig'ish mumkin edi.
        if not conn.execute("SELECT 1 FROM users WHERE user_id=?",
                            (inviter_id,)).fetchone():
            return False
        _touch_user(conn, user_id)
        # Birinchi taklif qilgan yutadi: invited_by faqat bo'sh bo'lsa yoziladi.
        cur = conn.execute(
            "UPDATE users SET invited_by=?, invited_at=? "
            "WHERE user_id=? AND invited_by IS NULL AND ref_awarded_at IS NULL",
            (inviter_id, _utc_iso(now_tk()), user_id))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


async def remember_inviter(user_id, inviter_id):
    """Yangi odamni taklif qilganga biriktiradi. Yozildimi - True/False."""
    return await asyncio.to_thread(_remember_inviter, user_id, inviter_id)


def _award_referral(user_id):
    conn = _connect()
    try:
        # Mavsum ENG AVVAL: yangi hafta boshlangan bo'lsa _ensure_season o'zi
        # commit qiladi - bu pastdagi tranzaksiyani yarmida saqlab qo'ymasin.
        season = _ensure_season(conn)
        # Bitta UPDATE - ikki so'rov bir vaqtda kelsa ham ball bir marta
        # beriladi (SQLite yozishni navbat bilan bajaradi).
        cur = conn.execute(
            "UPDATE users SET ref_awarded_at=? "
            "WHERE user_id=? AND invited_by IS NOT NULL AND ref_awarded_at IS NULL",
            (_utc_iso(now_tk()), int(user_id)))
        if cur.rowcount != 1:
            conn.rollback()
            return None, 0
        inviter_id = conn.execute("SELECT invited_by FROM users WHERE user_id=?",
                                  (int(user_id),)).fetchone()["invited_by"]
        conn.execute("UPDATE users SET refs = refs + 1 WHERE user_id=?",
                     (inviter_id,))
        # Kubok bali ham - xuddi shu tranzaksiyada: yo ikkalasi, yo hech biri.
        # Fakultet shart emas: reyting users bilan JOIN orqali hisoblanadi,
        # keyinroq saralansa ball fakultetiga qo'shiladi (award() dagidek).
        conn.execute(
            "INSERT OR IGNORE INTO points "
            "(user_id, season_id, source_type, source_ref, points, created_at) "
            "VALUES (?,?,'referral',?,?,?)",
            (inviter_id, season["id"], str(int(user_id)), PTS_REFERRAL,
             _utc_iso(now_tk())))
        refs = conn.execute("SELECT refs FROM users WHERE user_id=?",
                            (inviter_id,)).fetchone()["refs"]
        conn.commit()
        return inviter_id, refs
    finally:
        conn.close()


async def award_referral(user_id):
    """Obuna tasdiqlanganda chaqiriladi. Qaytaradi: (taklif qilgan id,
    uning yangi bali) yoki (None, 0) - ball berilmadi yoki allaqachon berilgan."""
    return await asyncio.to_thread(_award_referral, user_id)


def _referral_count(user_id):
    conn = _connect()
    try:
        row = conn.execute("SELECT refs FROM users WHERE user_id=?",
                           (int(user_id),)).fetchone()
        return int(row["refs"]) if row else 0
    finally:
        conn.close()


async def referral_count(user_id):
    """Shu odam nechta do'st keltirgan."""
    return await asyncio.to_thread(_referral_count, user_id)


# ---------------------------------------------------------------- manba
# Reklama havolasi: t.me/<bot>?start=src_kanal yoki watch_hp1_uz-skanal.
# Faqat yangi odam uchun va faqat BIRINCHI manba - qaysi reklama odamni
# olib kelganini bilish uchun.

def _remember_source(user_id, code):
    conn = _connect()
    try:
        _touch_user(conn, user_id)
        cur = conn.execute(
            "UPDATE users SET source=?, source_at=? "
            "WHERE user_id=? AND source IS NULL",
            (code, _utc_iso(now_tk()), int(user_id)))
        conn.commit()
        return cur.rowcount == 1
    finally:
        conn.close()


async def remember_source(user_id, code):
    return await asyncio.to_thread(_remember_source, user_id, code)


def _source_report():
    conn = _connect()
    try:
        total = conn.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        rows = conn.execute(
            "SELECT source, COUNT(*) n FROM users WHERE source IS NOT NULL "
            "GROUP BY source ORDER BY n DESC").fetchall()
        referred = conn.execute(
            "SELECT COUNT(*) FROM users WHERE ref_awarded_at IS NOT NULL").fetchone()[0]
        attached = conn.execute(
            "SELECT COUNT(*) FROM users WHERE invited_by IS NOT NULL").fetchone()[0]
        return {"total": total,
                "sources": [(r["source"], r["n"]) for r in rows],
                "referred": referred, "attached": attached}
    finally:
        conn.close()


async def source_report():
    """Admin hisoboti uchun: jami, manbalar bo'yicha, do'st taklifi bilan."""
    return await asyncio.to_thread(_source_report)


# Darajalar: (kerakli do'stlar soni, kod), kattadan kichikka.
RANKS = [
    (50, "great_wizard"),
    (20, "auror"),
    (10, "quidditch_captain"),
    (5,  "prefect"),
    (1,  "first_year"),
    (0,  "muggle"),
]

# Nomlar shu yerda - bot xabari ham, ilova ham shu yerdan oladi.
RANK_NAMES = {
    "uz": {"great_wizard": "Buyuk sehrgar", "auror": "Auror",
           "quidditch_captain": "Kvidich sardori", "prefect": "Prefekt",
           "first_year": "Birinchi kurs talabasi", "muggle": "Maggl"},
    "ru": {"great_wizard": "Великий волшебник", "auror": "Аврор",
           "quidditch_captain": "Капитан по квиддичу", "prefect": "Староста",
           "first_year": "Первокурсник", "muggle": "Маггл"},
    "en": {"great_wizard": "Great Wizard", "auror": "Auror",
           "quidditch_captain": "Quidditch Captain", "prefect": "Prefect",
           "first_year": "First-year", "muggle": "Muggle"},
}

REF_TOP = 10


def rank_of(refs):
    """Do'stlar soniga qarab daraja kodi."""
    for need, code in RANKS:
        if refs >= need:
            return code
    return RANKS[-1][1]


def rank_name(refs, lang="uz"):
    names = RANK_NAMES.get(lang) or RANK_NAMES["uz"]
    return names[rank_of(refs)]


def _next_rank(refs):
    """Keyingi daraja: (kerakli son, kod) yoki None - eng yuqorisida."""
    for need, code in reversed(RANKS):
        if need > refs:
            return need, code
    return None


def _referral_board(user_id, lang="uz"):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT user_id, first_name, house, refs FROM users WHERE refs > 0 "
            "ORDER BY refs DESC, COALESCE(ref_awarded_at, created_at) ASC, "
            "user_id ASC").fetchall()
        mine = conn.execute("SELECT refs FROM users WHERE user_id=?",
                            (int(user_id),)).fetchone()
        my_refs = int(mine["refs"]) if mine else 0

        top, place = [], None
        for i, r in enumerate(rows):
            if r["user_id"] == int(user_id):
                place = i + 1
            if i < REF_TOP:
                top.append({"pos": i + 1, "name": r["first_name"] or "Sehrgar",
                            "house": r["house"], "refs": int(r["refs"]),
                            "me": r["user_id"] == int(user_id)})

        names = RANK_NAMES.get(lang) or RANK_NAMES["uz"]
        nxt = _next_rank(my_refs)
        return {
            "top": top,
            "total": len(rows),
            "me": {
                "refs": my_refs,
                "place": place,                   # None - hali do'st yo'q
                "rank": rank_of(my_refs),
                "rank_name": names[rank_of(my_refs)],
                "next_need": nxt[0] if nxt else None,
                "next_name": names[nxt[1]] if nxt else None,
                "cup_points": my_refs * PTS_REFERRAL,
            },
            "ranks": [{"need": need, "code": code, "name": names[code]}
                      for need, code in reversed(RANKS)],
            "pts_per_friend": PTS_REFERRAL,
        }
    finally:
        conn.close()


async def referral_board(user_id, lang="uz"):
    """Ilovadagi reyting bo'limi uchun: TOP 10, o'z o'rni, darajalar."""
    return await asyncio.to_thread(_referral_board, user_id, lang)


def _resort_until(conn):
    row = conn.execute("SELECT value FROM settings WHERE key=?",
                       (RESORT_KEY,)).fetchone()
    return row["value"] if row and row["value"] else None


def _can_resort(user_id):
    conn = _connect()
    try:
        row = conn.execute("SELECT house FROM users WHERE user_id=?",
                           (int(user_id),)).fetchone()
        if not row or not row["house"]:
            return True, None            # hali saralanmagan - har doim mumkin
        until = _resort_until(conn)
        if not until:
            return False, None
        end = _parse_iso(until)
        if end and datetime.now(timezone.utc) < end:
            return True, until
        return False, until
    finally:
        conn.close()


async def can_resort(user_id):
    """(mumkinmi, muhlat) — muhlat ichida eski foydalanuvchilar qayta saralanadi."""
    return await asyncio.to_thread(_can_resort, user_id)


def _set_house(user_id, house, first_name=None):
    if house not in HOUSES:
        return False
    conn = _connect()
    try:
        _touch_user(conn, user_id, first_name)
        row = conn.execute("SELECT house FROM users WHERE user_id=?",
                           (int(user_id),)).fetchone()
        if row and row["house"]:
            # Fakultet allaqachon bor. Faqat muhlat ichida almashtiriladi.
            until = _resort_until(conn)
            end = _parse_iso(until) if until else None
            if not (end and datetime.now(timezone.utc) < end):
                return False
        clean_name = first_name.strip()[:32].split()[0] if first_name else None
        if clean_name:
            conn.execute("UPDATE users SET house=?, sorted_at=?, first_name=? WHERE user_id=?",
                         (house, _utc_iso(now_tk()), clean_name, int(user_id)))
        else:
            conn.execute("UPDATE users SET house=?, sorted_at=? WHERE user_id=?",
                         (house, _utc_iso(now_tk()), int(user_id)))
        conn.commit()
        return True
    finally:
        conn.close()


async def set_house(user_id, house, first_name=None):
    """Fakultetni yozadi. Umrbod: qayta yozish faqat muhlat ichida."""
    return await asyncio.to_thread(_set_house, user_id, house, first_name)


def _open_resort_window(days):
    conn = _connect()
    try:
        until = _utc_iso(now_tk() + timedelta(days=days))
        conn.execute("INSERT INTO settings (key, value) VALUES (?,?) "
                     "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                     (RESORT_KEY, until))
        conn.commit()
        return until
    finally:
        conn.close()


async def open_resort_window(days=7):
    """Qayta saralanish muhlatini ochadi (xabar yuborilgan kunda chaqiriladi)."""
    return await asyncio.to_thread(_open_resort_window, days)


def _sorted_users():
    conn = _connect()
    try:
        return [(r["user_id"], r["house"]) for r in conn.execute(
            "SELECT user_id, house FROM users WHERE house IS NOT NULL "
            "ORDER BY user_id")]
    finally:
        conn.close()


async def sorted_users():
    """Fakulteti bor foydalanuvchilar — muhlat xabari uchun."""
    return await asyncio.to_thread(_sorted_users)


# ---------------------------------------------------------------- mavsum

def _ensure_season(conn):
    """Joriy haftaga mos faol mavsumni qaytaradi, kerak bo'lsa yaratadi.

    MUHIM: eskirgan mavsumni JIMGINA yopmaydi. 1.0 da shunday qilingan edi
    va natijada birinchi mavsum g'olibsiz, nishonsiz yopilib ketdi —
    ball bergan birinchi foydalanuvchi uni bexosdan yopib yuborgan.
    Endi to'liq yopish jarayoni chaqiriladi.
    """
    starts, ends = season_bounds()

    row = conn.execute(
        "SELECT * FROM seasons WHERE status='active' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if row:
        if row["starts_at"] == starts:
            return dict(row)
        _finalize(conn, row["id"])      # g'olib + nishonlar

    cur = conn.execute(
        "INSERT INTO seasons (starts_at, ends_at, status) VALUES (?,?,'active')",
        (starts, ends))
    conn.commit()
    return dict(conn.execute(
        "SELECT * FROM seasons WHERE id=?", (cur.lastrowid,)).fetchone())


def _current_season():
    conn = _connect()
    try:
        return _ensure_season(conn)
    finally:
        conn.close()


async def current_season():
    return await asyncio.to_thread(_current_season)


# ---------------------------------------------------------------- ball

def _award(user_id, source_type, source_ref, pts):
    conn = _connect()
    try:
        _touch_user(conn, user_id)
        season = _ensure_season(conn)
        cur = conn.execute(
            "INSERT OR IGNORE INTO points "
            "(user_id, season_id, source_type, source_ref, points, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (int(user_id), season["id"], source_type, str(source_ref),
             int(pts), _utc_iso(now_tk())))
        conn.commit()
        # rowcount 0 -> UNIQUE cheklovi ushladi, ya'ni ball avval berilgan
        return cur.rowcount > 0
    finally:
        conn.close()


async def award(user_id, source_type, source_ref, pts):
    """Ball beradi. Takroriy urinish bo'lsa False qaytaradi.

    Takrorlanishni baza o'zi to'sadi (UNIQUE), kodda tekshirish shart emas.
    Fakultet bu yerda talab qilinmaydi: reyting `users` bilan JOIN orqali
    hisoblanadi, ya'ni keyinroq saralangan odamning oldingi ballari ham
    fakultetiga qo'shiladi.
    """
    return await asyncio.to_thread(_award, user_id, source_type, source_ref, pts)


def _award_chess(user_id, game_id, result):
    """Jonli shaxmat natijasi uchun ball. `result`: "win" yoki "draw"."""
    if result == "win":
        source_type, pts = "chess_win", PTS_CHESS_WIN
    elif result == "draw":
        source_type, pts = "chess_draw", PTS_CHESS_DRAW
    else:
        return {"ok": False, "error": "bad_result", "points": 0}

    conn = _connect()
    try:
        _touch_user(conn, user_id)
        season = _ensure_season(conn)

        # Mavsumdagi cheklov. Ayni o'yin uchun ball avval berilgan bo'lsa
        # ham shu son ichida turadi - pastdagi UNIQUE uni ikkinchi marta
        # o'tkazmaydi.
        used = conn.execute(
            "SELECT COUNT(*) FROM points WHERE user_id=? AND season_id=? "
            "AND source_type IN ('chess_win','chess_draw')",
            (int(user_id), season["id"])).fetchone()[0]
        if used >= CHESS_MAX_PER_SEASON:
            return {"ok": False, "error": "limit", "points": 0,
                    "used": used, "limit": CHESS_MAX_PER_SEASON}

        cur = conn.execute(
            "INSERT OR IGNORE INTO points "
            "(user_id, season_id, source_type, source_ref, points, created_at) "
            "VALUES (?,?,?,?,?,?)",
            (int(user_id), season["id"], source_type, str(game_id), int(pts),
             _utc_iso(now_tk())))
        conn.commit()
        if cur.rowcount == 0:
            # Shu o'yin uchun ball allaqachon berilgan
            return {"ok": False, "error": "already", "points": 0,
                    "used": used, "limit": CHESS_MAX_PER_SEASON}
        return {"ok": True, "points": pts,
                "used": used + 1, "limit": CHESS_MAX_PER_SEASON}
    finally:
        conn.close()


async def award_chess(user_id, game_id, result):
    """Shaxmat balli. Mavsumdagi cheklovni ham tekshiradi."""
    return await asyncio.to_thread(_award_chess, user_id, game_id, result)


# ---------------------------------------------------------------- reyting

_ACTIVE_SQL = """
WITH active AS (
    SELECT p.user_id, u.house, SUM(p.points) AS pts
    FROM points p
    JOIN users u ON u.user_id = p.user_id
    WHERE p.season_id = ? AND u.house IS NOT NULL
    GROUP BY p.user_id, u.house
    HAVING SUM(p.points) >= ?
)
SELECT house,
       COUNT(*)                          AS active_members,
       SUM(pts)                          AS total_points,
       CAST(SUM(pts) AS REAL) / COUNT(*) AS avg_points
FROM active
GROUP BY house
ORDER BY total_points DESC
"""


def _leaderboard(season_id):
    conn = _connect()
    try:
        rows = conn.execute(_ACTIVE_SQL, (season_id, ACTIVE_MIN_POINTS)).fetchall()
        seen = {}
        out = []
        for r in rows:
            active = r["active_members"]
            item = {
                "house": r["house"],
                "total_points": r["total_points"],
                "active_members": active,
                "avg_points": round(r["avg_points"], 1),
                "qualified": True,
            }
            out.append(item)
            seen[r["house"]] = True

        for h in HOUSES:
            if h not in seen:
                out.append({"house": h, "total_points": 0, "active_members": 0,
                            "avg_points": 0.0, "qualified": True})
        return out
    finally:
        conn.close()


async def leaderboard(season_id):
    """Fakultetlar reytingi — o'rtacha ball bo'yicha (umumiy ball emas)."""
    return await asyncio.to_thread(_leaderboard, season_id)


def _remaining_today(conn, user_id, season_id):
    """Foydalanuvchi bugun yana qancha ball ola olishi mumkin."""
    total = 0

    # 1. Kunlik savol
    today = today_tk()
    row = conn.execute(
        "SELECT q.id FROM daily_schedule d JOIN questions q ON q.id=d.question_id "
        "WHERE d.date=?", (today,)).fetchone()
    if row:
        done = conn.execute(
            "SELECT 1 FROM answers WHERE user_id=? AND season_id=? AND question_id=?",
            (int(user_id), season_id, row["id"])).fetchone()
        if not done:
            total += PTS_DAILY
    else:
        # Savol hali tanlanmagan, lekin bazada bor bo'lsa - olinishi mumkin
        any_daily = conn.execute(
            "SELECT 1 FROM questions WHERE kind='daily' AND is_active=1").fetchone()
        if any_daily:
            total += PTS_DAILY

    # 2. Imtihon savollari (barcha 8 qism bo'yicha qolgan savollar)
    for part in range(1, FILM_PARTS + 1):
        has_qs = conn.execute(
            "SELECT 1 FROM questions WHERE kind='film' AND film_part=? AND is_active=1 LIMIT 1",
            (part,)).fetchone()
        if has_qs:
            ans_count = conn.execute(
                "SELECT COUNT(DISTINCT a.question_id) FROM answers a "
                "JOIN questions q ON q.id=a.question_id "
                "WHERE a.user_id=? AND a.season_id=? AND q.kind='film' AND q.film_part=?",
                (int(user_id), season_id, part)).fetchone()[0]
            left_for_part = max(0, QUIZ_PER_FILM - ans_count)
            total += left_for_part * PTS_FILM_QUIZ

    return total


def _exam_pending(conn, user_id, season_id):
    """Joriy mavsumda imtihoni topshirilmagan qism raqamlari (1..8)."""
    pending = []
    for part in range(1, FILM_PARTS + 1):
        has_qs = conn.execute(
            "SELECT 1 FROM questions WHERE kind='film' AND film_part=? AND is_active=1 LIMIT 1",
            (part,)).fetchone()
        if not has_qs:
            continue

        ans_count = conn.execute(
            "SELECT COUNT(DISTINCT a.question_id) FROM answers a "
            "JOIN questions q ON q.id=a.question_id "
            "WHERE a.user_id=? AND a.season_id=? AND q.kind='film' AND q.film_part=?",
            (int(user_id), season_id, part)).fetchone()[0]

        if ans_count < QUIZ_PER_FILM:
            pending.append(part)
    return pending


async def exam_pending(user_id, season_id):
    """Joriy mavsumda imtihoni topshirilmagan qismlar ro'yxati."""
    def _do():
        conn = _connect()
        try:
            return _exam_pending(conn, user_id, season_id)
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


def _hall(conn, house, user_id, season_id):
    """Fakultet zali: total, active, va faol a'zolar ro'yxati (kamayish tartibida)."""
    if not house or house not in HOUSES:
        return None

    total = conn.execute(
        "SELECT COUNT(*) FROM users WHERE house=?", (house,)).fetchone()[0]

    rows = conn.execute(
        "SELECT u.user_id, u.username, COALESCE(u.first_name, 'Sehrgar') AS name, COALESCE(SUM(p.points), 0) AS pts "
        "FROM users u "
        "LEFT JOIN points p ON u.user_id=p.user_id AND p.season_id=? "
        "WHERE u.house=? "
        "GROUP BY u.user_id "
        "ORDER BY pts DESC, u.user_id ASC",
        (season_id, house)).fetchall()

    active_count = sum(1 for r in rows if r["pts"] >= ACTIVE_MIN_POINTS)
    members = []
    for r in rows:
        raw_name = (r["name"] or "Sehrgar").strip()
        first_word = raw_name.split()[0] if raw_name else "Sehrgar"
        members.append({
            "uid": r["user_id"],
            "username": r["username"],
            "name": first_word[:20],
            "points": r["pts"],
            "me": (r["user_id"] == int(user_id)),
            "active": r["pts"] >= ACTIVE_MIN_POINTS
        })

    return {
        "total": total,
        "active": active_count,
        "members": members
    }


async def hall(house, user_id, season_id):
    """Fakultet zali ma'lumotlari."""
    def _do():
        conn = _connect()
        try:
            return _hall(conn, house, user_id, season_id)
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


def _feed(conn, limit=50):
    """So'nggi saralanishlar tasmasi (5 tagacha, yangisidan eskisiga)."""
    rows = conn.execute(
        "SELECT user_id, COALESCE(first_name, 'Sehrgar') AS name, house, sorted_at "
        "FROM users "
        "WHERE house IS NOT NULL AND sorted_at IS NOT NULL "
        "ORDER BY sorted_at DESC "
        "LIMIT ?", (limit,)).fetchall()

    now = datetime.now(timezone.utc)
    feed_list = []
    for r in rows:
        when = _parse_iso(r["sorted_at"])
        if when:
            ago_min = max(1, int((now - when).total_seconds() / 60))
        else:
            ago_min = 60
        raw_name = (r["name"] or "Sehrgar").strip()
        first_word = raw_name.split()[0] if raw_name else "Sehrgar"
        feed_list.append({
            "name": first_word[:20],
            "house": r["house"],
            "ago_minutes": ago_min
        })
    return feed_list


async def feed(limit=50):
    """Jonli tasma (so'nggi saralanishlar)."""
    def _do():
        conn = _connect()
        try:
            return _feed(conn, limit)
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


def _user_stats(user_id, season_id):
    conn = _connect()
    try:
        row = conn.execute("SELECT house FROM users WHERE user_id=?",
                           (int(user_id),)).fetchone()
        house = row["house"] if row else None

        pts = conn.execute(
            "SELECT COALESCE(SUM(points),0) FROM points "
            "WHERE user_id=? AND season_id=?",
            (int(user_id), season_id)).fetchone()[0]

        is_active = pts >= ACTIVE_MIN_POINTS
        to_active = max(0, ACTIVE_MIN_POINTS - pts)

        rank = None
        if house and is_active:
            rank = conn.execute(
                "SELECT COUNT(*)+1 FROM ("
                "  SELECT p.user_id, SUM(p.points) s FROM points p "
                "  JOIN users u ON u.user_id=p.user_id "
                "  WHERE p.season_id=? AND u.house=? "
                "  GROUP BY p.user_id HAVING s > ?"
                ")", (season_id, house, pts)).fetchone()[0]

        codes = [r["code"] for r in conn.execute(
            "SELECT DISTINCT code FROM badges WHERE user_id=?",
            (int(user_id),))]

        return {
            "house": house,
            "points": pts,
            "max_points": MAX_POINTS,
            "is_active": is_active,
            "to_active": to_active,
            "house_rank": rank,
            "badges": codes,
            "remaining_today": _remaining_today(conn, user_id, season_id),
        }
    finally:
        conn.close()


async def user_stats(user_id, season_id):
    return await asyncio.to_thread(_user_stats, user_id, season_id)


def compute_gap(table, stats):
    """Taranglik bloki uchun: eng yaqin raqib va farq.

    `closable` — bugun olinadigan ballar fakultet O'RTACHASIGA qancha
    qo'shishi. O'rtacha = jami / faol a'zolar, shuning uchun bitta odamning
    ballari a'zolar soniga bo'linadi.
    """
    house = stats.get("house")
    if not house or not stats.get("is_active"):
        return None

    mine = next((x for x in table if x["house"] == house), None)
    if not mine or not mine["qualified"]:
        return None

    rivals = [x for x in table if x["qualified"] and x["house"] != house]
    if not rivals:
        return None

    ahead_of_me = [x for x in rivals if x["avg_points"] > mine["avg_points"]]
    if ahead_of_me:
        # Ortdamiz: eng yaqin oldindagi raqib
        rival = min(ahead_of_me, key=lambda x: x["avg_points"] - mine["avg_points"])
        ahead = False
    else:
        # Yetakchimiz: eng yaqin orqadagi raqib
        rival = max(rivals, key=lambda x: x["avg_points"])
        ahead = True

    diff = round(abs(rival["avg_points"] - mine["avg_points"]), 1)
    members = max(1, mine["active_members"])
    closable = round(stats.get("remaining_today", 0) / members, 1)

    return {"house": rival["house"], "diff": diff, "ahead": ahead,
            "closable": closable}


# ---------------------------------------------------------------- savollar

def _pick_film_questions(user_id, season_id, film_part):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT q.* FROM question_assignments a JOIN questions q ON q.id=a.question_id "
            "WHERE a.user_id=? AND a.season_id=? AND a.film_part=? ORDER BY q.id",
            (int(user_id), season_id, film_part)).fetchall()

        if not rows:
            pool = conn.execute(
                "SELECT * FROM questions "
                "WHERE kind='film' AND film_part=? AND is_active=1",
                (film_part,)).fetchall()
            if not pool:
                return []            # savollar hali yuklanmagan - jim o'tamiz
            # Tasodif - QAYSI savollar tanlanishida. Ko'rsatish tartibi esa
            # barqaror bo'lishi kerak: foydalanuvchi yarmida to'xtab, keyin
            # qaytsa, savollar o'sha tartibda davom etsin.
            chosen = sorted(random.sample(list(pool), min(QUIZ_PER_FILM, len(pool))),
                            key=lambda r: r["id"])
            conn.executemany(
                "INSERT OR IGNORE INTO question_assignments "
                "(user_id, season_id, film_part, question_id) VALUES (?,?,?,?)",
                [(int(user_id), season_id, film_part, q["id"]) for q in chosen])
            conn.commit()
            rows = chosen

        answered = {r["question_id"] for r in conn.execute(
            "SELECT question_id FROM answers WHERE user_id=? AND season_id=?",
            (int(user_id), season_id))}

        return [_row_to_question(r) for r in rows if r["id"] not in answered]
    finally:
        conn.close()


async def film_questions(user_id, season_id, film_part):
    """Shu qism uchun biriktirilgan, hali javob berilmagan savollar."""
    return await asyncio.to_thread(
        _pick_film_questions, user_id, season_id, film_part)


def _row_to_question(r):
    try:
        options = json.loads(r["options"])
    except (TypeError, ValueError):
        options = []
    return {"id": r["id"], "body": r["body"], "options": options,
            "correct_index": r["correct_index"]}


def _daily_question(date_str):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT q.* FROM daily_schedule d JOIN questions q ON q.id=d.question_id "
            "WHERE d.date=?", (date_str,)).fetchone()
        if row:
            return _row_to_question(row)

        row = conn.execute(
            "SELECT q.*, ("
            "  SELECT COUNT(*) FROM daily_schedule d WHERE d.question_id=q.id"
            ") AS used FROM questions q "
            "WHERE q.kind='daily' AND q.is_active=1 "
            "ORDER BY used ASC, RANDOM() LIMIT 1").fetchone()
        if not row:
            return None              # savollar hali yuklanmagan

        conn.execute(
            "INSERT OR IGNORE INTO daily_schedule (date, question_id) VALUES (?,?)",
            (date_str, row["id"]))
        conn.commit()
        return _row_to_question(row)
    finally:
        conn.close()


async def daily_question(date_str=None):
    """Shu kunning savoli. Belgilanmagan bo'lsa tanlab, jadvalga yozadi."""
    return await asyncio.to_thread(_daily_question, date_str or today_tk())


def _record_answer(user_id, season_id, question_id, is_correct):
    conn = _connect()
    try:
        cur = conn.execute(
            "INSERT OR IGNORE INTO answers "
            "(user_id, season_id, question_id, is_correct, answered_at) "
            "VALUES (?,?,?,?,?)",
            (int(user_id), season_id, int(question_id),
             1 if is_correct else 0, _utc_iso(now_tk())))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


async def record_answer(user_id, season_id, question_id, is_correct):
    """Javobni yozadi. Noto'g'ri javob ham yoziladi — qayta urinib bo'lmaydi."""
    return await asyncio.to_thread(
        _record_answer, user_id, season_id, question_id, is_correct)


def _already_answered(user_id, season_id, question_id):
    conn = _connect()
    try:
        return conn.execute(
            "SELECT 1 FROM answers WHERE user_id=? AND season_id=? AND question_id=?",
            (int(user_id), season_id, int(question_id))).fetchone() is not None
    finally:
        conn.close()


async def already_answered(user_id, season_id, question_id):
    return await asyncio.to_thread(
        _already_answered, user_id, season_id, question_id)


# ---------------------------------------------------------------- nishonlar

def _earned_badges(conn, season_id):
    found = []

    for r in conn.execute(
            "SELECT user_id FROM points WHERE season_id=? AND source_type='film_open' "
            "GROUP BY user_id HAVING COUNT(DISTINCT source_ref) >= ?",
            (season_id, FILM_PARTS)):
        found.append((r["user_id"], "all_films"))

    for r in conn.execute(
            "SELECT a.user_id FROM answers a JOIN questions q ON q.id=a.question_id "
            "WHERE a.season_id=? AND q.kind='film' GROUP BY a.user_id "
            "HAVING COUNT(*) >= ? AND SUM(a.is_correct) = COUNT(*)",
            (season_id, FILM_PARTS * QUIZ_PER_FILM)):
        found.append((r["user_id"], "flawless_exam"))

    for r in conn.execute(
            "SELECT a.user_id FROM answers a JOIN questions q ON q.id=a.question_id "
            "WHERE a.season_id=? AND q.kind='daily' GROUP BY a.user_id "
            "HAVING COUNT(*) >= ? AND SUM(a.is_correct) = COUNT(*)",
            (season_id, DAILY_PER_WEEK)):
        found.append((r["user_id"], "perfect_week"))

    for r in conn.execute(
            "SELECT user_id, COUNT(DISTINCT DATE(created_at)) AS days FROM points "
            "WHERE season_id=? GROUP BY user_id HAVING days >= 7", (season_id,)):
        found.append((r["user_id"], "streak_7"))

    return found


def _finalize(conn, season_id):
    """Mavsumni yopadi: g'olib + nishonlar. Natijani qaytaradi."""
    winner = None
    for item in _leaderboard(season_id):
        if item["qualified"]:
            winner = item["house"]
            break

    stamp = _utc_iso(now_tk())
    badges = _earned_badges(conn, season_id)
    conn.executemany(
        "INSERT OR IGNORE INTO badges (user_id, code, season_id, earned_at) "
        "VALUES (?,?,?,?)",
        [(uid, code, season_id, stamp) for uid, code in badges])

    conn.execute("UPDATE seasons SET status='closed', winner_house=? WHERE id=?",
                 (winner, season_id))
    conn.commit()
    return {"closed_id": season_id, "winner_house": winner,
            "badges": badges, "table": _leaderboard(season_id)}


def _close_season(season_id=None):
    conn = _connect()
    try:
        if season_id is None:
            row = conn.execute(
                "SELECT * FROM seasons WHERE status='active' "
                "ORDER BY id DESC LIMIT 1").fetchone()
            if not row:
                return None
            season_id = row["id"]

        result = _finalize(conn, season_id)
        result["new_season_id"] = _ensure_season(conn)["id"]
        return result
    finally:
        conn.close()


async def close_season(season_id=None):
    """Mavsumni yopadi, g'olibni aniqlaydi, nishon beradi, yangisini ochadi."""
    return await asyncio.to_thread(_close_season, season_id)


def _recount(season_id):
    """Yopilgan mavsumni qayta hisoblaydi (1.0 xatosidan keyin tiklash uchun)."""
    conn = _connect()
    try:
        return _finalize(conn, season_id)
    finally:
        conn.close()


async def recount_season(season_id):
    return await asyncio.to_thread(_recount, season_id)


# ---------------------------------------------------------------- savol yuklash

def _load_questions(items, replace=False):
    conn = _connect()
    try:
        if replace:
            conn.execute("UPDATE questions SET is_active=0")
        added = 0
        for q in items:
            kind = q.get("kind")
            if kind not in ("film", "daily"):
                continue
            options = q.get("options") or []
            if len(options) != 4:
                continue
            ci = q.get("correct_index")
            if not isinstance(ci, int) or not 0 <= ci <= 3:
                continue
            conn.execute(
                "INSERT INTO questions (kind, film_part, lang, body, options, "
                "correct_index, is_active) VALUES (?,?,?,?,?,?,1)",
                (kind, q.get("film_part"), q.get("lang", "uz"), q["body"],
                 json.dumps(options, ensure_ascii=False), ci))
            added += 1
        conn.commit()
        return added
    finally:
        conn.close()


async def load_questions(items, replace=False):
    """JSON ro'yxatdan savollarni yuklaydi. Noto'g'ri yozuvlar o'tkaziladi."""
    return await asyncio.to_thread(_load_questions, items, replace)


def _counts():
    conn = _connect()
    try:
        out = {}
        for name in ("users", "seasons", "points", "questions", "answers",
                     "question_assignments", "daily_schedule", "badges"):
            out[name] = conn.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
        out["sorted_users"] = conn.execute(
            "SELECT COUNT(*) FROM users WHERE house IS NOT NULL").fetchone()[0]
        out["named_users"] = conn.execute(
            "SELECT COUNT(*) FROM users WHERE first_name IS NOT NULL").fetchone()[0]
        out["resort_until"] = _resort_until(conn)
        return out
    finally:
        conn.close()


async def counts():
    """Diagnostika uchun jadval hajmlari."""
    return await asyncio.to_thread(_counts)


async def get_user_tasks(user_id):
    season = await current_season()
    if not season:
        return {"tasks": []}
        
    today_str = today_tk()
    
    def _fetch():
        res = []
        conn = _connect()
        try:
            ans = conn.execute(
                "SELECT 1 FROM answers WHERE user_id=? AND season_id=? AND question_id IN (SELECT question_id FROM daily_schedule WHERE date=?)",
                (int(user_id), season["id"], today_str)).fetchone()
            has_daily = not ans
            
            opened_films = conn.execute(
                "SELECT source_ref FROM points WHERE user_id=? AND season_id=? AND source_type='film_open'",
                (int(user_id), season["id"])).fetchall()
            opened_refs = [row["source_ref"] for row in opened_films]
        finally:
            conn.close()
            
        if has_daily:
            dq = _daily_question(today_str)
            if dq:
                res.append({
                    "id": "daily",
                    "type": "daily",
                    "title": "Kunlik savol",
                    "questions": [dq]
                })
                
        for mov_id in opened_refs:
            film_part = 0
            if mov_id.startswith("hp"):
                try:
                    film_part = int(mov_id[2:])
                except:
                    pass
            if film_part:
                qs = _pick_film_questions(user_id, season["id"], film_part)
                if qs:
                    res.append({
                        "id": f"quiz_{mov_id}",
                        "type": "film_quiz",
                        "film_id": mov_id,
                        "title": f"Garri Potter {film_part}-qismi bo'yicha imtihon",
                        "questions": qs
                    })
        return res

    tasks = await asyncio.to_thread(_fetch)
    return {"tasks": tasks}


async def submit_task_answer(user_id, task_type, question_id, selected_index):
    season = await current_season()
    if not season:
        return {"ok": False, "error": "No active season"}
        
    def _check():
        conn = _connect()
        try:
            q = conn.execute("SELECT correct_index FROM questions WHERE id=?", (int(question_id),)).fetchone()
            if not q:
                return {"ok": False, "error": "Question not found"}
                
            ans = conn.execute("SELECT 1 FROM answers WHERE user_id=? AND season_id=? AND question_id=?", 
                               (int(user_id), season["id"], int(question_id))).fetchone()
            if ans:
                return {"ok": False, "error": "Already answered"}
                
            is_correct = (int(selected_index) == q["correct_index"])
            return {"ok": True, "correct": is_correct, "correct_index": q["correct_index"]}
        finally:
            conn.close()

    res = await asyncio.to_thread(_check)
    if not res["ok"]:
        return res
        
    fresh = await record_answer(user_id, season["id"], question_id, res["correct"])
    pts = 0
    if res["correct"] and fresh:
        if task_type == "daily":
            pts = PTS_DAILY
        elif task_type == "film_quiz":
            pts = PTS_FILM_QUIZ
            
        if pts > 0:
            await award(user_id, task_type, str(question_id), pts)
            
    res["points"] = pts
    return res

_CHAT_SELECT = (
    "SELECT c.id, c.user_id, COALESCE(u.first_name, 'Sehrgar') AS name, u.house AS user_house, "
    "c.message, c.created_at, c.reply_to, c.edited_at, c.deleted, c.rev, "
    "r.user_id AS r_uid, COALESCE(ru.first_name, 'Sehrgar') AS r_name, ru.house AS r_house, r.message AS r_text, r.deleted AS r_deleted "
    "FROM chat_messages c "
    "LEFT JOIN users u ON u.user_id = c.user_id "
    "LEFT JOIN chat_messages r ON r.id = c.reply_to "
    "LEFT JOIN users ru ON ru.user_id = r.user_id ")

_NEXT_REV = "(SELECT COALESCE(MAX(rev), 0) + 1 FROM chat_messages)"

CHAT_EDIT_HOURS = 48
CHAT_REACTIONS = ("👍", "❤️", "😂", "🔥", "😮", "⚡")


def _chat_row(r):
    if r["deleted"]:
        return {"id": r["id"], "rev": r["rev"], "deleted": True}
    m = {
        "id": r["id"],
        "uid": r["user_id"],
        "name": r["name"],
        "house": r["user_house"],
        "text": r["message"],
        "time": r["created_at"],
        "rev": r["rev"],
    }
    if r["edited_at"]:
        m["edited"] = True
    if r["reply_to"]:
        if r["r_uid"] is None or r["r_deleted"]:
            m["reply"] = {"id": r["reply_to"], "deleted": True}
        else:
            m["reply"] = {"id": r["reply_to"], "uid": r["r_uid"], "name": r["r_name"],
                          "house": r["r_house"], "text": (r["r_text"] or "")[:120]}
    return m


def _chat_reactions(conn, messages, viewer):
    """Har xabarga [{"e": emoji, "n": soni, "me": bosganmi}] qo'shadi."""
    ids = [m["id"] for m in messages if not m.get("deleted")]
    if not ids:
        return messages
    rows = conn.execute(
        "SELECT message_id, emoji, COUNT(*) AS n, MAX(user_id = ?) AS mine "
        "FROM chat_reactions WHERE message_id IN (%s) "
        "GROUP BY message_id, emoji ORDER BY MIN(rowid)" % ",".join("?" * len(ids)),
        [int(viewer or 0)] + ids).fetchall()
    by_id = {}
    for r in rows:
        by_id.setdefault(r["message_id"], []).append(
            {"e": r["emoji"], "n": r["n"], "me": bool(r["mine"])})
    for m in messages:
        if m["id"] in by_id:
            m["reactions"] = by_id[m["id"]]
    return messages


def _chat_one(conn, msg_id, viewer):
    row = conn.execute(_CHAT_SELECT + "WHERE c.id=?", (msg_id,)).fetchone()
    return _chat_reactions(conn, [_chat_row(row)], viewer)[0] if row else None


async def get_chat_messages(house, limit=50, after=None, before=None, since=None, viewer=0):
    """Xona xabarlari, eskisidan yangisiga.

    since  - shu o'zgarish raqamidan keyin nima o'zgardi (yangi, tahrirlangan,
             o'chirilgan, reaksiya olgan xabarlar) - jonli yangilanish uchun;
    after  - shu id dan KEYINGI xabarlar (eski ilova shunday so'raydi);
    before - shu id dan OLDINGI xabarlar (yuqoriga surilganda eski sahifa).
    Hech biri berilmasa - oxirgi `limit` ta xabar.
    """
    def _do():
        conn = _connect()
        try:
            if since is not None:
                rows = conn.execute(
                    _CHAT_SELECT + "WHERE c.house=? AND c.rev>? ORDER BY c.rev ASC LIMIT ?",
                    (house, int(since), limit)).fetchall()
                return _chat_reactions(conn, [_chat_row(r) for r in rows], viewer)
            if after is not None:
                rows = conn.execute(
                    _CHAT_SELECT + "WHERE c.house=? AND c.id>? AND c.deleted=0 ORDER BY c.id ASC LIMIT ?",
                    (house, int(after), limit)).fetchall()
                return _chat_reactions(conn, [_chat_row(r) for r in rows], viewer)
            if before is not None:
                rows = conn.execute(
                    _CHAT_SELECT + "WHERE c.house=? AND c.id<? AND c.deleted=0 ORDER BY c.id DESC LIMIT ?",
                    (house, int(before), limit)).fetchall()
            else:
                rows = conn.execute(
                    _CHAT_SELECT + "WHERE c.house=? AND c.deleted=0 ORDER BY c.id DESC LIMIT ?",
                    (house, limit)).fetchall()
            return _chat_reactions(conn, [_chat_row(r) for r in reversed(rows)], viewer)
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


def _read_state(conn, house, user_id):
    row = conn.execute("SELECT last_id FROM chat_reads WHERE user_id=? AND room=?",
                       (int(user_id), house)).fetchone()
    if row is None and house.startswith("dm:"):
        # Shaxsiy suhbat: hali ochilmagan bo'lsa - undagi hamma xabar o'qilmagan.
        row = {"last_id": 0}
    elif row is None:
        # Birinchi marta: hammasi o'qilgan hisoblanadi - yangi odam (yoki shu
        # imkoniyat qo'shilgan kun hamma) yuzlab eski xabarni "yangi" deb ko'rmasin.
        top = conn.execute("SELECT COALESCE(MAX(id), 0) FROM chat_messages WHERE house=?",
                           (house,)).fetchone()[0]
        conn.execute("INSERT OR IGNORE INTO chat_reads (user_id, room, last_id) VALUES (?,?,?)",
                     (int(user_id), house, top))
        conn.commit()
        return top, 0
    unread = conn.execute(
        "SELECT COUNT(*) FROM chat_messages WHERE house=? AND id>? AND deleted=0 AND user_id<>?",
        (house, row["last_id"], int(user_id))).fetchone()[0]
    return row["last_id"], unread


async def chat_read_state(house, user_id):
    """(o'qilgan oxirgi xabar id si, o'qilmaganlar soni)."""
    def _do():
        conn = _connect()
        try:
            return _read_state(conn, house, user_id)
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chat_unread_counts(user_id, rooms):
    """{xona: o'qilmaganlar soni} - kubok oynasidagi tugma va chat yorliqlari uchun."""
    def _do():
        conn = _connect()
        try:
            return {room: _read_state(conn, house, user_id)[1] for room, house in rooms.items()}
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def mark_chat_read(house, user_id, msg_id):
    """O'qilgan joyni faqat oldinga suradi (eski qurilma orqaga qaytara olmaydi)."""
    def _do():
        conn = _connect()
        try:
            top = conn.execute("SELECT COALESCE(MAX(id), 0) FROM chat_messages WHERE house=?",
                               (house,)).fetchone()[0]
            last = min(int(msg_id), top)
            conn.execute(
                "INSERT INTO chat_reads (user_id, room, last_id) VALUES (?,?,?) "
                "ON CONFLICT(user_id, room) DO UPDATE SET last_id=MAX(last_id, excluded.last_id)",
                (int(user_id), house, last))
            conn.commit()
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def get_chat_around(house, read_id, viewer, before=15, after=100):
    """Birinchi o'qilmagan xabar atrofi: o'qilganlardan `before` tasi (tushunish uchun)
    va o'qilmaganlardan `after` tasi. (xabarlar, tepada yana bormi, pastda yana bormi)."""
    def _do():
        conn = _connect()
        try:
            old = conn.execute(
                _CHAT_SELECT + "WHERE c.house=? AND c.id<=? AND c.deleted=0 ORDER BY c.id DESC LIMIT ?",
                (house, int(read_id), before + 1)).fetchall()
            new = conn.execute(
                _CHAT_SELECT + "WHERE c.house=? AND c.id>? AND c.deleted=0 ORDER BY c.id ASC LIMIT ?",
                (house, int(read_id), after + 1)).fetchall()
            more, more_new = len(old) > before, len(new) > after
            rows = list(reversed(old[:before])) + new[:after]
            return _chat_reactions(conn, [_chat_row(r) for r in rows], viewer), more, more_new
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chat_bans():
    """{user_id: until} - amaldagi bloklar (until None - butunlay). Muddati o'tganlar o'chiriladi."""
    def _do():
        conn = _connect()
        try:
            conn.execute("DELETE FROM chat_bans WHERE until IS NOT NULL AND until < ?",
                         (_utc_iso(now_tk()),))
            conn.commit()
            return {r["user_id"]: r["until"] for r in conn.execute("SELECT user_id, until FROM chat_bans")}
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chat_ban(user_id, by, hours=None):
    """Bloklaydi va muddatini qaytaradi (None - butunlay)."""
    def _do():
        conn = _connect()
        try:
            until = _utc_iso(now_tk() + timedelta(hours=hours)) if hours else None
            conn.execute(
                "INSERT OR REPLACE INTO chat_bans (user_id, banned_by, banned_at, until) VALUES (?,?,?,?)",
                (int(user_id), int(by), _utc_iso(now_tk()), until))
            conn.commit()
            return until
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chat_unban(user_id):
    def _do():
        conn = _connect()
        try:
            conn.execute("DELETE FROM chat_bans WHERE user_id=?", (int(user_id),))
            conn.commit()
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


def _dm_peer(room, user_id):
    """ "dm:5:12" va 5 -> 12."""
    try:
        a, b = (int(x) for x in room[3:].split(":"))
    except ValueError:
        return None
    return b if a == int(user_id) else a if b == int(user_id) else None


async def chat_user(user_id):
    """Chat uchun odam: {uid, name, house} yoki None."""
    def _do():
        conn = _connect()
        try:
            r = conn.execute("SELECT user_id, COALESCE(first_name, 'Sehrgar') AS name, house "
                             "FROM users WHERE user_id=?", (int(user_id),)).fetchone()
            return {"uid": r["user_id"], "name": r["name"], "house": r["house"]} if r else None
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chat_members(house, season_id):
    """Fakultetga kirganlar (house None - hamma fakultet), shu mavsum ballari bo'yicha."""
    def _do():
        conn = _connect()
        try:
            where, args = "u.house IN (%s)" % ",".join("?" * len(HOUSES)), list(HOUSES)
            if house:
                where, args = "u.house=?", [house]
            rows = conn.execute(
                "SELECT u.user_id, COALESCE(u.first_name, 'Sehrgar') AS name, u.house, "
                "COALESCE(SUM(p.points), 0) AS pts FROM users u "
                "LEFT JOIN points p ON p.user_id=u.user_id AND p.season_id=? "
                "WHERE " + where + " GROUP BY u.user_id ORDER BY pts DESC, u.user_id ASC",
                [season_id] + args).fetchall()
            return [{"uid": r["user_id"], "name": (r["name"] or "Sehrgar").strip()[:40],
                     "house": r["house"], "points": r["pts"]} for r in rows]
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chat_dm_list(user_id):
    """Shaxsiy suhbatlar: oxirgi xabari bo'yicha, yangisi tepada."""
    def _do():
        conn = _connect()
        try:
            uid = int(user_id)
            rooms = conn.execute(
                "SELECT house AS room, MAX(id) AS last_id FROM chat_messages "
                "WHERE deleted=0 AND (house LIKE ? OR house LIKE ?) "
                "GROUP BY house ORDER BY last_id DESC LIMIT 100",
                ("dm:%d:%%" % uid, "dm:%%:%d" % uid)).fetchall()
            out = []
            for r in rooms:
                peer = _dm_peer(r["room"], uid)
                if peer is None:
                    continue
                p = conn.execute("SELECT COALESCE(first_name, 'Sehrgar') AS name, house FROM users "
                                 "WHERE user_id=?", (peer,)).fetchone()
                m = conn.execute("SELECT user_id, message, created_at FROM chat_messages WHERE id=?",
                                 (r["last_id"],)).fetchone()
                out.append({
                    "room": "dm:%d" % peer,
                    "peer": {"uid": peer, "name": p["name"] if p else "Sehrgar", "house": p["house"] if p else None},
                    "last": {"uid": m["user_id"], "text": (m["message"] or "")[:120], "time": m["created_at"]},
                    "unread": _read_state(conn, r["room"], uid)[1],
                })
            return out
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chat_max_rev(house):
    def _do():
        conn = _connect()
        try:
            return conn.execute("SELECT COALESCE(MAX(rev), 0) FROM chat_messages WHERE house=?",
                                (house,)).fetchone()[0]
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def post_chat_message(house, user_id, message, reply_to=None):
    """Xabarni saqlaydi va uni ro'yxatdagi ko'rinishida qaytaradi.

    reply_to boshqa xonadagi yoki o'chirilgan xabarga ishora qilsa - e'tiborsiz qoldiriladi.
    """
    def _do():
        conn = _connect()
        try:
            target = None
            if reply_to:
                ok = conn.execute(
                    "SELECT 1 FROM chat_messages WHERE id=? AND house=? AND deleted=0",
                    (int(reply_to), house)).fetchone()
                target = int(reply_to) if ok else None
            stamp = _utc_iso(now_tk())
            cur = conn.execute(
                "INSERT INTO chat_messages (house, user_id, message, created_at, reply_to, rev) "
                "VALUES (?,?,?,?,?," + _NEXT_REV + ")",
                (house, int(user_id), message.strip(), stamp, target)
            )
            conn.commit()
            return _chat_one(conn, cur.lastrowid, user_id)
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


def _own_live_message(conn, house, msg_id):
    return conn.execute(
        "SELECT id, user_id, created_at FROM chat_messages WHERE id=? AND house=? AND deleted=0",
        (int(msg_id), house)).fetchone()


async def edit_chat_message(house, user_id, msg_id, text):
    """O'z xabarini tahrirlash (CHAT_EDIT_HOURS soat ichida). Xato bo'lsa - matn kodi."""
    def _do():
        conn = _connect()
        try:
            row = _own_live_message(conn, house, msg_id)
            if not row or row["user_id"] != int(user_id):
                return "not_found"
            made = _parse_iso(row["created_at"])
            if made and (now_tk() - made).total_seconds() > CHAT_EDIT_HOURS * 3600:
                return "too_old"
            conn.execute(
                "UPDATE chat_messages SET message=?, edited_at=?, rev=" + _NEXT_REV + " WHERE id=?",
                (text.strip(), _utc_iso(now_tk()), row["id"]))
            conn.commit()
            return _chat_one(conn, row["id"], user_id)
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def delete_chat_message(house, user_id, msg_id, admin=False):
    """O'z xabarini (admin - istalganini) o'chiradi. Qator qoladi, matn tozalanadi:
    boshqa ilovalar o'zgarish raqami orqali "o'chirildi" deb bilib oladi."""
    def _do():
        conn = _connect()
        try:
            row = _own_live_message(conn, house, msg_id)
            if not row or (row["user_id"] != int(user_id) and not admin):
                return False
            conn.execute(
                "UPDATE chat_messages SET message='', deleted=1, rev=" + _NEXT_REV + " WHERE id=?",
                (row["id"],))
            conn.execute("DELETE FROM chat_reactions WHERE message_id=?", (row["id"],))
            conn.commit()
            return True
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def react_chat_message(house, user_id, msg_id, emoji):
    """Reaksiya: bir odam - bir xabarga bitta. Xuddi shu belgini qayta bosish uni olib tashlaydi."""
    def _do():
        conn = _connect()
        try:
            row = _own_live_message(conn, house, msg_id)
            if not row:
                return None
            old = conn.execute(
                "SELECT emoji FROM chat_reactions WHERE message_id=? AND user_id=?",
                (row["id"], int(user_id))).fetchone()
            if old and old["emoji"] == emoji:
                conn.execute("DELETE FROM chat_reactions WHERE message_id=? AND user_id=?",
                             (row["id"], int(user_id)))
            else:
                conn.execute(
                    "INSERT OR REPLACE INTO chat_reactions (message_id, user_id, emoji) VALUES (?,?,?)",
                    (row["id"], int(user_id), emoji))
            conn.execute("UPDATE chat_messages SET rev=" + _NEXT_REV + " WHERE id=?", (row["id"],))
            conn.commit()
            return _chat_one(conn, row["id"], user_id)
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chess_create_game(user_id, time_control=300):
    def _do():
        conn = _connect()
        try:
            import secrets
            game_id = secrets.token_hex(4)
            stamp = _utc_iso(now_tk())
            initial_fen = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"
            conn.execute(
                "INSERT INTO chess_games (id, white_uid, black_uid, fen, turn, status, white_time, black_time, last_move_at, created_at) "
                "VALUES (?, ?, NULL, ?, 'w', 'waiting', ?, ?, ?, ?)",
                (game_id, int(user_id), initial_fen, time_control, time_control, stamp, stamp)
            )
            conn.commit()
            return game_id
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chess_join_game(game_id, user_id):
    def _do():
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM chess_games WHERE id=?", (game_id,)).fetchone()
            if not row:
                return {"ok": False, "error": "not_found"}
            if row["status"] != "waiting":
                if row["white_uid"] == int(user_id) or row["black_uid"] == int(user_id):
                    return {"ok": True, "game_id": game_id}
                return {"ok": False, "error": "game_already_started"}
            if row["white_uid"] == int(user_id):
                return {"ok": True, "game_id": game_id}
            
            stamp = _utc_iso(now_tk())
            conn.execute(
                "UPDATE chess_games SET black_uid=?, status='active', last_move_at=? WHERE id=?",
                (int(user_id), stamp, game_id)
            )
            conn.commit()
            return {"ok": True, "game_id": game_id}
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chess_get_game(game_id):
    def _do():
        conn = _connect()
        try:
            row = conn.execute(
                "SELECT g.*, "
                "COALESCE(uw.first_name, 'Sehrgar') AS white_name, uw.house AS white_house, "
                "COALESCE(ub.first_name, 'Sehrgar') AS black_name, ub.house AS black_house "
                "FROM chess_games g "
                "LEFT JOIN users uw ON uw.user_id = g.white_uid "
                "LEFT JOIN users ub ON ub.user_id = g.black_uid "
                "WHERE g.id=?", (game_id,)).fetchone()
            if not row:
                return None
            return {
                "id": row["id"],
                "white_uid": row["white_uid"],
                "white_name": row["white_name"],
                "white_house": row["white_house"],
                "black_uid": row["black_uid"],
                "black_name": row["black_name"],
                "black_house": row["black_house"],
                "fen": row["fen"],
                "turn": row["turn"],
                "status": row["status"],
                "winner_uid": row["winner_uid"],
                "win_reason": row["win_reason"],
                "white_time": row["white_time"],
                "black_time": row["black_time"],
                "last_move_at": row["last_move_at"],
                "created_at": row["created_at"]
            }
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chess_make_move(game_id, user_id, fen, next_turn, white_time, black_time):
    def _do():
        conn = _connect()
        try:
            stamp = _utc_iso(now_tk())
            conn.execute(
                "UPDATE chess_games SET fen=?, turn=?, white_time=?, black_time=?, last_move_at=? WHERE id=?",
                (fen, next_turn, white_time, black_time, stamp, game_id)
            )
            conn.commit()
            return True
        finally:
            conn.close()
    return await asyncio.to_thread(_do)


async def chess_finish_game(game_id, user_id, winner_uid, win_reason):
    """O'yinni yakunlaydi va kim yutganini QAT'IY aniqlaydi.

    Shaxmat mantig'i brauzerda hisoblanadi, ya'ni natija mijozdan keladi va
    server uni tekshira olmaydi. Himoya shu sababli uch qatlamli:

      1) faqat shu o'yinning ikki qatnashchisi yozishi mumkin;
      2) natija BIRINCHI yozilganda qayd etiladi va keyin o'zgarmaydi -
         ikkinchi o'yinchi boshqacha da'vo qilsa, qabul qilinmaydi;
      3) mavsumda ballanadigan o'yinlar soni cheklangan (award_chess).

    Qaytaradi: {"ok": ..., "result": "win"/"loss"/"draw", ...}
    """
    def _do():
        conn = _connect()
        try:
            row = conn.execute("SELECT * FROM chess_games WHERE id=?",
                               (game_id,)).fetchone()
            if not row:
                return {"ok": False, "error": "not_found"}

            uid = int(user_id)
            white, black = row["white_uid"], row["black_uid"]
            if uid not in (white, black):
                return {"ok": False, "error": "not_a_player"}

            # Jonli o'yin emas: raqib qo'shilmagan yoki o'zi bilan o'zi.
            if not black or white == black:
                return {"ok": False, "error": "not_pvp"}

            if row["status"] == "finished":
                # Natija allaqachon qayd etilgan - o'zgartirmaymiz.
                final_winner = row["winner_uid"]
            else:
                final_winner = int(winner_uid) if winner_uid else None
                if final_winner is not None and final_winner not in (white, black):
                    return {"ok": False, "error": "bad_winner"}
                conn.execute(
                    "UPDATE chess_games SET status='finished', winner_uid=?, "
                    "win_reason=? WHERE id=?",
                    (final_winner, win_reason, game_id))
                conn.commit()

            if final_winner is None:
                natija = "draw"
            elif int(final_winner) == uid:
                natija = "win"
            else:
                natija = "loss"
            return {"ok": True, "result": natija, "winner_uid": final_winner}
        finally:
            conn.close()
    return await asyncio.to_thread(_do)
