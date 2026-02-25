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
WEBAPP_URL = "https://sening-domen.uz"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- QAT'IY MA'LUMOTLAR BAZASI ---
MOVIES_DB = {
    "hp1": {
        "en": {
            "video_id": "BAACAgIAAxkBAAM4aZ6a7sHm5GczPeY-FGBGBQNTnhgAAmyeAAKyQQhIzAgwWVas_WI6BA", # Shu yerni yangilash esingdan chiqmasin
            "thumb_id": "AAMCAgADGQEAAzhpnpruwebkZzM95j4UYEYFA1OeGAACbJ4AArJBCEjMCDBZVqz9YgEAB20AAzoE",
            "caption": "🎬 <b>Harry Potter and the Philosopher's Stone</b>\n\n🧙‍♂️ <i>Sizni sehrgarlar olamiga eltuvchi afsonaviy asarning birinchi qismi. Hogwartsga xush kelibsiz!</i>\n\n🖥 Sifat: 1080p (FullHD)\n🇬🇧 Til: Ingliz tili"
        },
        "uz": {
            "video_id": "kiritilmagan",
            "thumb_id": "kiritilmagan",
            "caption": "Tez orada..."
        },
        "ru": {
            "video_id": "kiritilmagan",
            "thumb_id": "kiritilmagan",
            "caption": "Tez orada..."
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
        [InlineKeyboardButton(text="🎬 Katalogni ochish", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])

async def is_subscribed(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        logging.error(f"Kanalga a'zolikni tekshirishda xato: {e}")
        return False

@dp.message(CommandStart())
async def start_cmd(message: types.Message, command: CommandObject):
    payload = command.args
    user_id = message.from_user.id
    
    if not await is_subscribed(user_id):
        await message.answer("Filmlarni ko'rish uchun avval kanalimizga obuna bo'ling!", reply_markup=check_sub_keyboard())
        return

    if payload:
        try:
            # Probellarni tozalash va ajratish
            movie_key, lang = payload.strip().split('_')
            movie_data = MOVIES_DB[movie_key][lang]
            
            if movie_data["video_id"] == "kiritilmagan":
                await message.answer("⏳ Bu tildagi film tez orada yuklanadi.")
                return

            # --- MANA SEN SO'RAGAN QISMI (THUMBNAIL BILAN) ---
            await message.answer_video(
                video=movie_data["video_id"], 
                thumbnail=movie_data["thumb_id"], # Rasm qo'shib yuborish
                caption=movie_data["caption"],
                parse_mode="HTML"
            )
        
        except (ValueError, KeyError):
            await message.answer("⚠️ Xato: Kino yoki til tizimda topilmadi.")
        except Exception as e:
            logging.error(f"Video yuborishda xato: {e}")
            await message.answer(f"⚠️ Telegram API xatosi: {str(e)}")
    else:
        await message.answer("Xush kelibsiz! Kinolarni ko'rish uchun katalogni oching.", reply_markup=webapp_keyboard())

@dp.callback_query(F.data == "check_sub")
async def check_sub_handler(callback: types.CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.message.edit_text("✅ Obuna tasdiqlandi! Katalogni oching:", reply_markup=webapp_keyboard())
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



