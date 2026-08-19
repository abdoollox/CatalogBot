#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
1-qismni ko'rib, 2-qismga o'tmagan foydalanuvchilarga eslatma yuboradi.

Kimga yuborilmaydi:
  - kanalda bo'lmaganlar (jonli tekshiriladi)
  - botni bloklaganlar
  - avval shu xabarni olganlar (sent_hp2.json)

Ishlatish:
    python3 remind_hp2.py                 # faqat ro'yxatni ko'rsatadi, yubormaydi
    python3 remind_hp2.py --send --limit 50
    python3 remind_hp2.py --send          # qolganlarning hammasiga
"""

import json
import os
import re
import sys
import time
import urllib.request
import urllib.error
from datetime import datetime

BASE = "/root/CatalogBot"
USERS_FILE = os.path.join(BASE, "data", "users_db.json")
SENT_FILE = os.path.join(BASE, "data", "sent_hp2.json")
ENV_FILE = os.path.join(BASE, ".env")

WEBAPP_URL = "https://abdoollox.github.io/CatalogWebApp/"
TIME_FMT = "%Y-%m-%d %H:%M:%S"

# Xabarlar orasidagi tanaffus (soniya). 0.08 ≈ 12 xabar/sekund.
DELAY = 0.08

TEXT = (
    "🎬 <b>Sayohatingiz endigina boshlangan edi.</b>\n\n"
    "Siz <b>1-qismni</b> ko'rdingiz. "
    "<b>2-qism — «Maxfiy Hujra»</b> sizni kutmoqda.\n\n"
    "Kolleksiyada barcha 8 qism bor."
)
BUTTON = "🎬 Kolleksiyani ochish"

IN_CHANNEL = ("member", "administrator", "creator")
SYSTEM = ("start", "subscribed", "left", "blocked", "unblocked")


def load_env(path):
    env = {}
    if not os.path.exists(path):
        return env
    with open(path, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("#") and "=" in line:
                k, v = line.split("=", 1)
                env[k.strip()] = v.strip()
    return env


def api(token, method, params, retries=3):
    url = "https://api.telegram.org/bot%s/%s" % (token, method)
    data = json.dumps(params).encode("utf-8")
    for attempt in range(retries):
        try:
            req = urllib.request.Request(
                url, data=data, headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8"))
        except urllib.error.HTTPError as e:
            body = e.read().decode("utf-8", "ignore")
            try:
                parsed = json.loads(body)
            except ValueError:
                parsed = {"ok": False, "error_code": e.code}
            if e.code == 429:
                wait = parsed.get("parameters", {}).get("retry_after", 3)
                print("   ... Telegram sekinlashtirishni so'radi, %ds kutamiz" % wait)
                time.sleep(wait + 1)
                continue
            return parsed
        except Exception:
            time.sleep(1.5 * (attempt + 1))
    return {"ok": False, "error_code": 0}


def has_film(clicks, num):
    pat = re.compile(r"^hp%d(_|$)" % num)
    for k in clicks:
        if pat.match(k):
            return True
    return False


def last_seen(clicks):
    best = None
    for k, stamps in clicks.items():
        if k in SYSTEM:
            continue
        for s in stamps or []:
            try:
                t = datetime.strptime(s, TIME_FMT)
            except Exception:
                continue
            if best is None or t > best:
                best = t
    return best or datetime(2000, 1, 1)


def main():
    send = "--send" in sys.argv
    limit = None
    if "--limit" in sys.argv:
        try:
            limit = int(sys.argv[sys.argv.index("--limit") + 1])
        except Exception:
            print("--limit dan keyin son kerak")
            sys.exit(1)

    env = load_env(ENV_FILE)
    token = env.get("BOT_TOKEN")
    channel = env.get("CHANNEL_ID")
    if not token or not channel:
        print("XATO: .env da BOT_TOKEN yoki CHANNEL_ID yo'q")
        sys.exit(1)

    with open(USERS_FILE, encoding="utf-8") as f:
        db = json.load(f)
    print("Bazada: %d foydalanuvchi" % len(db))

    sent_before = {}
    if os.path.exists(SENT_FILE):
        try:
            with open(SENT_FILE, encoding="utf-8") as f:
                sent_before = json.load(f)
        except Exception:
            sent_before = {}
    if sent_before:
        print("Avval yuborilgan: %d" % len(sent_before))

    # 1-bosqich: hp1 bor, hp2 yo'q
    pool = []
    for uid, info in db.items():
        clicks = (info or {}).get("clicks", {}) or {}
        if not has_film(clicks, 1):
            continue
        if has_film(clicks, 2):
            continue
        if "blocked" in clicks:
            continue
        if uid in sent_before:
            continue
        pool.append((uid, info.get("nickname", ""), last_seen(clicks)))

    pool.sort(key=lambda x: x[2], reverse=True)
    print("1-qismda to'xtaganlar (bloklamagan, yangi): %d" % len(pool))

    if limit:
        pool = pool[:limit]
        print("Cheklov: %d kishi" % len(pool))

    # 2-bosqich: kanal a'zoligi
    print("\nKanal a'zoligi tekshirilmoqda...")
    targets = []
    for uid, nick, seen in pool:
        r = api(token, "getChatMember", {"chat_id": channel, "user_id": int(uid)})
        if r.get("ok") and r["result"].get("status") in IN_CHANNEL:
            targets.append((uid, nick, seen))
        time.sleep(0.05)
    print("Kanalda: %d / %d" % (len(targets), len(pool)))

    if not targets:
        print("\nYuboriladigan odam yo'q.")
        return

    print("\n=== YUBORILADI: %d kishi ===" % len(targets))
    for uid, nick, seen in targets[:10]:
        print("   %-12s %-22s oxirgi: %s" % (uid, nick[:22], seen.date()))
    if len(targets) > 10:
        print("   ... va yana %d" % (len(targets) - 10))

    if not send:
        print("\n[SINOV REJIMI] Hech narsa yuborilmadi.")
        print("Yuborish uchun: python3 remind_hp2.py --send --limit 50")
        return

    kb = {"inline_keyboard": [[{"text": BUTTON, "web_app": {"url": WEBAPP_URL}}]]}

    ok = failed = blocked = 0
    print("\nYuborilmoqda...")
    for i, (uid, nick, seen) in enumerate(targets, 1):
        r = api(token, "sendMessage", {
            "chat_id": int(uid),
            "text": TEXT,
            "parse_mode": "HTML",
            "reply_markup": kb,
        })
        if r.get("ok"):
            ok += 1
            sent_before[uid] = datetime.now().strftime(TIME_FMT)
        else:
            code = r.get("error_code")
            desc = (r.get("description") or "").lower()
            if code == 403 or "blocked" in desc or "deactivated" in desc:
                blocked += 1
                sent_before[uid] = "blocked"
            else:
                failed += 1
                print("   xato %s: %s" % (uid, r.get("description")))
        if i % 25 == 0:
            print("   ... %d / %d" % (i, len(targets)))
        time.sleep(DELAY)

    with open(SENT_FILE, "w", encoding="utf-8") as f:
        json.dump(sent_before, f, ensure_ascii=False, indent=1)

    print("\n=== NATIJA ===")
    print("  yuborildi: %d" % ok)
    print("  bloklagan: %d" % blocked)
    print("  xato:      %d" % failed)
    print("\nRo'yxat saqlandi: %s" % SENT_FILE)


if __name__ == "__main__":
    main()
