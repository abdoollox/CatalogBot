"""Xogvarts kubogi — bot va API qatlami.

hpcup.py baza bilan ishlaydi, bu modul esa foydalanuvchi bilan:
imtihon savollari, kunlik savol, reyting, mavsum yopilishi.

main.py dan faqat `register(dp, bot, app, cfg)` chaqiriladi.
"""

import os
import json
import asyncio
import logging
from datetime import datetime, timedelta

from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest

import hpcup

# main.py tomonidan to'ldiriladi
_cfg = {
    "users_file": "/app/users_db.json",
    "channel_id": None,
    "verify_init_data": None,
    "cors": None,
}

HOUSE_NAME = {
    "gryffindor": "Grifindor",
    "slytherin": "Sliterin",
    "ravenclaw": "Reyvenklo",
    "hufflepuff": "Xaffelpaff",
}

BADGE_NAME = {
    "all_films": "Sakkiz qism",
    "flawless_exam": "Benuqson imtihon",
    "perfect_week": "Mukammal hafta",
    "streak_7": "Yetti kun ketma-ket",
}

LETTERS = ["A", "B", "C", "D"]

# Mavsum yopilishini e'lon qilish. HP_ANNOUNCE=0 bo'lsa kanalga yozilmaydi.
ANNOUNCE = os.getenv("HP_ANNOUNCE", "1") != "0"


# ---------------------------------------------------------- fakultet

# users_db.json katta (yarim megabayt). Har ball berishda qayta o'qimaslik
# uchun fayl o'zgarganini mtime bo'yicha kuzatamiz.
_house_cache = {"mtime": None, "map": {}}


def _read_houses():
    path = _cfg["users_file"]
    try:
        mtime = os.path.getmtime(path)
    except OSError:
        return {}

    if _house_cache["mtime"] == mtime:
        return _house_cache["map"]

    try:
        with open(path, "r", encoding="utf-8") as f:
            db = json.load(f)
    except (OSError, ValueError):
        return _house_cache["map"]

    out = {}
    for uid, rec in db.items():
        latest_time, latest_house = None, None
        for key, stamps in (rec.get("clicks") or {}).items():
            if not key.startswith("house_") or not stamps:
                continue
            name = key[len("house_"):]
            when = max(stamps)
            # Bir necha marta saralanganlar bor - eng oxirgisi olinadi.
            if latest_time is None or when > latest_time:
                latest_time, latest_house = when, name
        if latest_house:
            out[str(uid)] = latest_house

    _house_cache["mtime"] = mtime
    _house_cache["map"] = out
    return out


async def user_house(user_id):
    """Foydalanuvchining hozirgi fakulteti yoki None.

    Alohida jadval yaratilmaydi — fakultet allaqachon users_db.json ichida
    `house_<nom>` hodisasi sifatida saqlanadi (spetsifikatsiya 0.2).
    """
    houses = await asyncio.to_thread(_read_houses)
    return houses.get(str(user_id))


# ---------------------------------------------------------- ball berish

async def award_film_open(user, film_part):
    """Kino ochilgani uchun ball. Mavsumda har qism uchun bir marta."""
    house = await user_house(user.id)
    if not house:
        return False
    season = await hpcup.current_season()
    return await hpcup.award(user.id, house, "film_open",
                             str(film_part), hpcup.PTS_FILM_OPEN)


# ---------------------------------------------------------- savol chizish

def _question_kb(prefix, q):
    kb = []
    for i, opt in enumerate(q["options"][:4]):
        kb.append([InlineKeyboardButton(
            text="%s) %s" % (LETTERS[i], opt),
            callback_data="%s:%d:%d" % (prefix, q["id"], i))])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _question_text(q, header):
    return "%s\n\n<b>%s</b>" % (header, q["body"])


# ---------------------------------------------------------- kino imtihoni

async def offer_quiz(bot, user, film_part):
    """Kino yuborilgandan keyin imtihon taklifi.

    Majburiy emas — foydalanuvchi o'zi bosadi (kutilmagan push xabar
    yubormaslik qoidasi).
    """
    house = await user_house(user.id)
    if not house:
        return

    season = await hpcup.current_season()
    qs = await hpcup.film_questions(user.id, season["id"], film_part)
    if not qs:
        return                      # savollar yuklanmagan yoki tugagan

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="Imtihonni boshlash (%d ta savol)" % len(qs),
        callback_data="hpq:go:%d" % film_part)]])
    try:
        await bot.send_message(
            user.id,
            "🎓 <b>%s uchun imtihon</b>\n\n"
            "Har bir to'g'ri javob — %d ball, fakultetingiz hisobiga.\n"
            "Bir savolga bir marta javob beriladi." % (
                "%d-qism" % film_part, hpcup.PTS_FILM_QUIZ),
            parse_mode="HTML", reply_markup=kb)
    except Exception as e:
        logging.error("Imtihon taklifida xato: %s", e)


async def _send_next_film_question(bot, user_id, film_part, message=None):
    season = await hpcup.current_season()
    qs = await hpcup.film_questions(user_id, season["id"], film_part)

    if not qs:
        total = await hpcup.user_stats(user_id, season["id"])
        text = ("✅ <b>Imtihon tugadi.</b>\n\n"
                "Mavsumdagi ballingiz: <b>%d</b>" % total["points"])
        if message:
            try:
                await message.edit_text(text, parse_mode="HTML")
                return
            except TelegramBadRequest:
                pass
        await bot.send_message(user_id, text, parse_mode="HTML")
        return

    q = qs[0]
    header = "%d-qism · %d ta savol qoldi" % (film_part, len(qs))
    text = _question_text(q, header)
    kb = _question_kb("hpa:%d" % film_part, q)

    if message:
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            return
        except TelegramBadRequest:
            pass
    await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=kb)


# ---------------------------------------------------------- kunlik savol

async def send_daily(bot, user_id, message=None):
    house = await user_house(user_id)
    if not house:
        text = ("Kunlik savolda qatnashish uchun avval fakultetingizni "
                "aniqlang — kolleksiyadagi «Saralanish» kartasi orqali.")
        await bot.send_message(user_id, text)
        return

    q = await hpcup.daily_question()
    if not q:
        await bot.send_message(user_id, "Bugunga savol tayyorlanmagan.")
        return

    season = await hpcup.current_season()
    if await hpcup.already_answered(user_id, season["id"], q["id"]):
        stats = await hpcup.user_stats(user_id, season["id"])
        await bot.send_message(
            user_id,
            "Bugungi savolga javob bergansiz.\n"
            "Mavsumdagi ballingiz: <b>%d</b>\n\n"
            "Ertaga yangi savol bo'ladi." % stats["points"],
            parse_mode="HTML")
        return

    text = _question_text(q, "📅 <b>Bugungi savol</b> — %d ball" % hpcup.PTS_DAILY)
    kb = _question_kb("hpd", q)
    if message:
        try:
            await message.edit_text(text, parse_mode="HTML", reply_markup=kb)
            return
        except TelegramBadRequest:
            pass
    await bot.send_message(user_id, text, parse_mode="HTML", reply_markup=kb)


# ---------------------------------------------------------- reyting matni

def format_table(season, table):
    lines = ["🏆 <b>Xogvarts kubogi</b>\n"]
    if not table:
        lines.append("Bu haftada hali hech kim ball to'plamagan.")
        return "\n".join(lines)

    place = 0
    for row in table:
        name = HOUSE_NAME.get(row["house"], row["house"])
        if row["qualified"]:
            place += 1
            lines.append("<b>%d. %s</b> — %.1f o'rtacha ball (%d a'zo)" % (
                place, name, row["avg_points"], row["active_members"]))
        else:
            lines.append("· %s — musobaqaga qo'shilish uchun yana <b>%d</b> a'zo kerak"
                         % (name, row["needed"]))
    lines.append("\n<i>Reyting o'rtacha ball bo'yicha — katta fakultet "
                 "avtomatik yutmasligi uchun.</i>")
    return "\n".join(lines)


# ---------------------------------------------------------- mavsum yopuvchi

async def _announce(bot, result):
    if not ANNOUNCE or not _cfg["channel_id"]:
        return
    winner = result["winner_house"]
    if winner:
        head = "🏆 <b>Hafta g'olibi — %s!</b>\n" % HOUSE_NAME.get(winner, winner)
    else:
        head = ("🏆 <b>Hafta yakunlandi</b>\n\nBu hafta g'olib aniqlanmadi — "
                "hech bir fakultet 5 faol a'zo chegarasidan o'tmadi.\n")
    text = head + "\n" + format_table(None, result["table"])
    try:
        await bot.send_message(_cfg["channel_id"], text, parse_mode="HTML")
    except Exception as e:
        logging.error("Mavsum e'lonida xato: %s", e)


async def season_watcher(bot, interval=300):
    """Mavsum tugaganini kuzatadi va yopadi.

    Alohida cron kerak emas — bot allaqachon doim ishlab turadi.
    Har 5 daqiqada tekshiradi, ya'ni yopilish yakshanba 23:59 dan keyin
    eng kechi 5 daqiqa ichida bo'ladi.
    """
    await asyncio.sleep(10)
    while True:
        try:
            season = await hpcup.current_season()
            ends = datetime.strptime(season["ends_at"], "%Y-%m-%dT%H:%M:%SZ")
            now_utc = hpcup.now_tk().astimezone(hpcup.timezone.utc).replace(tzinfo=None)
            if now_utc >= ends:
                logging.info("Mavsum %s yopilmoqda", season["id"])
                result = await hpcup.close_season(season["id"])
                if result:
                    logging.info("G'olib: %s, nishonlar: %d",
                                 result["winner_house"], len(result["badges"]))
                    await _announce(bot, result)
        except Exception as e:
            logging.error("Mavsum kuzatuvchisida xato: %s", e)
        await asyncio.sleep(interval)


# ---------------------------------------------------------- API

async def api_leaderboard(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(_web().Response(status=204))

    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data and request.method == "POST":
        try:
            body = await request.json()
            init_data = str(body.get("initData", ""))
        except Exception:
            init_data = ""

    user = _cfg["verify_init_data"](init_data)
    if not user:
        return cors(_web().json_response({"ok": False, "error": "bad_auth"}, status=403))

    season = await hpcup.current_season()
    table = await hpcup.leaderboard(season["id"])
    stats = await hpcup.user_stats(user["id"], season["id"])
    if not stats["house"]:
        stats["house"] = await user_house(user["id"])

    return cors(_web().json_response({
        "season": {"id": season["id"], "ends_at": season["ends_at"]},
        "houses": table,
        "me": {"house": stats["house"], "points": stats["points"],
               "house_rank": stats["house_rank"], "badges": stats["badges"]},
    }))


async def profile_extra(user_id):
    """/api/profile javobiga qo'shiladigan kubok ma'lumotlari."""
    season = await hpcup.current_season()
    stats = await hpcup.user_stats(user_id, season["id"])
    return {
        "season": {"id": season["id"], "ends_at": season["ends_at"]},
        "points": stats["points"],
        "house_rank": stats["house_rank"],
        "badges": stats["badges"],
    }


def _web():
    from aiohttp import web
    return web


# ---------------------------------------------------------- ro'yxatdan o'tkazish

def register(dp, bot, app, cfg):
    """main.py shu funksiyani chaqiradi."""
    _cfg.update(cfg)

    @dp.callback_query(F.data.startswith("hpq:go:"))
    async def _quiz_start(callback: types.CallbackQuery):
        try:
            part = int(callback.data.split(":")[2])
        except (IndexError, ValueError):
            await callback.answer()
            return
        await _send_next_film_question(bot, callback.from_user.id, part,
                                       callback.message)
        await callback.answer()

    @dp.callback_query(F.data.startswith("hpa:"))
    async def _quiz_answer(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        try:
            film_part, qid, choice = int(parts[1]), int(parts[2]), int(parts[3])
        except (IndexError, ValueError):
            await callback.answer()
            return

        uid = callback.from_user.id
        season = await hpcup.current_season()

        # To'g'ri javobni bilish uchun savolni topamiz
        qs = await hpcup.film_questions(uid, season["id"], film_part)
        target = next((q for q in qs if q["id"] == qid), None)
        if target is None:
            await callback.answer("Bu savolga javob berilgan.", show_alert=True)
            await _send_next_film_question(bot, uid, film_part, callback.message)
            return

        correct = (choice == target["correct_index"])
        fresh = await hpcup.record_answer(uid, season["id"], qid, correct)

        if correct and fresh:
            house = await user_house(uid)
            await hpcup.award(uid, house, "film_quiz", str(qid), hpcup.PTS_FILM_QUIZ)
            await callback.answer("To'g'ri! +%d ball" % hpcup.PTS_FILM_QUIZ)
        else:
            right = target["options"][target["correct_index"]]
            await callback.answer("Noto'g'ri. To'g'ri javob: %s" % right,
                                  show_alert=True)

        await _send_next_film_question(bot, uid, film_part, callback.message)

    @dp.callback_query(F.data.startswith("hpd:"))
    async def _daily_answer(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        try:
            qid, choice = int(parts[1]), int(parts[2])
        except (IndexError, ValueError):
            await callback.answer()
            return

        uid = callback.from_user.id
        season = await hpcup.current_season()
        q = await hpcup.daily_question()
        if not q or q["id"] != qid:
            await callback.answer("Bu savol eskirgan.", show_alert=True)
            return

        correct = (choice == q["correct_index"])
        fresh = await hpcup.record_answer(uid, season["id"], qid, correct)
        if not fresh:
            await callback.answer("Javob bergansiz.", show_alert=True)
            return

        if correct:
            house = await user_house(uid)
            await hpcup.award(uid, house, "daily", hpcup.today_tk(), hpcup.PTS_DAILY)
            tail = "✅ <b>To'g'ri!</b> +%d ball" % hpcup.PTS_DAILY
        else:
            tail = "❌ <b>Noto'g'ri.</b> To'g'ri javob: %s" % q["options"][q["correct_index"]]

        stats = await hpcup.user_stats(uid, season["id"])
        try:
            await callback.message.edit_text(
                "%s\n\nMavsumdagi ballingiz: <b>%d</b>\n\nErtaga yangi savol bo'ladi."
                % (tail, stats["points"]), parse_mode="HTML")
        except TelegramBadRequest:
            pass
        await callback.answer()

    @dp.message(F.text == "/kunlik")
    async def _daily_cmd(message: types.Message):
        await send_daily(bot, message.from_user.id)

    @dp.message(F.text == "/reyting")
    async def _table_cmd(message: types.Message):
        season = await hpcup.current_season()
        table = await hpcup.leaderboard(season["id"])
        await message.answer(format_table(season, table), parse_mode="HTML")

    app.router.add_route("*", "/api/leaderboard", api_leaderboard)
    logging.info("Xogvarts kubogi ulandi (e'lon: %s)", "yoqilgan" if ANNOUNCE else "o'chirilgan")
