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
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1001234567890"))
CHANNEL_URL = "https://t.me/garripotter_cinema" # Agar haqiqiy kanal havolasini yozmagan bo'lsang, API xato beradi
WEBAPP_URL = "https://sening-domen.uz"

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- QAT'IY MA'LUMOTLAR BAZASI ---
MOVIES_DB = {
    "hp1": {
        "en": {
            "video_id": "BAACAgIAAxkBAAM4aZ6a7sHm5GczPeY-FGBGBQNTnhgAAmyeAAKyQQhIzAgwWVas_WI6BA",
            "thumb_id": "AAMCAgADGQEAASE5TWmeeva3f772jxZf_kHY4KhDqX7DAAJsngACskEISF4j6hkn5kztAQAHbQADOgQ",
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

# --- ADMIN ASBOBI: Video ID sini ushlab olish ---
@dp.message(F.video)
async def get_video_id(message: types.Message):
    # Bu funksiya botga har qanday video tashlanganda uning shaxsiy ID sini qaytaradi
    await message.reply(f"Sening boting uchun maxsus ID:\n\n<code>{message.video.file_id}</code>", parse_mode="HTML")


@dp.message(CommandStart())
async def start_cmd(message: types.Message, command: CommandObject):
    payload = command.args
    user_id = message.from_user.id
    
    if not await is_subscribed(user_id):
        await message.answer("Filmlarni ko'rish uchun avval kanalimizga obuna bo'ling!", reply_markup=check_sub_keyboard())
        return

    if payload:
        # 1. Kiritilgan ma'lumotni tozalash va klaviatura xatolarini tuzatish
        payload = payload.strip().lower()
        payload = payload.replace('е', 'e').replace('р', 'p') # Kirill harflarini avtomat lotinchaga o'giradi
        
        parts = payload.split('_')
        
        # 2. Aniq diagnostika: Nima xato ketganini yuziga aytish
        if len(parts) != 2:
            await message.answer(f"⚠️ Format xatosi. Siz kiritdingiz: '{payload}'.\nTo'g'ri format: hp1_en")
            return
            
        movie_key, lang = parts
        
        if movie_key not in MOVIES_DB:
            await message.answer(f"⚠️ Baza xatosi: '{movie_key}' kodli kino topilmadi.")
            return
            
        if lang not in MOVIES_DB[movie_key]:
            await message.answer(f"⚠️ Baza xatosi: '{movie_key}' kinoda '{lang}' tili yo'q.")
            return
            
        movie_data = MOVIES_DB[movie_key][lang]
        
        if movie_data["video_id"] == "kiritilmagan":
            await message.answer("⏳ Bu tildagi film tez orada yuklanadi.")
            return

        try:
            # 3. API chekloviga ko'ra thumbnail olib tashlandi
            await message.answer_video(
                video=movie_data["video_id"], 
                caption=movie_data["caption"],
                parse_mode="HTML"
            )
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




