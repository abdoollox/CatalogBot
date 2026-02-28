import os
import asyncio
import logging
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart, CommandObject
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiohttp import web

# --- TIZIM KO'ZLARINI OCHISH (LOGGING) ---
logging.basicConfig(level=logging.INFO)

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003826689337"))
CHANNEL_URL = "https://t.me/garripotter_cinema"
WEBAPP_URL = "https://abdoollox.github.io/CatalogWebApp/"
DB_CHANNEL_ID = -1003641399832

bot = Bot(token=TOKEN)
dp = Dispatcher()

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
            "message_id": 0,
            "caption": "<b>8. Garri Potter va Ajal Tuhfasi 2</b>"
        },
        "ru": {
            "message_id": 25,
            "caption": "<b>8. Гарри Поттер и Дары Смерти Часть II</b>"
        }
    }
}

def check_sub_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Kanalga obuna bo'lish", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="2️⃣ Tasdiqlash", callback_data="check_sub")]
    ])

def webapp_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Kutubxonani ochish", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])

# --- MANA SHU YERGA YANGI FUNKSIYANI QO'SHASAN ---
from aiogram.utils.keyboard import InlineKeyboardBuilder

def movie_delivery_keyboard():
    builder = InlineKeyboardBuilder()
    
    # 1-qavat: Katalogga qaytish (Mijozni tizimda olib qolish)
    builder.row(
        InlineKeyboardButton(
            text="🎬 Kutubxonani ochish", 
            web_app=WebAppInfo(url=WEBAPP_URL)
        )
    )
    
    # 2-qavat: SOTUV VORONKASIGA KO'PRIK
    # DIQQAT: "sotuv_bot_username" degan joyni o'zingning haqiqiy kolleksiya boting nomiga almashtir!
    builder.row(
        InlineKeyboardButton(
            text="🗝 Maxfiy sandiqni ochish", 
            url="https://t.me/garripotter_cinemabot?start=start"
        )
    )
    
    return builder.as_markup()
    
# ------------------------------------------------

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
        pass # Agar Telegram xabarni o'chirishga ruxsat bermasa, bot qulamasligi uchun himoya
        
    payload = command.args
    user_id = message.from_user.id
    
    if not await is_subscribed(user_id):
        await message.answer("Filmlarni ko'rish uchun avval kanalimizga obuna bo'ling!", reply_markup=check_sub_keyboard())
        return

    if payload:
        try:
            # 1. Tozalash bosqichi
            payload_clean = payload.strip()
            parts = payload_clean.split('_')
            
            # 2. Diagnostika: Bo'linishdagi xatoni ushlash
            if len(parts) != 2:
                await message.answer(f"⚠️ DIAGNOSTIKA (ValueError): Signal ikkiga bo'linmadi.\nSiz yuborgan aniq signal: '{payload}'\nUzunligi: {len(payload)} ta belgi.")
                return
                
            movie_key, lang = parts
            
            # 3. Diagnostika: Kino kalitini tekshirish
            if movie_key not in MOVIES_DB:
                await message.answer(f"⚠️ DIAGNOSTIKA (KeyError - Kino): '{movie_key}' bazada topilmadi.\nBazadagi mavjud kinolar: {list(MOVIES_DB.keys())}")
                return
                
            # 4. Diagnostika: Tilni tekshirish
            if lang not in MOVIES_DB[movie_key]:
                await message.answer(f"⚠️ DIAGNOSTIKA (KeyError - Til): '{movie_key}' kinoda '{lang}' tili topilmadi.\nMavjud tillar: {list(MOVIES_DB[movie_key].keys())}")
                return
                
            movie_data = MOVIES_DB[movie_key][lang]
            
            if movie_data.get("message_id", 0) == 0:
                await message.answer("⏳ Bu tildagi film tez orada yuklanadi.")
                return

            # Asosiy yuborish qismi
            await bot.copy_message(
                chat_id=message.from_user.id,
                from_chat_id=DB_CHANNEL_ID,
                message_id=movie_data["message_id"],
                caption=movie_data["caption"], # Kanaldagi yozuvni o'zimiznikiga almashtiramiz
                parse_mode="HTML",
                reply_markup=movie_delivery_keyboard(),
                protect_content=True
            )
        
        except Exception as e:
            logging.error(f"Kritik API xatosi: {e}")
            await message.answer(f"⚠️ Telegram API xatosi (Fayl yuborish quladi): {str(e)}")
    else:
        # UX optimizatsiya qilingan kutib olish xabari
        welcome_text = (
            "🪄 <b>Hogwarts Cinema'ga Xush Kelibsiz!</b>\n\n"
            
            "Garri Potter olamidagi barcha filmlarni yuqori sifatda, reklamalarsiz va 3 xil tilda (🇺🇿 🇷🇺 🇬🇧) tomosha qiling.\n\n"
            
            "👇 <b>Kino tanlash uchun pastdagi tugma orqali kutubxonani oching:</b>"
        )
        await message.answer(welcome_text, parse_mode="HTML", reply_markup=webapp_keyboard())

@dp.callback_query(F.data == "check_sub")
async def check_sub_handler(callback: types.CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.message.edit_text("✅ Obuna tasdiqlandi! Kutubxonani oching:", reply_markup=webapp_keyboard())
    else:
        await callback.answer("Hali obuna bo'lmadingiz! Avval kanalga a'zo bo'ling.", show_alert=True)

# --- ADMIN ASBOBI: Video va Thumbnail ID larini ushlab olish ---
@dp.message(F.video)
async def get_video_info(message: types.Message):
    video_id = message.video.file_id
    # Agar videoda rasm (cover) bo'lsa uni oladi, yo'q bo'lsa xabar beradi
    thumb_id = message.video.thumbnail.file_id if message.video.thumbnail else "Rasm (cover) topilmadi"
    
    text = (
        f"Sening boting uchun maxsus ID'lar:\n\n"
        f"🎬 <b>Video ID:</b>\n<code>{video_id}</code>\n\n"
        f"🖼 <b>Thumbnail ID:</b>\n<code>{thumb_id}</code>"
    )
    
    await message.reply(text, parse_mode="HTML")


async def handle(request):
    return web.Response(text="Hogwarts Bot is Alive!")

async def main():
    logging.info("Bot va Server ishga tushmoqda...")
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    logging.info("Veb-server ishga tushdi.")
    
    try:
        await bot.delete_webhook(drop_pending_updates=True) 
        await dp.start_polling(bot)
    except Exception as e:
        logging.error(f"BOT KRITIK XATOGA UCHRADI: {e}")
        raise e

if __name__ == "__main__":
    asyncio.run(main())




































