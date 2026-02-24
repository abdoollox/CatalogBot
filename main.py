import os
import asyncio
from dotenv import load_dotenv
from aiogram import Bot, Dispatcher, types, F
from aiogram.filters import CommandStart
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiohttp import web # Render uchun qo'shildi

# DANGEROUS ASSUMPTION: Token va ID larni ochiq kodda saqlash xavfsizlikka zid. 
# Hozircha test uchun ishlatamiz, keyin .env faylga o'tkazishing shart.
load_dotenv()
TOKEN = "8593850986:AAEoe23weaHuhxX5urYxgqytfT4f2jPaoek"
CHANNEL_ID = -1003535019162 # O'z kanalingning aniq ID sini yoz
CHANNEL_URL = "https://t.me/garripotter_cinema" # Ochiq yoki yopiq havola
WEBAPP_URL = "https://abdoollox.notion.site/2e45b1c59e7c80a1987ed80a45d1c129?v=2e45b1c59e7c8092bd37000ca5cfb393&source=copy_link" # WebApp joylashgan manzil (hozircha bo'sh tursin yoki biror saytni yoz)

bot = Bot(token=TOKEN)
dp = Dispatcher()

# 1. Obuna bo'lishni so'rovchi tugmalar
def check_sub_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="1️⃣ Kanalga obuna bo'lish", url=CHANNEL_URL)],
        [InlineKeyboardButton(text="2️⃣ Tasdiqlash", callback_data="check_sub")]
    ])

# 2. Obuna bo'lgach ochiladigan WebApp tugmasi
def webapp_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Katalogni ochish", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])

# 3. Asosiy tekshiruvchi funksiya (Stress-testdan o'tgan)
async def is_subscribed(user_id):
    try:
        member = await bot.get_chat_member(chat_id=CHANNEL_ID, user_id=user_id)
        # Status "left" yoki "kicked" bo'lsa, False qaytaradi
        return member.status in ["member", "administrator", "creator"]
    except Exception as e:
        # Failure mode: Agar bot kanalda admin bo'lmasa yoki API qulasa, shu yerda xato ushlanadi
        print(f"Xato yuz berdi: {e}")
        return False

# 4. /start bosilganda ishlovchi mantiq
@dp.message(CommandStart())
async def start_cmd(message: types.Message):
    if await is_subscribed(message.from_user.id):
        await message.answer("Xush kelibsiz! Kinolarni ko'rish uchun katalogni oching.", reply_markup=webapp_keyboard())
    else:
        await message.answer("Filmlarni ko'rish uchun avval kanalimizga obuna bo'ling!", reply_markup=check_sub_keyboard())

# 5. "Tasdiqlash" tugmasi bosilganda ishlovchi mantiq
@dp.callback_query(F.data == "check_sub")
async def check_sub_handler(callback: types.CallbackQuery):
    if await is_subscribed(callback.from_user.id):
        # Obuna bo'lgan bo'lsa, xabarni o'zgartiramiz
        await callback.message.edit_text("✅ Obuna tasdiqlandi! Katalogni oching:", reply_markup=webapp_keyboard())
    else:
        # Obuna bo'lmagan bo'lsa, ekranga pop-up xabar chiqaramiz
        await callback.answer("Hali obuna bo'lmadingiz! Avval kanalga a'zo bo'ling.", show_alert=True)

# --- RENDER UCHUN SOXTA SERVER (Health check o'tishi uchun) ---
async def handle(request):
    return web.Response(text="Hogwarts Bot is Alive!")

async def main():
    print("Bot va Server ishga tushmoqda...")
    # Botni fon rejimida yurgizish
    asyncio.create_task(dp.start_polling(bot))
    
    # Render kutayotgan serverni ishga tushirish
    app = web.Application()
    app.router.add_get('/', handle)
    runner = web.AppRunner(app)
    await runner.setup()
    
    port = int(os.getenv("PORT", 8080)) # Render o'zi PORT beradi
    site = web.TCPSite(runner, '0.0.0.0', port)
    await site.start()
    
    # Dastur yopilmasligi uchun cheksiz kutish
    await asyncio.Event().wait()

if __name__ == "__main__":
    asyncio.run(main())


