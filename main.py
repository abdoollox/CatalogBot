import os
import re
import time
import asyncio
import logging

# --- TIZIM KO'ZLARINI OCHISH (LOGGING) ---
# MUHIM: bu blok 'import sheets' dan OLDIN turishi SHART. sheets.py import
# paytida logging.info() chaqiradi, Python esa shunda root logger'ga WARNING
# darajali handler'ni o'zi o'rnatib qo'yadi - natijada keyin chaqirilgan
# basicConfig() jim qoladi va barcha INFO loglar yo'qoladi.
# force=True - kutubxona allaqachon handler qo'ygan bo'lsa ham ustidan yozadi.
logging.basicConfig(level=logging.INFO, force=True)

# aiogram HAR BIR update uchun INFO yozadi (dispatcher.py: 'Update id=... is
# handled'). Docker'da log rotatsiyasi yo'q, shuning uchun bu diskni to'ldiradi
# va haqiqiy xabarlarni ko'mib tashlaydi. Faqat ogohlantirish/xatolar qolsin.
logging.getLogger("aiogram.event").setLevel(logging.WARNING)

import json
import html
import contextvars
import aiofiles
import urllib.parse
import hmac
import hashlib
import aiohttp
import sheets
import catalog
import emoji
import hpcup
import hpbot
import hpchess
import hpleave
import hpkanal
import hpmusic
try:
    import hpxat            # xat rasmi (Pillow kerak)
except Exception as _xat_error:   # kutubxona yo'q bo'lsa bot baribir ishlasin
    hpxat = None
    logging.error("Xat rasmi moduli yuklanmadi: %s", _xat_error)
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import Command, CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiohttp import web
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest, TelegramNetworkError

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003826689337"))
CHANNEL_URL = "https://t.me/garripotter_kolleksiya"
WEBAPP_URL = "https://abdoollox.github.io/CatalogWebApp/"
IMG_URL = "https://abdoollox.github.io/CatalogWebApp/img"
BOT_USERNAME = "garripotterkinobot"
# /holat kabi xizmat buyruqlari faqat shu odamlarga (.env: ADMIN_IDS=1,2)
ADMIN_IDS = {int(x) for x in os.getenv("ADMIN_IDS", "").replace(" ", "").split(",")
             if x.isdigit()}
DB_CHANNEL_ID = -1003641399832
# "Sinov o'quvchisi": admin ilovada shu rejimni yoqsa, so'rovlari MANFIY
# raqamli alohida hisobga tushadi (-<o'z raqami>). Shunda u ilovani chinakam
# yangi odam sifatida boshidan o'tadi: fakultet, tayoqcha, ball, chat - hammasi
# noldan. Asl hisobiga tegilmaydi, istalgan payt "Noldan boshlash" bilan
# sinov hisobi butunlay tozalanadi. Reyting/kubok/chat manfiy raqamlarni
# hisobga olmaydi (hpcup.REAL_ONLY).
TEST_HEADER = "X-HP-Test"
_test_mode = contextvars.ContextVar("hp_test_mode", default=False)


def test_uid(user_id):
    """Sinov rejimidagi admin uchun soxta (manfiy) raqam."""
    return -abs(int(user_id))


def tg_chat_id(user_id):
    """Telegramga yozish uchun haqiqiy chat raqami.

    Sinov o'quvchisi bazada manfiy raqam bilan yuradi, lekin film va
    xabarlar baribir adminning o'z chatiga kelishi kerak - aks holda
    kutubxona qismini sinab bo'lmaydi.
    """
    return abs(int(user_id))
# Kuzatuv paneli (dashboard) shu kalit bilan loglarni o'qiydi. Kalit .env da
# turadi; bo'sh bo'lsa panel manzili butunlay yopiq qoladi.
DASH_TOKEN = os.getenv("DASH_TOKEN", "")

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- BAZA QULFI VA FAYL MANZILI ---
db_lock = asyncio.Lock()
USERS_FILE = "users_db.json"

# --- FILMLAR KATALOGI ---
# Ro'yxatning o'zi catalog.py da. Uni shu yerda takrorlamaymiz: ilgari
# ayni ro'yxat WebApp ichida ham yozilgan edi va ikkalasi bir-biridan
# uzoqlashib ketish xavfi bor edi.
MOVIES_DB = catalog.FILMS


# --- MIJOZ HARAKATLARINI BAZAGA YOZISH ---
async def log_user_action(user: types.User, payload: str, sheet_payload: str = None):
    """Harakatni users_db.json va Google Sheets'ga yozadi.

    sheet_payload - faqat jadvalda ko'rinadigan nom (masalan `web_hp1_uz`).
    Bazadagi kalit o'zgarmaydi: remind_hp2.py va migrate.py `hp1_uz` ni o'qiydi.
    """
    async with db_lock:
        try:
            async with aiofiles.open(USERS_FILE, "r", encoding="utf-8") as f:
                content = await f.read()
                db = json.loads(content) if content else {}
        except (FileNotFoundError, json.JSONDecodeError):
            db = {}

        user_id = str(user.id)
        
        if user_id not in db:
            db[user_id] = {
                "nickname": user.full_name,
                "username": f"@{user.username}" if user.username else "Yo'q",
                "clicks": {}
            }
        else:
            db[user_id]["nickname"] = user.full_name
            db[user_id]["username"] = f"@{user.username}" if user.username else "Yo'q"

        if payload not in db[user_id]["clicks"]:
            db[user_id]["clicks"][payload] = []
            
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        db[user_id]["clicks"][payload].append(now)

        async with aiofiles.open(USERS_FILE, "w", encoding="utf-8") as f:
            await f.write(json.dumps(db, indent=4, ensure_ascii=False))

    await sheets.append_click(user.id, db[user_id]["nickname"], db[user_id]["username"],
                              sheet_payload or payload, now)


async def send_html(chat_id, text, **kw):
    """HTML xabar yuboradi; custom emoji ishlamasa oddiy belgilar bilan
    qayta uriniladi.

    Custom emoji faqat bot egasida Telegram Premium bo'lsa ishlaydi.
    Premium tugasa yoki to'plam o'chsa Telegram butun xabarni rad etishi
    mumkin - asosiy oqim shu sababdan to'xtab qolmasligi kerak.
    """
    try:
        return await bot.send_message(chat_id, text, parse_mode="HTML", **kw)
    except TelegramBadRequest as e:
        oddiy = emoji.strip_tags(text)
        if oddiy == text:
            raise
        logging.warning("Custom emoji bilan yuborilmadi (%s): %s", chat_id, e)
        return await bot.send_message(chat_id, oddiy, parse_mode="HTML", **kw)


# --- BOT MATNLARI (uch tilda) ---
# Foydalanuvchi /start da tilni bir marta tanlaydi; keyin BARCHA xabarlar
# va filmlar shu tilda boradi.

TEXTS = {
    "uz": {
        "subscribe": emoji.tag("yopiq") + " Filmlarni ko'rish uchun avval "
                     "kanalimizga obuna bo'ling!",
        "btn_sub": "Kanalga obuna bo'lish",
        "btn_check": "Tasdiqlash",
        "btn_open": "Kolleksiyani ochish",
        "btn_lang": "Tilni o'zgartirish",
        "not_subscribed": "Hali obuna bo'lmadingiz! Avval kanalga a'zo bo'ling.",
        "soon": "⏳ Bu tildagi film tez orada yuklanadi.",
        "brand": "GARRI POTTER KOLLEKSIYA",
        "nothing_found": "Topilmadi",
        "try_other": "Boshqa nom bilan urinib ko'ring",
        "btn_watch": "Tomosha qilish",
        "btn_search": "Qidirish",
        "ref_new": (emoji.tag("dostlar") + " <b>Yangi do'st qo'shildi!</b>\n\n"
                    "Siz ulashgan havola orqali yana bir kishi kolleksiyaga "
                    "qo'shildi.\n\nTaklif qilgan do'stlaringiz: <b>%d</b>\n"
                    "Darajangiz: <b>%s</b>\n"
                    "Xogvarts kubogi: <b>+%d ball</b>"),
        "btn_share_more": "Yana ulashish",
        "promo_title": "Kolleksiyani taklif qilish",
        "promo_desc": "Garri Potter Kolleksiyasi — sizning havolangiz bilan",
        "promo": ["%d ta film — hammasi bir joyda",
                  "O'zbek, rus va ingliz tillarida",
                  "1080p sifatda, reklamasiz, bepul",
                  "Taklif qildi: <b>%s</b>",
                  "Tugmani bosing va istalgan filmni oling"],
        "catalog": (
            emoji.tag("kolleksiya") + " <b>Garri Potter Kolleksiyasiga xush kelibsiz!</b>\n\n"
            "Garri Potter olamidagi barcha filmlarni yuqori sifatda, "
            "reklamalarsiz va 3 xil tilda (🇺🇿 🇷🇺 🇬🇧) tomosha qiling.\n\n"
            + emoji.tag("tomosha") +
            " <b>Kino tanlash uchun pastdagi tugma orqali kolleksiyani oching:</b>"
        ),
    },
    "ru": {
        "subscribe": emoji.tag("yopiq") + " Чтобы смотреть фильмы, сначала "
                     "подпишитесь на наш канал!",
        "btn_sub": "Подписаться на канал",
        "btn_check": "Подтвердить",
        "btn_open": "Открыть коллекцию",
        "btn_lang": "Сменить язык",
        "not_subscribed": "Вы ещё не подписаны! Сначала вступите в канал.",
        "soon": "⏳ Фильм на этом языке скоро появится.",
        "brand": "КОЛЛЕКЦИЯ ГАРРИ ПОТТЕРА",
        "nothing_found": "Ничего не найдено",
        "try_other": "Попробуйте другое название",
        "btn_watch": "Смотреть",
        "btn_search": "Поиск",
        "ref_new": (emoji.tag("dostlar") + " <b>Новый друг присоединился!</b>\n\n"
                    "По вашей ссылке к коллекции присоединился ещё один "
                    "человек.\n\nПриглашённых друзей: <b>%d</b>\n"
                    "Ваш уровень: <b>%s</b>\n"
                    "Кубок Хогвартса: <b>+%d очков</b>"),
        "btn_share_more": "Поделиться ещё",
        "promo_title": "Пригласить в коллекцию",
        "promo_desc": "Коллекция «Гарри Поттер» — с вашей ссылкой",
        "promo": ["%d фильмов — всё в одном месте",
                  "На узбекском, русском и английском",
                  "В качестве 1080p, без рекламы, бесплатно",
                  "Пригласил(а): <b>%s</b>",
                  "Нажмите кнопку и получите любой фильм"],
        "catalog": (
            emoji.tag("kolleksiya") + " <b>Добро пожаловать в коллекцию «Гарри Поттер»!</b>\n\n"
            "Смотрите все фильмы вселенной Гарри Поттера в высоком качестве, "
            "без рекламы и на 3 языках (🇺🇿 🇷🇺 🇬🇧).\n\n"
            + emoji.tag("tomosha") +
            " <b>Откройте коллекцию кнопкой ниже и выберите фильм:</b>"
        ),
    },
    "en": {
        "subscribe": emoji.tag("yopiq") + " To watch the films, please "
                     "subscribe to our channel first!",
        "btn_sub": "Subscribe to the channel",
        "btn_check": "Confirm",
        "btn_open": "Open the collection",
        "btn_lang": "Change language",
        "not_subscribed": "You are not subscribed yet! Please join the channel first.",
        "soon": "⏳ The film in this language will be uploaded soon.",
        "brand": "HARRY POTTER COLLECTION",
        "nothing_found": "Nothing found",
        "try_other": "Try another title",
        "btn_watch": "Watch",
        "btn_search": "Search",
        "ref_new": (emoji.tag("dostlar") + " <b>A new friend joined!</b>\n\n"
                    "One more person joined the collection through the link "
                    "you shared.\n\nFriends invited: <b>%d</b>\n"
                    "Your rank: <b>%s</b>\n"
                    "Hogwarts Cup: <b>+%d points</b>"),
        "btn_share_more": "Share more",
        "promo_title": "Invite to the collection",
        "promo_desc": "Harry Potter Collection — with your link",
        "promo": ["%d films — all in one place",
                  "In Uzbek, Russian and English",
                  "1080p quality, ad-free, free",
                  "Invited by: <b>%s</b>",
                  "Tap the button and get any film"],
        "catalog": (
            emoji.tag("kolleksiya") + " <b>Welcome to the Harry Potter Collection!</b>\n\n"
            "Watch every film from the Harry Potter universe in high quality, "
            "ad-free and in 3 languages (🇺🇿 🇷🇺 🇬🇧).\n\n"
            + emoji.tag("tomosha") +
            " <b>Open the collection with the button below and pick a film:</b>"
        ),
    },
}

DEFAULT_LANG = "uz"


def T(lang):
    return TEXTS.get(lang, TEXTS[DEFAULT_LANG])


async def user_lang(user_id):
    """Tanlangan til yoki None (hali tanlamagan)."""
    try:
        return await hpcup.get_lang(user_id)
    except Exception as e:
        logging.error("Tilni o'qishda xato: %s", e)
        return None


# Til hali noma'lum - shuning uchun matn uchala tilda ham beriladi.
LANG_PROMPT = (
    emoji.tag("til") + " 🇺🇿 <b>Tilni tanlang.</b> "
    "Filmlar va barcha xabarlar shu tilda bo'ladi.\n"
    + emoji.tag("til") + " 🇷🇺 <b>Выберите язык.</b> "
    "Фильмы и все сообщения будут на нём.\n"
    + emoji.tag("til") + " 🇬🇧 <b>Choose a language.</b> "
    "Films and all messages will use it.")


def lang_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🇺🇿 O'zbekcha", callback_data="lang:uz")],
        [InlineKeyboardButton(text="🇷🇺 Русский", callback_data="lang:ru")],
        [InlineKeyboardButton(text="🇬🇧 English", callback_data="lang:en")],
    ])


def check_sub_keyboard(lang=DEFAULT_LANG):
    t = T(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t["btn_sub"], url=CHANNEL_URL,
                              icon_custom_emoji_id=emoji.icon("yopiq"))],
        [InlineKeyboardButton(text=t["btn_check"], callback_data="check_sub",
                              icon_custom_emoji_id=emoji.icon("tasdiq"))]
    ])

def webapp_url(lang):
    """WebApp manzili tanlangan til bilan.

    Busiz ilova o'z til ekranini qaytadan ko'rsatardi - foydalanuvchi
    tilni ikki marta tanlashiga to'g'ri kelardi.
    """
    return "%s?lang=%s" % (WEBAPP_URL, lang if lang in catalog.LANGS else DEFAULT_LANG)


def webapp_keyboard(lang=DEFAULT_LANG):
    t = T(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t["btn_open"], web_app=WebAppInfo(url=webapp_url(lang)),
                              icon_custom_emoji_id=emoji.icon("kolleksiya"))],
        # Til tugmasi SHART: aks holda noto'g'ri til tanlagan odam botda
        # uni o'zgartira olmay qolardi.
        [InlineKeyboardButton(text=t["btn_lang"], callback_data="lang:pick",
                              icon_custom_emoji_id=emoji.icon("til"))],
    ])

LOCALES = {
    "uz": {
        "collection_btn": "Kolleksiya",
        "share_btn": "Ulashish",
        "share_text": "🎬 Menga bu filmlar kolleksiyasi yoqdi. Siz ham foydalanib ko'ring!"
    },
    "ru": {
        "collection_btn": "Коллекция",
        "share_btn": "Поделиться",
        "share_text": "🎬 Мне понравилась эта коллекция фильмов. Попробуйте и вы!"
    },
    "en": {
        "collection_btn": "Collection",
        "share_btn": "Share",
        "share_text": "🎬 I really liked this movie collection. Check it out!"
    }
}

def movie_delivery_keyboard(movie_key, lang="uz", vk_url=None):
    """Film ostidagi tugmalar.

    "Ulashish" endi `switch_inline_query` ishlatadi: Telegram chat tanlatadi
    va o'sha chatga film KARTASI tushadi. Ilgari bu oddiy `t.me/share/url`
    havolasi edi - u shunchaki matn yuborardi, karta ham, referal ham yo'q edi.
    """
    loc = LOCALES.get(lang, LOCALES["uz"])
    t = T(lang)
    builder = InlineKeyboardBuilder()

    if vk_url:
        builder.row(InlineKeyboardButton(
            text="4K formatda ko'rish", url=vk_url,
            icon_custom_emoji_id=emoji.icon("sifat")))

    builder.row(
        # Bo'sh qator: chat tanlatmaydi, qidiruv shu chatda boshlanadi.
        InlineKeyboardButton(
            text=t["btn_search"], switch_inline_query_current_chat="",
            icon_custom_emoji_id=emoji.icon("qidiruv")),
        # Chat tanlatadi va o'sha chatga shu filmning kartasi tushadi.
        InlineKeyboardButton(
            text=loc["share_btn"], switch_inline_query="%s_%s" % (movie_key, lang),
            icon_custom_emoji_id=emoji.icon("dostlar")))

    builder.row(InlineKeyboardButton(
        text=loc["collection_btn"],
        web_app=WebAppInfo(url=webapp_url(lang)),
        icon_custom_emoji_id=emoji.icon("kolleksiya")))

    return builder.as_markup()
    

# Telegram ba'zan javobsiz osilib qoladi (standart kutish 60 soniya). Odam
# shuncha kutmaydi - ilovani yopib ketadi. Qisqa kutib, yana bir urinamiz.
SUB_CHECK_TIMEOUT = 6
SUB_CHECK_TRIES = 2


async def is_subscribed(user_id):
    """True - a'zo, False - a'zo emas, None - Telegram javob bermadi.

    None ni "a'zo emas" deb hisoblamang (`if not ...` emas, `is False`):
    tarmoq uzilgani uchun a'zo odamni filmsiz qoldirmaymiz.
    """
    for urinish in range(1, SUB_CHECK_TRIES + 1):
        try:
            member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id,
                                               request_timeout=SUB_CHECK_TIMEOUT)
            return member.status in ["member", "administrator", "creator"]
        except TelegramNetworkError as e:
            logging.warning("A'zolikni tekshirib bo'lmadi (%s, %s-urinish): %s",
                            user_id, urinish, e)
        except Exception as e:
            logging.error(f"Kanalga a'zolikni tekshirishda xato: {e}")
            return False
    logging.error("A'zolik noma'lum, film beriladi: %s", user_id)
    return None

@dp.message(CommandStart())    
async def start_cmd(message: types.Message, command: CommandObject):
    try:
        await message.delete()
    except Exception:
        pass 
        
    raw = (command.args or "").strip()
    user_id = message.from_user.id
    payload, inviter_id, source = parse_payload(raw)

    is_new = True
    try:
        async with aiofiles.open(USERS_FILE, "r", encoding="utf-8") as f:
            content = await f.read()
            is_new = str(user_id) not in (json.loads(content) if content else {})
    except (FileNotFoundError, json.JSONDecodeError):
        pass

    if not payload or is_new:
        await log_user_action(message.from_user, "start")

    if message.from_user and message.from_user.first_name:
        try:
            await hpcup.touch_user(message.from_user.id, message.from_user.first_name, message.from_user.username)
        except Exception:
            pass

    # Referal, 1-bosqich: faqat YANGI odam kimgadir biriktiriladi. Botdan
    # avval foydalangan odam hech kimga ball keltirmaydi. Ball bu yerda
    # emas - obuna tasdiqlanganda beriladi (notify_inviter).
    if inviter_id and is_new:
        try:
            if await hpcup.remember_inviter(user_id, inviter_id):
                await log_user_action(message.from_user, "invited_%d" % inviter_id)
        except Exception as e:
            logging.error("Taklif qilganni yozishda xato: %s", e)

    # Reklama manbasi (`src_kanal`, `...-skanal`): faqat yangi odam va faqat
    # birinchisi - odamni qaysi reklama BIRINCHI olib kelgani muhim.
    source = clean_source(source)
    if source and is_new:
        try:
            if await hpcup.remember_source(user_id, source):
                await log_user_action(message.from_user, "src_" + source)
        except Exception as e:
            logging.error("Manbani yozishda xato: %s", e)
    
    lang = await user_lang(user_id)

    # Chuqur havolada til allaqachon bor (`watch_hp1_uz`) - so'ramaymiz,
    # aksincha o'shani eslab qolamiz.
    _, havola_tili = film_va_til(payload)
    if havola_tili:
        lang = havola_tili
        try:
            await hpcup.set_lang(user_id, lang)
        except Exception as e:
            logging.error("Tilni saqlashda xato: %s", e)

    # Til hali tanlanmagan - birinchi qadam shu. Nima uchun kelganini
    # eslab qolamiz, til tanlangach o'sha yerdan davom etamiz.
    if not lang:
        remember_pending(user_id, payload, None)
        await send_html(user_id, LANG_PROMPT, reply_markup=lang_keyboard())
        return

    await continue_flow(message.from_user, user_id, payload, lang)


async def continue_flow(user, chat_id, payload, lang):
    """Til ma'lum bo'lgandan keyingi yo'l: obuna -> film yoki katalog."""
    if await is_subscribed(user.id) is False:
        taklif = await send_html(chat_id, T(lang)["subscribe"],
                                 reply_markup=check_sub_keyboard(lang))
        # Nima uchun kelganini eslab qolamiz: a'zo bo'lgan zahoti davom etamiz.
        remember_pending(user.id, payload, taklif.message_id)
        return

    if payload:
        await handle_payload(user, chat_id, payload)
    else:
        await send_welcome(chat_id, lang)
    # Film yoki katalog yuborilgandan KEYIN - yangi odam kutib qolmasin.
    await notify_inviter(user)


@dp.callback_query(F.data.startswith("lang:"))
async def lang_handler(callback: types.CallbackQuery):
    """Til tanlandi (yoki qayta tanlash so'raldi)."""
    tanlov = callback.data.split(":", 1)[1]
    user_id = callback.from_user.id

    # Katalogdagi "Tilni o'zgartirish" tugmasi - ro'yxatni qayta ko'rsatamiz.
    # Eski xabar o'chiriladi: chatda ikkita katalog kartasi qolib ketmasin.
    if tanlov == "pick":
        await callback.answer()
        try:
            await callback.message.delete()
        except Exception as e:
            logging.warning("Katalog kartasini o'chirib bo'lmadi (%s): %s",
                            user_id, e)
        await send_html(user_id, LANG_PROMPT, reply_markup=lang_keyboard())
        return

    if tanlov not in catalog.LANGS:
        await callback.answer()
        return

    try:
        await hpcup.set_lang(user_id, tanlov)
    except Exception as e:
        logging.error("Tilni saqlashda xato: %s", e)

    # Til so'ragan xabar endi keraksiz
    try:
        await callback.message.delete()
    except Exception as e:
        logging.warning("Til xabarini o'chirib bo'lmadi (%s): %s", user_id, e)

    await callback.answer()

    payload, _ = take_pending(user_id)
    await continue_flow(callback.from_user, user_id, payload, tanlov)


# --- OBUNA KUTAYOTGANLAR ---
# Odam kanalga a'zo bo'lgan ZAHOTI oqim davom etishi kerak: "Tasdiqlash"
# tugmasini bosish shart emas. Bot kanalda administrator, ya'ni a'zolik
# o'zgarishi haqidagi hodisani oladi (`chat_member`).
#
# Nima kutayotgani shu yerda saqlanadi: film havolasi bilan kelgan bo'lsa
# o'sha film, aks holda oddiy salomlashuv. Xotirada - odam odatda bir
# necha daqiqada obuna bo'ladi, baza bilan band qilish ortiqcha.

PENDING_TTL = 3600        # soniya
PENDING_LIMIT = 1000

pending_subs = {}         # user_id -> (vaqt, payload, taklif_xabari_id)


def remember_pending(user_id, payload, prompt_message_id):
    if len(pending_subs) >= PENDING_LIMIT:
        eng_eski = min(pending_subs, key=lambda k: pending_subs[k][0])
        pending_subs.pop(eng_eski, None)
    pending_subs[user_id] = (time.time(), payload, prompt_message_id)


def take_pending(user_id):
    """Kutilayotgan ishni oladi va ro'yxatdan chiqaradi."""
    item = pending_subs.pop(user_id, None)
    if not item:
        return None, None
    qachon, payload, prompt_id = item
    if time.time() - qachon > PENDING_TTL:
        return None, None
    return payload, prompt_id


async def handle_payload(user, chat_id, payload):
    """Chuqur havola bilan kelgan filmni yuboradi.

    start_cmd dan ham, obuna tasdiqlangandan keyin ham chaqiriladi -
    shuning uchun alohida funksiya.
    """
    try:
        movie_key, lang = film_va_til(payload)
        if not movie_key:
            logging.warning("Tanib bo'lmagan havola: %r", payload)
            await bot.send_message(chat_id, T(await user_lang(chat_id) or DEFAULT_LANG)["soon"])
            return

        movie_data = MOVIES_DB[movie_key][lang]
        # Statistika kaliti: har doim `hp3_uz` ko'rinishida, `watch_` va
        # referal qismisiz - eski yozuvlar bilan bir xil bo'lsin.
        payload_clean = "%s_%s" % (movie_key, lang)

        if movie_data.get("message_id", 0) == 0:
            await bot.send_message(chat_id, T(lang)["soon"])
            return

        # Xavfsiz tizim: Mijoz harakatini qayd etish. Jadvalda film qayerdan
        # olingani ko'rinadi: WebApp zaxira havolasi (`web_`) yoki bot.
        origin = "web" if payload.startswith(WEB_PREFIX) else "bot"
        await log_user_action(user, payload_clean, "%s_%s" % (origin, payload_clean))

        vk_url = movie_data.get("vk_url") if lang == "uz" else None

        await send_film(chat_id, movie_key, lang, vk_url)

        # Xogvarts kubogi: kino ochilgani uchun ball (agar fakulteti bo'lsa).
        # Kinoning o'zi allaqachon yuborilgan - bu yerdagi xato
        # foydalanuvchiga ta'sir qilmasligi kerak.
        try:
            if movie_key.startswith("hp"):
                await hpbot.award_film_open(user, int(movie_key[2:]))
        except Exception as cup_error:
            logging.error("Kubok qismida xato: %s", cup_error)

    except Exception as e:
        logging.error(f"Kritik API xatosi: {e}")
        await bot.send_message(chat_id, f"⚠️ Telegram API xatosi (Fayl yuborish quladi): {str(e)}")


async def after_subscribe(user, chat_id, payload, prompt_message_id=None):
    """Obuna tasdiqlangach oqimni davom ettiradi.

    Ikki joydan chaqiriladi: `chat_member` hodisasi (avtomatik yo'l) va
    "Tasdiqlash" tugmasi (zaxira yo'l - hodisa kechiksa yoki yetib
    kelmasa odam baribir o'tib keta olsin).
    """
    # "Obuna bo'ling" xabari endi keraksiz - o'chiriladi.
    if prompt_message_id:
        try:
            await bot.delete_message(chat_id, prompt_message_id)
        except Exception as e:
            # Jim yutmaymiz: o'chmay qolsa sababini bilishimiz kerak.
            logging.warning("Taklif xabarini o'chirib bo'lmadi (%s): %s", chat_id, e)

    # "Obuna tasdiqlandi" degan alohida xabar yuborilmaydi - foydalanuvchi
    # buni o'zi biladi, ortiqcha qadam bo'lardi.
    lang = await user_lang(user.id) or DEFAULT_LANG

    if payload:
        # Odam aynan shu film uchun kelgan edi - o'shani beramiz. Ilgari bu
        # yo'qolib ketardi: obunadan keyin faqat katalog ko'rsatilardi va
        # izlab kelingan film yuborilmasdi.
        await handle_payload(user, chat_id, payload)
    else:
        await send_welcome(chat_id, lang)
    await notify_inviter(user)


async def notify_inviter(user):
    """Referal, 2-bosqich: obuna tasdiqlandi - taklif qilganga ball va xabar.

    Bir necha joydan chaqiriladi (obuna uch yo'l bilan aniqlanadi), lekin
    ball bir marta beriladi - buni baza kafolatlaydi. Hech qanday xato
    yangi odamning oqimini to'xtatmasligi kerak.
    """
    try:
        inviter_id, refs = await hpcup.award_referral(user.id)
    except Exception as e:
        logging.error("Referal balini berishda xato (%s): %s", user.id, e)
        return
    if not inviter_id:
        return
    await log_user_action(user, "ref_awarded")
    lang = await user_lang(inviter_id) or DEFAULT_LANG
    t = T(lang)
    try:
        # Tugma yangi ulashishga undaydi: chat tanlatadi va o'sha yerda
        # film qidiruvi ochiladi - aylanma shu bilan davom etadi.
        matn = t["ref_new"] % (refs, hpcup.rank_name(refs, lang),
                               hpcup.PTS_REFERRAL)
        await send_html(inviter_id, matn,
                        reply_markup=InlineKeyboardMarkup(inline_keyboard=[[
                            InlineKeyboardButton(
                                text=t["btn_share_more"], switch_inline_query="",
                                icon_custom_emoji_id=emoji.icon("dostlar"))]]))
    except Exception as e:
        # Taklif qilgan botni bloklagan bo'lishi mumkin - ball baribir yozildi.
        logging.info("Taklif qilganga xabar bormadi (%s): %s", inviter_id, e)


async def send_welcome(chat_id, lang=DEFAULT_LANG):
    """Katalogni foydalanuvchi tanlagan tilda ko'rsatadi.

    Ilgari fakulteti yo'qlarga avval saralanish taklif qilinardi. Endi
    yo'q: bot faqat film ko'rmoqchi bo'lganlar uchun, saralanish esa
    WebApp'dagi Xogvarts kubogining bir qismi. Botga filmga aloqasi
    bo'lmagan qadam qo'shilmaydi.

    Xabar obyekti emas, chat_id qabul qiladi: obuna hodisasidan keyin
    ham chaqiriladi, u yerda javob beriladigan xabar yo'q.
    """
    await send_html(chat_id, T(lang)["catalog"],
                    reply_markup=webapp_keyboard(lang))


@dp.callback_query(F.data == "check_sub")
async def check_sub_handler(callback: types.CallbackQuery):
    """Zaxira yo'l. Odatda `chat_member` hodisasi buni oldindan bajaradi;
    bu tugma hodisa kechikkan yoki yetib kelmagan holat uchun qoladi."""
    lang = await user_lang(callback.from_user.id) or DEFAULT_LANG
    if await is_subscribed(callback.from_user.id) is False:
        await callback.answer(T(lang)["not_subscribed"], show_alert=True)
        return

    payload, _ = take_pending(callback.from_user.id)
    await callback.answer()
    await after_subscribe(callback.from_user, callback.from_user.id, payload,
                          callback.message.message_id)

# --- INLINE QIDIRUV ---
# Istalgan chatda `@bot azkaban` deb yozilganda ishlaydi. Ulashilgan
# kartaning har bir havolasi ulashgan odamning id sini olib yuradi -
# ulashish va do'st taklif qilish bitta mexanizm.

# Telegram bitta javobda eng ko'pi 50 ta natija qabul qiladi. Bizda
# 11 film x 3 til = 33 - hammasi sig'adi.
INLINE_LIMIT = 50
BAYROQ = {"uz": "🇺🇿", "ru": "🇷🇺", "en": "🇬🇧"}
TIL_NOMI = {"uz": "O'zbekcha", "ru": "Русский", "en": "English"}

# Bot o'z kartasini boshqa botnikidan ajratishi uchun (ishga tushishda olinadi)
BOT_ID = None


# Karta qatorlarining nomlari - karta FILM tilida yoziladi (ruscha
# versiyani ulashgan odamning kartasi ruscha), foydalanuvchi tilida emas.
KARTA = {
    "uz": {"yil": "Yil", "vaqt": "Davomiyligi",
           "til": "Til", "sifat": "Sifat",
           "soat": "%d soat %d daqiqa"},
    "ru": {"yil": "Год", "vaqt": "Длительность",
           "til": "Язык", "sifat": "Качество",
           "soat": "%d ч %d мин"},
    "en": {"yil": "Year", "vaqt": "Runtime",
           "til": "Language", "sifat": "Quality",
           "soat": "%d h %d min"},
}


def share_caption(movie_key, film, lang, sharer_id=None):
    """Ulashiladigan karta matni (Marvel botidagi karta tartibida).

    Yuborilgan film ostida ham AYNAN SHU matn turadi (send_film) - odam
    ikki xil ko'rinish ko'rmasin.

    Oxirgi qatordagi havola - ulashayotgan odamning havolasi. Odam matnni
    nusxalab tarqatsa ham ball unga tushadi.
    """
    t, k = T(lang), KARTA[lang]

    # "Seriya: Garri Potter (2/8)" qatori ATAYLAB yo'q: 2026-yil dekabrda
    # Garri Potter SERIALI chiqadi va "seriya" so'zi odamni chalg'itishi
    # mumkin (foydalanuvchi qarori, 2026-09-10).
    lines = [
        film[lang]["caption"],
        "— — — — — — — — — —",
        "%s %s: %s" % (emoji.tag("yil"), k["yil"], film["year"]),
    ]
    daqiqa = catalog.RUNTIME.get(movie_key)
    if daqiqa:
        lines.append("%s %s: %s" % (emoji.tag("vaqt"), k["vaqt"],
                                    k["soat"] % divmod(daqiqa, 60)))
    # Sifat faqat yuklangan versiyada - yuklanmaganida bu va'da bo'lib qolardi
    if catalog.is_ready(movie_key, lang):
        lines.append("%s %s: %s" % (emoji.tag("sifat"), k["sifat"], catalog.QUALITY))
    # Faqat shu versiyaning tili. Boshqa tillar ("yana 🇷🇺 🇬🇧") ataylab
    # yozilmaydi - foydalanuvchi kerak emas dedi (2026-09-10).
    lines.append("%s %s: %s %s" % (emoji.tag("til"), k["til"],
                                   BAYROQ[lang], TIL_NOMI[lang]))
    reyting = catalog.IMDB.get(movie_key)
    if reyting:
        lines.append("%s IMDb: %.1f" % (emoji.tag("yulduz"), reyting))

    lines += [
        "",
        '%s <b><a href="%s">%s</a></b>' % (
            emoji.tag("tasdiq"), film_link(movie_key, lang, sharer_id), t["brand"]),
    ]
    return "\n".join(lines)


async def send_film(chat_id, movie_key, lang, vk_url=None):
    """Filmni yopiq kanaldan nusxalab yuboradi, ostida to'liq karta matni.

    Matndagi havola filmni olgan odamning o'z havolasi (Marvel botidagidek).
    Custom emoji rad etilsa (Premium tugagan va h.k.) - oddiy belgilar bilan
    qayta yuboriladi: film yetkazish HECH QACHON shu sababdan to'xtamasin.
    """
    matn = share_caption(movie_key, catalog.FILMS[movie_key], lang, chat_id)
    kw = dict(chat_id=chat_id, from_chat_id=DB_CHANNEL_ID,
              message_id=catalog.FILMS[movie_key][lang]["message_id"],
              parse_mode="HTML",
              reply_markup=movie_delivery_keyboard(movie_key, lang, vk_url),
              protect_content=True)
    try:
        return await bot.copy_message(caption=matn, **kw)
    except TelegramBadRequest as e:
        logging.warning("Film custom emoji bilan yuborilmadi (%s): %s", chat_id, e)
        return await bot.copy_message(caption=emoji.strip_tags(matn), **kw)


def share_keyboard(movie_key, lang, sharer_id=None):
    t = T(lang)
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t["btn_watch"],
                              url=film_link(movie_key, lang, sharer_id),
                              icon_custom_emoji_id=emoji.icon("tomosha"))],
        # Bo'sh qator: chat tanlatmaydi, shu chatning o'zida qidiruv boshlanadi.
        [InlineKeyboardButton(text=t["btn_search"],
                              switch_inline_query_current_chat="",
                              icon_custom_emoji_id=emoji.icon("qidiruv"))],
    ])


@dp.inline_query()
async def inline_search(query: types.InlineQuery):
    """Natijalar HAR DOIM Article ko'rinishida.

    Faqat rasmdan iborat natijalarni (InlineQueryResultPhoto) Telegram to'r
    qilib chizadi va nom bilan tavsifni UMUMAN ko'rsatmaydi - qaysi film
    ekani bilinmay qolardi.
    """
    lang = await user_lang(query.from_user.id) or DEFAULT_LANG
    t = T(lang)
    raw = (query.query or "").strip()

    # "chess_<kod>" - ilovadan do'stni shaxmatga chaqirish kartasi.
    m = CHESS_QUERY.match(raw.lower())
    if m:
        await answer_chess(query, lang, m.group(1))
        return

    # "taklif" - film emas, butun kolleksiyaning reklama kartasi.
    if raw.lower() in PROMO_QUERIES:
        await answer_promo(query, lang)
        return

    # Aniq film+til ("hp3_uz") - film ostidagi "Ulashish" tugmasi shuni
    # yuboradi. Bunda faqat o'sha bitta karta: odam aynan qaysi versiyani
    # ko'rgan bo'lsa, o'shani ulashadi.
    aniq_film, aniq_til = film_va_til(raw)
    if aniq_film:
        juftlar = [(aniq_film, aniq_til)]
    else:
        # Har bir topilgan film UCHALA tildagi versiyasi bilan chiqadi.
        # Foydalanuvchining o'z tili birinchi - avval o'z tilidagi to'plam.
        tartib = [lang] + [l for l in catalog.LANGS if l != lang]
        topildi = catalog.search(raw, limit=len(catalog.FILMS))
        juftlar = [(fid, l) for l in tartib for fid, _ in topildi]

    # Yuklanmagan versiya ko'rsatilmaydi: ulashilsa, do'st uni ocha olmasdi.
    juftlar = [(f, l) for f, l in juftlar if catalog.is_ready(f, l)][:INLINE_LIMIT]

    natijalar = []
    for movie_key, film_tili in juftlar:
        film = catalog.FILMS[movie_key]
        # Til birinchi qatorda aniq ko'rinsin - bir filmning uch versiyasi
        # yonma-yon turadi, ular faqat shu bilan ajraladi.
        qator1 = "%s %s  ·  %s" % (BAYROQ[film_tili], TIL_NOMI[film_tili], film["year"])
        if movie_key in catalog.IMDB:
            qator1 += "  ·  ⭐ %.1f" % catalog.IMDB[movie_key]
        qator2 = catalog.SERIES.get(film["kind"], "")

        natijalar.append(types.InlineQueryResultArticle(
            id="%s_%s" % (movie_key, film_tili),
            title="%d. %s" % (film["order"], film[film_tili]["title"]),
            description=qator1 + "\n" + qator2,
            thumbnail_url=sq_url(movie_key, film_tili),
            thumbnail_width=320,
            thumbnail_height=320,
            input_message_content=types.InputTextMessageContent(
                message_text=share_caption(movie_key, film, film_tili,
                                           query.from_user.id),
                parse_mode="HTML",
                link_preview_options=preview_options(movie_key, film_tili)),
            reply_markup=share_keyboard(movie_key, film_tili, query.from_user.id),
        ))

    if not natijalar:
        natijalar.append(types.InlineQueryResultArticle(
            id="empty",
            title=t["nothing_found"],
            description=t["try_other"],
            input_message_content=types.InputTextMessageContent(
                message_text="https://t.me/%s" % BOT_USERNAME)))

    try:
        # is_personal SHART: kartadagi havola ulashgan odamning id sini olib
        # yuradi. Umumiy keshda birovning havolasi boshqasiga tushib qolardi.
        await query.answer(natijalar, cache_time=30, is_personal=True)
    except Exception as e:
        logging.error("Inline javobida xato: %s", e)


@dp.chosen_inline_result()
async def inline_shared(chosen: types.ChosenInlineResult):
    """Karta haqiqatan yuborilganda ishlaydi (ulashish statistikasi).

    Faqat BotFather'da /setinlinefeedback yoqilgan bo'lsa keladi.
    """
    if chosen.result_id == "empty":
        return
    try:
        await log_user_action(chosen.from_user, "share_%s" % chosen.result_id)
    except Exception as e:
        logging.error("Ulashishni yozishda xato: %s", e)


# Karta tugmasidagi havoladan film id sini ajratamiz. Bu matnni tahlil
# qilishdan ishonchliroq: matn o'zgarishi mumkin, havola formati esa
# barqaror. Regex `-` da to'xtaydi, ya'ni referal qismi tushib qoladi.
VIA_START = re.compile(r"[?&]start=watch_([A-Za-z0-9_]+)")


def movie_from_markup(markup):
    if not markup:
        return None
    for qator in markup.inline_keyboard:
        for tugma in qator:
            if tugma.url:
                topildi = VIA_START.search(tugma.url)
                if topildi:
                    return topildi.group(1)
    return None


@dp.message(Command("holat"), F.from_user.id.in_(ADMIN_IDS))
async def status_cmd(message: types.Message):
    """Admin uchun: katalog, rasmlar va odamlar qayerdan kelgani."""
    tayyor = ", ".join("%s %d/%d" % (BAYROQ[l], len(catalog.FILMS) - len(catalog.not_ready(l)),
                                       len(catalog.FILMS)) for l in catalog.LANGS)
    rep = await hpcup.source_report()
    lines = [
        "📊 <b>Holat</b>", "",
        "Yuklangan filmlar: %s" % tayyor,
        "Karta rasmlari: <b>%d / %d</b>" % (len(wide_versions),
                                            len(catalog.FILMS) * len(catalog.LANGS)),
        "Reklama kartasi: <b>%d / %d</b>" % (sum(1 for l in catalog.LANGS
                                                if (promo_state.get(l) or {}).get("id")),
                                             len(catalog.LANGS)),
        "", "👥 <b>Foydalanuvchilar: %d</b>" % rep["total"], "", "📣 <b>Manbalar</b>",
    ]
    for code, n in rep["sources"]:
        lines.append("• %s — <b>%d</b>" % (html.escape(SOURCES.get(code, code)), n))
    if not rep["sources"]:
        lines.append("<i>Hali reklama havolasidan kelgan yo'q.</i>")
    lines.append("• Do'st taklifi bilan — <b>%d</b> (obuna bo'lmagan: %d)"
                 % (rep["referred"], rep["attached"] - rep["referred"]))
    lines += ["", "🔗 <b>Reklama havolalari</b>"]
    for code, name in SOURCES.items():
        lines.append("%s:\n<code>%s</code>" % (html.escape(name), source_link(code)))
    await message.answer("\n".join(lines), parse_mode="HTML",
                         link_preview_options=types.LinkPreviewOptions(is_disabled=True))


@dp.message(F.via_bot)
async def inline_pick(message: types.Message):
    """Bot bilan chatda qidiruvdan film tanlanganda - filmni yuboramiz.

    Guruhda ushlamaymiz: u yerda karta do'stlarga ulashish uchun tashlangan,
    unga javoban film yuborish noqulay bo'lardi.
    """
    if not message.via_bot or (BOT_ID and message.via_bot.id != BOT_ID):
        return
    if message.chat.type != "private":
        return

    payload = movie_from_markup(message.reply_markup)
    if not payload:
        return

    user_id = message.from_user.id
    lang = await user_lang(user_id) or DEFAULT_LANG

    if await is_subscribed(user_id) is False:
        taklif = await send_html(user_id, T(lang)["subscribe"],
                                 reply_markup=check_sub_keyboard(lang))
        remember_pending(user_id, payload, taklif.message_id)
        return

    await handle_payload(message.from_user, user_id, payload)
    try:
        await bot.delete_message(message.chat.id, message.message_id)
    except Exception:
        pass          # ruxsat bo'lmasa jim o'tamiz


@dp.message(F.video, F.chat.type == "private")
async def get_video_info(message: types.Message):
    video_id = message.video.file_id
    thumb_id = message.video.thumbnail.file_id if message.video.thumbnail else "Rasm (cover) topilmadi"
    
    text = (
        f"Sening boting uchun maxsus ID'lar:\n\n"
        f"🎬 <b>Video ID:</b>\n<code>{video_id}</code>\n\n"
        f"🖼 <b>Thumbnail ID:</b>\n<code>{thumb_id}</code>"
    )
    
    await message.reply(text, parse_mode="HTML")

@dp.my_chat_member()
async def bot_status_changed(event: types.ChatMemberUpdated):
    if event.chat.type != "private":
        return
    status = event.new_chat_member.status
    if status == "kicked":
        await log_user_action(event.from_user, "blocked")


@dp.chat_member()
async def channel_status_changed(event: types.ChatMemberUpdated):
    if str(event.chat.id) != str(CHANNEL_ID):
        return
    old = event.old_chat_member.status
    new = event.new_chat_member.status
    was_in = old in ("member", "administrator", "creator")
    is_in = new in ("member", "administrator", "creator")
    # Holati o'zgargan odam - `new_chat_member.user`. `from_user` esa amalni
    # BAJARGAN kishi: admin kimnidir chiqarsa yoki qo'shsa, u admin bo'ladi va
    # hodisa adminning nomiga yozilib qolardi.
    member = event.new_chat_member.user
    if was_in and not is_in:
        await log_user_action(member, "left")
        # Nega ketganini so'raymiz (bir necha daqiqadan keyin, navbat bilan).
        await hpleave.on_left(member)
    elif is_in and not was_in:
        await log_user_action(member, "subscribed")
        # So'rovdan keyin qaytgan bo'lsa - o'lchov uchun belgilab qo'yamiz.
        await hpleave.mark_returned(member.id)

        # Kutayotgan odam bo'lsa - oqimni O'ZIMIZ davom ettiramiz.
        # "Tasdiqlash" tugmasini bosish shart emas.
        payload, prompt_id = take_pending(member.id)
        if prompt_id or payload:
            try:
                await after_subscribe(member, member.id,
                                      payload, prompt_id)
            except Exception as e:
                # Bot bilan suhbat boshlanmagan bo'lsa yozib bo'lmaydi -
                # bunda "Tasdiqlash" tugmasi zaxira yo'l bo'lib qoladi.
                logging.error("Obunadan keyin davom ettirishda xato: %s", e)
        else:
            # Kutilayotgan ish yo'q (masalan, xotira yangilangan), lekin
            # odam kimdir taklif qilgan yangi foydalanuvchi bo'lishi mumkin.
            await notify_inviter(member)


ALLOWED_ORIGIN = "https://abdoollox.github.io"
VALID_HOUSES = {"gryffindor", "slytherin", "ravenclaw", "hufflepuff"}
VALID_WOODS = {"oak", "yew", "cherry", "holly", "aspen", "walnut"}
VALID_CORES = {"phoenix", "dragon", "unicorn"}
VALID_FLEX = {"rigid", "springy", "supple", "yielding"}
# Onboarding qadamlari - asardagi yo'l tartibida. Panel voronkasi shulardan
# yig'iladi: xat -> xiyobon -> Gringotts -> hayvon -> tayoqcha -> bilet ->
# poyezd -> saralanish. Tayoqcha (wand_*), saralash boshlanishi (sort_start)
# va fakultet (house_*) allaqachon yoziladi, shuning uchun bu yerda yo'q.
ONB_STEPS = {"letter", "alley", "gringotts", "ticket", "train"}
# Uy hayvoni: xatdagi rasmiy ro'yxat (boyo'g'li, mushuk, qurbaqa) va kalamush -
# ro'yxatda yo'q, lekin asarda uchraydi (Ronning Qorasochi).
VALID_PETS = {"owl", "cat", "toad", "rat"}


def check_value(kind, value):
    """Qiymatni tekshiradi. To'g'ri bo'lsa Sheets uchun matn qaytaradi."""
    parts = value.split("_")

    if kind == "house":
        if value in VALID_HOUSES:
            return "house_" + value
        return None

    if kind == "wand":
        if len(parts) != 3:
            return None
        wood, core, flex = parts
        if wood in VALID_WOODS and core in VALID_CORES and flex in VALID_FLEX:
            return "wand_" + value
        return None

    # Saralashni boshlaganlar soni. Tugatganlar bilan nisbati kuzatiladi:
    # umrbod ogohlantirishi kiritilgandan keyin bu nisbat tushmasligi kerak.
    if kind == "sort_start":
        return "sort_start"

    # Onboarding qadami. Ilova har qadamni bir marta yuboradi (qurilmada
    # belgilab qo'yadi), takrori kelsa ham panel odam bo'yicha sanaydi.
    if kind == "onb":
        if value in ONB_STEPS:
            return "onb_" + value
        return None

    if kind == "pet":
        if value in VALID_PETS:
            return "pet_" + value
        return None

    return None


class _WebUser:
    """log_user_action uchun minimal foydalanuvchi obyekti."""
    def __init__(self, data):
        self.id = data["id"]
        name = (data.get("first_name") or "") + " " + (data.get("last_name") or "")
        self.full_name = name.strip() or "Nomsiz"
        self.username = data.get("username")


def _cors(resp):
    resp.headers["Access-Control-Allow-Origin"] = ALLOWED_ORIGIN
    # GET - /api/leaderboard uchun. initData esa URL'ga emas, maxsus
    # sarlavhaga qo'yiladi: query string nginx access log'iga tushadi va
    # foydalanuvchi ma'lumoti bilan imzo o'sha yerda qolib ketardi.
    resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = ("Content-Type, X-Telegram-Init-Data, "
                                                    "X-Dash-Token, " + TEST_HEADER)
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp


def verify_init_data(init_data):
    """Telegram imzosini tekshiradi. To'g'ri bo'lsa user dict qaytaradi."""
    if not init_data or not TOKEN:
        return None
    try:
        pairs = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
    except Exception:
        return None

    got = pairs.pop("hash", None)
    if not got:
        return None

    check = "\n".join("%s=%s" % (k, pairs[k]) for k in sorted(pairs))
    secret = hmac.new(b"WebAppData", TOKEN.encode(), hashlib.sha256).digest()
    calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
    if not hmac.compare_digest(calc, got):
        return None

    # Eskirgan sessiyalarni rad etamiz (24 soat)
    try:
        age = datetime.now().timestamp() - int(pairs.get("auth_date", 0))
        if age < -300 or age > 86400:
            return None
    except Exception:
        return None

    try:
        user = json.loads(pairs.get("user", "{}"))
    except Exception:
        return None

    if not user.get("id"):
        return None

    # Sinov o'quvchisi rejimi: imzo HAQIQIY (odam baribir o'zi), lekin
    # raqamni manfiyga almashtiramiz - server uchun bu butunlay boshqa,
    # bo'm-bo'sh odam. Faqat adminlar uchun.
    try:
        if _test_mode.get() and int(user["id"]) in ADMIN_IDS:
            user = dict(user)
            user["id"] = test_uid(user["id"])
            user["first_name"] = "Sinov o'quvchisi"
            user.pop("username", None)
    except Exception:
        pass

    return user


@web.middleware
async def test_mode_middleware(request, handler):
    """Har so'rovda sinov sarlavhasini o'qiydi (contextvar so'rovga xos)."""
    _test_mode.set(request.headers.get(TEST_HEADER, "") == "1")
    return await handler(request)


async def api_test_reset(request):
    """Sinov o'quvchisini butunlay o'chiradi - keyingi kirish yana noldan.

    Faqat admin va faqat sinov sarlavhasi bilan. Asl hisobga TEGMAYDI.
    """
    if request.method == "OPTIONS":
        return _cors(web.Response(status=204))

    init = request.headers.get("X-Telegram-Init-Data", "")
    if not init:
        try:
            body = await request.json()
        except Exception:
            body = {}
        init = str(body.get("initData", ""))

    # Bu yerda _test_mode yoqiq bo'lsa user allaqachon manfiy raqamli bo'ladi.
    user = verify_init_data(init)
    if not user:
        return _cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))

    uid = int(user["id"])
    if uid >= 0 or abs(uid) not in ADMIN_IDS:
        return _cors(web.json_response({"ok": False, "error": "not_allowed"}, status=403))

    try:
        await hpcup.test_reset(uid)
    except Exception as e:
        logging.error("Sinov hisobini tozalashda xato: %s", e)
        return _cors(web.json_response({"ok": False, "error": "baza"}, status=503))

    logging.info("Sinov o'quvchisi tozalandi: %s", uid)
    return _cors(web.json_response({"ok": True}))


async def api_loglar(request):
    """Kuzatuv paneli uchun: Logs varag'ining nusxasi (CSV).

    Kalit sarlavhada keladi, URL'da emas: query string nginx access log'iga
    tushadi va kalit o'sha yerda qolib ketardi.
    """
    if request.method == "OPTIONS":
        return _cors(web.Response(status=204))

    got = request.headers.get("X-Dash-Token", "")
    if not DASH_TOKEN or not hmac.compare_digest(got, DASH_TOKEN):
        return _cors(web.json_response({"ok": False, "error": "bad_token"}, status=403))

    text = await sheets.read_csv()
    if text is None:
        return _cors(web.json_response({"ok": False, "error": "sheets_yoq"}, status=503))

    resp = web.Response(text=text, content_type="text/csv", charset="utf-8")
    # 20 mingdan ortiq qator ~1.3 MB; siqilganda ~10 baravar kichik bo'ladi.
    resp.enable_compression()
    return _cors(resp)


async def api_sabablar(request):
    """Kuzatuv paneli: kanalni tark etganlar so'rovi (hp.db, leave_survey)."""
    if request.method == "OPTIONS":
        return _cors(web.Response(status=204))

    got = request.headers.get("X-Dash-Token", "")
    if not DASH_TOKEN or not hmac.compare_digest(got, DASH_TOKEN):
        return _cors(web.json_response({"ok": False, "error": "bad_token"}, status=403))

    try:
        rows = await asyncio.to_thread(hpleave.panel_rows, tuple(ADMIN_IDS))
    except Exception as e:
        logging.error("Sabablarni o'qishda xato: %s", e)
        return _cors(web.json_response({"ok": False, "error": "baza"}, status=503))

    resp = web.json_response({"ok": True, "rows": rows,
                              "labels": hpleave.BUTTONS["uz"]})
    resp.enable_compression()
    return _cors(resp)


async def api_kanal(request):
    """Kuzatuv paneli: kanal obunachilari Telegramning o'zidan (nazorat uchun).

    Panel sonni loglardan hisoblaydi; bu yerdagi son faqat solishtirish uchun.
    """
    if request.method == "OPTIONS":
        return _cors(web.Response(status=204))

    got = request.headers.get("X-Dash-Token", "")
    if not DASH_TOKEN or not hmac.compare_digest(got, DASH_TOKEN):
        return _cors(web.json_response({"ok": False, "error": "bad_token"}, status=403))

    son = None
    try:
        son = await hpkanal.hozir(bot, CHANNEL_ID)
    except Exception as e:
        logging.error("Kanal sonini olishda xato: %s", e)
    try:
        suratlar = await asyncio.to_thread(hpkanal.tarix)
    except Exception as e:
        logging.error("Kanal tarixini o'qishda xato: %s", e)
        suratlar = []
    return _cors(web.json_response({"ok": True, "hozir": son, "tarix": suratlar}))


async def _cup_block(user_id):
    """Kubok ma'lumotlari. Kubok ishlamasa ham profil javob bersin."""
    try:
        return await hpbot.profile_extra(user_id)
    except Exception as e:
        logging.error("Kubok ma'lumotini olishda xato: %s", e)
        return None


async def handle_house(request):
    if request.method == "OPTIONS":
        return _cors(web.Response(status=204))

    # Faqat o'qish rejimi: GET so'rov yoki qiymatsiz POST.
    # initData sarlavhada keladi - URL'ga qo'yilmaydi (access log'ga tushmasin).
    if request.method == "GET":
        user = verify_init_data(request.headers.get("X-Telegram-Init-Data", ""))
        if not user:
            return _cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
        if user.get("first_name"):
            try:
                await hpcup.touch_user(user["id"], user.get("first_name"), user.get("username"))
            except Exception:
                pass
        return _cors(web.json_response({"ok": True, "cup": await _cup_block(user["id"])}))

    try:
        body = await request.json()
    except Exception:
        return _cors(web.json_response({"ok": False, "error": "bad_json"}, status=400))

    # Eski format: {"house": "..."} — hali ishlaydi
    if body.get("house"):
        kind, value = "house", str(body.get("house", ""))
    else:
        kind, value = str(body.get("kind", "")), str(body.get("value", ""))

    # Qiymat yuborilmagan bo'lsa - bu ham o'qish so'rovi
    if not kind and not value:
        user = verify_init_data(str(body.get("initData", "")))
        if not user:
            return _cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
        if user.get("first_name"):
            try:
                await hpcup.touch_user(user["id"], user.get("first_name"), user.get("username"))
            except Exception:
                pass
        return _cors(web.json_response({"ok": True, "cup": await _cup_block(user["id"])}))

    if len(value) > 64:
        return _cors(web.json_response({"ok": False, "error": "too_long"}, status=400))

    payload = check_value(kind, value)
    if not payload:
        return _cors(web.json_response({"ok": False, "error": "bad_value"}, status=400))

    user = verify_init_data(str(body.get("initData", "")))
    if not user:
        return _cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))

    # Fakultet UMRBOD. Faqat ilova tomonda tugmani yashirish yetarli emas —
    # server ham rad etishi kerak (spetsifikatsiya 3.0, 2-bo'lim).
    if kind == "house":
        try:
            accepted = await hpcup.set_house(user["id"], value, user.get("first_name"))
        except Exception as e:
            logging.error("Fakultet yozishda xato: %s", e)
            accepted = False
        if not accepted:
            return _cors(web.json_response(
                {"ok": False, "error": "house_locked",
                 "cup": await _cup_block(user["id"])}, status=409))
        if accepted.get("changed"):
            try:
                await hpbot.welcome_join(user["id"], value)
            except Exception as e:
                logging.error("Xush kelibsiz xabarida xato: %s", e)
    else:
        if user.get("first_name"):
            try:
                await hpcup.touch_user(user["id"], user.get("first_name"), user.get("username"))
            except Exception:
                pass

    # Sinov o'quvchisi (manfiy raqam) statistikaga yozilmaydi
    try:
        if int(user["id"]) > 0:
            await log_user_action(_WebUser(user), payload)
    except Exception as e:
        logging.error("Profil yozishda xato: %s", e)
        return _cors(web.json_response({"ok": False, "error": "server"}, status=500))

    return _cors(web.json_response({"ok": True, "cup": await _cup_block(user["id"])}))


# --- CHUQUR HAVOLA GRAMMATIKASI ---
# Hamma narsa shu yerdan boshlanadi: ulashilgan karta ham, reklama manbasi
# ham `t.me/<bot>?start=<payload>` orqali keladi.
#
#     <asosiy qism>[-r<taklif qilgan id>][-s<manba kodi>]
#
# Asosiy qism: `hp3_uz` (film) yoki `watch_hp3_uz` (ulashilgan kartadan).
# `_` film ichida, `-` qo'shimchalar orasida - ular chalkashmaydi.
#
# `watch_` prefiksi kod qo'lda yozilganmi yoki kartadan bosilganmi - shuni
# ajratadi, ya'ni ulashish qancha odam keltirganini o'lchash imkonini beradi.
#
# Telegram cheklovi: payload 64 belgigacha, faqat A-Za-z0-9_- .

REF_PREFIX = "ref"
REF_SEP = "-r"
SRC_PREFIX = "src_"
WATCH_PREFIX = "watch_"
# WebApp API ishlamaganda botga havola orqali o'tadi: `web_hp3_uz`.
WEB_PREFIX = "web_"


def parse_ref(payload):
    """'ref123456' -> 123456. Boshqa payload uchun None."""
    if not payload.startswith(REF_PREFIX):
        return None
    tail = payload[len(REF_PREFIX):]
    return int(tail) if tail.isdigit() else None


def parse_payload(raw):
    """Payload'ni uch qismga ajratadi: (film, taklif qilgan id, manba)."""
    parts = (raw or "").split("-")
    body = parts[0]
    inviter = None
    source = ""

    for tail in parts[1:]:
        if tail[:1] == "r" and tail[1:].isdigit():
            inviter = int(tail[1:])
        elif tail[:1] == "s" and tail[1:]:
            source = tail[1:]

    if body.startswith(SRC_PREFIX):
        source = source or body[len(SRC_PREFIX):]
        body = ""
    else:
        ref = parse_ref(body)
        if ref is not None:
            inviter = inviter if inviter is not None else ref
            body = ""

    return body, inviter, source


# Reklama joylari. Kod havolaga yoziladi: t.me/<bot>?start=src_kanal
# Ro'yxatda yo'q kod ham yoziladi - hisobotda kodning o'zi ko'rinadi.
SOURCES = {
    "kanal":  "Garri Potter Kolleksiya kanali",
    "marvel": "Marvel Kolleksiya",
    "kino":   "Kino Kolleksiya",
}
_SOURCE_RE = re.compile(r"[a-z0-9_]{1,32}")


def clean_source(code):
    """Havoladagi manba kodi: kichik harf, faqat [a-z0-9_]. Yaroqsiz - ""."""
    code = (code or "").strip().lower()
    return code if _SOURCE_RE.fullmatch(code) else ""


def source_link(code, movie_key=None, lang=DEFAULT_LANG):
    """Reklama uchun havola. Film berilsa - to'g'ridan o'sha filmga."""
    if movie_key:
        payload = "%s%s_%s-s%s" % (WATCH_PREFIX, movie_key, lang, code)
    else:
        payload = SRC_PREFIX + code
    return "https://t.me/%s?start=%s" % (BOT_USERNAME, payload)


def ref_link(user_id):
    return "https://t.me/%s?start=%s%d" % (BOT_USERNAME, REF_PREFIX, user_id)


def film_link(movie_key, lang, sharer_id=None):
    """Ulashiladigan havola. Payload FAQAT shu yerda yig'iladi."""
    payload = "%s%s_%s" % (WATCH_PREFIX, movie_key, lang)
    if sharer_id:
        payload += "%s%d" % (REF_SEP, sharer_id)
    return "https://t.me/%s?start=%s" % (BOT_USERNAME, payload)


def film_va_til(payload):
    """`watch_hp3_uz` yoki `hp3_uz` -> ("hp3", "uz"). Tanimasa (None, None).

    `watch_` prefiksi ulashilgan kartadan kelganini bildiradi - filmni
    topishda u ahamiyatsiz, shuning uchun shu yerda olib tashlanadi.
    """
    body = (payload or "").strip()
    for prefix in (WATCH_PREFIX, WEB_PREFIX):
        if body.startswith(prefix):
            body = body[len(prefix):]
    parts = body.split("_")
    if len(parts) != 2:
        return None, None
    movie_key, lang = parts
    if movie_key not in catalog.FILMS or lang not in catalog.LANGS:
        return None, None
    return movie_key, lang


# --- 16:9 KARTA RASMLARI ---
# Ulashilgan kartada rasm matn USTIDA chiqadi (link preview). Rasmlar
# GitHub Pages da: img/wide/<id>_<til>.jpg (CatalogWebApp/tools/widegen.py).
#
# Qaysi rasm haqiqatan borligini bot o'zi tekshiradi (HEAD so'rov). Rasmi
# yo'q filmda preview o'chiriladi - aks holda Telegram matndagi birinchi
# havolani ochib, o'rniga bot kartasini chizib qo'yardi.
#
# Versiya: Telegram rasmni URL bo'yicha KESHLAYDI. Rasm yangilansa ham URL
# o'zgarmasa - eski rasm ko'rinib qolaveradi. Shuning uchun URL oxiriga
# ETag dan olingan belgi qo'shiladi (?v=...). Tekshiruv ishga tushishda va
# har 6 soatda - rasm qo'shilsa botni qayta ishga tushirish shart emas.

wide_versions = {}        # (film, til) -> versiya belgisi


def wide_path(movie_key, lang):
    return "%s/wide/%s_%s.jpg" % (IMG_URL, movie_key, lang)


def wide_url(movie_key, lang):
    versiya = wide_versions.get((movie_key, lang))
    url = wide_path(movie_key, lang)
    return "%s?v=%s" % (url, versiya) if versiya else url


WIDE_URINISH = 3          # tarmoq uzilsa har rasm uchun nechta urinish


async def refresh_wides():
    """Qaysi rasmlar borligini yangilaydi.

    Serverning GitHub bilan aloqasi beqaror - bitta so'rov yo'lda uzilishi
    mumkin (sinovda 24 tadan bittasi birinchi urinishda tushib qoldi).
    Shuning uchun:
      - har rasm uchun bir necha urinish;
      - rasm FAQAT aniq 404 bo'lsa ro'yxatdan chiqariladi. Tarmoq xatosida
        oldingi holat saqlanadi - vaqtinchalik uzilish avval topilgan
        rasmni o'chirib yubormasin.
    """
    yangi = dict(wide_versions)       # eski holatdan boshlaymiz
    vaqt = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=vaqt) as s:
        async def bitta(k, l):
            for urinish in range(WIDE_URINISH):
                try:
                    async with s.head(wide_path(k, l)) as r:
                        if r.status == 200:
                            belgi = (r.headers.get("ETag") or
                                     r.headers.get("Last-Modified") or "1")
                            yangi[(k, l)] = hashlib.md5(belgi.encode()).hexdigest()[:8]
                            return
                        if r.status == 404:
                            yangi.pop((k, l), None)      # aniq yo'q
                            return
                        # 5xx va boshqalar - qayta urinamiz
                except Exception:
                    pass
                await asyncio.sleep(1 + urinish)
            # Hech bir urinish javob bermadi - eski holat o'z joyida qoladi.
        await asyncio.gather(*(bitta(k, l) for k in catalog.FILMS
                               for l in catalog.LANGS))
    wide_versions.clear()
    wide_versions.update(yangi)
    logging.info("Karta rasmlari: %d / %d", len(yangi),
                 len(catalog.FILMS) * len(catalog.LANGS))


async def wide_watcher(interval=6 * 3600):
    while True:
        try:
            await refresh_wides()
        except Exception as e:
            logging.error("Karta rasmlarini tekshirishda xato: %s", e)
        try:
            await ensure_promo()
        except Exception as e:
            logging.error("Reklama rasmini tekshirishda xato: %s", e)
        await asyncio.sleep(interval)


def preview_options(movie_key, lang):
    if (movie_key, lang) not in wide_versions:
        return types.LinkPreviewOptions(is_disabled=True)
    return types.LinkPreviewOptions(
        # Aniq False: aiogram bu maydonga "standart qiymat" belgisini qo'yadi,
        # u esa Python'da rost deb o'qiladi va chalkashtiradi. Aniq qiymat
        # bilan Telegramga nima ketishi shubhasiz bo'ladi.
        is_disabled=False,
        url=wide_url(movie_key, lang),
        prefer_large_media=True,
        show_above_text=True,         # rasm matn USTIDA
    )


# --- REKLAMA KARTASI ("taklif") ---
# Inline'da "taklif" yozilsa (tugmalar switch_inline_query="taklif" yuboradi)
# film emas, butun kolleksiyaning rasmli kartasi chiqadi. Tugmasidagi
# havolada ulashgan odamning id si bor - referal xuddi film kartasidagidek.
#
# Nega CachedPhoto: tashqi URL bilan yuborilgan InlineQueryResultPhoto da
# Telegram caption'ni tashlab yuborishi mumkin (Marvel botida shunday
# bo'lgan). Shuning uchun rasm bir marta yopiq kanalga yuklanadi va
# file_id saqlanadi. Rasm yangilansa (ETag o'zgarsa) - qayta yuklanadi.
# Rasmlar: CatalogWebApp/img/promo_<til>.jpg (tools/promogen.py).

PROMO_QUERIES = {"taklif", "invite", "пригласить"}
PROMO_FILE = os.getenv("PROMO_FILE", "/data/promo.json")
promo_state = {}          # til -> {"etag": ..., "id": file_id}; shaxmat: "chess_<til>"


def promo_path(lang):
    return "%s/promo_%s.jpg" % (IMG_URL, lang)


def card_images():
    """(promo_state kaliti, rasm manzili): reklama va shaxmat taklifi kartalari."""
    for lang in catalog.LANGS:
        yield lang, promo_path(lang)
        yield "chess_" + lang, "%s/chess_%s.jpg" % (IMG_URL, lang)


async def load_promo():
    try:
        async with aiofiles.open(PROMO_FILE, "r", encoding="utf-8") as f:
            promo_state.update(json.loads(await f.read() or "{}"))
    except (FileNotFoundError, ValueError):
        pass


async def ensure_promo():
    """Har til uchun rasm yopiq kanalga yuklanganiga ishonch hosil qiladi."""
    changed = False
    vaqt = aiohttp.ClientTimeout(total=15)
    async with aiohttp.ClientSession(timeout=vaqt) as s:
        for lang, path in card_images():
            try:
                async with s.head(path) as r:
                    if r.status != 200:
                        continue
                    belgi = r.headers.get("ETag") or r.headers.get("Last-Modified") or "1"
            except Exception:
                continue            # tarmoq uzildi - eski file_id qolaveradi
            etag = hashlib.md5(belgi.encode()).hexdigest()[:8]
            joriy = promo_state.get(lang) or {}
            if joriy.get("id") and joriy.get("etag") == etag:
                continue
            try:
                msg = await bot.send_photo(DB_CHANNEL_ID,
                                           "%s?v=%s" % (path, etag),
                                           disable_notification=True)
                promo_state[lang] = {"etag": etag, "id": msg.photo[-1].file_id}
                changed = True
                logging.info("Reklama rasmi yuklandi: %s", lang)
            except Exception as e:
                logging.error("Reklama rasmini yuklashda xato (%s): %s", lang, e)
    if changed:
        try:
            async with aiofiles.open(PROMO_FILE, "w", encoding="utf-8") as f:
                await f.write(json.dumps(promo_state, ensure_ascii=False))
        except Exception as e:
            logging.error("promo.json ga yozishda xato: %s", e)


def promo_caption(lang, inviter_name=None):
    t = T(lang)
    p = t["promo"]
    films = len(catalog.FILMS)
    lines = [
        '%s <b>%s</b>' % (emoji.tag("kolleksiya"), t["brand"]),
        "— — — — — — — — — —",
        "%s %s" % (emoji.tag("tomosha"), p[0] % films),
        "%s %s" % (emoji.tag("til"), p[1]),
        "%s %s" % (emoji.tag("sifat"), p[2]),
    ]
    if inviter_name:
        lines += ["", "%s %s" % (emoji.tag("dostlar"), p[3] % html.escape(inviter_name))]
    lines += ["", p[4]]
    return "\n".join(lines)


def promo_keyboard(lang, sharer_id):
    return InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(
        text=T(lang)["btn_open"], url=ref_link(sharer_id),
        icon_custom_emoji_id=emoji.icon("kolleksiya"))]])


async def answer_promo(query, lang):
    t = T(lang)
    cap = promo_caption(lang, query.from_user.first_name)
    kb = promo_keyboard(lang, query.from_user.id)
    file_id = (promo_state.get(lang) or {}).get("id")
    if file_id:
        card = types.InlineQueryResultCachedPhoto(
            id="promo", photo_file_id=file_id, title=t["promo_title"],
            description=t["promo_desc"], caption=cap, parse_mode="HTML",
            reply_markup=kb)
    else:
        # Zaxira: rasm hali kanalga yuklanmagan bo'lsa - tashqi manzil
        card = types.InlineQueryResultPhoto(
            id="promo", photo_url=promo_path(lang), thumbnail_url=promo_path(lang),
            photo_width=1280, photo_height=720, title=t["promo_title"],
            description=t["promo_desc"], caption=cap, parse_mode="HTML",
            reply_markup=kb)
    try:
        await query.answer([card], cache_time=0, is_personal=True)
    except Exception as e:
        logging.error("Reklama kartasida xato: %s", e)


# --- SHAXMAT TAKLIF KARTASI ---
# Ilovada "Do'stni jangga chaqirish" bosilganda do'stga rasmli karta boradi:
# kim chaqiryapti, vaqt, ball va o'yinni ochadigan tugma. Ikki yo'l bor:
#   1) tayyor karta (savePreparedInlineMessage + WebApp.shareMessage, Bot API
#      8.0) - Telegram darhol chat tanlatadi, karta o'zi jo'natiladi;
#   2) eski mijozlarda - inline "chess_<kod>" (film kartasi kabi).
# Tugma o'yinni to'g'ridan-to'g'ri ochadi (t.me/<bot>/catalog?startapp=...).
# Rasm: CatalogWebApp/img/chess_<til>.jpg (tools/chessgen.py).

CHESS_QUERY = re.compile(r"^chess_([0-9a-f]{8})$")
CHESS_T = {
    "uz": {"title": "Sehrgar shaxmati", "call": "<b>%s</b> sizni jangga chaqirmoqda!",
           "time": "Vaqt: %s", "min": "%d daqiqa", "plus": " + %d soniya",
           "pts": "G'alaba — fakultetingizga +%d ball",
           "tap": "Pastdagi tugmani bosing — o'yin darhol ochiladi.",
           "code": "Kod", "btn": "O'yinga kirish", "desc": "Do'stingizni shaxmat jangiga chaqiring"},
    "ru": {"title": "Волшебные шахматы", "call": "<b>%s</b> вызывает вас на поединок!",
           "time": "Время: %s", "min": "%d мин", "plus": " + %d сек",
           "pts": "Победа — +%d очков вашему факультету",
           "tap": "Нажмите кнопку ниже — игра откроется сразу.",
           "code": "Код", "btn": "Войти в игру", "desc": "Вызовите друга на шахматный поединок"},
    "en": {"title": "Wizard's chess", "call": "<b>%s</b> challenges you to a duel!",
           "time": "Time: %s", "min": "%d min", "plus": " + %d sec",
           "pts": "Win — +%d points for your house",
           "tap": "Tap the button below — the game opens right away.",
           "code": "Code", "btn": "Join the game", "desc": "Challenge your friend to a chess duel"},
}


def chess_link(code):
    return "https://t.me/%s/catalog?startapp=chess_%s" % (BOT_USERNAME, code)


def chess_caption(lang, info):
    c = CHESS_T.get(lang, CHESS_T[DEFAULT_LANG])
    vaqt = c["min"] % (info["base"] // 60) + (c["plus"] % info["inc"] if info["inc"] else "")
    return "\n".join([
        "♟️ <b>%s</b>" % c["title"],
        "— — — — — — — — — —",
        "%s %s" % (emoji.tag("dostlar"), c["call"] % html.escape(info["name"] or "")),
        "%s %s" % (emoji.tag("vaqt"), c["time"] % vaqt),
        "%s %s" % (emoji.tag("yulduz"), c["pts"] % hpcup.PTS_CHESS_WIN),
        "",
        c["tap"],
        "%s: <code>%s</code>" % (c["code"], info["id"]),
    ])


def chess_button(lang, code):
    c = CHESS_T.get(lang, CHESS_T[DEFAULT_LANG])
    return InlineKeyboardButton(text=c["btn"], url=chess_link(code),
                                icon_custom_emoji_id=emoji.icon("tomosha"))


async def chess_lang(user_id, lang):
    if lang in catalog.LANGS:
        return lang
    return await user_lang(user_id) or DEFAULT_LANG


async def answer_chess(query, lang, code):
    info = await hpchess.brief(code)
    if not info or info["status"] != "waiting":
        # Boshlangan / tugagan o'yinga taklif yuborishning ma'nosi yo'q.
        await query.answer([], cache_time=0, is_personal=True)
        return
    c = CHESS_T.get(lang, CHESS_T[DEFAULT_LANG])
    cap = chess_caption(lang, info)
    kb = InlineKeyboardMarkup(inline_keyboard=[[chess_button(lang, code)]])
    file_id = (promo_state.get("chess_" + lang) or {}).get("id")
    if file_id:
        card = types.InlineQueryResultCachedPhoto(
            id="chess_" + code, photo_file_id=file_id, title=c["title"],
            description=c["desc"], caption=cap, parse_mode="HTML", reply_markup=kb)
    else:
        url = "%s/chess_%s.jpg" % (IMG_URL, lang)
        card = types.InlineQueryResultPhoto(
            id="chess_" + code, photo_url=url, thumbnail_url=url,
            photo_width=1280, photo_height=720, title=c["title"],
            description=c["desc"], caption=cap, parse_mode="HTML", reply_markup=kb)
    try:
        await query.answer([card], cache_time=0, is_personal=True)
    except Exception as e:
        logging.error("Shaxmat kartasida xato: %s", e)


async def prepare_chess_share(user_id, code, lang, info):
    """Tayyor karta id si (WebApp.shareMessage uchun). aiogram 3.4 bu usulni
    bilmaydi - Bot API ga to'g'ridan-to'g'ri murojaat qilinadi."""
    lang = await chess_lang(user_id, lang)
    c = CHESS_T.get(lang, CHESS_T[DEFAULT_LANG])
    result = {
        "type": "photo", "id": "chess_" + code,
        "caption": chess_caption(lang, info), "parse_mode": "HTML",
        "reply_markup": {"inline_keyboard": [[{
            "text": c["btn"], "url": chess_link(code),
            "icon_custom_emoji_id": emoji.icon("tomosha")}]]},
    }
    file_id = (promo_state.get("chess_" + lang) or {}).get("id")
    if file_id:
        result["photo_file_id"] = file_id
    else:
        url = "%s/chess_%s.jpg" % (IMG_URL, lang)
        result.update(photo_url=url, thumbnail_url=url, photo_width=1280, photo_height=720)
    if not result["reply_markup"]["inline_keyboard"][0][0]["icon_custom_emoji_id"]:
        del result["reply_markup"]["inline_keyboard"][0][0]["icon_custom_emoji_id"]
    payload = {"user_id": int(user_id), "result": result,
               "allow_user_chats": True, "allow_group_chats": True}
    vaqt = aiohttp.ClientTimeout(total=10)
    async with aiohttp.ClientSession(timeout=vaqt) as s:
        async with s.post("https://api.telegram.org/bot%s/savePreparedInlineMessage" % TOKEN,
                          json=payload) as r:
            data = await r.json()
    if not data.get("ok"):
        logging.error("savePreparedInlineMessage: %s", data.get("description"))
        return None
    return data["result"]["id"]


def sq_url(movie_key, lang):
    """Inline ro'yxatdagi kvadrat ikonka (tools/sqgen.py yasaydi)."""
    return "%s/sq/%s_%s.jpg" % (IMG_URL, movie_key, lang)


# --- ILOVADAN TO'G'RIDAN-TO'G'RI YUBORISH ---
# Ilgari WebApp filmni chuqur havola orqali ochardi: ilova YOPILIB, bot
# chatiga o'tilardi. Natijada foydalanuvchi kubok, chat va shaxmatdan uzilib
# qolardi va qaytish uchun ilovani boshqatdan ochishi kerak edi.
#
# Endi film shu API orqali yuboriladi - ilova ochiq qoladi. Tasdiq oynasi
# o'rniga "bekor qilish" ishlatiladi: to'g'ri bosgan odam to'siqni sezmaydi,
# xato bosgan esa 2 daqiqa ichida qaytarib oladi.

UNDO_WINDOW = 120        # soniya - shu muddat ichida bekor qilinadi
UNDO_LIMIT = 500         # xotirada saqlanadigan eng ko'p yozuv

# (user_id, message_id) -> (vaqt, film_id, til). Xotirada, chunki bu
# ma'lumot 2 daqiqadan keyin keraksiz - baza bilan band qilish ortiqcha.
recent_sends = {}


def remember_send(user_id, message_id, movie_key, lang):
    if len(recent_sends) >= UNDO_LIMIT:
        eng_eski = min(recent_sends, key=lambda k: recent_sends[k][0])
        recent_sends.pop(eng_eski, None)
    recent_sends[(user_id, message_id)] = (time.time(), movie_key, lang)


def take_send(user_id, message_id):
    """Bekor qilish mumkinmi - tekshiradi va ro'yxatdan chiqaradi."""
    item = recent_sends.pop((user_id, message_id), None)
    if not item:
        return None
    qachon, movie_key, lang = item
    if time.time() - qachon > UNDO_WINDOW:
        return None
    return movie_key, lang


async def api_send(request):
    """WebApp so'ragan filmni foydalanuvchiga yuboradi."""
    if request.method == "OPTIONS":
        return _cors(web.Response(status=204))
    if request.method != "POST":
        return _cors(web.json_response({"ok": False, "error": "method"}, status=405))

    try:
        body = await request.json()
    except Exception:
        return _cors(web.json_response({"ok": False, "error": "bad_json"}, status=400))

    data = verify_init_data(request.headers.get("X-Telegram-Init-Data", "")
                            or str(body.get("initData", "")))
    if not data:
        return _cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))

    user = _WebUser(data)
    movie_key = str(body.get("movie_id", ""))
    lang = str(body.get("lang", "uz"))

    movie_data = catalog.get(movie_key, lang)
    if not movie_data:
        return _cors(web.json_response({"ok": False, "error": "unknown"}, status=404))

    # Bu tilda hali yuklanmagan. WebApp bunday kartani kulrang qilib
    # ko'rsatadi, lekin eski ilova qolib ketishi mumkin - server ham tekshiradi.
    if not catalog.is_ready(movie_key, lang):
        return _cors(web.json_response({"ok": False, "error": "not_ready"}))

    if await is_subscribed(tg_chat_id(user.id)) is False:
        # WebApp buni ko'rib, foydalanuvchini botga yo'naltiradi
        return _cors(web.json_response({"ok": False, "error": "not_subscribed"}))

    vk_url = movie_data.get("vk_url") if lang == "uz" else None
    try:
        sent = await send_film(tg_chat_id(user.id), movie_key, lang, vk_url)
    except Exception as e:
        # Eng ko'p uchraydigani: foydalanuvchi botni hech qachon ochmagan,
        # shuning uchun bot unga yoza olmaydi.
        logging.error("API orqali yuborishda xato (%s): %s", movie_key, e)
        return _cors(web.json_response({"ok": False, "error": "send_failed"}))

    # Sinov o'quvchisining harakati statistikaga yozilmaydi
    if user.id > 0:
        await log_user_action(user, "%s_%s" % (movie_key, lang), "web_%s_%s" % (movie_key, lang))
    remember_send(user.id, sent.message_id, movie_key, lang)

    # Xogvarts kubogi: kino ochilgani uchun ball. Film allaqachon yuborilgan,
    # shuning uchun bu yerdagi xato foydalanuvchiga ta'sir qilmasligi kerak.
    try:
        await hpcup.touch_user(user.id, data.get("first_name"), data.get("username"))
        if movie_key.startswith("hp"):
            await hpbot.award_film_open(user, int(movie_key[2:]))
    except Exception as cup_error:
        logging.error("Kubok qismida xato: %s", cup_error)

    return _cors(web.json_response({"ok": True,
                                    "title": movie_data["title"],
                                    "message_id": sent.message_id}))


async def api_undo(request):
    """Yangi yuborilgan filmni chatdan o'chiradi (xato bosganlar uchun)."""
    if request.method == "OPTIONS":
        return _cors(web.Response(status=204))
    if request.method != "POST":
        return _cors(web.json_response({"ok": False, "error": "method"}, status=405))

    try:
        body = await request.json()
    except Exception:
        return _cors(web.json_response({"ok": False, "error": "bad_json"}, status=400))

    data = verify_init_data(request.headers.get("X-Telegram-Init-Data", "")
                            or str(body.get("initData", "")))
    if not data:
        return _cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))

    user = _WebUser(data)
    try:
        message_id = int(body.get("message_id", 0))
    except (TypeError, ValueError):
        message_id = 0

    # Ro'yxatda yo'q bo'lsa: muhlati o'tgan yoki bu xabar bu odamniki emas.
    topildi = take_send(user.id, message_id)
    if not topildi:
        return _cors(web.json_response({"ok": False, "error": "expired"}))

    movie_key, lang = topildi
    try:
        await bot.delete_message(tg_chat_id(user.id), message_id)
    except Exception as e:
        logging.info("Bekor qilishda o'chirib bo'lmadi (%s): %s", movie_key, e)
        return _cors(web.json_response({"ok": False, "error": "delete_failed"}))

    if user.id > 0:
        await log_user_action(user, "bekor_%s" % movie_key)
    logging.info("Bekor qilindi: %s -> %s", user.id, movie_key)
    return _cors(web.json_response({"ok": True, "movie_id": movie_key}))


# --- XOGVARTSDAN MAKTUB RASMI ---
# Ilovadagi "Xatni ulashish" shu yerga keladi. Rasm ismga qarab yasaladi va
# ochiq manzilda turadi (Telegram Stories faqat ochiq URL ni oladi), lekin
# manzilda ism emas, tasodifiy token bo'ladi.
PUBLIC_BASE = "https://bot.tizimshunos.uz"
_xat_vaqt = {}          # {uid: oxirgi so'rov} - daqiqada bir necha marta bosilmasin


async def prepare_xat_share(user_id, lang, url):
    """Chatga ulashish uchun tayyor xabar (shaxmat kartasi bilan bir xil usul)."""
    matn = {"uz": "Menga Xogvartsdan maktub keldi!",
            "ru": "Мне пришло письмо из Хогвартса!",
            "en": "My Hogwarts letter has arrived!"}.get(lang, "Xogvartsdan maktub")
    tugma = {"uz": "Menga ham maktub kelsin",
             "ru": "Хочу своё письмо",
             "en": "Get my own letter"}.get(lang, "Xogvartsga kirish")
    result = {
        "type": "photo", "id": "xat_%s" % int(time.time()),
        "caption": matn,
        "photo_url": url, "thumbnail_url": url,
        "photo_width": 1080, "photo_height": 1920,
        "reply_markup": {"inline_keyboard": [[{
            "text": tugma,
            "url": "https://t.me/%s/catalog?startapp=olam" % BOT_USERNAME}]]},
    }
    payload = {"user_id": int(user_id), "result": result,
               "allow_user_chats": True, "allow_group_chats": True}
    vaqt = aiohttp.ClientTimeout(total=10)
    try:
        async with aiohttp.ClientSession(timeout=vaqt) as s:
            async with s.post(
                    "https://api.telegram.org/bot%s/savePreparedInlineMessage" % TOKEN,
                    json=payload) as r:
                data = await r.json()
        if data.get("ok"):
            return data["result"]["id"]
        logging.error("Xat uchun savePreparedInlineMessage: %s", data.get("description"))
    except Exception as e:
        logging.error("Xat xabarini tayyorlashda xato: %s", e)
    return None


async def api_xat(request):
    """Xat rasmini yasaydi va manzilini qaytaradi."""
    if request.method == "OPTIONS":
        return _cors(web.Response(status=204))
    if request.method != "POST":
        return _cors(web.json_response({"ok": False, "error": "method"}, status=405))
    if not hpxat:
        return _cors(web.json_response({"ok": False, "error": "yoq"}, status=503))

    try:
        body = await request.json()
    except Exception:
        body = {}

    user = verify_init_data(request.headers.get("X-Telegram-Init-Data", "")
                            or str(body.get("initData", "")))
    if not user:
        return _cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))

    uid = int(user["id"])
    hozir = time.time()
    if hozir - _xat_vaqt.get(uid, 0) < 3:
        return _cors(web.json_response({"ok": False, "error": "tez"}, status=429))
    _xat_vaqt[uid] = hozir

    lang = str(body.get("lang", "uz"))
    try:
        token = await asyncio.to_thread(hpxat.ensure, uid, user.get("first_name"), lang)
    except Exception as e:
        logging.error("Xat rasmini yasashda xato: %s", e)
        return _cors(web.json_response({"ok": False, "error": "server"}, status=500))

    url = "%s/api/xat/%s.jpg" % (PUBLIC_BASE, token)
    share_id = None
    if uid > 0:          # sinov o'quvchisiga Telegram xabari tayyorlanmaydi
        share_id = await prepare_xat_share(uid, lang, url)
    return _cors(web.json_response({"ok": True, "url": url, "share_id": share_id}))


async def api_xat_file(request):
    """Yasalgan rasmni beradi (token bilan, ismsiz)."""
    if not hpxat:
        return web.Response(status=404, text="yoq")
    token = request.match_info.get("token", "")
    if not re.fullmatch(r"[0-9a-f]{20}", token):
        return web.Response(status=404, text="yoq")
    yol = hpxat.path_of(token)
    if not os.path.exists(yol):
        return web.Response(status=404, text="yoq")
    return web.FileResponse(yol, headers={"Cache-Control": "public, max-age=604800",
                                          "Access-Control-Allow-Origin": "*"})


# --- GRINGOTTS HAMYONI VA XIYOBONDAGI XARIDLAR ---
# Onboarding qadamlari shu yerdan o'tadi: xona ochish (pul), uy hayvoni,
# tayoqcha, bilet. Har qadam logga ham yoziladi (panel voronkasi uchun).
_wallet_vaqt = {}


async def api_wallet(request):
    if request.method == "OPTIONS":
        return _cors(web.Response(status=204))
    if request.method != "POST":
        return _cors(web.json_response({"ok": False, "error": "method"}, status=405))

    try:
        body = await request.json()
    except Exception:
        body = {}

    user = verify_init_data(request.headers.get("X-Telegram-Init-Data", "")
                            or str(body.get("initData", "")))
    if not user:
        return _cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))

    uid = int(user["id"])
    amal = str(body.get("action", "get"))

    if amal != "get":
        hozir = time.time()
        if hozir - _wallet_vaqt.get(uid, 0) < 1:
            return _cors(web.json_response({"ok": False, "error": "tez"}, status=429))
        _wallet_vaqt[uid] = hozir

    try:
        if user.get("first_name"):
            await hpcup.touch_user(uid, user.get("first_name"), user.get("username"))

        if amal == "get":
            return _cors(web.json_response({"ok": True, "wallet": await hpcup.wallet(uid)}))

        if amal == "vault":
            holat, yangi = await hpcup.open_vault(uid)
            if yangi and uid > 0:
                await log_user_action(_WebUser(user), "onb_gringotts")
            return _cors(web.json_response({"ok": True, "wallet": holat, "new": yangi}))

        if amal == "buy":
            item = str(body.get("item", ""))
            holat, xato = await hpcup.buy(uid, item)
            if not xato and uid > 0 and item in hpcup.PET_PRICES:
                await log_user_action(_WebUser(user), "pet_" + item)
            return _cors(web.json_response({"ok": not xato, "error": xato, "wallet": holat}))

        if amal == "ticket":
            holat, xato = await hpcup.give_ticket(uid)
            if not xato and uid > 0:
                await log_user_action(_WebUser(user), "onb_ticket")
            return _cors(web.json_response({"ok": not xato, "error": xato, "wallet": holat}))
    except Exception as e:
        logging.error("Hamyon amalida xato (%s): %s", amal, e)
        return _cors(web.json_response({"ok": False, "error": "server"}, status=500))

    return _cors(web.json_response({"ok": False, "error": "amal"}, status=400))


async def handle(request):
    return web.Response(text="Bot is alive!")

async def main():
    logging.info("Bot va Server ishga tushmoqda...")
    app = web.Application(middlewares=[test_mode_middleware])
    app.router.add_get('/', handle)
    app.router.add_route('*', '/api/house', handle_house)
    app.router.add_route('*', '/api/profile', handle_house)
    app.router.add_route('*', '/api/send', api_send)
    app.router.add_route('*', '/api/undo', api_undo)
    app.router.add_route('*', '/api/loglar', api_loglar)
    app.router.add_route('*', '/api/sabablar', api_sabablar)
    app.router.add_route('*', '/api/kanal', api_kanal)
    app.router.add_route('*', '/api/test/reset', api_test_reset)
    app.router.add_route('*', '/api/xat', api_xat)
    app.router.add_route('*', '/api/wallet', api_wallet)
    app.router.add_get('/api/xat/{token}.jpg', api_xat_file)

    # --- Xogvarts kubogi ---
    # Baza va handlerlar. Kubok ishlamay qolsa ham bot ishlashda davom etsin -
    # kino tarqatish asosiy vazifa, musobaqa ustiga qo'shimcha.
    try:
        # users_db.json - 1.0 dagi fakultetlarni ko'chirish uchun manba
        await hpcup.init(USERS_FILE)
        hpbot.register(dp, bot, app, {
            "channel_id": CHANNEL_ID,
            "verify_init_data": verify_init_data,
            "cors": _cors,
            "admin_ids": ADMIN_IDS,
            "chess_share": prepare_chess_share,
        })
        asyncio.create_task(hpbot.season_watcher(bot))
    except Exception as cup_error:
        logging.error("Xogvarts kubogi ishga tushmadi: %s", cup_error)

    # --- Soundtrack kutubxonasi ---
    # Alohida try: musiqa ishlamasa ham filmlar tarqatilaversin. hpleave dan
    # OLDIN turishi shart: u guruhdagi "#hp1" kabi matnni ham ushlab qolardi.
    try:
        async def _music_log(user, payload):
            await log_user_action(_WebUser(user), payload)
        hpmusic.register(dp, bot, app, {
            "token": TOKEN,
            "admin_ids": ADMIN_IDS,
            "verify_init_data": verify_init_data,
            "cors": _cors,
            "is_subscribed": is_subscribed,
            "tg_chat_id": tg_chat_id,
            "log": _music_log,
        })
    except Exception as music_error:
        logging.error("Soundtrack ishga tushmadi: %s", music_error)

    # --- Chiqib ketish so'rovi ---
    # Alohida try: bu ishlamay qolsa ham bot kino tarqatishda davom etsin.
    # hpleave handlerlari ENG OXIRIDA ro'yxatdan o'tadi - ularning ichida
    # matnni ushlaydigan handler bor, u boshqalardan oldin turmasligi kerak.
    try:
        await hpleave.init()
        hpleave.register(dp, bot, {
            "is_subscribed": is_subscribed,
            "user_lang": user_lang,
            "channel_url": CHANNEL_URL,
            "admin_ids": ADMIN_IDS,
        })
    except Exception as leave_error:
        logging.error("Chiqish so'rovi ishga tushmadi: %s", leave_error)

    # Karta rasmlari kubokka bog'liq emas - u ishlamasa ham ishga tushsin.
    await load_promo()
    asyncio.create_task(wide_watcher())
    # Kanal soni - loglar to'g'ri tushayotganini tekshirish uchun
    asyncio.create_task(hpkanal.kuzatuvchi(bot, CHANNEL_ID))
    # Panel keshini oldindan to'ldiramiz: birinchi so'rov 15 soniya kutmasin.
    if DASH_TOKEN:
        asyncio.create_task(sheets.read_csv())

    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info("Veb-server ishga tushdi.")
    
    # Bot o'z inline kartasini boshqa botnikidan ajratishi uchun kerak.
    global BOT_ID
    try:
        BOT_ID = (await bot.me()).id
        logging.info("Bot id: %s", BOT_ID)
    except Exception as e:
        logging.error("Bot id sini olishda xato: %s", e)

    try:
        await bot.delete_webhook(drop_pending_updates=True) 
        await dp.start_polling(
            bot,
            # inline_query SHART: ro'yxatda bo'lmasa Telegram bu update'ni
            # umuman yubormaydi va qidiruv jimgina ishlamaydi. chat_member
            # ham xuddi shunday - sukut bo'yicha yuborilmaydi.
            allowed_updates=["message", "callback_query", "my_chat_member",
                             "chat_member", "inline_query",
                             "chosen_inline_result"])
    except Exception as e:
        logging.error(f"BOT KRITIK XATOGA UCHRADI: {e}")
        raise e

if __name__ == "__main__":
    asyncio.run(main())






