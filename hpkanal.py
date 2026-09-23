"""Kanal obunachilari soni — NAZORAT uchun.

Panel kanaldagi odamlarni LOGLARDAN hisoblaydi (boshlang'ich son + qo'shilgan
- chiqqan). Bu modul esa Telegramning o'zidan haqiqiy sonni olib, har kuni
bazaga yozib boradi. Ikkalasi teng chiqsa - loglar to'g'ri tushyapti; farq
paydo bo'lsa, qaysi kundan boshlangani ko'rinadi. Telegram soni panelga
ko'chirilmaydi, faqat yonma-yon ko'rsatiladi.

Kun yozuvi soatda bir yangilanadi, shuning uchun kun tugaganda unda o'sha
kunning oxirgi soni qoladi (Toshkent vaqti bilan).
"""
import time
import asyncio
import logging

import hpcup

_kesh = {"son": None, "vaqt": 0.0}


def _ulan():
    conn = hpcup._connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS kanal_soni ("
        " sana TEXT PRIMARY KEY,"       # Toshkent kuni, YYYY-MM-DD
        " son INTEGER NOT NULL,"
        " vaqt TEXT NOT NULL)")         # oxirgi o'lchov, UTC ISO
    return conn


def _yoz(son):
    t = hpcup.now_tk()
    conn = _ulan()
    try:
        conn.execute(
            "INSERT INTO kanal_soni (sana, son, vaqt) VALUES (?,?,?) "
            "ON CONFLICT(sana) DO UPDATE SET son=excluded.son, vaqt=excluded.vaqt",
            (t.strftime("%Y-%m-%d"), int(son), hpcup._utc_iso(t)))
        conn.commit()
    finally:
        conn.close()


def tarix(kun=400):
    """Kunlik suratlar, eskisidan yangisiga: [{sana, son, vaqt}]."""
    conn = _ulan()
    try:
        rows = conn.execute("SELECT sana, son, vaqt FROM kanal_soni "
                            "ORDER BY sana DESC LIMIT ?", (int(kun),)).fetchall()
        return [dict(r) for r in reversed(rows)]
    finally:
        conn.close()


async def hozir(bot, channel_id, eskirish=300):
    """Telegramdagi hozirgi son. Panel tez-tez so'rasa ham Telegramga
    besh daqiqada bir marta murojaat qilinadi."""
    if _kesh["son"] is not None and time.time() - _kesh["vaqt"] < eskirish:
        return _kesh["son"]
    son = await bot.get_chat_member_count(chat_id=channel_id)
    _kesh.update(son=son, vaqt=time.time())
    try:
        await asyncio.to_thread(_yoz, son)
    except Exception as e:
        logging.error("Kanal sonini bazaga yozishda xato: %s", e)
    return son


async def kuzatuvchi(bot, channel_id, interval=3600):
    """Har soatda sonni yangilab, kun yozuviga qo'yadi."""
    while True:
        try:
            await hozir(bot, channel_id, eskirish=0)
        except Exception as e:
            logging.error("Kanal sonini olishda xato: %s", e)
        await asyncio.sleep(interval)
