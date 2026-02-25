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

# --- QAT'IY MA'LUMOTLAR BAZASI ---
MOVIES_DB = {
    "hp1": {
        "uz": "UZBEK_TILIDAGI_FILE_ID_SHU_YERGA_YOZILADI",
        "ru": "RUS_TILIDAGI_FILE_ID_SHU_YERGA_YOZILADI",
        "en": "AgACAgIAAxkBAAEhOU1pnnr2rmDA0Uc1c35VGSrdKCKt9AACZAxrGwpg-Us1GE7r935_oQEAAwIAA3MAAzoE" # Senda shu bor edi
    }
}
# ---------------------------------

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
        print(f"Xato yuz berdi: {e}")
        return False

# --- YANGILANGAN VA AQLI KIRITILGAN START FUNKSIYASI ---
@dp.message(CommandStart())
async def start_cmd(message: types.Message, command: CommandObject):
    payload = command.args # Dum qismini (hp1_en) ushlab olish
    user_id = message.from_user.id
    
    if not await is_subscribed(user_id):
        await message.answer("Filmlarni ko'rish uchun avval kanalimizga obuna bo'ling!", reply_markup=check_sub_keyboard())
        return

    # Agar botga deep link orqali kirilgan bo'lsa
    if payload:
        try:
            movie_key, lang = payload.split('_') 
            file_id = MOVIES_DB[movie_key][lang]
            
            if file_id == "UZBEK_TILIDAGI_FILE_ID_SHU_YERGA_YOZILADI" or file_id.endswith("_kiritilmagan"):
                await message.answer("Bu tildagi film tez orada yuklanadi.")
                return

            await message.answer_video(video=file_id, caption="🎬 Yoqimli tomosha!")
        
        except (ValueError, KeyError):
            await message.answer("⚠️ Xato: Kino yoki til tizimda topilmadi.")
        except Exception as e:
            await message.answer(f"⚠️ Telegram API xatosi (Video ID eskirgan yoki noto'g'ri): {str(e)}")
    else:
        # Oddiy start bosilganda
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
    asyncio.create_task(dp.start_polling(bot))
    
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080))
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())
