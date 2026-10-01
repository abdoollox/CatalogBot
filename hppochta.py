"""Boyo'g'li pochtasi — ilovadagi bildirishnomalar.

Xatlar ilova ichida turadi (🦉 belgisi, o'qilmaganlar soni). Odam ilovaga
qaytmasa xatni ko'rmaydi, shuning uchun bot ham bitta qisqa xabar yuboradi -
lekin faqat odam buni o'chirmagan bo'lsa (ilovada ham, bot xabaridagi tugma
bilan ham o'chiriladi). Hozircha bitta tur bor: onboarding eslatmasi.

Onboarding eslatmasi (egasi bilan kelishilgan, 2026-10-01):
  - xatni ochib, fakultetga yetmagan odam;
  - oxirgi qadamidan 1 kun o'tsa - birinchi eslatma, 3 kun o'tsa - ikkinchisi
    (birinchisidan kamida 2 kun keyin), shundan keyin boshqa yo'q;
  - 30 kundan beri jim odamga yozilmaydi; bot xabari faqat 10:00-21:00 da.

Qadamlar ilova (`/api/profile`) yuborganda shu yerga ham yoziladi. Shu
modul paydo bo'lishidan oldingi qadamlar bir marta loglardan (Sheets) olinadi.
"""
import asyncio
import csv
import io
import logging
from datetime import datetime, timedelta, timezone

from aiogram import F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest
from aiohttp import web

import hpcup

# Ilovadagi yo'l tartibi bilan bir xil (js/09-sehrli-olam.js jrSteps)
YOL = ["letter", "alley", "gringotts", "wand", "ticket", "train", "sortst", "house"]

BIRINCHI = timedelta(days=1)
IKKINCHI = timedelta(days=3)
ORALIQ = timedelta(days=2)       # ikki eslatma orasida kamida
JIM_CHEGARA = timedelta(days=30)
MAX_ESLATMA = 2
SOAT_BOSH, SOAT_OXIR = 10, 21    # bot xabari shu oraliqda (Toshkent)

_cfg = {}

# Bot xabari: sarlavha va matn keyingi qadamga qarab (ilovadagi matnlar bilan bir xil ruhda)
MATN = {
    "uz": {
        "alley": ("Diagon xiyoboni sizni kutmoqda", "Xatdagi ro'yxat tayyor, g'isht devor ochiq. Xogvartsga yo'l shu yerdan boshlanadi."),
        "gringotts": ("Gringotts eshiklari ochiq", "Ota-onangiz qoldirgan oltinlar bankda sizni kutib turibdi."),
        "wand": ("Olivander tayoqchangizni kutyapti", "Tayoqchani sehrgar emas, tayoqcha sehrgarni tanlaydi."),
        "ticket": ("Xagrid biletingizni ushlab turibdi", "9¾ platformaga bilet - Qovoqxonada, Xagridning qo'lida."),
        "train": ("Xogvarts ekspressi jo'nashga tayyor", "9¾ platformada poyezd sizsiz ketmaydi."),
        "sortst": ("Katta zalda Saralovchi qalpoq kutmoqda", "Bir qadam qoldi - qaysi fakultetga tushasiz?"),
        "house": ("Saralovchi qalpoq hali qaror qilmadi", "Savollarni oxirigacha javob bering - fakultetingiz e'lon qilinadi."),
        "kick": "🦉 <b>Boyo'g'li pochtasi</b>",
        "again": "Xogvarts sizni unutgani yo'q.",
        "open": "🦉 Xatni o'qish",
        "off": "🔕 Telegramda kerak emas",
        "offed": "Yaxshi, endi xatlar faqat ilova ichidagi 🦉 pochtada bo'ladi. U yerdan qayta yoqishingiz mumkin.",
    },
    "ru": {
        "alley": ("Косой переулок ждёт вас", "Список из письма готов, кирпичная стена открыта. Путь в Хогвартс начинается здесь."),
        "gringotts": ("Двери Гринготтса открыты", "Золото, оставленное родителями, ждёт вас в банке."),
        "wand": ("Олливандер ждёт вас", "Не волшебник выбирает палочку, а палочка - волшебника."),
        "ticket": ("Хагрид держит ваш билет", "Билет на платформу 9¾ - в «Дырявом котле», у Хагрида."),
        "train": ("Хогвартс-экспресс готов к отправлению", "На платформе 9¾ поезд без вас не уйдёт."),
        "sortst": ("Распределяющая шляпа ждёт в Большом зале", "Остался один шаг - на какой факультет вы попадёте?"),
        "house": ("Шляпа ещё не приняла решение", "Ответьте на вопросы до конца - и факультет будет объявлен."),
        "kick": "🦉 <b>Совиная почта</b>",
        "again": "Хогвартс вас не забыл.",
        "open": "🦉 Прочитать письмо",
        "off": "🔕 Не нужно в Telegram",
        "offed": "Хорошо, теперь письма будут только в 🦉 почте внутри приложения. Там же можно включить снова.",
    },
    "en": {
        "alley": ("Diagon Alley is waiting", "The list from your letter is ready and the brick wall is open. The road to Hogwarts starts here."),
        "gringotts": ("Gringotts doors are open", "The gold your parents left you is waiting at the bank."),
        "wand": ("Ollivander is waiting for you", "The wand chooses the wizard, not the other way round."),
        "ticket": ("Hagrid is holding your ticket", "Your Platform 9¾ ticket is at the Leaky Cauldron, with Hagrid."),
        "train": ("The Hogwarts Express is ready to leave", "On Platform 9¾ the train won't leave without you."),
        "sortst": ("The Sorting Hat is waiting in the Great Hall", "One step left - which house will you join?"),
        "house": ("The Sorting Hat hasn't decided yet", "Answer the questions to the end and your house will be announced."),
        "kick": "🦉 <b>Owl Post</b>",
        "again": "Hogwarts hasn't forgotten you.",
        "open": "🦉 Read the letter",
        "off": "🔕 Not in Telegram",
        "offed": "Fine - letters will now arrive only in the 🦉 post inside the app. You can turn this back on there.",
    },
}


# ---------------------------------------------------------------- baza

def _ulan():
    conn = hpcup._connect()
    conn.executescript(
        "CREATE TABLE IF NOT EXISTS onb_qadam ("
        " user_id INTEGER NOT NULL, qadam TEXT NOT NULL, vaqt TEXT NOT NULL,"
        " PRIMARY KEY (user_id, qadam));"
        "CREATE TABLE IF NOT EXISTS pochta ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " user_id INTEGER NOT NULL,"
        " tur TEXT NOT NULL,"            # hozircha 'onb'
        " qadam TEXT,"                   # onb: keyingi qilinishi kerak bo'lgan qadam
        " n INTEGER NOT NULL DEFAULT 1,"  # nechanchi eslatma
        " yaratildi TEXT NOT NULL,"
        " oqildi TEXT,"                  # ilovada ochib ko'rilgan
        " bot_holat TEXT,"               # yuborildi | bloklagan | xato | ochirilgan | sinov
        " bot_vaqt TEXT,"
        " bosildi TEXT,"                 # bot xabaridagi tugma bilan ilovaga kirdi
        " bajarildi TEXT);"              # eslatilgan qadam keyin bajarildi
        "CREATE INDEX IF NOT EXISTS pochta_user ON pochta(user_id, id);"
        "CREATE TABLE IF NOT EXISTS pochta_sozlama ("
        " user_id INTEGER PRIMARY KEY, bot INTEGER NOT NULL DEFAULT 1, vaqt TEXT NOT NULL);"
        "CREATE TABLE IF NOT EXISTS pochta_meta (k TEXT PRIMARY KEY, v TEXT);")
    return conn


def _hozir():
    return hpcup._utc_iso(hpcup.now_tk())


def _qadam_yoz(user_id, qadam, vaqt=None):
    conn = _ulan()
    try:
        v = vaqt or _hozir()
        cur = conn.execute("INSERT OR IGNORE INTO onb_qadam (user_id, qadam, vaqt) VALUES (?,?,?)",
                           (int(user_id), qadam, v))
        # Shu qadam haqida eslatilgan bo'lsa - u endi bajarildi
        conn.execute("UPDATE pochta SET bajarildi=? WHERE user_id=? AND tur='onb' AND qadam=? "
                     "AND bajarildi IS NULL", (v, int(user_id), qadam))
        conn.commit()
        return cur.rowcount > 0
    finally:
        conn.close()


async def qadam(user_id, kind, value=None):
    """Ilova yuborgan qadamni yozadi. kind: onb/wand/sort_start/house."""
    if int(user_id) <= 0:
        return
    q = {"onb": value, "wand": "wand", "sort_start": "sortst", "house": "house"}.get(kind)
    if q not in YOL:
        return
    try:
        await asyncio.to_thread(_qadam_yoz, user_id, q)
    except Exception as e:
        logging.error("Onboarding qadamini yozishda xato (%s): %s", user_id, e)


def _log_vaqt(matn):
    """Logdagi UTC vaqt ('2026-09-26 14:51:00') -> UTC ISO."""
    try:
        dt = datetime.strptime(matn.strip()[:19], "%Y-%m-%d %H:%M:%S")
        return dt.replace(tzinfo=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    except (ValueError, AttributeError):
        return None


def _log_qadam(payload):
    if payload.startswith("onb_") and payload[4:] in YOL:
        return payload[4:]
    if payload.startswith("wand_"):
        return "wand"
    if payload == "sort_start":
        return "sortst"
    if payload.startswith("house_"):
        return "house"
    return None


def _toldir(matn):
    """Loglardagi eski qadamlarni bazaga ko'chiradi (bir marta)."""
    yozuvlar = []
    for r in csv.reader(io.StringIO(matn)):
        if len(r) < 5:
            continue
        q = _log_qadam(r[3].strip())
        v = _log_vaqt(r[4])
        if not q or not v:
            continue
        try:
            uid = int(r[0])
        except ValueError:
            continue
        if uid > 0:
            yozuvlar.append((v, uid, q))
    yozuvlar.sort()
    conn = _ulan()
    try:
        # Xatdan oldingi qadam (yo'l paydo bo'lmasidan oldingi saralanish) olinmaydi:
        # ilova va panel ham shunday sanaydi.
        xat = {}
        for v, uid, q in yozuvlar:
            if q == "letter" and uid not in xat:
                xat[uid] = v
        n = 0
        for v, uid, q in yozuvlar:
            if uid in xat and v >= xat[uid]:
                n += conn.execute("INSERT OR IGNORE INTO onb_qadam (user_id, qadam, vaqt) VALUES (?,?,?)",
                                  (uid, q, v)).rowcount
        conn.execute("INSERT OR REPLACE INTO pochta_meta (k, v) VALUES ('toldirildi', ?)", (_hozir(),))
        conn.commit()
        return n
    finally:
        conn.close()


def _toldirilganmi():
    conn = _ulan()
    try:
        return bool(conn.execute("SELECT v FROM pochta_meta WHERE k='toldirildi'").fetchone())
    finally:
        conn.close()


# ---------------------------------------------------------------- kim eslatma oladi

def _nomzodlar(hozir):
    """[(uid, keyingi_qadam, n)] - shu daqiqada eslatma olishi kerak bo'lganlar."""
    conn = _ulan()
    try:
        qadamlar = {}
        for r in conn.execute("SELECT user_id, qadam, vaqt FROM onb_qadam"):
            qadamlar.setdefault(r["user_id"], {})[r["qadam"]] = r["vaqt"]
        eslatma = {}
        for r in conn.execute("SELECT user_id, COUNT(*) AS n, MAX(yaratildi) AS oxiri FROM pochta "
                              "WHERE tur='onb' GROUP BY user_id"):
            eslatma[r["user_id"]] = (r["n"], r["oxiri"])
        uylar = {r["user_id"] for r in conn.execute("SELECT user_id FROM users WHERE house IS NOT NULL")}
    finally:
        conn.close()

    out = []
    for uid, q in qadamlar.items():
        if uid <= 0 or "letter" not in q or "house" in q or uid in uylar:
            continue
        n, oxiri = eslatma.get(uid, (0, None))
        if n >= MAX_ESLATMA:
            continue
        keyingi = next((s for s in YOL if s not in q), None)
        if not keyingi:
            continue
        jim = hozir - max(hpcup._parse_iso(v) for v in q.values())
        if jim > JIM_CHEGARA:
            continue
        if n == 0 and jim >= BIRINCHI:
            out.append((uid, keyingi, 1))
        elif n == 1 and jim >= IKKINCHI and hozir - hpcup._parse_iso(oxiri) >= ORALIQ:
            out.append((uid, keyingi, 2))
    return out


def _yarat(uid, keyingi, n):
    conn = _ulan()
    try:
        cur = conn.execute("INSERT INTO pochta (user_id, tur, qadam, n, yaratildi) VALUES (?,?,?,?,?)",
                           (uid, "onb", keyingi, n, _hozir()))
        conn.commit()
        return cur.lastrowid
    finally:
        conn.close()


def _bot_holat(pid, holat):
    conn = _ulan()
    try:
        conn.execute("UPDATE pochta SET bot_holat=?, bot_vaqt=? WHERE id=?", (holat, _hozir(), pid))
        conn.commit()
    finally:
        conn.close()


def _bot_yoqmi(uid):
    conn = _ulan()
    try:
        r = conn.execute("SELECT bot FROM pochta_sozlama WHERE user_id=?", (int(uid),)).fetchone()
        return True if r is None else bool(r["bot"])
    finally:
        conn.close()


def _sozla(uid, yoq):
    conn = _ulan()
    try:
        conn.execute("INSERT INTO pochta_sozlama (user_id, bot, vaqt) VALUES (?,?,?) "
                     "ON CONFLICT(user_id) DO UPDATE SET bot=excluded.bot, vaqt=excluded.vaqt",
                     (int(uid), 1 if yoq else 0, _hozir()))
        conn.commit()
    finally:
        conn.close()


def bot_matni(lang, keyingi, n):
    t = MATN.get(lang) or MATN["uz"]
    sarlavha, matn = t.get(keyingi, t["alley"])
    bosh = t["kick"] + "\n\n" + ("<i>" + t["again"] + "</i>\n" if n > 1 else "")
    return bosh + "<b>" + sarlavha + "</b>\n" + matn


async def _yubor(bot, uid, pid, keyingi, n):
    if not await asyncio.to_thread(_bot_yoqmi, uid):
        await asyncio.to_thread(_bot_holat, pid, "ochirilgan")
        return "ochirilgan"
    lang = (await hpcup.get_lang(uid)) or "uz"
    t = MATN.get(lang) or MATN["uz"]
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t["open"], web_app=WebAppInfo(
            url="%s?lang=%s&owl=1" % (_cfg.get("webapp_url", ""), lang)))],
        [InlineKeyboardButton(text=t["off"], callback_data="owl_off")]])
    try:
        await bot.send_message(uid, bot_matni(lang, keyingi, n), parse_mode="HTML", reply_markup=kb)
        holat = "yuborildi"
    except TelegramForbiddenError:
        holat = "bloklagan"
    except Exception as e:
        logging.error("Pochta xabarini yuborishda xato (%s): %s", uid, e)
        holat = "xato"
    await asyncio.to_thread(_bot_holat, pid, holat)
    return holat


async def aylana(bot, hozir=None):
    """Bitta tekshiruv: eslatma kerak bo'lganlarga xat yaratib, botdan yuboradi."""
    hozir = hozir or hpcup.now_tk()
    tk = hozir.astimezone(hpcup.TASHKENT)
    if not (SOAT_BOSH <= tk.hour < SOAT_OXIR):
        return []
    natija = []
    for uid, keyingi, n in await asyncio.to_thread(_nomzodlar, hozir.astimezone(timezone.utc)):
        pid = await asyncio.to_thread(_yarat, uid, keyingi, n)
        natija.append((uid, keyingi, n, await _yubor(bot, uid, pid, keyingi, n)))
        await asyncio.sleep(0.2)
    if natija:
        logging.info("Boyo'g'li pochtasi: %d ta eslatma", len(natija))
    return natija


async def kuzatuvchi(bot, read_csv=None, interval=900):
    """Har 15 daqiqada tekshiradi. Birinchi marta eski qadamlarni loglardan oladi."""
    await asyncio.sleep(60)     # bot to'liq ishga tushsin
    if read_csv and not await asyncio.to_thread(_toldirilganmi):
        try:
            matn = await read_csv()
            if matn:
                n = await asyncio.to_thread(_toldir, matn)
                logging.info("Onboarding qadamlari loglardan olindi: %d ta", n)
        except Exception as e:
            logging.error("Onboarding qadamlarini loglardan olishda xato: %s", e)
    while True:
        try:
            await aylana(bot)
        except Exception as e:
            logging.error("Boyo'g'li pochtasi tekshiruvida xato: %s", e)
        await asyncio.sleep(interval)


# ---------------------------------------------------------------- ilova uchun

def _royxat(uid):
    conn = _ulan()
    try:
        rows = conn.execute("SELECT id, tur, qadam, n, yaratildi, oqildi, bajarildi FROM pochta "
                            "WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(uid),)).fetchall()
    finally:
        conn.close()
    items = [{"id": r["id"], "tur": r["tur"], "qadam": r["qadam"], "n": r["n"], "t": r["yaratildi"],
              "read": bool(r["oqildi"]), "done": bool(r["bajarildi"])} for r in rows]
    return {"items": items, "unread": sum(1 for x in items if not x["read"]),
            "bot": _bot_yoqmi(uid)}


def _oqildi(uid, ids=None):
    conn = _ulan()
    try:
        if ids:
            q = ",".join("?" * len(ids))
            conn.execute("UPDATE pochta SET oqildi=? WHERE user_id=? AND oqildi IS NULL AND id IN (%s)" % q,
                         [_hozir(), int(uid)] + [int(i) for i in ids])
        else:
            conn.execute("UPDATE pochta SET oqildi=? WHERE user_id=? AND oqildi IS NULL", (_hozir(), int(uid)))
        conn.commit()
    finally:
        conn.close()


def _bosildi(uid):
    conn = _ulan()
    try:
        conn.execute("UPDATE pochta SET bosildi=? WHERE user_id=? AND bot_holat='yuborildi' AND bosildi IS NULL",
                     (_hozir(), int(uid)))
        conn.commit()
    finally:
        conn.close()


async def api_pochta(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    if request.method != "POST":
        return cors(web.json_response({"ok": False, "error": "method"}, status=405))
    try:
        body = await request.json()
    except Exception:
        body = {}
    user = _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", "")
                                    or str(body.get("initData", "")))
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
    uid = int(user["id"])
    amal = str(body.get("action", "list"))
    try:
        if amal == "read":
            ids = body.get("ids")
            ids = [int(i) for i in ids][:100] if isinstance(ids, list) else None
            await asyncio.to_thread(_oqildi, uid, ids)
        elif amal == "bot":
            await asyncio.to_thread(_sozla, uid, bool(body.get("on")))
        elif amal == "came":
            await asyncio.to_thread(_bosildi, uid)
        elif amal != "list":
            return cors(web.json_response({"ok": False, "error": "amal"}, status=400))
        return cors(web.json_response(dict({"ok": True}, **await asyncio.to_thread(_royxat, uid))))
    except Exception as e:
        logging.error("Pochta amalida xato (%s): %s", amal, e)
        return cors(web.json_response({"ok": False, "error": "server"}, status=500))


# ---------------------------------------------------------------- panel uchun

def _panel():
    conn = _ulan()
    try:
        xatlar = [[r["id"], str(r["user_id"]), r["tur"], r["qadam"], r["n"], r["yaratildi"], r["oqildi"],
                   r["bot_holat"], r["bosildi"], r["bajarildi"]]
                  for r in conn.execute("SELECT * FROM pochta ORDER BY id")]
        ochirgan = conn.execute("SELECT COUNT(*) FROM pochta_sozlama WHERE bot=0").fetchone()[0]
        return {"xatlar": xatlar, "ochirgan": ochirgan}
    finally:
        conn.close()


async def api_pochtapanel(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    if not _cfg["dash_ok"](request):
        return cors(web.json_response({"ok": False}, status=403))
    return cors(web.json_response(dict({"ok": True}, **await asyncio.to_thread(_panel))))


# ---------------------------------------------------------------- bot tugmasi

async def owl_off(call):
    try:
        await asyncio.to_thread(_sozla, call.from_user.id, False)
        lang = (await hpcup.get_lang(call.from_user.id)) or "uz"
        t = MATN.get(lang) or MATN["uz"]
        try:
            # "O'chirish" tugmasi olinadi, "Xatni o'qish" qoladi
            kb = call.message.reply_markup
            if kb and kb.inline_keyboard:
                await call.message.edit_reply_markup(
                    reply_markup=InlineKeyboardMarkup(inline_keyboard=kb.inline_keyboard[:1]))
        except TelegramBadRequest:
            pass
        await call.answer(t["offed"], show_alert=True)
    except Exception as e:
        logging.error("Pochtani o'chirishda xato: %s", e)
        await call.answer()


def register(dp, app, cfg):
    """cfg: cors, verify_init_data, dash_ok, webapp_url."""
    _cfg.update(cfg)
    _ulan().close()
    app.router.add_route('*', '/api/pochta', api_pochta)
    app.router.add_route('*', '/api/pochtapanel', api_pochtapanel)
    dp.callback_query.register(owl_off, F.data == "owl_off")
