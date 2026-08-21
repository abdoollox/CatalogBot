"""Xogvarts kubogi — SQLite qatlami.

Haftalik fakultetlar musobaqasi: ball, mavsum, savol, nishon.
Bu modul faqat baza bilan ishlaydi — Telegram yoki HTTP haqida bilmaydi.

sqlite3 bloklovchi kutubxona, aiogram esa async. Shuning uchun har bir
ochiq funksiya `asyncio.to_thread` orqali chaqiriladi (sheets.py kabi).
Sinxron variantlari `_` bilan boshlanadi va faqat shu modul ichida ishlatiladi.
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
                      #                              JAMI = 350

FILM_PARTS = 8
QUIZ_PER_FILM = 3
MIN_ACTIVE_MEMBERS = 5   # fakultet g'olib bo'lishi uchun minimal faol a'zo

BADGE_CODES = ("all_films", "flawless_exam", "perfect_week", "streak_7")

SCHEMA = """
CREATE TABLE IF NOT EXISTS seasons (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    starts_at   TEXT NOT NULL,
    ends_at     TEXT NOT NULL,
    status      TEXT NOT NULL
                CHECK (status IN ('active','closed')),
    winner_house TEXT
);

CREATE TABLE IF NOT EXISTS points (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    season_id   INTEGER NOT NULL REFERENCES seasons(id),
    house       TEXT NOT NULL,
    source_type TEXT NOT NULL
                CHECK (source_type IN ('film_open','film_quiz','daily')),
    source_ref  TEXT NOT NULL,
    points      INTEGER NOT NULL,
    created_at  TEXT NOT NULL,
    UNIQUE (user_id, season_id, source_type, source_ref)
);

CREATE INDEX IF NOT EXISTS idx_points_season_house ON points(season_id, house);
CREATE INDEX IF NOT EXISTS idx_points_season_user  ON points(season_id, user_id);

CREATE TABLE IF NOT EXISTS questions (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    kind          TEXT NOT NULL
                  CHECK (kind IN ('film','daily')),
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

CREATE TABLE IF NOT EXISTS badges (
    user_id   INTEGER NOT NULL,
    code      TEXT NOT NULL,
    season_id INTEGER REFERENCES seasons(id),
    earned_at TEXT NOT NULL,
    PRIMARY KEY (user_id, code, season_id)
);
"""


# ---------------------------------------------------------------- vaqt

def now_tk():
    """Hozirgi vaqt, Toshkent mintaqasida."""
    return datetime.now(TASHKENT)


def today_tk():
    """Bugungi sana 'YYYY-MM-DD' ko'rinishida, Toshkent vaqti bo'yicha."""
    return now_tk().strftime("%Y-%m-%d")


def _utc_iso(dt):
    """Mintaqali vaqtni '...Z' ko'rinishidagi UTC ISO matnga o'giradi."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def season_bounds(moment=None):
    """Berilgan payt tushadigan haftaning chegaralari.

    Dushanba 00:00 dan yakshanba 23:59 gacha (Toshkent vaqti),
    UTC ISO matn ko'rinishida qaytariladi.
    """
    moment = moment or now_tk()
    moment = moment.astimezone(TASHKENT)
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


def _init():
    conn = _connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
        _ensure_season(conn)
    finally:
        conn.close()


async def init():
    """Bazani yaratadi va joriy mavsum borligiga ishonch hosil qiladi."""
    await asyncio.to_thread(_init)
    logging.info("Xogvarts kubogi bazasi tayyor: %s", DB_PATH)


# ---------------------------------------------------------------- mavsum

def _ensure_season(conn):
    """Joriy haftaga mos faol mavsumni qaytaradi, kerak bo'lsa yaratadi."""
    starts, ends = season_bounds()

    row = conn.execute(
        "SELECT * FROM seasons WHERE status='active' ORDER BY id DESC LIMIT 1"
    ).fetchone()

    if row:
        # Faol mavsum shu haftaga tegishli bo'lsa - o'shani ishlatamiz.
        if row["starts_at"] == starts:
            return dict(row)
        # Hafta o'tib ketgan, lekin yopilmagan (bot o'chiq turgan bo'lishi
        # mumkin). Eskisini yopib, yangisini ochamiz.
        conn.execute("UPDATE seasons SET status='closed' WHERE id=?", (row["id"],))

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

def _award(user_id, house, source_type, source_ref, pts):
    conn = _connect()
    try:
        season = _ensure_season(conn)
        cur = conn.execute(
            "INSERT OR IGNORE INTO points "
            "(user_id, season_id, house, source_type, source_ref, points, created_at) "
            "VALUES (?,?,?,?,?,?,?)",
            (int(user_id), season["id"], house, source_type, str(source_ref),
             int(pts), _utc_iso(now_tk())))
        conn.commit()
        # rowcount 0 -> UNIQUE cheklovi ushladi, ya'ni ball avval berilgan
        return cur.rowcount > 0
    finally:
        conn.close()


async def award(user_id, house, source_type, source_ref, pts):
    """Ball beradi. Takroriy urinish bo'lsa False qaytaradi.

    Takrorlanishni baza o'zi to'sadi (UNIQUE), kodda tekshirish shart emas.
    """
    if not house or house == "none":
        return False
    return await asyncio.to_thread(
        _award, user_id, house, source_type, source_ref, pts)


# ---------------------------------------------------------------- reyting

def _leaderboard(season_id):
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT house, SUM(points) AS total_points, "
            "       COUNT(DISTINCT user_id) AS active_members, "
            "       CAST(SUM(points) AS REAL) / COUNT(DISTINCT user_id) AS avg_points "
            "FROM points WHERE season_id=? GROUP BY house ORDER BY avg_points DESC",
            (season_id,)).fetchall()
        out = []
        for r in rows:
            active = r["active_members"]
            qualified = active >= MIN_ACTIVE_MEMBERS
            item = {
                "house": r["house"],
                "total_points": r["total_points"],
                "active_members": active,
                "avg_points": round(r["avg_points"], 1),
                "qualified": qualified,
            }
            if not qualified:
                item["needed"] = MIN_ACTIVE_MEMBERS - active
            out.append(item)
        return out
    finally:
        conn.close()


async def leaderboard(season_id):
    """Fakultetlar reytingi — o'rtacha ball bo'yicha, umumiy ball bo'yicha emas."""
    return await asyncio.to_thread(_leaderboard, season_id)


def _user_stats(user_id, season_id):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(points),0) AS pts, house FROM points "
            "WHERE user_id=? AND season_id=?", (int(user_id), season_id)).fetchone()
        pts = row["pts"] if row else 0
        house = row["house"] if row and row["house"] else None

        rank = None
        if house:
            rank = conn.execute(
                "SELECT COUNT(*)+1 FROM ("
                "  SELECT user_id, SUM(points) s FROM points "
                "  WHERE season_id=? AND house=? GROUP BY user_id HAVING s > ?"
                ")", (season_id, house, pts)).fetchone()[0]

        codes = [r["code"] for r in conn.execute(
            "SELECT DISTINCT code FROM badges WHERE user_id=?",
            (int(user_id),)).fetchall()]

        return {"points": pts, "house": house, "house_rank": rank, "badges": codes}
    finally:
        conn.close()


async def user_stats(user_id, season_id):
    return await asyncio.to_thread(_user_stats, user_id, season_id)


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
            # qaytsa, savollar o'sha tartibda davom etsin (bazadan ular
            # ORDER BY q.id bilan o'qiladi).
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
            (int(user_id), season_id)).fetchall()}

        return [_row_to_question(r) for r in rows if r["id"] not in answered]
    finally:
        conn.close()


async def film_questions(user_id, season_id, film_part):
    """Shu qism uchun biriktirilgan, hali javob berilmagan savollar.

    Birinchi marta chaqirilganda tasodifiy 3 ta savol biriktiriladi va
    keyingi urinishlarda o'shalar qaytariladi — yodlab olishning oldini
    olish uchun har mavsumda qaytadan tanlanadi.
    """
    return await asyncio.to_thread(
        _pick_film_questions, user_id, season_id, film_part)


def _row_to_question(r):
    try:
        options = json.loads(r["options"])
    except Exception:
        options = []
    return {
        "id": r["id"],
        "body": r["body"],
        "options": options,
        "correct_index": r["correct_index"],
    }


def _daily_question(date_str):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT q.* FROM daily_schedule d JOIN questions q ON q.id=d.question_id "
            "WHERE d.date=?", (date_str,)).fetchone()
        if row:
            return _row_to_question(row)

        # Bugunga savol belgilanmagan - eng kam ishlatilganini tanlaymiz.
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
    """Javobni yozadi. Takroriy urinish bo'lsa False qaytaradi.

    Noto'g'ri javob ham yoziladi — qayta urinib bo'lmaydi.
    """
    return await asyncio.to_thread(
        _record_answer, user_id, season_id, question_id, is_correct)


def _already_answered_daily(user_id, season_id, question_id):
    conn = _connect()
    try:
        row = conn.execute(
            "SELECT 1 FROM answers WHERE user_id=? AND season_id=? AND question_id=?",
            (int(user_id), season_id, int(question_id))).fetchone()
        return row is not None
    finally:
        conn.close()


async def already_answered(user_id, season_id, question_id):
    return await asyncio.to_thread(
        _already_answered_daily, user_id, season_id, question_id)


# ---------------------------------------------------------------- nishonlar

def _earned_badges(conn, season_id):
    """Mavsum bo'yicha nishon qozonganlarni hisoblaydi."""
    found = []

    # 1) all_films - 8 ta qismni ham ochgan
    for r in conn.execute(
            "SELECT user_id FROM points "
            "WHERE season_id=? AND source_type='film_open' "
            "GROUP BY user_id HAVING COUNT(DISTINCT source_ref) >= ?",
            (season_id, FILM_PARTS)):
        found.append((r["user_id"], "all_films"))

    # 2) flawless_exam - 24 ta imtihon savolining hammasi to'g'ri
    for r in conn.execute(
            "SELECT a.user_id FROM answers a JOIN questions q ON q.id=a.question_id "
            "WHERE a.season_id=? AND q.kind='film' "
            "GROUP BY a.user_id "
            "HAVING COUNT(*) >= ? AND SUM(a.is_correct) = COUNT(*)",
            (season_id, FILM_PARTS * QUIZ_PER_FILM)):
        found.append((r["user_id"], "flawless_exam"))

    # 3) perfect_week - 7 ta kunlik savolning hammasi to'g'ri
    for r in conn.execute(
            "SELECT a.user_id FROM answers a JOIN questions q ON q.id=a.question_id "
            "WHERE a.season_id=? AND q.kind='daily' "
            "GROUP BY a.user_id "
            "HAVING COUNT(*) >= 7 AND SUM(a.is_correct) = COUNT(*)",
            (season_id,)):
        found.append((r["user_id"], "perfect_week"))

    # 4) streak_7 - ketma-ket 7 kun kamida 1 ball
    for r in conn.execute(
            "SELECT user_id, COUNT(DISTINCT DATE(created_at)) AS days FROM points "
            "WHERE season_id=? GROUP BY user_id HAVING days >= 7", (season_id,)):
        found.append((r["user_id"], "streak_7"))

    return found


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

        # 1) G'olib - o'rtacha ball bo'yicha, chegaradan o'tganlar orasidan
        winner = None
        for item in _leaderboard(season_id):
            if item["qualified"]:
                winner = item["house"]
                break

        # 2) Nishonlar
        stamp = _utc_iso(now_tk())
        badges = _earned_badges(conn, season_id)
        conn.executemany(
            "INSERT OR IGNORE INTO badges (user_id, code, season_id, earned_at) "
            "VALUES (?,?,?,?)",
            [(uid, code, season_id, stamp) for uid, code in badges])

        # 3) Mavsumni yopish
        conn.execute("UPDATE seasons SET status='closed', winner_house=? WHERE id=?",
                     (winner, season_id))
        conn.commit()

        # 4) Yangi mavsum
        new_season = _ensure_season(conn)

        return {
            "closed_id": season_id,
            "winner_house": winner,
            "badges": badges,
            "table": _leaderboard(season_id),
            "new_season_id": new_season["id"],
        }
    finally:
        conn.close()


async def close_season(season_id=None):
    """Mavsumni yopadi, g'olibni aniqlaydi, nishon beradi, yangisini ochadi."""
    return await asyncio.to_thread(_close_season, season_id)


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
    """JSON ro'yxatdan savollarni yuklaydi. Noto'g'ri yozuvlar o'tkazib yuboriladi."""
    return await asyncio.to_thread(_load_questions, items, replace)


def _counts():
    conn = _connect()
    try:
        out = {}
        for name in ("seasons", "points", "questions", "answers",
                     "question_assignments", "daily_schedule", "badges"):
            out[name] = conn.execute("SELECT COUNT(*) FROM " + name).fetchone()[0]
        out["film_questions"] = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE kind='film' AND is_active=1"
        ).fetchone()[0]
        out["daily_questions"] = conn.execute(
            "SELECT COUNT(*) FROM questions WHERE kind='daily' AND is_active=1"
        ).fetchone()[0]
        return out
    finally:
        conn.close()


async def counts():
    """Diagnostika uchun jadval hajmlari."""
    return await asyncio.to_thread(_counts)
