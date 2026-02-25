import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiohttp import web # Render uchun qo'shildi
from aiogram.filters import CommandStart, CommandObject

load_dotenv()
TOKEN = os.getenv("BOT_TOKEN")
CHANNEL_ID = int(os.getenv("CHANNEL_ID", "-1003535019162")) # O'z kanalingning aniq ID sini yoz
CHANNEL_URL = "https://t.me/garripotter_cinema" # Ochiq yoki yopiq havola
WEBAPP_URL = "https://abdoollox.notion.site/2e45b1c59e7c80a1987ed80a45d1c129?v=2e45b1c59e7c8092bd37000ca5cfb393&source=copy_link" # WebApp joylashgan manzil (hozircha bo'sh tursin yoki biror saytni yoz)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- YANGILANGAN QAT'IY MA'LUMOTLAR BAZASI (OBJECT MODEL) ---
MOVIES_DB = {
    "hp1": {
        "en": {
            "video_id": "BAACAgIAAxkBAAEhOU1pnnr2t3--9o8WX_5B2OCoQ6l-wwACbJ4AArJBCEheI-oZJ-ZM7ToE",
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
# ---------------------------------

# --- YANGILANGAN START FUNKSIYASI ---
@dp.message(CommandStart())
async def start_cmd(message: types.Message, command: CommandObject):
    payload = command.args
    user_id = message.from_user.id
    
    if not await is_subscribed(user_id):
        await message.answer("Filmlarni ko'rish uchun avval kanalimizga obuna bo'ling!", reply_markup=check_sub_keyboard())
        return

    if payload:
        try:
            movie_key, lang = payload.split('_') 
            movie_data = MOVIES_DB[movie_key][lang] # Endi bu yalang'och ID emas, butun bir obyekt
            
            if movie_data["video_id"] == "kiritilmagan":
                await message.answer("⏳ Bu tildagi film tez orada yuklanadi.")
                return

            # Videoni rasm, matn va HTML formatlash bilan birga yuborish
            await message.answer_video(
                video=movie_data["video_id"], 
                thumbnail=movie_data["thumb_id"], # Rasm qo'shildi
                caption=movie_data["caption"],    # Maxsus matn qo'shildi
                parse_mode="HTML"                 # Matnni chiroyli qilish uchun
            )
        
        except (ValueError, KeyError):
            await message.answer("⚠️ Xato: Kino yoki til tizimda topilmadi.")
        except Exception as e:
            await message.answer(f"⚠️ Telegram API xatosi: {str(e)}")
    else:
        await message.answer("Xush kelibsiz! Kinolarni ko'rish uchun katalogni oching.", reply_markup=webapp_keyboard())
        
# --------------------------------------------------------

@dp.callback_query(F.data == "check_sub")
async def check_sub_handler(callback: types.CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        await callback.message.edit_text("✅ Obuna tasdiqlandi! Katalogni oching:", reply_markup=webapp_keyboard())
    else:
        await callback.answer("Hali obuna bo'lmadingiz! Avval kanalga a'zo bo'ling.", show_alert=True)

# Render uchun server
async def handle(request):
    return web.Response(text="Hogwarts Bot is Alive!")

async def main():
    print("Bot va Server ishga tushmoqda...")
    
    # 1. Veb-serverni tayyorlash (U orqa fonda xalaqit bermay ishlayveradi)
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    print("Veb-server ishga tushdi.")
    
    # 2. Zombi jarayonning oldini olish: Pollingni bloklovchi asosiy jarayonga aylantiramiz
    try:
        # Ikkita bot to'qnashib qolmasligi uchun eskirgan so'rovlarni tozalaymiz
        await bot.delete_webhook(drop_pending_updates=True) 
        await dp.start_polling(bot) # Agar bu qulasa, dastur ham qulaydi!
    except Exception as e:
        print(f"BOT KRITIK XATOGA UCHRADI: {e}")
        raise e # Renderga dastur o'lganini xabar qilish

if __name__ == "__main__":
    asyncio.run(main())



