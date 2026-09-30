#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Kunlik zaxira: baza va barcha muhim fayllar bitta zip arxivda.

Har kuni 03:00 (Toshkent) cron orqali ishga tushadi.

Arxiv ichida:
  - hp.db          — SQLite Online Backup API bilan (baza band bo'lsa ham butun nusxa)
  - users_db.json  — foydalanuvchilar va bosishlar tarixi
  - music.json, music_raw.json, films.json, promo.json — bor bo'lsa

Qayerga:
  - backups/daily/hp-YYYY-MM-DD.zip  (serverda, oxirgi KEEP_DAYS kun)
  - Telegram: HP_BACKUP_CHAT, u yo'q bo'lsa .env dagi BIRINCHI admin (ADMIN_IDS)

ESKI XATO (2026-09-28 da topildi): nusxalar `backups/hp-*.db` da turardi va
tozalash qo'lda olingan `hp-before-*.db` larni ham sanardi. Ular alifboda
keyin turgani uchun har kuni YANGI nusxa o'chib ketardi - 37 kun zaxira
bo'lmagan. Endi kundalik nusxalar alohida `daily/` papkasida.

Ishlatish:
    python3 backup_hp.py            # zaxira olish va yuborish
    python3 backup_hp.py --test     # zaxira olinadi, Telegramga yuborilmaydi
"""

import os
import sys
import glob
import json
import time
import sqlite3
import zipfile
import logging
import tempfile
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(BASE, "data")
DB = os.path.join(DATA, "hp.db")
OUT_ROOT = os.path.join(BASE, "backups")
OUT_DIR = os.path.join(OUT_ROOT, "daily")
ENV_FILE = os.path.join(BASE, ".env")
KEEP_DAYS = 14
# Deploydan oldin qo'lda olinadigan nusxalar (backups/hp-before-*.db):
# 30 kundan eskilari o'chiriladi, lekin eng yangi 5 tasi doim qoladi.
MANUAL_DAYS = 30
MANUAL_KEEP = 5
EXTRA = ["users_db.json", "music.json", "music_raw.json", "films.json", "promo.json"]

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def read_env():
    env = {}
    try:
        with open(ENV_FILE, "r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip().strip('"').strip("'")
    except OSError as e:
        logging.warning("`.env` o'qilmadi: %s", e)
    return env


def db_copy(target):
    """hp.db ning butun nusxasi + tekshiruv. Muvaffaqiyatli bo'lsa qisqa hisobot."""
    # Oddiy ulanish: "faqat o'qish" rejimi WAL bazada -shm fayli bo'lmasa ochilmay qolishi mumkin
    src = sqlite3.connect(DB, timeout=30)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)          # = sqlite3 ".backup"
        finally:
            dst.close()
    finally:
        src.close()
    check = sqlite3.connect(target)
    try:
        state = check.execute("PRAGMA integrity_check").fetchone()[0]
        users = check.execute("SELECT COUNT(*) FROM users").fetchone()[0]
        points = check.execute("SELECT COUNT(*) FROM points").fetchone()[0]
    finally:
        check.close()
    if state != "ok":
        raise RuntimeError("baza nusxasi buzuq (integrity_check=%s)" % state)
    return "%d odam, %d ball yozuvi" % (users, points)


def make_backup():
    if not os.path.exists(DB):
        logging.error("Baza topilmadi: %s", DB)
        return None, None
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    target = os.path.join(OUT_DIR, "hp-%s.zip" % stamp)

    with tempfile.TemporaryDirectory() as tmp:
        db_tmp = os.path.join(tmp, "hp.db")
        summary = db_copy(db_tmp)
        tmp_zip = target + ".tmp"
        with zipfile.ZipFile(tmp_zip, "w", zipfile.ZIP_DEFLATED) as z:
            z.write(db_tmp, "hp.db")
            for name in EXTRA:
                path = os.path.join(DATA, name)
                if not os.path.exists(path):
                    continue
                try:
                    with open(path, encoding="utf-8") as f:
                        json.load(f)          # buzuq JSON zaxiraga "yaxshi" bo'lib kirmasin
                except Exception as e:
                    logging.error("%s buzuq, arxivga baribir qo'shildi: %s", name, e)
                z.write(path, name)
        os.replace(tmp_zip, target)

    logging.info("Zaxira tayyor: %s (%d bayt; %s)", target, os.path.getsize(target), summary)
    return target, summary


def send_to_telegram(path, token, chat_id, caption):
    """Faylni Telegram chatiga yuboradi (multipart, kutubxonasiz)."""
    boundary = "----hpbackup%d" % int(time.time() * 1000)
    with open(path, "rb") as f:
        blob = f.read()
    parts = [
        ("--%s\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n%s\r\n"
         % (boundary, chat_id)).encode(),
        ("--%s\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n%s\r\n"
         % (boundary, caption)).encode(),
        ("--%s\r\nContent-Disposition: form-data; name=\"disable_notification\"\r\n\r\ntrue\r\n"
         % boundary).encode(),
        ("--%s\r\nContent-Disposition: form-data; name=\"document\"; filename=\"%s\"\r\n"
         "Content-Type: application/zip\r\n\r\n" % (boundary, os.path.basename(path))).encode(),
        blob,
        ("\r\n--%s--\r\n" % boundary).encode(),
    ]
    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendDocument" % token, data=b"".join(parts),
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
    last = None
    for urinish in range(3):              # server tarmog'i beqaror
        try:
            with urllib.request.urlopen(req, timeout=120) as resp:
                answer = json.loads(resp.read().decode())
            if answer.get("ok"):
                return True
            raise RuntimeError("Telegram rad etdi: %s" % answer.get("description"))
        except Exception as e:
            last = e
            time.sleep(10 * (urinish + 1))
    raise last


def prune():
    daily = sorted(glob.glob(os.path.join(OUT_DIR, "hp-*.zip")))
    for old in daily[:-KEEP_DAYS]:
        os.remove(old)
        logging.info("Eski kundalik zaxira o'chirildi: %s", os.path.basename(old))
    manual = sorted(glob.glob(os.path.join(OUT_ROOT, "hp-before-*.db")), key=os.path.getmtime)
    chegara = time.time() - MANUAL_DAYS * 86400
    for old in manual[:-MANUAL_KEEP]:
        if os.path.getmtime(old) < chegara:
            os.remove(old)
            logging.info("Eski qo'lda olingan nusxa o'chirildi: %s", os.path.basename(old))


def main():
    test_only = "--test" in sys.argv
    try:
        path, summary = make_backup()
    except Exception as e:
        logging.error("Zaxira olinmadi: %s", e)
        path, summary = None, None
    env = read_env()
    token = env.get("BOT_TOKEN")
    admins = [x for x in env.get("ADMIN_IDS", "").replace(" ", "").split(",") if x.lstrip("-").isdigit()]
    chat = env.get("HP_BACKUP_CHAT") or (admins[0] if admins else None)

    if not path:
        # Zaxira olinmagani ham jim qolmasin - admin bilsin
        if token and chat and not test_only:
            try:
                req = urllib.request.Request(
                    "https://api.telegram.org/bot%s/sendMessage" % token,
                    data=json.dumps({"chat_id": chat, "text": "⚠️ Kundalik zaxira OLINMADI. "
                                     "Serverdagi backups/backup.log ni tekshirish kerak."}).encode(),
                    headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req, timeout=30).read()
            except Exception as e:
                logging.error("Ogohlantirish ham yuborilmadi: %s", e)
        return 1

    if test_only:
        logging.info("TEST rejimi — Telegramga yuborilmadi.")
    elif token and chat:
        caption = "🗄 Garri Potter zaxirasi — %s\n%s" % (datetime.now().strftime("%Y-%m-%d %H:%M"), summary)
        try:
            send_to_telegram(path, token, chat, caption)
            logging.info("Telegramga yuborildi (chat %s)", chat)
        except Exception as e:
            logging.error("Telegramga yuborishda xato: %s", e)
    else:
        logging.warning("BOT_TOKEN yoki qabul qiluvchi chat yo'q — zaxira faqat serverda.")

    prune()
    return 0


if __name__ == "__main__":
    sys.exit(main())
