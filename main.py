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
import hpcup
import hpbot
from datetime import datetime
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import (InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo,
                          BotCommand)
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


def check_sub_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Kanalga obuna bo'lish", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="2️⃣ Tasdiqlash", callback_data="check_sub")]
    ])

def webapp_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Kolleksiyani ochish", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])

LOCALES = {
    "uz": {
        "collection_btn": "🎬 Filmlar kolleksiyasi",
        "share_btn": "👥 Do'stlarga ulashish",
        "share_text": "🎬 Menga bu filmlar kolleksiyasi yoqdi. Siz ham foydalanib ko'ring!"
    },
    "ru": {
        "collection_btn": "🎬 Коллекция фильмов",
        "share_btn": "👥 Поделиться с друзьями",
        "share_text": "🎬 Мне понравилась эта коллекция фильмов. Попробуйте и вы!"
    },
    "en": {
        "collection_btn": "🎬 Movie Collection",
        "share_btn": "👥 Share with friends",
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
                text="⚡️ 4K formatda ko'rish", 
                url=vk_url
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
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    )
    
    # --- 3-QATOR: Do'stlarga ulashish ---
    builder.row(
        InlineKeyboardButton(
            text=loc["share_btn"], 
            url=final_share_link
        )
    )
    
    return builder.as_markup()
    

async def deliver_movie(user, movie_key, lang):
    """Filmni foydalanuvchiga yuboradi. Uch joydan chaqiriladi:
    chuqur havola (/start), WebApp (/api/send) va bot chatidagi qidiruv.

    Ilgari bu mantiq ikki joyda nusxalangan edi; uchinchisi qo'shilganda
    ular bir-biridan uzoqlashib ketishi aniq edi.

    Qaytaradi: (sent_message, xato_kodi). Biri None bo'ladi.
    """
    data = catalog.get(movie_key, lang)
    if not data:
        return None, "unknown"
    if not catalog.is_ready(movie_key, lang):
        return None, "not_ready"

    vk_url = data.get("vk_url") if lang == "uz" else None
    try:
        sent = await bot.copy_message(
            chat_id=user.id,
            from_chat_id=DB_CHANNEL_ID,
            message_id=data["message_id"],
            caption=data["caption"],
            parse_mode="HTML",
            reply_markup=movie_delivery_keyboard(lang, vk_url),
            protect_content=True,
        )
    except Exception as e:
        logging.error("Film yuborishda xato (%s_%s): %s", movie_key, lang, e)
        return None, "send_failed"

    await log_user_action(user, "%s_%s" % (movie_key, lang))

    # Kubok qismidagi xato filmga ta'sir qilmasligi kerak - film allaqachon
    # yuborilgan.
    try:
        await hpcup.set_lang(user.id, lang)
        if movie_key.startswith("hp"):
            await hpbot.award_film_open(user, int(movie_key[2:]))
    except Exception as cup_error:
        logging.error("Kubok qismida xato: %s", cup_error)

    return sent, None


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
    
    if not await is_subscribed(user_id):
        await message.answer("Filmlarni ko'rish uchun avval kanalimizga obuna bo'ling!", reply_markup=check_sub_keyboard())
        return

    if payload:
        try:
            payload_clean = payload.strip()
            parts = payload_clean.split('_')
            
            if len(parts) != 2:
                await message.answer(f"⚠️ DIAGNOSTIKA (ValueError): Signal ikkiga bo'linmadi.\nSiz yuborgan aniq signal: '{payload}'\nUzunligi: {len(payload)} ta belgi.")
                return
                
            movie_key, lang = parts
            
            if movie_key not in MOVIES_DB:
                await message.answer(f"⚠️ DIAGNOSTIKA (KeyError - Kino): '{movie_key}' bazada topilmadi.\nBazadagi mavjud kinolar: {list(MOVIES_DB.keys())}")
                return
                
            if lang not in catalog.LANGS:
                await message.answer(f"⚠️ DIAGNOSTIKA (KeyError - Til): '{movie_key}' kinoda '{lang}' tili topilmadi.\nMavjud tillar: {list(catalog.LANGS)}")
                return
                
            sent, xato = await deliver_movie(message.from_user, movie_key, lang)
            if xato == "not_ready":
                await message.answer("⏳ Bu tildagi film tez orada yuklanadi.")
            elif xato:
                await message.answer("⚠️ Filmni yuborib bo'lmadi. Birozdan keyin urinib ko'ring.")

        except Exception as e:
            logging.error(f"Kritik API xatosi: {e}")
            await message.answer(f"⚠️ Telegram API xatosi (Fayl yuborish quladi): {str(e)}")
    else:
        await send_welcome(message)


CATALOG_TEXT = (
    "🪄 <b>Hogwarts Cinema'ga Xush Kelibsiz!</b>\n\n"

    "Garri Potter olamidagi barcha filmlarni yuqori sifatda, reklamalarsiz va 3 xil tilda (🇺🇿 🇷🇺 🇬🇧) tomosha qiling.\n\n"

    "👇 <b>Kino tanlash uchun pastdagi tugma orqali kolleksiyani oching:</b>"
)

SORTING_TEXT = (
    "🎩 <b>Saralovchi shlyapa sizni kutmoqda</b>\n\n"

    "Bir necha savol — va siz o'z fakultetingizni bilib olasiz. "
    "Shundan keyin har ko'rgan kinongiz fakultetingizga ball olib keladi, "
    "haftalik <b>Xogvarts kubogi</b>da esa fakultetlar bellashadi.\n\n"

    "Bu majburiy emas — kinolarni shusiz ham ko'raverasiz."
)


def sorting_keyboard():
    """Saralanish taklifi. O'tkazib yuborish tugmasi SHART —
    foydalanuvchilarning 40% i aniq bir kinoni qidirib keladi, yo'lni
    to'sib qo'ysak asosiy qiymat buziladi."""
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎩 Saralanish",
                              web_app=WebAppInfo(url=WEBAPP_URL + "?screen=sort"))],
        [InlineKeyboardButton(text="Hozir emas, kinolarni ko'rsat",
                              callback_data="skip_sort")],
    ])


async def send_welcome(message):
    """Fakulteti yo'qlarga avval shlyapa, keyin katalog."""
    try:
        has_house = await hpbot.user_house(message.from_user.id)
    except Exception as e:
        logging.error("Fakultetni aniqlashda xato: %s", e)
        has_house = True          # shubha bo'lsa - eski oqim, yo'lni to'smaymiz

    if not has_house:
        await message.answer(SORTING_TEXT, parse_mode="HTML",
                             reply_markup=sorting_keyboard())
        return

    await message.answer(CATALOG_TEXT, parse_mode="HTML",
                         reply_markup=webapp_keyboard())


@dp.callback_query(F.data == "skip_sort")
async def skip_sort_handler(callback: types.CallbackQuery):
    try:
        await callback.message.edit_text(CATALOG_TEXT, parse_mode="HTML",
                                         reply_markup=webapp_keyboard())
    except TelegramBadRequest as e:
        if "message is not modified" not in str(e):
            raise
    await callback.answer()

@dp.callback_query(F.data == "check_sub")
async def check_sub_handler(callback: types.CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        # Oqim: start -> obuna -> saralash shlyapasi -> kinolar
        try:
            has_house = await hpbot.user_house(callback.from_user.id)
        except Exception as e:
            logging.error("Fakultetni aniqlashda xato: %s", e)
            has_house = True

        if has_house:
            text, markup = "✅ Obuna tasdiqlandi! Kolleksiyani oching:", webapp_keyboard()
        else:
            text, markup = "✅ Obuna tasdiqlandi!\n\n" + SORTING_TEXT, sorting_keyboard()

        try:
            await callback.message.edit_text(text, parse_mode="HTML", reply_markup=markup)
        except TelegramBadRequest as e:
            # Tugma ikki marta bosilsa xabar o'zgarmaydi - bu xato emas
            if "message is not modified" not in str(e):
                raise
        await callback.answer()
    else:
        await callback.answer("Hali obuna bo'lmadingiz! Avval kanalga a'zo bo'ling.", show_alert=True)

# --- BOT CHATIDA FILM QIDIRISH ---
# Ilgari botga biror narsa yozilsa u UMUMAN javob bermasdi. Foydalanuvchi
# filmni topish uchun WebApp ni ochishga majbur edi.

QIDIRUV = {
    "uz": {
        "topildi": "🔍 <b>«%s»</b> bo'yicha topildi:",
        "yoq": ("🔍 <b>«%s»</b> bo'yicha hech narsa topilmadi.\n\n"
                "Film nomini yoki raqamini yozing — masalan <b>Azkaban</b> yoki <b>3</b>.\n"
                "Butun kolleksiya: /kinolar"),
        "hammasi": "🎬 <b>Kolleksiyadagi barcha filmlar:</b>",
        "til_tanla": "🌐 <b>%s</b> — qaysi tilda ko'rasiz?",
        "tez_orada": "⏳ Bu film hali hech qaysi tilda yuklanmagan.",
        "obuna": "Filmlarni ko'rish uchun avval kanalimizga obuna bo'ling!",
    },
    "ru": {
        "topildi": "🔍 Найдено по запросу <b>«%s»</b>:",
        "yoq": ("🔍 По запросу <b>«%s»</b> ничего не найдено.\n\n"
                "Напишите название или номер фильма — например <b>Азкабана</b> или <b>3</b>.\n"
                "Вся коллекция: /kinolar"),
        "hammasi": "🎬 <b>Все фильмы коллекции:</b>",
        "til_tanla": "🌐 <b>%s</b> — на каком языке смотрите?",
        "tez_orada": "⏳ Этот фильм пока не загружен ни на одном языке.",
        "obuna": "Чтобы смотреть фильмы, сначала подпишитесь на наш канал!",
    },
    "en": {
        "topildi": "🔍 Found for <b>«%s»</b>:",
        "yoq": ("🔍 Nothing found for <b>«%s»</b>.\n\n"
                "Type a film name or number — for example <b>Azkaban</b> or <b>3</b>.\n"
                "Full collection: /kinolar"),
        "hammasi": "🎬 <b>All films in the collection:</b>",
        "til_tanla": "🌐 <b>%s</b> — which language?",
        "tez_orada": "⏳ This film has not been uploaded in any language yet.",
        "obuna": "To watch the films, please subscribe to our channel first!",
    },
}

TIL_NOMI = {"uz": "🇺🇿 O'zbekcha", "ru": "🇷🇺 Русский", "en": "🇬🇧 English"}


async def user_lang(user_id):
    """Eslab qolingan til. Bilinmasa o'zbekcha (bosishlarning 86% i shunda)."""
    try:
        return await hpcup.get_lang(user_id) or "uz"
    except Exception:
        return "uz"


def search_keyboard(hits, lang):
    """Topilgan filmlar - har biri alohida tugma."""
    kb = InlineKeyboardBuilder()
    for fid, film in hits:
        nom = film[lang]["title"] if lang in film else film["uz"]["title"]
        kb.row(InlineKeyboardButton(text="🎬 %s. %s" % (film["order"], nom),
                                    callback_data="f:%s" % fid))
    return kb.as_markup()


def lang_keyboard(movie_key):
    """Film qaysi tillarda tayyor bo'lsa - o'sha tillar tugmasi."""
    kb = InlineKeyboardBuilder()
    for l in catalog.LANGS:
        if catalog.is_ready(movie_key, l):
            kb.row(InlineKeyboardButton(text=TIL_NOMI[l],
                                        callback_data="f:%s:%s" % (movie_key, l)))
    return kb.as_markup()


async def show_results(message, query, hits, lang):
    t = QIDIRUV.get(lang, QIDIRUV["uz"])
    if not hits:
        await message.answer(t["yoq"] % query[:60], parse_mode="HTML")
        return
    sarlavha = t["hammasi"] if not query else t["topildi"] % query[:60]
    await message.answer(sarlavha, parse_mode="HTML",
                         reply_markup=search_keyboard(hits, lang))


@dp.message(F.text == "/kinolar")
async def all_movies_cmd(message: types.Message):
    lang = await user_lang(message.from_user.id)
    await show_results(message, "", catalog.search("", limit=20), lang)


# Buyruq bo'lmagan har qanday matn - qidiruv so'rovi.
# `~F.text.startswith("/")` SHART: aks holda bu handler /kunlik va /reyting
# buyruqlarini ham yutib yuborardi (ular keyinroq ro'yxatga olinadi).
@dp.message(F.text & ~F.text.startswith("/"))
async def search_cmd(message: types.Message):
    query = (message.text or "").strip()
    if not query:
        return
    lang = await user_lang(message.from_user.id)
    try:
        await hpcup.touch_user(message.from_user.id, message.from_user.first_name,
                               message.from_user.username)
    except Exception:
        pass
    await show_results(message, query, catalog.search(query), lang)


@dp.callback_query(F.data.startswith("f:"))
async def send_found_movie(callback: types.CallbackQuery):
    """Qidiruv natijasidagi tugma bosilganda filmni yuboradi."""
    parts = callback.data.split(":")
    movie_key = parts[1] if len(parts) > 1 else ""
    if movie_key not in catalog.FILMS:
        await callback.answer()
        return

    lang = parts[2] if len(parts) > 2 else await user_lang(callback.from_user.id)
    t = QIDIRUV.get(lang, QIDIRUV["uz"])

    if not await is_subscribed(callback.from_user.id):
        await callback.message.answer(t["obuna"], reply_markup=check_sub_keyboard())
        await callback.answer()
        return

    # Eslab qolingan tilda tayyor bo'lmasa - mavjud tillarni taklif qilamiz.
    if not catalog.is_ready(movie_key, lang):
        bor = [l for l in catalog.LANGS if catalog.is_ready(movie_key, l)]
        if not bor:
            await callback.answer(t["tez_orada"], show_alert=True)
            return
        nom = catalog.FILMS[movie_key][lang]["title"]
        await callback.message.answer(t["til_tanla"] % nom, parse_mode="HTML",
                                      reply_markup=lang_keyboard(movie_key))
        await callback.answer()
        return

    sent, xato = await deliver_movie(callback.from_user, movie_key, lang)
    if xato:
        await callback.answer("⚠️ Yuborib bo'lmadi.", show_alert=True)
        return
    await callback.answer()


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

    try:
        await hpcup.touch_user(user.id, data.get("first_name"), data.get("username"))
    except Exception:
        pass

    sent, xato = await deliver_movie(user, movie_key, lang)
    if xato:
        # Eng ko'p uchraydigani: foydalanuvchi botni hech qachon ochmagan,
        # shuning uchun bot unga yoza olmaydi.
        return _cors(web.json_response({"ok": False, "error": xato}))

    remember_send(user.id, sent.message_id, movie_key, lang)
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
    return web.Response(text="Hogwarts Bot is Alive!")

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
    
    # Buyruqlar menyusi. Ilgari bo'sh edi - foydalanuvchi botda nima
    # qilish mumkinligini umuman bilmasdi.
    try:
        await bot.set_my_commands([
            BotCommand(command="kinolar", description="🎬 Barcha filmlar"),
            BotCommand(command="kunlik", description="❓ Kunlik savol"),
            BotCommand(command="reyting", description="🏆 Fakultetlar reytingi"),
        ])
    except Exception as e:
        logging.error("Buyruqlar menyusini o'rnatishda xato: %s", e)

    try:
        await bot.delete_webhook(drop_pending_updates=True) 
        await dp.start_polling(bot, allowed_updates=["message", "callback_query", "my_chat_member", "chat_member"])
    except Exception as e:
        logging.error(f"BOT KRITIK XATOGA UCHRADI: {e}")
        raise e

if __name__ == "__main__":
    asyncio.run(main())






