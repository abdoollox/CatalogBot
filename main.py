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
WEBAPP_URL = "https://abdoollox.github.io/WebApp/"
DB_CHANNEL_ID = -1003641399832

bot = Bot(token=TOKEN)
dp = Dispatcher()

# --- QAT'IY MA'LUMOTLAR BAZASI ---
MOVIES_DB = {
    "hp1": {
        "en": {
            "message_id": 2,
            "caption": "🎬 <b>Harry Potter and the Philosopher's Stone</b>"
        },
        "uz": {
            "video_id": "BAACAgIAAxkBAAIBAmmhPtrufpNuPlwMwSt6BgUSljNNAAKgkgACUhcBSFBrcYcb2zo2OgQ",
            "thumb_id": "AAMCAgADGQEAAgECaaE-2u5-k24-XAzBK3oGBRKWM00AAqCSAAJSFwFIUGtxhxvbOjYBAAdtAAM6BA",
            "caption": "🎬 <b>Garri Potter va Hikmatlar Toshi</b>"
        },
        "ru": {
            "video_id": "BAACAgIAAxkBAAO8aaAnjXFUC4llqb3irXal6a4GgccAAkKSAAIrpxFID96FSI3gmEE6BA",
            "thumb_id": "AAMCAgADGQEAA7xpoCeNcVQLiWWpveKtdqXprgaBxwACQpIAAiunEUgP3oVIjeCYQQEAB20AAzoE",
            "caption": "🎬 <b>Гарри Поттер и Философский Камень</b>"
        }
    },
    
    "hp2": {
        "en": {
            "video_id": "BAACAgIAAxkBAAPWaaBBC9FtkpBMLagnMZ2w0oLtr8MAArCLAALCvAFJlLX9zX0Oa446BA", 
            "thumb_id": "AAMCAgADGQEAA9ZpoEEL0W2SkEwtqCcxnbDSgu2vwwACsIsAAsK8AUmUtf3NfQ5rjgEAB20AAzoE",
            "caption": "🎬 <b>Harry Potter and the Chamber of Secrets</b>"
        },
        "uz": {
            "video_id": "BAACAgIAAxkBAAIBA2mhPtrZoI5jJ6SYo9bY1ghRboQTAAIBlQACUhcBSG1npCkk5acPOgQ",
            "thumb_id": "AAMCAgADGQEAAgEDaaE-2tmgjmMnpJij1tjWCFFuhBMAAgGVAAJSFwFIbWekKSTlpw8BAAdtAAM6BA",
            "caption": "🎬 <b>Garri Potter va Maxfiy Hujra</b>"
        },
        "ru": {
            "video_id": "BAACAgIAAxkBAAO-aaAoJAmK-jqKpZRDvJd8FVGyNpkAAhiQAAJXEJFIpZsNgkUDkY06BA",
            "thumb_id": "AAMCAgADGQEAA75poCgkCYr6OoqllEO8l3wVUbI2mQACGJAAAlcQkUilmw2CRQORjQEAB20AAzoE",
            "caption": "🎬 <b>Гарри Поттер и Тайная Kомнатa</b>"
        }
    },
    
    "hp3": {
        "en": {
            "video_id": "BAACAgIAAxkBAAPYaaBF-BZJbrI69f4Sz0EAAX7ralWyAALxiwACwrwBSenv_1uNrf_POgQ", 
            "thumb_id": "AAMCAgADGQEAA9hpoEX4Fklusjr1_hLPQQABfutqVbIAAvGLAALCvAFJ6e__W42t_88BAAdtAAM6BA",
            "caption": "🎬 <b>Harry Potter and the Prisioner of Azkaban</b>"
        },
        "uz": {
            "video_id": "BAACAgIAAxkBAAIBBGmhPtoiGmmWTCXcL0pH57t14vbYAAI2lQACUhcBSN16ks9jjzmhOgQ",
            "thumb_id": "AAMCAgADGQEAAgEEaaE-2iIaaZZMJdwvSkfnu3Xi9tgAAjaVAAJSFwFI3XqSz2OPOaEBAAdtAAM6BA",
            "caption": "🎬 <b>Garri Potter va Azkaban Maxbusi</b>"
        },
        "ru": {
            "video_id": "BAACAgIAAxkBAAPAaaAoOBcP3NyEPUoqprdvHuWq_2gAApGQAAJXEJFIeiQNsOVpQSk6BA",
            "thumb_id": "AAMCAgADGQEAA8BpoCg4Fw_c3IQ9Siqmt28e5ar_aAACkZAAAlcQkUh6JA2w5WlBKQEAB20AAzoE",
            "caption": "🎬 <b>Гарри Поттер и Узник Азкабана</b>"
        }
    },
    
    "hp4": {
        "en": {
            "video_id": "BAACAgIAAxkBAAPeaaBUqEHincpWqsZrQnoKXKxBuBkAAiWMAALCvAFJ4erNDpoIaZo6BA", 
            "thumb_id": "AAMCAgADGQEAA95poFSoQeKdylaqxmtCegpcrEG4GQACJYwAAsK8AUnh6s0OmghpmgEAB20AAzoE",
            "caption": "🎬 <b>Harry Potter and the Goblet of Fire</b>"
        },
        "uz": {
            "video_id": "BAACAgIAAxkBAAIBBWmhPtqhPbfXcYqLZEnpWAEFVy9VAAJ9lQACUhcBSOzxxEr39DbPOgQ",
            "thumb_id": "AAMCAgADGQEAAgEFaaE-2qE9t9dxiotkSelYAQVXL1UAAn2VAAJSFwFI7PHESvf0Ns8BAAdtAAM6BA",
            "caption": "🎬 <b>Garri Potter va Alanga Kubogi</b>"
        },
        "ru": {
            "video_id": "BAACAgIAAxkBAAPCaaAoRoC2hNDfoJZl87bzfgsdd6EAApaQAAJXEJFINf9dMuxL4AM6BA",
            "thumb_id": "AAMCAgADGQEAA8JpoChGgLaE0N-glmXztvN-Cx13oQAClpAAAlcQkUg1_10y7EvgAwEAB20AAzoE",
            "caption": "🎬 <b>Гарри Поттер и Кубок Огня</b>"
        }
    },
    
    "hp5": {
        "en": {
            "video_id": "BAACAgIAAxkBAAPgaaBUwxNC8tbgOIIqpAo0jsYUS3cAAiaMAALCvAFJPhaaDn5YoZs6BA", 
            "thumb_id": "AAMCAgADGQEAA-BpoFTDE0Ly1uA4giqkCjSOxhRLdwACJowAAsK8AUk-FpoOflihmwEAB20AAzoE",
            "caption": "🎬 <b>Harry Potter and the Order of the Phoenix</b>"
        },
        "uz": {
            "video_id": "BAACAgIAAxkBAAIBBmmhPtocgOCPDJR9LDUWkb411ARbAAKVlQACUhcBSCHT70Qi-d6ROgQ",
            "thumb_id": "AAMCAgADGQEAAgEGaaE-2hyA4I8MlH0sNRaRvjXUBFsAApWVAAJSFwFIIdPvRCL53pEBAAdtAAM6BA",
            "caption": "🎬 <b>Garri Potter va Feniks Jamiyati</b>"
        },
        "ru": {
            "video_id": "BAACAgIAAxkBAAPEaaAoV-QD2qqp_-k1T8Bm5hloOckAAreQAAJXEJFIQs0p2PZFwmo6BA",
            "thumb_id": "AAMCAgADGQEAA8RpoChX5APaqqn_6TVPwGbmGWg5yQACt5AAAlcQkUhCzSnY9kXCagEAB20AAzoE",
            "caption": "🎬 <b>Гарри Поттер и Орден Феникса</b>"
        }
    },
    
    "hp6": {
        "en": {
            "video_id": "BAACAgIAAxkBAAPiaaBU0rBOc749XfmyFvTN4pmag3kAAieMAALCvAFJ8WU6E-Dlbf86BA", 
            "thumb_id": "AAMCAgADGQEAA-JpoFTSsE5zvj1d-bIW9M3imZqDeQACJ4wAAsK8AUnxZToT4OVt_wEAB20AAzoE",
            "caption": "🎬 <b>Harry Potter and the Half-Blood Prince</b>"
        },
        "uz": {
            "video_id": "BAACAgIAAxkBAAIBB2mhPtohNqS3LnS-B9gko8TUTUnVAALMlQACUhcBSKJ0Ojbn5eQbOgQ",
            "thumb_id": "AAMCAgADGQEAAgEHaaE-2iE2pLcudL4H2CSjxNRNSdUAAsyVAAJSFwFIonQ6Nufl5BsBAAdtAAM6BA",
            "caption": "🎬 <b>Garri Potter va Tilsim Shaxzodasi</b>"
        },
        "ru": {
            "video_id": "BAACAgIAAxkBAAPGaaAobIpxq6DkIhMqaTa8S9KQXwoAAsqQAAJXEJFIt9lcOgABawgcOgQ",
            "thumb_id": "AAMCAgADGQEAA8ZpoChsinGroOQiEyppNrxL0pBfCgACypAAAlcQkUi32Vw6AAFrCBwBAAdtAAM6BA",
            "caption": "🎬 <b>Гарри Поттер и Принц Полукровка</b>"
        }
    },

    "hp7": {
        "en": {
            "video_id": "BAACAgIAAxkBAAPkaaBU42d4-nqwFimoujzeAfgMkUsAAiiMAALCvAFJFbRcT_-2Q8Q6BA", 
            "thumb_id": "AAMCAgADGQEAA-RpoFTjZ3j6erAWKai6PN4B-AyRSwACKIwAAsK8AUkVtFxP_7ZDxAEAB20AAzoE",
            "caption": "🎬 <b>Harry Potter and the Deathly Hallows Part 1</b>"
        },
        "uz": {
            "video_id": "BAACAgIAAxkBAAIBCGmhPtp8p9_yg-VSzk5r073h0-SzAAIdlgACUhcBSKaXEz2GI-fvOgQ",
            "thumb_id": "AAMCAgADGQEAAgEIaaE-2nyn3_KD5VLOTmvTveHT5LMAAh2WAAJSFwFIppcTPYYj5-8BAAdtAAM6BA",
            "caption": "🎬 <b>Garri Potter va Ajal Tuhfasi 1</b>"
        },
        "ru": {
            "video_id": "AAMCAgADGQEAA8hpoCh_W6E_xd5Nqa0AAYqkKnHMkYsAAgORAAJXEJFImfE1w7WPxfEBAAdtAAM6BA",
            "thumb_id": "AAMCAgADGQEAA8hpoCh_W6E_xd5Nqa0AAYqkKnHMkYsAAgORAAJXEJFImfE1w7WPxfEBAAdtAAM6BA",
            "caption": "🎬 <b>Гарри Поттер и Дары Смерти Часть I</b>"
        }
    },
    
    "hp8": {
        "en": {
            "video_id": "BAACAgIAAxkBAAPmaaBU8r6U3W-teCPoUQjy7WGH_9kAAimMAALCvAFJrtvdK3s_gQs6BA", 
            "thumb_id": "AAMCAgADGQEAA-ZpoFTyvpTdb614I-hRCPLtYYf_2QACKYwAAsK8AUmu290rez-BCwEAB20AAzoE",
            "caption": "🎬 <b>Harry Potter and the Deathly Hallows Part 2</b>"
        },
        "uz": {
            "video_id": "kiritilmagan",
            "thumb_id": "kiritilmagan",
            "caption": "🎬 <b>Garri Potter va Ajal Tuhfasi 2</b>"
        },
        "ru": {
            "video_id": "BAACAgIAAxkBAAPKaaAonCSpQjFSqjrlfS8JpBdWGlEAAkSRAAJXEJFILoE7ARD9BII6BA",
            "thumb_id": "AAMCAgADGQEAA8ppoCicJKlCMVKqOuV9LwmkF1YaUQACRJEAAlcQkUgugTsBEP0EggEAB20AAzoE",
            "caption": "🎬 <b>Гарри Поттер и Дары Смерти Часть II</b>"
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

# --- MANA SHU YERGA YANGI FUNKSIYANI QO'SHASAN ---
def back_to_catalog_keyboard():
    return InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎬 Katalogni ochish", web_app=WebAppInfo(url=WEBAPP_URL))]
    ])
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
            
            if movie_data["video_id"] == "kiritilmagan":
                await message.answer("⏳ Bu tildagi film tez orada yuklanadi.")
                return

            # Asosiy yuborish qismi
            await bot.copy_message(
                chat_id=message.from_user.id,
                from_chat_id=DB_CHANNEL_ID,
                message_id=movie_data["message_id"],
                caption=movie_data["caption"], # Kanaldagi yozuvni o'zimiznikiga almashtiramiz
                parse_mode="HTML",
                reply_markup=back_to_catalog_keyboard(),
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
            
            "👇 <b>Kino tanlash uchun pastdagi tugma orqali katalogni oching:</b>"
        )
        await message.answer(welcome_text, parse_mode="HTML", reply_markup=webapp_keyboard())

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























