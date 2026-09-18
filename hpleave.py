# -*- coding: utf-8 -*-
"""Kanalni tark etganlardan sababini so'rash.

Odam kanaldan chiqqanda unga shaxsiy chatda bitta xabar boradi: "nima
sabab bo'ldi?" va oltita tugma. Tugmani bosgach — sababga MOS javob va
"Kanalga qaytish" tugmasi. Uchta sababda qo'shimcha matn ham so'raladi.

Nega Telegram'ning haqiqiy so'rovnomasi (sendPoll) emas:
  * shaxsiy chatda ovoz bergan odam darrov "1 ovoz — 100%" natijasini
    ko'radi, bu g'alati ko'rinadi;
  * poll javobiga ALOHIDA javob qaytarib bo'lmaydi — ushlab qolish esa
    aynan o'sha javobda tug'iladi ("xabar ko'p edi" -> "ovozsiz qiling");
  * pollda kim ovoz berganini bilish uchun poll_id ni alohida bog'lash
    kerak, tugmada esa callback o'zi user_id ni olib keladi.

Ohang haqida: birinchi gap AYBLOV bo'lmasligi kerak. "Endi botdan
foydalana olmaysiz" deb boshlansa, xafa bo'lgan odam javob bermaydi —
botni bloklaydi. Bloklangan odam butunlay yo'qoladi (keyin unga hech
narsa yuborib bo'lmaydi), ya'ni qo'pol ohang bizga foyda emas, zarar
keltiradi. Shuning uchun a'zolik sharti xabar OXIRIDA, kichik kursiv
qator sifatida turadi.
"""

import time
import asyncio
import logging

import hpcup
from aiogram import types, F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.exceptions import TelegramBadRequest, TelegramForbiddenError

# --- O'LCHAMLAR ---
# Darrov so'ramaymiz: odamlarning bir qismi adashib chiqib, o'zi qaytadi.
# Ularga "nega ketdingiz?" deb yozsak ahmoqona bo'ladi.
ASK_DELAY = 300            # 5 daqiqa kutamiz
ASK_COOLDOWN_DAYS = 30     # bir odam oyiga bir martadan ko'p so'ralmaydi
COMMENT_TTL = 3600         # yozma javobni shuncha soniya kutamiz (1 soat)
SEND_PAUSE = 0.06          # ~16 xabar/sekund — Telegram chekloviga tushmaslik
QUEUE_LIMIT = 5000         # navbat shundan oshsa yangi hodisa tashlab ketiladi
AWAIT_LIMIT = 2000         # matn kutayotganlar ro'yxatining chegarasi

SCHEMA = """
CREATE TABLE IF NOT EXISTS leave_survey (
    id          INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id     INTEGER NOT NULL,
    left_at     TEXT NOT NULL,
    asked_at    TEXT,
    reason      TEXT,
    answered_at TEXT,
    comment     TEXT,
    returned_at TEXT
);
CREATE INDEX IF NOT EXISTS ix_leave_user ON leave_survey (user_id, left_at);
"""

# --- SABABLAR ---
# Kodlar bazaga yoziladi, o'zgartirilmasin (eski yozuvlar ma'nosini
# yo'qotadi). Matnni o'zgartirish mumkin.
REASONS = ("many_posts", "got_film", "bot_broken", "not_interesting",
           "accident", "other")

# Shu uchtasida tugmadan keyin yozma javob ham so'raymiz — eng qimmatli
# ma'lumot aynan o'sha yerdan chiqadi.
ASK_COMMENT = ("bot_broken", "not_interesting", "other")

BUTTONS = {
    "uz": {
        "many_posts":      "🔕 Xabarlar juda ko'p edi",
        "got_film":        "🎬 Kerakli filmni topib oldim",
        "bot_broken":      "🐌 Bot sekin / xato ishladi",
        "not_interesting": "🎭 Kontent qiziq emas edi",
        "accident":        "🤷 Tasodifan chiqib ketibman",
        "other":           "✍️ Boshqa sabab",
        "back":            "🪄 Kanalga qaytish",
    },
    "ru": {
        "many_posts":      "🔕 Слишком много сообщений",
        "got_film":        "🎬 Нашёл нужный фильм",
        "bot_broken":      "🐌 Бот работал медленно / с ошибкой",
        "not_interesting": "🎭 Контент неинтересен",
        "accident":        "🤷 Вышел случайно",
        "other":           "✍️ Другая причина",
        "back":            "🪄 Вернуться в канал",
    },
    "en": {
        "many_posts":      "🔕 Too many posts",
        "got_film":        "🎬 I found the film I needed",
        "bot_broken":      "🐌 The bot was slow or buggy",
        "not_interesting": "🎭 The content wasn't interesting",
        "accident":        "🤷 I left by accident",
        "other":           "✍️ Another reason",
        "back":            "🪄 Come back to the channel",
    },
}

ASK_TEXT = {
    "uz": ("🦉 <b>Boyo'g'li sizni izlab keldi...</b>\n\n"
           "Siz Xogvarts darvozasidan chiqib ketibsiz. Balki biz nimadir "
           "noto'g'ri qildik.\n\n"
           "Bir soniya vaqt ajratsangiz — nima sabab bo'ldi?\n\n"
           "<i>Filmlar faqat kanal a'zolariga ochiq. Qaytish har doim mumkin.</i>"),
    "ru": ("🦉 <b>Сова искала вас...</b>\n\n"
           "Вы покинули ворота Хогвартса. Возможно, мы что-то сделали не так.\n\n"
           "Если найдётся минутка — что стало причиной?\n\n"
           "<i>Фильмы открыты только подписчикам канала. Вернуться можно "
           "в любой момент.</i>"),
    "en": ("🦉 <b>An owl came looking for you...</b>\n\n"
           "You've left the gates of Hogwarts. Perhaps we did something wrong.\n\n"
           "If you have a moment — what made you leave?\n\n"
           "<i>Films are open to channel members only. You can come back "
           "any time.</i>"),
}

# Sababga MOS javob. Ushlab qolish shu yerda tug'iladi: har bir e'tirozga
# tayyor yechim beriladi, quruq "rahmat" emas.
REPLY = {
    "uz": {
        "many_posts": (
            "🔕 <b>Tushundik.</b>\n\n"
            "Kanalga haftasiga 2-3 tadan ortiq post chiqmaydi va biz hech "
            "qachon begona reklama bermaymiz. Agar shovqin bezovta qilsa — "
            "kanalni ovozsiz qilib qo'ying: bildirishnoma kelmaydi, filmlar "
            "esa ochiq qolaveradi.\n\n"
            "Rahmat, javobingiz biz uchun muhim."),
        "got_film": (
            "🎬 <b>Ajoyib, demak vazifamizni bajaribmiz!</b>\n\n"
            "Bilsangiz, kolleksiyada faqat 8 ta film va \"Fantastik "
            "maxluqlar\" emas: viktorina, sehrli shaxmat, Xogvarts kubogi "
            "musobaqasi va fakultetlar reytingi ham bor. Ularning hammasi "
            "faqat kanal a'zolariga ochiq.\n\n"
            "Rahmat, javobingiz biz uchun muhim."),
        "bot_broken": (
            "🐌 <b>Kechirasiz, bu bizning aybimiz.</b>\n\n"
            "Aynan nima ishlamadi? Shu yerga qisqacha yozib yuboring — "
            "o'qiymiz va tuzatamiz. Xohlamasangiz, javob bermasangiz ham "
            "bo'ladi."),
        "not_interesting": (
            "🎭 <b>To'g'ri gap uchun rahmat.</b>\n\n"
            "Nimasi qiziq emas edi yoki nimani ko'rishni xohlardingiz? "
            "Bir-ikki og'iz yozib yuborsangiz — keyingi safar shuni "
            "hisobga olamiz."),
        "accident": (
            "🤷 <b>Xayriyat!</b>\n\n"
            "Unda hammasi joyida. Pastdagi tugma bilan bir bosishda "
            "qaytasiz — kolleksiya ham, ballaringiz ham o'z joyida turibdi."),
        "other": (
            "✍️ <b>Eshitamiz.</b>\n\n"
            "Sababini shu yerga yozib yuboring. Har bir javobni o'zimiz "
            "o'qiymiz."),
        "saved": (
            "✅ <b>Rahmat, yozib oldik.</b>\n\n"
            "Har bir javobni o'qiymiz. Eshigimiz ochiq — istalgan vaqtda "
            "qaytishingiz mumkin."),
    },
    "ru": {
        "many_posts": (
            "🔕 <b>Поняли.</b>\n\n"
            "В канале выходит не больше 2-3 постов в неделю, и мы никогда "
            "не даём чужую рекламу. Если мешает шум — просто отключите "
            "уведомления канала: сообщения приходить не будут, а фильмы "
            "останутся открытыми.\n\n"
            "Спасибо, ваш ответ для нас важен."),
        "got_film": (
            "🎬 <b>Отлично, значит мы справились!</b>\n\n"
            "Кстати, в коллекции не только 8 фильмов и «Фантастические "
            "твари»: есть викторина, волшебные шахматы, турнир за Кубок "
            "Хогвартса и рейтинг факультетов. Всё это открыто только "
            "подписчикам.\n\n"
            "Спасибо, ваш ответ для нас важен."),
        "bot_broken": (
            "🐌 <b>Извините, это наша вина.</b>\n\n"
            "Что именно не сработало? Напишите пару слов прямо сюда — "
            "прочитаем и починим. Можно и не отвечать."),
        "not_interesting": (
            "🎭 <b>Спасибо за честность.</b>\n\n"
            "Что именно было неинтересно или что вы хотели бы видеть? "
            "Пара строк — и мы учтём это в следующий раз."),
        "accident": (
            "🤷 <b>Тогда всё в порядке!</b>\n\n"
            "Кнопка ниже вернёт вас одним нажатием — коллекция и ваши "
            "баллы на месте."),
        "other": (
            "✍️ <b>Слушаем.</b>\n\n"
            "Напишите причину прямо сюда. Мы читаем каждый ответ сами."),
        "saved": (
            "✅ <b>Спасибо, записали.</b>\n\n"
            "Мы читаем каждый ответ. Дверь открыта — возвращайтесь в "
            "любой момент."),
    },
    "en": {
        "many_posts": (
            "🔕 <b>Understood.</b>\n\n"
            "The channel gets no more than 2-3 posts a week, and we never "
            "run outside ads. If the noise is the problem, just mute the "
            "channel — no notifications, and the films stay open.\n\n"
            "Thank you, your answer matters to us."),
        "got_film": (
            "🎬 <b>Great — then we did our job!</b>\n\n"
            "By the way, the collection is more than the 8 films and "
            "Fantastic Beasts: there are quizzes, wizard chess, the "
            "Hogwarts Cup tournament and house rankings. All of it is "
            "open to channel members only.\n\n"
            "Thank you, your answer matters to us."),
        "bot_broken": (
            "🐌 <b>Sorry — that one is on us.</b>\n\n"
            "What exactly went wrong? Write a line here and we'll read it "
            "and fix it. No need to reply if you'd rather not."),
        "not_interesting": (
            "🎭 <b>Thanks for being honest.</b>\n\n"
            "What wasn't interesting, or what would you like to see? "
            "A line or two and we'll take it into account."),
        "accident": (
            "🤷 <b>No harm done!</b>\n\n"
            "The button below brings you back in one tap. Your collection "
            "and your points are right where you left them."),
        "other": (
            "✍️ <b>We're listening.</b>\n\n"
            "Write your reason here. We read every answer ourselves."),
        "saved": (
            "✅ <b>Thanks, noted.</b>\n\n"
            "We read every answer. The door is open — come back any time."),
    },
}

DEFAULT_LANG = "uz"

_cfg = {}                 # main.py beradigan sozlamalar
_queue = None             # asyncio.Queue — worker ichida to'ldiriladi
_awaiting = {}            # user_id -> (row_id, reason, muhlat)


def _lang(lang):
    return lang if lang in BUTTONS else DEFAULT_LANG


# ---------------------------------------------------------------- baza
# Jadval hp.db ichida yashaydi — alohida fayl ochish ortiqcha bo'lardi.
# hpcup._connect() WAL va timeout'larni allaqachon to'g'ri qo'yadi.

def _init():
    conn = hpcup._connect()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


async def init():
    await asyncio.to_thread(_init)
    logging.info("Chiqib ketish so'rovi jadvali tayyor.")


def _stamp():
    return hpcup._utc_iso(hpcup.now_tk())


def _log_leave(user_id):
    """Chiqish hodisasini yozadi va (row_id, so'rash_mumkinmi) qaytaradi.

    Hodisaning o'zi HAR DOIM yoziladi (statistika uchun kerak), lekin
    yaqinda so'ralgan odamdan qayta so'ralmaydi — aks holda kirib-chiqib
    yuradiganlar uchun bu bezorilikka aylanadi.
    """
    conn = hpcup._connect()
    try:
        chegara = hpcup._utc_iso(
            hpcup.now_tk() - hpcup.timedelta(days=ASK_COOLDOWN_DAYS))
        row = conn.execute(
            "SELECT 1 FROM leave_survey WHERE user_id=? AND asked_at IS NOT NULL "
            "AND asked_at > ? LIMIT 1", (int(user_id), chegara)).fetchone()
        cur = conn.execute(
            "INSERT INTO leave_survey (user_id, left_at) VALUES (?,?)",
            (int(user_id), _stamp()))
        conn.commit()
        return cur.lastrowid, row is None
    finally:
        conn.close()


async def log_leave(user_id):
    return await asyncio.to_thread(_log_leave, user_id)


def _mark_asked(row_id):
    conn = hpcup._connect()
    try:
        conn.execute("UPDATE leave_survey SET asked_at=? WHERE id=?",
                     (_stamp(), int(row_id)))
        conn.commit()
    finally:
        conn.close()


def _save_reason(row_id, reason):
    conn = hpcup._connect()
    try:
        conn.execute(
            "UPDATE leave_survey SET reason=?, answered_at=? WHERE id=?",
            (reason, _stamp(), int(row_id)))
        conn.commit()
    finally:
        conn.close()


def _save_comment(row_id, text):
    conn = hpcup._connect()
    try:
        conn.execute("UPDATE leave_survey SET comment=? WHERE id=?",
                     (text[:1000], int(row_id)))
        conn.commit()
    finally:
        conn.close()


def _mark_returned(user_id):
    """Odam qaytganda eng oxirgi so'ralgan yozuvni belgilaydi.

    Butun g'oyaning asosiy o'lchovi shu: so'rov yuborilganlardan
    nechtasi qaytdi.
    """
    conn = hpcup._connect()
    try:
        conn.execute(
            "UPDATE leave_survey SET returned_at=? WHERE id = ("
            "  SELECT id FROM leave_survey WHERE user_id=? AND asked_at IS NOT NULL"
            "  AND returned_at IS NULL ORDER BY left_at DESC LIMIT 1)",
            (_stamp(), int(user_id)))
        conn.commit()
    finally:
        conn.close()


async def mark_returned(user_id):
    try:
        await asyncio.to_thread(_mark_returned, user_id)
    except Exception as e:
        logging.error("Qaytganini belgilashda xato (%s): %s", user_id, e)


def _stats(days):
    conn = hpcup._connect()
    try:
        chegara = hpcup._utc_iso(hpcup.now_tk() - hpcup.timedelta(days=days))
        umumiy = conn.execute(
            "SELECT COUNT(*) AS ketgan,"
            " SUM(asked_at IS NOT NULL) AS soralgan,"
            " SUM(reason IS NOT NULL) AS javob,"
            " SUM(returned_at IS NOT NULL) AS qaytgan"
            " FROM leave_survey WHERE left_at > ?", (chegara,)).fetchone()
        sabablar = conn.execute(
            "SELECT reason, COUNT(*) AS n,"
            " SUM(returned_at IS NOT NULL) AS qaytgan"
            " FROM leave_survey WHERE left_at > ? AND reason IS NOT NULL"
            " GROUP BY reason ORDER BY n DESC", (chegara,)).fetchall()
        izohlar = conn.execute(
            "SELECT reason, comment FROM leave_survey"
            " WHERE comment IS NOT NULL AND left_at > ?"
            " ORDER BY id DESC LIMIT 10", (chegara,)).fetchall()
        return dict(umumiy), [dict(r) for r in sabablar], [dict(r) for r in izohlar]
    finally:
        conn.close()


# ---------------------------------------------------------------- tugmalar

def _ask_keyboard(row_id, lang):
    b = BUTTONS[_lang(lang)]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b[code], callback_data="lv:%s:%d" % (code, row_id))]
        for code in REASONS
    ])


def _back_keyboard(lang):
    b = BUTTONS[_lang(lang)]
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=b["back"], url=_cfg["channel_url"])]
    ])


# ---------------------------------------------------------------- navbat

async def _ask(user_id, row_id):
    """Bitta odamga so'rov yuboradi."""
    # Faqat ANIQ "a'zo emas" bo'lsa so'raymiz. is_subscribed None qaytarsa
    # (Telegram javob bermadi) jim o'tamiz — hali a'zo bo'lgan odamga
    # "nega ketdingiz?" deb yozib qo'yish eng yomon xato bo'lardi.
    if await _cfg["is_subscribed"](user_id) is not False:
        await mark_returned(user_id)
        return

    lang = _lang(await _cfg["user_lang"](user_id) or DEFAULT_LANG)
    try:
        await _cfg["bot"].send_message(
            user_id, ASK_TEXT[lang], parse_mode="HTML",
            reply_markup=_ask_keyboard(row_id, lang))
    except TelegramForbiddenError:
        # Botni bloklagan yoki umuman /start bosmagan odam — jim o'tamiz.
        return
    await asyncio.to_thread(_mark_asked, row_id)


async def _worker():
    """Navbatni birma-bir bo'shatadi.

    Bitta oqim ikki vazifani bajaradi: kutish muhlatini ushlaydi va
    yuborish tezligini cheklaydi. Elementlar navbatga vaqt tartibida
    tushgani uchun oddiy ketma-ket kutish yetarli.
    """
    while True:
        user_id, row_id, muhlat = await _queue.get()
        try:
            qoldi = muhlat - time.time()
            if qoldi > 0:
                await asyncio.sleep(qoldi)
            await _ask(user_id, row_id)
        except Exception as e:
            logging.error("Chiqish so'rovini yuborishda xato (%s): %s", user_id, e)
        finally:
            _queue.task_done()
        await asyncio.sleep(SEND_PAUSE)


async def on_left(user):
    """main.py chaqiradi: odam kanaldan chiqdi."""
    if user.is_bot or user.id in _cfg.get("admin_ids", ()):
        return
    try:
        row_id, sorash_mumkin = await log_leave(user.id)
    except Exception as e:
        logging.error("Chiqishni yozishda xato (%s): %s", user.id, e)
        return
    if not sorash_mumkin or _queue is None:
        return
    try:
        _queue.put_nowait((user.id, row_id, time.time() + ASK_DELAY))
    except asyncio.QueueFull:
        logging.warning("Chiqish so'rovi navbati to'ldi, tashlab ketildi: %s", user.id)


# ---------------------------------------------------------------- handlerlar

def _remember_awaiting(user_id, row_id, reason):
    if len(_awaiting) >= AWAIT_LIMIT:
        eng_eski = min(_awaiting, key=lambda k: _awaiting[k][2])
        _awaiting.pop(eng_eski, None)
    _awaiting[user_id] = (row_id, reason, time.time() + COMMENT_TTL)


def register(dp, bot, cfg):
    """main.py shu funksiyani chaqiradi."""
    global _queue
    _cfg.update(cfg)
    _cfg["bot"] = bot
    _queue = asyncio.Queue(maxsize=QUEUE_LIMIT)
    asyncio.create_task(_worker())

    @dp.callback_query(F.data.startswith("lv:"))
    async def _reason_picked(callback: types.CallbackQuery):
        parts = callback.data.split(":")
        try:
            reason, row_id = parts[1], int(parts[2])
        except (IndexError, ValueError):
            await callback.answer()
            return
        if reason not in REASONS:
            await callback.answer()
            return

        lang = _lang(await _cfg["user_lang"](callback.from_user.id) or DEFAULT_LANG)
        try:
            await asyncio.to_thread(_save_reason, row_id, reason)
        except Exception as e:
            logging.error("Sababni yozishda xato: %s", e)

        kutamiz = reason in ASK_COMMENT
        if kutamiz:
            _remember_awaiting(callback.from_user.id, row_id, reason)

        # Javob xuddi shu xabarning ustiga yoziladi: tugmalar yo'qoladi,
        # chatda ortiqcha xabar qolmaydi.
        try:
            await callback.message.edit_text(
                REPLY[lang][reason], parse_mode="HTML",
                reply_markup=None if kutamiz else _back_keyboard(lang))
        except TelegramBadRequest as e:
            logging.warning("So'rov xabarini tahrirlab bo'lmadi: %s", e)
        await callback.answer()

    @dp.message(F.text & ~F.text.startswith("/"))
    async def _comment(message: types.Message):
        """Sababdan keyingi yozma izoh.

        Bu handler ENG OXIRIDA ro'yxatdan o'tadi (register() main() ichida,
        boshqa hamma handler'lardan keyin chaqiriladi) va ro'yxatda
        bo'lmagan odamning matniga umuman tegmaydi.
        """
        item = _awaiting.get(message.from_user.id)
        if not item:
            return
        row_id, _reason, muhlat = item
        if time.time() > muhlat:
            _awaiting.pop(message.from_user.id, None)
            return
        _awaiting.pop(message.from_user.id, None)

        try:
            await asyncio.to_thread(_save_comment, row_id, message.text)
        except Exception as e:
            logging.error("Izohni yozishda xato: %s", e)

        lang = _lang(await _cfg["user_lang"](message.from_user.id) or DEFAULT_LANG)
        await message.answer(REPLY[lang]["saved"], parse_mode="HTML",
                             reply_markup=_back_keyboard(lang))

    @dp.message(F.text.startswith("/sabablar"),
                F.from_user.id.in_(_cfg.get("admin_ids", set())))
    async def _report(message: types.Message):
        bolaklar = message.text.split()
        try:
            days = int(bolaklar[1]) if len(bolaklar) > 1 else 30
        except ValueError:
            days = 30
        days = max(1, min(days, 365))

        umumiy, sabablar, izohlar = await asyncio.to_thread(_stats, days)
        ketgan = umumiy["ketgan"] or 0
        soralgan = umumiy["soralgan"] or 0
        javob = umumiy["javob"] or 0
        qaytgan = umumiy["qaytgan"] or 0

        def foiz(qism, butun):
            return "%.0f%%" % (100.0 * qism / butun) if butun else "—"

        qator = ["📊 <b>Chiqib ketish sabablari — %d kun</b>\n" % days,
                 "Chiqqan: <b>%d</b>" % ketgan,
                 "So'rov yuborildi: <b>%d</b>" % soralgan,
                 "Javob berdi: <b>%d</b> (%s)" % (javob, foiz(javob, soralgan)),
                 "Qaytdi: <b>%d</b> (%s)\n" % (qaytgan, foiz(qaytgan, soralgan))]

        if sabablar:
            qator.append("<b>Sabablar:</b>")
            for r in sabablar:
                qator.append("• %s — <b>%d</b> (%s), qaytgan: %d" % (
                    BUTTONS["uz"].get(r["reason"], r["reason"]),
                    r["n"], foiz(r["n"], javob), r["qaytgan"] or 0))
        if izohlar:
            qator.append("\n<b>So'nggi izohlar:</b>")
            for r in izohlar:
                matn = r["comment"].replace("<", "&lt;").replace(">", "&gt;")
                qator.append("• <i>%s</i>: %s" % (r["reason"], matn[:200]))

        await message.answer("\n".join(qator), parse_mode="HTML")
