"""Xogvarts kubogi — bot va API qatlami (spetsifikatsiya 2.0).

hpcup.py baza bilan ishlaydi, bu modul esa foydalanuvchi bilan:
imtihon savollari, kunlik savol, reyting, mavsum yopilishi.

main.py dan faqat `register(dp, bot, app, cfg)` chaqiriladi.
"""

import os
import random
import asyncio
import logging
from datetime import datetime, timezone

from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

import hpcup

# main.py tomonidan to'ldiriladi
_cfg = {
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

async def user_house(user_id):
    """Foydalanuvchining fakulteti yoki None.

    2.0 da fakultet `users` jadvalida va UMRBOD. 1.0 da u users_db.json
    ichidagi hodisalardan hisoblanardi — migratsiya paytida ko'chirilgan.
    """
    return await hpcup.get_house(user_id)


# ---------------------------------------------------------- ball berish

async def award_film_open(user, film_part):
    """Kino ochilgani uchun ball. Mavsumda har qism uchun bir marta.

    Fakultet talab qilinmaydi: reyting `users` bilan JOIN orqali hisoblanadi,
    ya'ni keyinroq saralangan odamning oldingi ballari ham hisobga o'tadi.
    """
    return await hpcup.award(user.id, "film_open", str(film_part),
                             hpcup.PTS_FILM_OPEN)


# ---------------------------------------------------------- savol chizish

def _question_kb(prefix, q):
    opts = q["options"][:4]
    order = list(range(len(opts)))
    random.shuffle(order)
    kb = []
    for i, orig_idx in enumerate(order):
        opt = opts[orig_idx]
        kb.append([InlineKeyboardButton(
            text="%s) %s" % (LETTERS[i], opt),
            callback_data="%s:%d:%d" % (prefix, q["id"], orig_idx))])
    return InlineKeyboardMarkup(inline_keyboard=kb)


def _question_text(q, header):
    return "%s\n\n<b>%s</b>" % (header, q["body"])


# ---------------------------------------------------------- kino imtihoni (o'chirilgan - bot oddiy foydalanuvchilar uchun)

async def offer_quiz(bot, user, film_part):
    """Kino yuborilgandan keyin imtihon taklifi o'chirilgan."""
    return


async def _send_next_film_question(bot, user_id, film_part, message=None):
    season = await hpcup.current_season()
    qs = await hpcup.film_questions(user_id, season["id"], film_part)

    if not qs:
        stats = await hpcup.user_stats(user_id, season["id"])
        text = ("✅ <b>Imtihon tugadi.</b>\n\n"
                "Mavsumdagi ballingiz: <b>%d / %d</b>" % (
                    stats["points"], stats["max_points"]))
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
            "Mavsumdagi ballingiz: <b>%d / %d</b>\n\nErtaga yangi savol bo'ladi."
            % (stats["points"], stats["max_points"]), parse_mode="HTML")
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

def format_table(table):
    lines = ["📊 <b>Reyting</b>\n"]
    place = 0
    for row in table:
        name = HOUSE_NAME.get(row["house"], row["house"])
        place += 1
        lines.append("<b>%d. %s</b> — %d ball (%d a'zo)" % (
            place, name, row["total_points"], row["active_members"]))
    lines.append("\n<i>Faol a'zo — mavsumda kamida %d ball to'plagan foydalanuvchi.</i>"
                 % hpcup.ACTIVE_MIN_POINTS)
    return "\n".join(lines)


# ---------------------------------------------------------- mavsum yopuvchi

async def _announce(bot, result):
    if not ANNOUNCE or not _cfg["channel_id"]:
        return
    winner = result["winner_house"]
    if winner:
        head = "🏆 <b>Hafta g'olibi — %s!</b>\n" % HOUSE_NAME.get(winner, winner)
    else:
        head = "🏆 <b>Hafta yakunlandi</b>\n\nBu hafta g'olib aniqlanmadi.\n"
    try:
        await bot.send_message(_cfg["channel_id"], head + "\n" +
                               format_table(result["table"]), parse_mode="HTML")
    except Exception as e:
        logging.error("Mavsum e'lonida xato: %s", e)


async def season_watcher(bot, interval=300):
    """Mavsum tugaganini kuzatadi va yopadi.

    Eslatma: hpcup._ensure_season ham eskirgan mavsumni to'liq yopadi
    (g'olib + nishonlar), shuning uchun bu yerda faqat e'lon qoladi.
    """
    await asyncio.sleep(10)
    last_seen = None
    while True:
        try:
            season = await hpcup.current_season()
            ends = datetime.strptime(season["ends_at"], "%Y-%m-%dT%H:%M:%SZ")
            now_utc = datetime.now(timezone.utc).replace(tzinfo=None)

            if now_utc >= ends:
                logging.info("Mavsum %s yopilmoqda", season["id"])
                result = await hpcup.close_season(season["id"])
                if result:
                    logging.info("G'olib: %s, nishonlar: %d",
                                 result["winner_house"], len(result["badges"]))
                    await _announce(bot, result)
            elif last_seen is not None and season["id"] != last_seen:
                # Mavsum boshqa yo'l bilan almashgan (ball berish paytida).
                # E'lon yuborilmagan bo'lsa - shu yerda yuboriladi.
                closed = await hpcup.recount_season(last_seen)
                if closed:
                    logging.info("Mavsum %s almashgani aniqlandi, g'olib: %s",
                                 last_seen, closed["winner_house"])
                    await _announce(bot, closed)
            last_seen = season["id"]
        except Exception as e:
            logging.error("Mavsum kuzatuvchisida xato: %s", e)
        await asyncio.sleep(interval)


# ---------------------------------------------------------- muhlat xabari

GRACE_TEXT = (
    "Xogvarts kubogi ishga tushmoqda. Musobaqa adolatli bo'lishi uchun "
    "fakultet endi o'zgartirilmaydi — asardagi kabi, saralash bir marta "
    "bo'ladi.\n\n"
    "Agar fakultetingizni o'zgartirmoqchi bo'lsangiz, <b>%s</b> gacha "
    "ulguring. Undan keyin qayta saralanish yopiladi."
)


async def send_grace_notice(bot, webapp_url, days=7, dry_run=True):
    """Fakulteti bor foydalanuvchilarga muhlat haqida xabar.

    Umumiy tarqatma EMAS — faqat `users.house IS NOT NULL` bo'lganlarga.
    dry_run=True bo'lsa hech kimga yuborilmaydi, faqat ro'yxat qaytariladi.
    """
    people = await hpcup.sorted_users()
    if dry_run:
        return {"total": len(people), "sent": 0, "blocked": 0, "failed": 0,
                "until": None, "dry_run": True}

    until = await hpcup.open_resort_window(days)
    human = hpcup._parse_iso(until).astimezone(hpcup.TASHKENT).strftime("%d.%m.%Y")
    text = GRACE_TEXT % human

    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text="Fakultetni ko'rish", web_app=types.WebAppInfo(url=webapp_url))]])

    sent = blocked = failed = 0
    for uid, _house in people:
        try:
            await bot.send_message(uid, text, parse_mode="HTML", reply_markup=kb)
            sent += 1
        except TelegramForbiddenError:
            blocked += 1        # botni bloklagan yoki chatni o'chirgan
        except Exception as e:
            failed += 1
            logging.error("Muhlat xabari %s ga yetmadi: %s", uid, e)
        await asyncio.sleep(0.15)   # Telegram cheklovidan o'tmaslik uchun

    logging.info("Muhlat xabari: %d yuborildi, %d bloklagan, %d xato",
                 sent, blocked, failed)
    return {"total": len(people), "sent": sent, "blocked": blocked,
            "failed": failed, "until": until, "dry_run": False}


# ---------------------------------------------------------- API

def _web():
    from aiohttp import web
    return web


def _init_data_from(request, body=None):
    head = request.headers.get("X-Telegram-Init-Data", "")
    if head:
        return head
    if body:
        return str(body.get("initData", ""))
    return ""


async def api_leaderboard(request):
    web = _web()
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))

    body = None
    if request.method == "POST":
        try:
            body = await request.json()
        except Exception:
            body = None

    user = _cfg["verify_init_data"](_init_data_from(request, body))
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))

    first_name = user.get("first_name")
    if first_name:
        try:
            await hpcup.touch_user(user["id"], first_name)
        except Exception:
            pass

    season = await hpcup.current_season()
    table = await hpcup.leaderboard(season["id"])
    stats = await hpcup.user_stats(user["id"], season["id"])
    gap = hpcup.compute_gap(table, stats)
    allowed, until = await hpcup.can_resort(user["id"])
    exam_pending = await hpcup.exam_pending(user["id"], season["id"])
    hall = await hpcup.hall(stats.get("house"), user["id"], season["id"])
    feed = await hpcup.feed(limit=50)

    me = {
        "house": stats["house"],
        "points": stats["points"],
        "max_points": stats["max_points"],
        "is_active": stats["is_active"],
        "to_active": stats["to_active"],
        "house_rank": stats["house_rank"],
        "badges": stats["badges"],
        # Spetsifikatsiyada bu ikkisi /api/profile da, lekin shu yerga ham
        # qo'shildi: WebApp qayta saralanish tugmasini ko'rsatish uchun
        # ikkinchi so'rov yubormasin.
        "can_resort": allowed,
        "resort_until": until,
        "exam_pending": exam_pending,
    }
    if gap:
        me["gap"] = gap

    resp = {
        "season": {"id": season["id"], "ends_at": season["ends_at"]},
        "houses": table,
        "me": me,
    }
    if hall:
        resp["hall"] = hall
    if feed:
        resp["feed"] = feed

    return cors(web.json_response(resp))


async def profile_extra(user_id):
    """/api/profile javobiga qo'shiladigan kubok ma'lumotlari."""
    season = await hpcup.current_season()
    stats = await hpcup.user_stats(user_id, season["id"])
    allowed, until = await hpcup.can_resort(user_id)
    exam_pending = await hpcup.exam_pending(user_id, season["id"])
    return {
        "season": {"id": season["id"], "ends_at": season["ends_at"]},
        "house": stats["house"],
        "points": stats["points"],
        "max_points": stats["max_points"],
        "is_active": stats["is_active"],
        "to_active": stats["to_active"],
        "house_rank": stats["house_rank"],
        "badges": stats["badges"],
        "can_resort": allowed,
        "resort_until": until,
        "exam_pending": exam_pending,
    }


# ---------------------------------------------------------- ro'yxatdan o'tkazish

def register(dp, bot, app, cfg):
    """main.py shu funksiyani chaqiradi."""
    _cfg.update(cfg)

    @dp.callback_query(F.data.startswith("hpq:go:"))
    async def _quiz_start(callback: types.CallbackQuery):
        if callback.from_user and callback.from_user.first_name:
            await hpcup.touch_user(callback.from_user.id, callback.from_user.first_name)
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
        if callback.from_user and callback.from_user.first_name:
            await hpcup.touch_user(callback.from_user.id, callback.from_user.first_name)
        parts = callback.data.split(":")
        try:
            film_part, qid, choice = int(parts[1]), int(parts[2]), int(parts[3])
        except (IndexError, ValueError):
            await callback.answer()
            return

        uid = callback.from_user.id
        season = await hpcup.current_season()

        qs = await hpcup.film_questions(uid, season["id"], film_part)
        target = next((q for q in qs if q["id"] == qid), None)
        if target is None:
            await callback.answer("Bu savolga javob berilgan.", show_alert=True)
            await _send_next_film_question(bot, uid, film_part, callback.message)
            return

        correct = (choice == target["correct_index"])
        fresh = await hpcup.record_answer(uid, season["id"], qid, correct)

        if correct and fresh:
            await hpcup.award(uid, "film_quiz", str(qid), hpcup.PTS_FILM_QUIZ)
            await callback.answer("To'g'ri! +%d ball" % hpcup.PTS_FILM_QUIZ)
        else:
            right = target["options"][target["correct_index"]]
            await callback.answer("Noto'g'ri. To'g'ri javob: %s" % right,
                                  show_alert=True)

        await _send_next_film_question(bot, uid, film_part, callback.message)

    @dp.callback_query(F.data.startswith("hpd:"))
    async def _daily_answer(callback: types.CallbackQuery):
        if callback.from_user and callback.from_user.first_name:
            await hpcup.touch_user(callback.from_user.id, callback.from_user.first_name)
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
            await hpcup.award(uid, "daily", hpcup.today_tk(), hpcup.PTS_DAILY)
            tail = "✅ <b>To'g'ri!</b> +%d ball" % hpcup.PTS_DAILY
        else:
            tail = ("❌ <b>Noto'g'ri.</b> To'g'ri javob: %s"
                    % q["options"][q["correct_index"]])

        stats = await hpcup.user_stats(uid, season["id"])
        try:
            await callback.message.edit_text(
                "%s\n\nMavsumdagi ballingiz: <b>%d / %d</b>\n\nErtaga yangi savol bo'ladi."
                % (tail, stats["points"], stats["max_points"]), parse_mode="HTML")
        except TelegramBadRequest:
            pass
        await callback.answer()

    @dp.message(F.text == "/kunlik")
    async def _daily_cmd(message: types.Message):
        if message.from_user and message.from_user.first_name:
            await hpcup.touch_user(message.from_user.id, message.from_user.first_name)
        await send_daily(bot, message.from_user.id)

    @dp.message(F.text == "/reyting")
    async def _table_cmd(message: types.Message):
        if message.from_user and message.from_user.first_name:
            await hpcup.touch_user(message.from_user.id, message.from_user.first_name)
        season = await hpcup.current_season()
        table = await hpcup.leaderboard(season["id"])
        await message.answer(format_table(table), parse_mode="HTML")

    async def api_tasks(request):
        web = _web()
        cors = _cfg["cors"]
        if request.method == "OPTIONS":
            return cors(web.Response(status=204))

        try:
            body = await request.json() if request.method == "POST" else None
        except Exception:
            body = None

        user = _cfg["verify_init_data"](_init_data_from(request, body))
        if not user:
            return cors(web.json_response({"error": "unauthorized"}, status=403))
        uid = user["id"]

        tasks_data = await hpcup.get_user_tasks(uid)
        return cors(web.json_response(tasks_data))

    async def api_submit_task(request):
        web = _web()
        cors = _cfg["cors"]
        if request.method == "OPTIONS":
            return cors(web.Response(status=204))
            
        try:
            body = await request.json()
        except Exception:
            return cors(web.json_response({"error": "invalid json"}, status=400))
            
        user = _cfg["verify_init_data"](_init_data_from(request, body))
        if not user:
            return cors(web.json_response({"error": "unauthorized"}, status=403))
        uid = user["id"]
            
        task_type = body.get("task_type")
        question_id = body.get("question_id")
        selected_index = body.get("selected_index")
        
        if not all([task_type, str(question_id).isdigit(), str(selected_index).isdigit()]):
            return cors(web.json_response({"error": "invalid parameters"}, status=400))
            
        res = await hpcup.submit_task_answer(uid, task_type, question_id, selected_index)
        return cors(web.json_response(res))

    app.router.add_route("*", "/api/tasks", api_tasks)
    app.router.add_route("*", "/api/tasks/submit", api_submit_task)
    app.router.add_route("*", "/api/leaderboard", api_leaderboard)
    logging.info("Xogvarts kubogi 3.0 ulandi (e'lon: %s)",
                 "yoqilgan" if ANNOUNCE else "o'chirilgan")
