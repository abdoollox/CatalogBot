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

FILM_PARTS = 8
QUIZ_PER_FILM = 3
DAILY_PER_WEEK = 7

# Bir mavsumda olish mumkin bo'lgan eng ko'p ball
MAX_POINTS = (PTS_FILM_OPEN * FILM_PARTS
              + PTS_FILM_QUIZ * FILM_PARTS * QUIZ_PER_FILM
              + PTS_DAILY * DAILY_PER_WEEK)          # = 350

ACTIVE_MIN_POINTS = 30    # foydalanuvchi "faol" hisoblanishi uchun kerak ball

HOUSES = ("gryffindor", "slytherin", "ravenclaw", "hufflepuff")
BADGE_CODES = ("all_films", "flawless_exam", "perfect_week", "streak_7")

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    user_id     INTEGER PRIMARY KEY,
    first_name  TEXT,
    house       TEXT,
    sorted_at   TEXT,
    created_at  TEXT NOT NULL
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
    source_type TEXT NOT NULL CHECK (source_type IN ('film_open','film_quiz','daily')),
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

async def get_chat_messages(house, limit=50):
    def _do():
        conn = _connect()
        try:
            rows = conn.execute(
                "SELECT c.id, c.user_id, COALESCE(u.first_name, 'Sehrgar') AS name, c.message, c.created_at "
                "FROM chat_messages c "
                "LEFT JOIN users u ON u.user_id = c.user_id "
                "WHERE c.house=? "
                "ORDER BY c.id DESC LIMIT ?", (house, limit)).fetchall()
            out = []
            for r in rows:
                out.append({
                    "id": r["id"],
                    "uid": r["user_id"],
                    "name": r["name"],
                    "text": r["message"],
                    "time": r["created_at"]
                })
            return list(reversed(out))
        finally:
            conn.close()
    return await asyncio.to_thread(_do)

async def post_chat_message(house, user_id, message):
    def _do():
        conn = _connect()
        try:
            stamp = _utc_iso(now_tk())
            conn.execute(
                "INSERT INTO chat_messages (house, user_id, message, created_at) "
                "VALUES (?,?,?,?)", (house, int(user_id), message.strip(), stamp)
            )
            conn.commit()
        finally:
            conn.close()
    return await asyncio.to_thread(_do)
