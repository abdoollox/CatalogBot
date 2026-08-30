import os
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

# --- QAT'IY MA'LUMOTLAR BAZASI ---
MOVIES_DB = {
    "hp1": {
        "en": {
            "message_id": 10,
            "caption": "<b>1. Harry Potter and the Philosopher's Stone</b>"
        },
        "uz": {
            "message_id": 26,
            "caption": "<b>1. Garri Potter va Hikmatlar Toshi</b>"
        },
        "ru": {
            "message_id": 18,
            "caption": "<b>1. Гарри Поттер и Философский Камень</b>"
        }
    },
    
    "hp2": {
        "en": {
            "message_id": 11,
            "caption": "<b>2. Harry Potter and the Chamber of Secrets</b>"
        },
        "uz": {
            "message_id": 27,
            "caption": "<b>2. Garri Potter va Maxfiy Hujra</b>"
        },
        "ru": {
            "message_id": 19,
            "caption": "<b>2. Гарри Поттер и Тайная Kомнатa</b>"
        }
    },
    
    "hp3": {
        "en": {
            "message_id": 12,
            "caption": "<b>3. Harry Potter and the Prisioner of Azkaban</b>"
        },
        "uz": {
            "message_id": 28,
            "caption": "<b>3. Garri Potter va Azkaban Maxbusi</b>"
        },
        "ru": {
            "message_id": 20,
            "caption": "<b>3. Гарри Поттер и Узник Азкабана</b>"
        }
    },
    
    "hp4": {
        "en": {
            "message_id": 13,
            "caption": "<b>4. Harry Potter and the Goblet of Fire</b>"
        },
        "uz": {
            "message_id": 29,
            "caption": "<b>4. Garri Potter va Alanga Kubogi</b>"
        },
        "ru": {
            "message_id": 21,
            "caption": "<b>4. Гарри Поттер и Кубок Огня</b>"
        }
    },
    
    "hp5": {
        "en": {
            "message_id": 14,
            "caption": "<b>5. Harry Potter and the Order of the Phoenix</b>"
        },
        "uz": {
            "message_id": 30,
            "caption": "<b>5. Garri Potter va Feniks Jamiyati</b>"
        },
        "ru": {
            "message_id": 22,
            "caption": "<b>5. Гарри Поттер и Орден Феникса</b>"
        }
    },
    
    "hp6": {
        "en": {
            "message_id": 15,
            "caption": "<b>6. Harry Potter and the Half-Blood Prince</b>"
        },
        "uz": {
            "message_id": 31,
            "caption": "<b>6. Garri Potter va Tilsim Shaxzodasi</b>"
        },
        "ru": {
            "message_id": 23,
            "caption": "<b>6. Гарри Поттер и Принц Полукровка</b>"
        }
    },

    "hp7": {
        "en": {
            "message_id": 16,
            "caption": "<b>7. Harry Potter and the Deathly Hallows Part 1</b>"
        },
        "uz": {
            "message_id": 32,
            "caption": "<b>7. Garri Potter va Ajal Tuhfasi 1</b>"
        },
        "ru": {
            "message_id": 24,
            "caption": "<b>7. Гарри Поттер и Дары Смерти Часть I</b>"
        }
    },
    
    "hp8": {
        "en": {
            "message_id": 17,
            "caption": "<b>8. Harry Potter and the Deathly Hallows Part 2</b>"
        },
        "uz": {
            "message_id": 33,
            "caption": "<b>8. Garri Potter va Ajal Tuhfasi 2</b>"
        },
        "ru": {
            "message_id": 25,
            "caption": "<b>8. Гарри Поттер и Дары Смерти Часть II</b>"
        }
    },

    "fb1": {
        "en": {
            "message_id": 37,
            "caption": "<b>1. Fantastic Beasts and Where to Find Them</b>"
        },
        "uz": {
            "message_id": 34,
            "caption": "<b>1. Fantastik Maxluqlar va ularni qayerdan topish mumkin</b>"
        },
        "ru": {
            "message_id": 0,
            "caption": "<b>1. Фантастические твари и где они обитают</b>"
        }
    },

    "fb2": {
        "en": {
            "message_id": 38,
            "caption": "<b>2. Fantastic Beasts: The Crimes of Grindelwald</b>"
        },
        "uz": {
            "message_id": 35,
            "caption": "<b>2. Fantastik Maxluqlar: Grindelvaldning jinoyatlari</b>"
        },
        "ru": {
            "message_id": 0,
            "caption": "<b>2. Фантастические твари: Преступления Грин-де-Вальда</b>"
        }
    },

    "fb3": {
        "en": {
            "message_id": 39,
            "caption": "<b>3. Fantastic Beasts: The Secrets of Dumbledore</b>"
        },
        "uz": {
            "message_id": 36,
            "caption": "<b>3. Fantastik Maxluqlar: Dambldor sirlari</b>"
        },
        "ru": {
            "message_id": 0,
            "caption": "<b>3. Фантастические твари: Тайны Дамблдора</b>"
        }
    }
}

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

def movie_delivery_keyboard(lang: str = "uz"):
    loc = LOCALES.get(lang, LOCALES["uz"])
    builder = InlineKeyboardBuilder()
    
    # 1. Ulashish matni va havolasi
    share_text = loc["share_text"]
    share_url = "https://t.me/garripotterkinobot/catalog"
    
    # 2. URL Encoding
    safe_text = urllib.parse.quote(share_text)
    safe_url = urllib.parse.quote(share_url)
    final_share_link = f"https://t.me/share/url?url={safe_url}&text={safe_text}"
    
    # --- 1-QATOR: Kolleksiya WebApp ---
    builder.row(
        InlineKeyboardButton(
            text=loc["collection_btn"], 
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    )
    
    # --- 2-QATOR: Do'stlarga ulashish ---
    builder.row(
        InlineKeyboardButton(
            text=loc["share_btn"], 
            url=final_share_link
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
            await hpcup.touch_user(message.from_user.id, message.from_user.first_name)
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
                
            if lang not in MOVIES_DB[movie_key]:
                await message.answer(f"⚠️ DIAGNOSTIKA (KeyError - Til): '{movie_key}' kinoda '{lang}' tili topilmadi.\nMavjud tillar: {list(MOVIES_DB[movie_key].keys())}")
                return
                
            movie_data = MOVIES_DB[movie_key][lang]
            
            if movie_data.get("message_id", 0) == 0:
                await message.answer("⏳ Bu tildagi film tez orada yuklanadi.")
                return

            # Xavfsiz tizim: Mijoz harakatini qayd etish
            await log_user_action(message.from_user, payload_clean)

            # Asosiy yuborish qismi
            await bot.copy_message(
                chat_id=message.from_user.id,
                from_chat_id=DB_CHANNEL_ID,
                message_id=movie_data["message_id"],
                caption=movie_data["caption"], 
                parse_mode="HTML",
                reply_markup=movie_delivery_keyboard(lang),
                protect_content=True
            )

            # Xogvarts kubogi: kino ochilgani uchun ball (agar fakulteti bo'lsa).
            # Kinoning o'zi allaqachon yuborilgan - bu yerdagi xato
            # foydalanuvchiga ta'sir qilmasligi kerak.
            try:
                if movie_key.startswith("hp"):
                    film_part = int(movie_key[2:])
                    await hpbot.award_film_open(message.from_user, film_part)
            except Exception as cup_error:
                logging.error("Kubok qismida xato: %s", cup_error)

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
                await hpcup.touch_user(user["id"], user["first_name"])
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
                await hpcup.touch_user(user["id"], user["first_name"])
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
                await hpcup.touch_user(user["id"], user["first_name"])
            except Exception:
                pass

    try:
        await log_user_action(_WebUser(user), payload)
    except Exception as e:
        logging.error("Profil yozishda xato: %s", e)
        return _cors(web.json_response({"ok": False, "error": "server"}, status=500))

    return _cors(web.json_response({"ok": True, "cup": await _cup_block(user["id"])}))


async def handle(request):
    return web.Response(text="Hogwarts Bot is Alive!")

async def main():
    logging.info("Bot va Server ishga tushmoqda...")
    app = web.Application()
    app.router.add_get('/', handle)
    app.router.add_route('*', '/api/house', handle_house)
    app.router.add_route('*', '/api/profile', handle_house)

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






