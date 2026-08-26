"""Xogvarts kubogi — savollarni bazaga yuklash skripti.

Ishlatish:
  python seed_questions.py          # bo'sh bazaga yuklaydi
  python seed_questions.py --force  # mavjud savollarni yangilaydi
"""

import os
import sys
import json
import sqlite3
import asyncio
import logging

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

import hpcup

async def main():
    force = "--force" in sys.argv
    questions_dir = os.path.join(os.path.dirname(__file__), "questions")
    if not os.path.isdir(questions_dir):
        logging.error("Savollar papkasi topilmadi: %s", questions_dir)
        return

    files = [
        "savollar-kino-1-4.json",
        "savollar-kino-5-8.json",
        "savollar-kunlik-1-30.json",
        "savollar-kunlik-31-60.json",
    ]

    total_loaded = 0
    first = True
    for fname in files:
        fpath = os.path.join(questions_dir, fname)
        if not os.path.exists(fpath):
            logging.warning("Fayl topilmadi: %s", fpath)
            continue

        with open(fpath, "r", encoding="utf-8") as f:
            items = json.load(f)

        replace = force and first
        added = await hpcup.load_questions(items, replace=replace)
        logging.info("Yuklandi: %s -> %d ta savol qo'shildi", fname, added)
        total_loaded += added
        first = False

    counts = await hpcup.counts()
    logging.info("Baza holati: %s", counts)
    logging.info("Jami qo'shildi: %d ta savol", total_loaded)

if __name__ == "__main__":
    asyncio.run(main())