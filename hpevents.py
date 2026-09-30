# -*- coding: utf-8 -*-
"""Foydalanuvchi harakatlari (bosishlar) - hp.db dagi `events` jadvali.

Ilgari har bosish `users_db.json` ga yozilardi: 2 MB lik fayl HAR SAFAR
to'liq o'qilib, qayta yozilardi. Yozish yarmida uzilsa (deploy, xotira
chegarasi) fayl buzilar, keyingi bosish esa uni "bo'sh" deb bitta odam
bilan ustidan yozib, butun tarixni o'chirardi. Endi har bosish bazaga
BITTA qator bo'lib qo'shiladi - tez va xavfsiz.

users_db.json 2026-09-30 da muzlatildi: birinchi ishga tushishda undagi
butun tarix shu jadvalga bir marta ko'chiriladi (settings.events_from_json),
fayl esa arxiv sifatida qoladi va boshqa yozilmaydi.

Google Sheets (kuzatuv paneli manbai) avvalgidek to'ldirilib boraveradi.
"""

import asyncio
import json
import logging

import hpcup

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    id       INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id  INTEGER NOT NULL,
    nickname TEXT,
    username TEXT,
    payload  TEXT NOT NULL,
    ts       TEXT NOT NULL              -- server vaqti (UTC), "YYYY-MM-DD HH:MM:SS"
);
CREATE INDEX IF NOT EXISTS idx_events_user ON events(user_id);
CREATE INDEX IF NOT EXISTS idx_events_payload ON events(payload);
"""
IMPORT_KEY = "events_from_json"


def _init(users_json):
    conn = hpcup._connect()
    try:
        conn.executescript(SCHEMA)
        done = conn.execute("SELECT value FROM settings WHERE key=?", (IMPORT_KEY,)).fetchone()
        if done:
            return None
        # Fayl topilmasa yoki buzuq bo'lsa - "ko'chirildi" deb BELGILANMAYDI:
        # keyingi ishga tushishda qayta urinadi (bo'sh tarix bilan yopib qo'ymasin).
        try:
            with open(users_json, encoding="utf-8") as f:
                db = json.load(f)
        except FileNotFoundError:
            logging.warning("users_db.json topilmadi (%s) - tarix ko'chirilmadi", users_json)
            return None
        rows = []
        for uid, rec in db.items():
            try:
                uid_i = int(uid)
            except (TypeError, ValueError):
                continue
            nick, uname = rec.get("nickname"), rec.get("username")
            for payload, stamps in (rec.get("clicks") or {}).items():
                for ts in stamps or []:
                    rows.append((uid_i, nick, uname, payload, ts))
        rows.sort(key=lambda r: r[4])
        conn.executemany("INSERT INTO events (user_id, nickname, username, payload, ts) "
                         "VALUES (?,?,?,?,?)", rows)
        conn.execute("INSERT INTO settings (key, value) VALUES (?,?)",
                     (IMPORT_KEY, "%d odam, %d yozuv" % (len(db), len(rows))))
        conn.commit()
        return len(db), len(rows)
    finally:
        conn.close()


async def init(users_json):
    res = await asyncio.to_thread(_init, users_json)
    if res:
        logging.info("users_db.json bazaga ko'chirildi: %d odam, %d yozuv", *res)


def imported():
    """users_db.json allaqachon ko'chirilganmi (hpcup migratsiyasi uchun)."""
    conn = hpcup._connect()
    try:
        row = conn.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='settings'").fetchone()
        return bool(row and conn.execute("SELECT 1 FROM settings WHERE key=?", (IMPORT_KEY,)).fetchone())
    finally:
        conn.close()


def _log(user_id, nickname, username, payload, ts):
    conn = hpcup._connect()
    try:
        conn.execute("INSERT INTO events (user_id, nickname, username, payload, ts) VALUES (?,?,?,?,?)",
                     (int(user_id), nickname, username, payload, ts))
        conn.commit()
    finally:
        conn.close()


async def log(user_id, nickname, username, payload, ts):
    await asyncio.to_thread(_log, user_id, nickname, username, payload, ts)


def _known(user_id):
    conn = hpcup._connect()
    try:
        return conn.execute("SELECT 1 FROM events WHERE user_id=? LIMIT 1", (int(user_id),)).fetchone() is not None
    finally:
        conn.close()


async def known(user_id):
    """Bu odam botga avval kelganmi (birorta harakati yozilganmi)."""
    return await asyncio.to_thread(_known, user_id)
