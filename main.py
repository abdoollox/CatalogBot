import os
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
import aiofiles
import urllib.parse
import hmac
import hashlib
import sheets
import catalog
import emoji
import hpcup
import hpbot
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiohttp import web
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.exceptions import TelegramBadRequest

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003826689337"))
CHANNEL_URL = "https://t.me/garripotter_kolleksiya"
WEBAPP_URL = "https://abdoollox.github.io/CatalogWebApp/"
DB_CHANNEL_ID = -1003641399832

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
async def log_user_action(user: types.User, payload: str):
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

    await sheets.append_click(user.id, db[user_id]["nickname"], db[user_id]["username"], payload, now)


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
        "collection_btn": "Filmlar kolleksiyasi",
        "share_btn": "Do'stlarga ulashish",
        "share_text": "🎬 Menga bu filmlar kolleksiyasi yoqdi. Siz ham foydalanib ko'ring!"
    },
    "ru": {
        "collection_btn": "Коллекция фильмов",
        "share_btn": "Поделиться с друзьями",
        "share_text": "🎬 Мне понравилась эта коллекция фильмов. Попробуйте и вы!"
    },
    "en": {
        "collection_btn": "Movie Collection",
        "share_btn": "Share with friends",
        "share_text": "🎬 I really liked this movie collection. Check it out!"
    }
}

def movie_delivery_keyboard(lang: str = "uz", vk_url: str = None):
    loc = LOCALES.get(lang, LOCALES["uz"])
    builder = InlineKeyboardBuilder()
    
    # --- 1-QATOR: 4K Formatda ko'rish (faqat havola mavjud bo'lsa) ---
    if vk_url:
        builder.row(
            InlineKeyboardButton(
                text="4K formatda ko'rish",
                url=vk_url,
                icon_custom_emoji_id=emoji.icon("sifat")
            )
        )
    
    # 1. Ulashish matni va havolasi
    share_text = loc["share_text"]
    share_url = "https://t.me/garripotterkinobot/catalog"
    
    # 2. URL Encoding
    safe_text = urllib.parse.quote(share_text)
    safe_url = urllib.parse.quote(share_url)
    final_share_link = f"https://t.me/share/url?url={safe_url}&text={safe_text}"
    
    # --- 2-QATOR: Kolleksiya WebApp ---
    builder.row(
        InlineKeyboardButton(
            text=loc["collection_btn"],
            web_app=WebAppInfo(url=webapp_url(lang)),
            icon_custom_emoji_id=emoji.icon("kolleksiya")
        )
    )
    
    # --- 3-QATOR: Do'stlarga ulashish ---
    builder.row(
        InlineKeyboardButton(
            text=loc["share_btn"],
            url=final_share_link,
            icon_custom_emoji_id=emoji.icon("dostlar")
        )
    )
    
    return builder.as_markup()
    

async def is_subscribed(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logging.error(f"Kanalga a'zolikni tekshirishda xato: {e}")
        return False

@dp.message(CommandStart())    
async def start_cmd(message: types.Message, command: CommandObject):
    try:
        await message.delete()
    except Exception:
        pass 
        
    payload = command.args
    user_id = message.from_user.id

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
    
    lang = await user_lang(user_id)

    # Chuqur havolada til allaqachon bor (masalan `hp1_uz`) - so'ramaymiz,
    # aksincha o'shani eslab qolamiz.
    if payload and "_" in payload:
        havola_tili = payload.strip().split("_")[-1]
        if havola_tili in catalog.LANGS:
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
    if not await is_subscribed(user.id):
        taklif = await send_html(chat_id, T(lang)["subscribe"],
                                 reply_markup=check_sub_keyboard(lang))
        # Nima uchun kelganini eslab qolamiz: a'zo bo'lgan zahoti davom etamiz.
        remember_pending(user.id, payload, taklif.message_id)
        return

    if payload:
        await handle_payload(user, chat_id, payload)
    else:
        await send_welcome(chat_id, lang)


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
        payload_clean = payload.strip()
        parts = payload_clean.split('_')

        if len(parts) != 2:
            await bot.send_message(chat_id, f"⚠️ DIAGNOSTIKA (ValueError): Signal ikkiga bo'linmadi.\nSiz yuborgan aniq signal: '{payload}'\nUzunligi: {len(payload)} ta belgi.")
            return

        movie_key, lang = parts

        if movie_key not in MOVIES_DB:
            await bot.send_message(chat_id, f"⚠️ DIAGNOSTIKA (KeyError - Kino): '{movie_key}' bazada topilmadi.\nBazadagi mavjud kinolar: {list(MOVIES_DB.keys())}")
            return

        if lang not in catalog.LANGS:
            await bot.send_message(chat_id, f"⚠️ DIAGNOSTIKA (KeyError - Til): '{movie_key}' kinoda '{lang}' tili topilmadi.\nMavjud tillar: {list(catalog.LANGS)}")
            return

        movie_data = MOVIES_DB[movie_key][lang]

        if movie_data.get("message_id", 0) == 0:
            await bot.send_message(chat_id, T(lang)["soon"])
            return

        # Xavfsiz tizim: Mijoz harakatini qayd etish
        await log_user_action(user, payload_clean)

        vk_url = movie_data.get("vk_url") if lang == "uz" else None

        await bot.copy_message(
            chat_id=chat_id,
            from_chat_id=DB_CHANNEL_ID,
            message_id=movie_data["message_id"],
            caption=movie_data["caption"],
            parse_mode="HTML",
            reply_markup=movie_delivery_keyboard(lang, vk_url),
            protect_content=True
        )

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
        return

    await send_welcome(chat_id, lang)


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
    if not await is_subscribed(callback.from_user.id):
        await callback.answer(T(lang)["not_subscribed"], show_alert=True)
        return

    payload, _ = take_pending(callback.from_user.id)
    await callback.answer()
    await after_subscribe(callback.from_user, callback.from_user.id, payload,
                          callback.message.message_id)

@dp.message(F.video)
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
    if was_in and not is_in:
        await log_user_action(event.from_user, "left")
    elif is_in and not was_in:
        await log_user_action(event.from_user, "subscribed")

        # Kutayotgan odam bo'lsa - oqimni O'ZIMIZ davom ettiramiz.
        # "Tasdiqlash" tugmasini bosish shart emas.
        payload, prompt_id = take_pending(event.from_user.id)
        if prompt_id or payload:
            try:
                await after_subscribe(event.from_user, event.from_user.id,
                                      payload, prompt_id)
            except Exception as e:
                # Bot bilan suhbat boshlanmagan bo'lsa yozib bo'lmaydi -
                # bunda "Tasdiqlash" tugmasi zaxira yo'l bo'lib qoladi.
                logging.error("Obunadan keyin davom ettirishda xato: %s", e)


ALLOWED_ORIGIN = "https://abdoollox.github.io"
VALID_HOUSES = {"gryffindor", "slytherin", "ravenclaw", "hufflepuff"}
VALID_WOODS = {"oak", "yew", "cherry", "holly", "aspen", "walnut"}
VALID_CORES = {"phoenix", "dragon", "unicorn"}
VALID_FLEX = {"rigid", "springy", "supple", "yielding"}


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
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
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

    return user if user.get("id") else None


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
    else:
        if user.get("first_name"):
            try:
                await hpcup.touch_user(user["id"], user.get("first_name"), user.get("username"))
            except Exception:
                pass

    try:
        await log_user_action(_WebUser(user), payload)
    except Exception as e:
        logging.error("Profil yozishda xato: %s", e)
        return _cors(web.json_response({"ok": False, "error": "server"}, status=500))

    return _cors(web.json_response({"ok": True, "cup": await _cup_block(user["id"])}))


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

    if not await is_subscribed(user.id):
        # WebApp buni ko'rib, foydalanuvchini botga yo'naltiradi
        return _cors(web.json_response({"ok": False, "error": "not_subscribed"}))

    vk_url = movie_data.get("vk_url") if lang == "uz" else None
    try:
        sent = await bot.copy_message(
            chat_id=user.id,
            from_chat_id=DB_CHANNEL_ID,
            message_id=movie_data["message_id"],
            caption=movie_data["caption"],
            parse_mode="HTML",
            reply_markup=movie_delivery_keyboard(lang, vk_url),
            protect_content=True,
        )
    except Exception as e:
        # Eng ko'p uchraydigani: foydalanuvchi botni hech qachon ochmagan,
        # shuning uchun bot unga yoza olmaydi.
        logging.error("API orqali yuborishda xato (%s): %s", movie_key, e)
        return _cors(web.json_response({"ok": False, "error": "send_failed"}))

    await log_user_action(user, "%s_%s" % (movie_key, lang))
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
        await bot.delete_message(user.id, message_id)
    except Exception as e:
        logging.info("Bekor qilishda o'chirib bo'lmadi (%s): %s", movie_key, e)
        return _cors(web.json_response({"ok": False, "error": "delete_failed"}))

    await log_user_action(user, "bekor_%s" % movie_key)
    logging.info("Bekor qilindi: %s -> %s", user.id, movie_key)
    return _cors(web.json_response({"ok": True, "movie_id": movie_key}))


async def handle(request):
    return web.Response(text="Bot is alive!")

async def main():
    logging.info("Bot va Server ishga tushmoqda...")
    app = web.Application()
    app.router.add_get('/', handle)
    app.router.add_route('*', '/api/house', handle_house)
    app.router.add_route('*', '/api/profile', handle_house)
    app.router.add_route('*', '/api/send', api_send)
    app.router.add_route('*', '/api/undo', api_undo)

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
        })
        asyncio.create_task(hpbot.season_watcher(bot))
    except Exception as cup_error:
        logging.error("Xogvarts kubogi ishga tushmadi: %s", cup_error)

    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info("Veb-server ishga tushdi.")
    
    try:
        await bot.delete_webhook(drop_pending_updates=True) 
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "my_chat_member", "chat_member"])
    except Exception as e:
        logging.error(f"BOT KRITIK XATOGA UCHRADI: {e}")
        raise e

if __name__ == "__main__":
    asyncio.run(main())






