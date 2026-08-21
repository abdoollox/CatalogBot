#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Xogvarts kubogi bazasining kunlik zaxirasi.

Har kuni 03:00 (Toshkent) cron orqali ishga tushadi.

`cp` ISHLATILMAYDI — yozuv paytida buzilgan nusxa berishi mumkin. Buning
o'rniga SQLite Online Backup API (`sqlite3 .backup` buyrug'i bilan aynan
bir xil mexanizm) ishlatiladi: baza band bo'lsa ham butun nusxa oladi.

Zaxira qayerga boradi:
  - HP_BACKUP_CHAT .env da bo'lsa -> Telegram chatiga yuboriladi (masofaviy)
  - bo'lmasa -> faqat backups/ papkasida saqlanadi (7 kun)

Ishlatish:
    python3 backup_hp.py            # zaxira olish
    python3 backup_hp.py --test     # tekshirish, hech narsa yubormaydi
"""

import os
import sys
import glob
import json
import sqlite3
import logging
import urllib.request
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "hp.db")
OUT_DIR = os.path.join(BASE, "backups")
ENV_FILE = os.path.join(BASE, ".env")
KEEP_DAYS = 7

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


def make_backup():
    """Online Backup API orqali butun nusxa oladi."""
    if not os.path.exists(DB):
        logging.error("Baza topilmadi: %s", DB)
        return None

    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d")
    target = os.path.join(OUT_DIR, "hp-%s.db" % stamp)

    src = sqlite3.connect("file:%s?mode=ro" % DB, uri=True)
    try:
        dst = sqlite3.connect(target)
        try:
            src.backup(dst)          # = sqlite3 ".backup"
        finally:
            dst.close()
    finally:
        src.close()

    # Nusxa haqiqatan o'qilishini tekshiramiz - buzuq fayl yuborilmasin
    check = sqlite3.connect(target)
    try:
        state = check.execute("PRAGMA integrity_check").fetchone()[0]
        seasons = check.execute("SELECT COUNT(*) FROM seasons").fetchone()[0]
        points = check.execute("SELECT COUNT(*) FROM points").fetchone()[0]
    finally:
        check.close()

    if state != "ok":
        logging.error("Zaxira buzuq (integrity_check=%s), o'chirildi", state)
        os.remove(target)
        return None

    size = os.path.getsize(target)
    logging.info("Zaxira tayyor: %s (%d bayt, %d mavsum, %d ball yozuvi)",
                 target, size, seasons, points)
    return target


def send_to_telegram(path, token, chat_id):
    """Faylni Telegram chatiga yuboradi (multipart, kutubxonasiz)."""
    boundary = "----hpbackup%s" % datetime.now().strftime("%H%M%S%f")
    with open(path, "rb") as f:
        blob = f.read()

    parts = []
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"chat_id\"\r\n\r\n%s\r\n"
                  % (boundary, chat_id)).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"caption\"\r\n\r\n"
                  "Xogvarts kubogi zaxirasi — %s\r\n"
                  % (boundary, datetime.now().strftime("%Y-%m-%d %H:%M"))).encode())
    parts.append(("--%s\r\nContent-Disposition: form-data; name=\"document\"; "
                  "filename=\"%s\"\r\nContent-Type: application/octet-stream\r\n\r\n"
                  % (boundary, os.path.basename(path))).encode())
    parts.append(blob)
    parts.append(("\r\n--%s--\r\n" % boundary).encode())
    body = b"".join(parts)

    req = urllib.request.Request(
        "https://api.telegram.org/bot%s/sendDocument" % token,
        data=body,
        headers={"Content-Type": "multipart/form-data; boundary=%s" % boundary})
    with urllib.request.urlopen(req, timeout=120) as resp:
        answer = json.loads(resp.read().decode())
    if not answer.get("ok"):
        raise RuntimeError("Telegram rad etdi: %s" % answer)
    return True


def prune():
    files = sorted(glob.glob(os.path.join(OUT_DIR, "hp-*.db")))
    for old in files[:-KEEP_DAYS]:
        try:
            os.remove(old)
            logging.info("Eski zaxira o'chirildi: %s", os.path.basename(old))
        except OSError:
            pass


def main():
    test_only = "--test" in sys.argv

    path = make_backup()
    if not path:
        return 1

    env = read_env()
    token = env.get("BOT_TOKEN")
    chat = env.get("HP_BACKUP_CHAT")

    if test_only:
        logging.info("TEST rejimi — Telegramga yuborilmadi.")
    elif token and chat:
        try:
            send_to_telegram(path, token, chat)
            logging.info("Telegramga yuborildi (chat %s)", chat)
        except Exception as e:
            logging.error("Telegramga yuborishda xato: %s", e)
    else:
        logging.warning("HP_BACKUP_CHAT .env da yo'q — zaxira faqat shu "
                        "serverda saqlanmoqda. Disk nosoz bo'lsa yo'qoladi.")

    prune()
    return 0


if __name__ == "__main__":
    sys.exit(main())
