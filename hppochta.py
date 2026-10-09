"""Boyo'g'li pochtasi — ilovadagi bildirishnomalar.

Xatlar ilova ichida turadi (🦉 belgisi, o'qilmaganlar soni). Odam ilovaga
qaytmasa xatni ko'rmaydi, shuning uchun bot ham bitta qisqa xabar yuboradi -
lekin faqat odam buni o'chirmagan bo'lsa (ilovada ham, bot xabaridagi tugma
bilan ham o'chiriladi). Hozircha bitta tur bor: onboarding eslatmasi.

Onboarding eslatmasi (egasi bilan kelishilgan, 2026-10-01):
  - xatni ochib, fakultetga yetmagan odam;
  - oxirgi qadamidan 1 kun o'tsa - birinchi eslatma, 3 kun o'tsa - ikkinchisi
    (birinchisidan kamida 2 kun keyin);
  - 2-eslatmadan keyin ham shu qadamda tursa - haftada bir marta (chegarasiz; egasi, 2026-10-03);
    sanoq to'xtagan qadam bo'yicha; bot xabari faqat 10:00-21:00 da.

Qo'lda xat (egasi paneldan yozadi, 2026-10-01): kimga - hammaga, fakultetga,
saralanmaganlarga yoki bitta odamga (til bo'yicha ham tanlasa bo'ladi);
avval "o'zimga sinab ko'rish". Bot xabari yana faqat o'chirmaganlarga.

Shaxsiy xabar (egasi so'radi, 2026-10-01): chatda kimdir shaxsiy yozsa va
qabul qiluvchi uni 1 daqiqada o'qimasa - pochtaga "falonchi sizga yozdi" xati.
Bitta suhbatdan o'qilmagan xat bo'lsa yangisi ochilmaydi, eskisining soni
oshadi; bot xabari bitta suhbat uchun soatiga ko'pi bilan bir marta, tunda
(22:00-08:00) ovozsiz. Suhbatni ochib o'qisa - xat o'zi o'qilgan bo'ladi.

Kubok natijasi (egasi so'radi, 2026-10-01): hafta yopilgach har saralangan
odamga o'z xati - g'olib, fakultetining o'rni, o'zi qo'shgan ball, yangi
nishonlari. Ilovadagi xat darhol, bot xabari 10:00-21:00 da va faqat shu hafta
ball to'plaganlarga (jim odamni har hafta bezovta qilmaslik uchun).
Pochta paydo bo'lishidan oldin yopilgan haftalar uchun xat yozilmaydi.

Qadamlar ilova (`/api/profile`) yuborganda shu yerga ham yoziladi. Shu
modul paydo bo'lishidan oldingi qadamlar bir marta loglardan (Sheets) olinadi.
"""
import asyncio
import csv
import html
import json
import io
import logging
from datetime import datetime, timedelta, timezone

from aiogram import F
from aiogram.types import InlineKeyboardMarkup, InlineKeyboardButton, WebAppInfo
from aiogram.exceptions import TelegramForbiddenError, TelegramBadRequest, TelegramRetryAfter
from aiohttp import web

import hpcup

# Ilovadagi yo'l tartibi bilan bir xil (js/09-sehrli-olam.js jrSteps)
YOL = ["letter", "alley", "gringotts", "wand", "ticket", "train", "sortst", "house"]

BIRINCHI = timedelta(days=1)
IKKINCHI = timedelta(days=3)
ORALIQ = timedelta(days=2)       # ikki eslatma orasida kamida
HAFTA = timedelta(days=7)        # 2-eslatmadan keyin: shu qadamda turgan bo'lsa haftada bir marta
# Egasi (2026-10-03): umumiy "jami 2 ta" va "30 kun jim" chegaralari olib tashlandi.
# Sanoq endi odam TO'XTAGAN QADAM bo'yicha: yangi qadamda to'xtasa, yana 1-eslatmadan boshlanadi.
SOAT_BOSH, SOAT_OXIR = 10, 21    # bot xabari shu oraliqda (Toshkent)

_cfg = {}

# Bot xabari: sarlavha va matn keyingi qadamga qarab (ilovadagi matnlar bilan bir xil ruhda)
MATN = {
    "uz": {
        "alley": ("Gringotts sizni kutmoqda", "Xogvartsga yo'l sehrgarlar bankidan boshlanadi: goblin kalitingizni ko'zdan kechirmoqchi."),
        "gringotts": ("Gringotts eshiklari ochiq", "Xogvarts sizga ajratgan galleonlar bankda kutib turibdi."),
        "wand": ("Olivander tayoqchangizni kutyapti", "Tayoqchani sehrgar emas, tayoqcha sehrgarni tanlaydi."),
        "ticket": ("Xagrid 9¾ platformada kutmoqda", "Biletingiz Xagridning qo'lida - Kings Kross vokzalida, g'isht ustun yonida."),
        "train": ("Xogvarts ekspressi jo'nashga tayyor", "9¾ platformada poyezd sizsiz ketmaydi."),
        "sortst": ("Katta zalda Saralovchi qalpoq kutmoqda", "Bir qadam qoldi - qaysi fakultetga tushasiz?"),
        "house": ("Saralovchi qalpoq hali qaror qilmadi", "Savollarni oxirigacha javob bering - fakultetingiz e'lon qilinadi."),
        "kick": "🦉 <b>Boyo'g'li pochtasi</b>",
        "again": "Xogvarts sizni unutgani yo'q.",
        "open": "🦉 Xatni o'qish",
        "off": "🔕 Telegramda kerak emas",
        "offed": "Yaxshi, endi xatlar faqat ilova ichidagi 🦉 pochtada bo'ladi. U yerdan qayta yoqishingiz mumkin.",
        "dm": "<b>%s</b> sizga shaxsiy xabar yozdi:", "dmN": "<b>%s</b> sizga %d ta shaxsiy xabar yozdi. Oxirgisi:",
        "dmChess": "♟️ shaxmatga chaqirdi", "reply": "✉️ Javob yozish",
        "cupWin": "🏆 %s kubokni oldi!", "cupWinYou": "Tabriklaymiz! Fakultetingiz hafta g'olibi: %s ball.",
        "cupLost": "🏆 Hafta g'olibi — %s", "cupPlace": "%s %d-o'rinda: %s ball.",
        "cupNone": "🏆 Hafta yakunlandi", "cupNoneB": "Bu hafta g'olib aniqlanmadi.",
        "cupMe": "Siz %s ball qo'shdingiz.", "cupZero": "Siz bu hafta ball to'plamadingiz — yangi haftada fakultetingizga yordam bering.",
        "cupBadge": "Yangi nishon: %s", "cupGo": "🏆 Kubokni ko'rish",
        "cupGal": "Mukofot: +%s galleon hamyoningizga tushdi.",
        "houses": {"gryffindor": "Grifindor", "slytherin": "Sliterin", "ravenclaw": "Reyvenklo", "hufflepuff": "Xaffelpaff"},
        "badges": {"all_films": "Sakkiz qism", "flawless_exam": "Benuqson imtihon", "perfect_week": "Mukammal hafta", "streak_7": "Yetti kun ketma-ket"},
    },
    "ru": {
        "alley": ("Гринготтс ждёт вас", "Путь в Хогвартс начинается с банка волшебников: гоблин хочет осмотреть ваш ключ."),
        "gringotts": ("Двери Гринготтса открыты", "Галлеоны, которые выделил вам Хогвартс, ждут вас в банке."),
        "wand": ("Олливандер ждёт вас", "Не волшебник выбирает палочку, а палочка - волшебника."),
        "ticket": ("Хагрид ждёт на платформе 9¾", "Ваш билет у Хагрида - на вокзале Кингс-Кросс, у кирпичной колонны."),
        "train": ("Хогвартс-экспресс готов к отправлению", "На платформе 9¾ поезд без вас не уйдёт."),
        "sortst": ("Распределяющая шляпа ждёт в Большом зале", "Остался один шаг - на какой факультет вы попадёте?"),
        "house": ("Шляпа ещё не приняла решение", "Ответьте на вопросы до конца - и факультет будет объявлен."),
        "kick": "🦉 <b>Совиная почта</b>",
        "again": "Хогвартс вас не забыл.",
        "open": "🦉 Прочитать письмо",
        "off": "🔕 Не нужно в Telegram",
        "offed": "Хорошо, теперь письма будут только в 🦉 почте внутри приложения. Там же можно включить снова.",
        "dm": "<b>%s</b> написал(а) вам личное сообщение:", "dmN": "<b>%s</b> написал(а) вам %d личных сообщений. Последнее:",
        "dmChess": "♟️ вызывает на шахматную дуэль", "reply": "✉️ Ответить",
        "cupWin": "🏆 %s забирает кубок!", "cupWinYou": "Поздравляем! Ваш факультет - победитель недели: %s очков.",
        "cupLost": "🏆 Победитель недели — %s", "cupPlace": "%s на %d-м месте: %s очков.",
        "cupNone": "🏆 Неделя завершена", "cupNoneB": "На этой неделе победитель не определён.",
        "cupMe": "Вы принесли %s очков.", "cupZero": "На этой неделе у вас нет очков — помогите факультету в новой неделе.",
        "cupBadge": "Новый значок: %s", "cupGo": "🏆 Открыть кубок",
        "cupGal": "Награда: +%s галлеонов в ваш кошелёк.",
        "houses": {"gryffindor": "Гриффиндор", "slytherin": "Слизерин", "ravenclaw": "Когтевран", "hufflepuff": "Пуффендуй"},
        "badges": {"all_films": "Восемь частей", "flawless_exam": "Безупречный экзамен", "perfect_week": "Идеальная неделя", "streak_7": "Семь дней подряд"},
    },
    "en": {
        "alley": ("Gringotts is waiting", "The road to Hogwarts starts at the wizarding bank: a goblin wants to examine your key."),
        "gringotts": ("Gringotts doors are open", "The galleons Hogwarts set aside for you are waiting at the bank."),
        "wand": ("Ollivander is waiting for you", "The wand chooses the wizard, not the other way round."),
        "ticket": ("Hagrid is waiting at Platform 9¾", "Hagrid has your ticket - at King's Cross, by the brick pillar."),
        "train": ("The Hogwarts Express is ready to leave", "On Platform 9¾ the train won't leave without you."),
        "sortst": ("The Sorting Hat is waiting in the Great Hall", "One step left - which house will you join?"),
        "house": ("The Sorting Hat hasn't decided yet", "Answer the questions to the end and your house will be announced."),
        "kick": "🦉 <b>Owl Post</b>",
        "again": "Hogwarts hasn't forgotten you.",
        "open": "🦉 Read the letter",
        "off": "🔕 Not in Telegram",
        "offed": "Fine - letters will now arrive only in the 🦉 post inside the app. You can turn this back on there.",
        "dm": "<b>%s</b> sent you a private message:", "dmN": "<b>%s</b> sent you %d private messages. The latest:",
        "dmChess": "♟️ challenges you to wizard chess", "reply": "✉️ Reply",
        "cupWin": "🏆 %s takes the Cup!", "cupWinYou": "Congratulations! Your house won the week: %s points.",
        "cupLost": "🏆 House of the week — %s", "cupPlace": "%s is in place %d: %s points.",
        "cupNone": "🏆 The week is over", "cupNoneB": "No winner this week.",
        "cupMe": "You earned %s points.", "cupZero": "You earned no points this week — help your house in the new one.",
        "cupBadge": "New badge: %s", "cupGo": "🏆 Open the Cup",
        "cupGal": "Reward: +%s Galleons added to your wallet.",
        "houses": {"gryffindor": "Gryffindor", "slytherin": "Slytherin", "ravenclaw": "Ravenclaw", "hufflepuff": "Hufflepuff"},
        "badges": {"all_films": "All eight parts", "flawless_exam": "Flawless exam", "perfect_week": "Perfect week", "streak_7": "Seven days in a row"},
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
        "CREATE TABLE IF NOT EXISTS pochta_meta (k TEXT PRIMARY KEY, v TEXT);"
        "CREATE TABLE IF NOT EXISTS tarqatma ("
        " id INTEGER PRIMARY KEY AUTOINCREMENT,"
        " sarlavha TEXT NOT NULL, matn TEXT NOT NULL DEFAULT '',"
        " kimga TEXT NOT NULL,"          # JSON: {tur, fakultet, uid, til}
        " bot INTEGER NOT NULL DEFAULT 1,"  # Telegramga ham yuborilsinmi
        " sinov INTEGER NOT NULL DEFAULT 0,"
        " yaratildi TEXT NOT NULL, tugadi TEXT,"
        " jami INTEGER NOT NULL DEFAULT 0, yetdi INTEGER NOT NULL DEFAULT 0,"
        " bloklagan INTEGER NOT NULL DEFAULT 0, ochirilgan INTEGER NOT NULL DEFAULT 0,"
        " xato INTEGER NOT NULL DEFAULT 0);")
    ustun = {r["name"] for r in conn.execute("PRAGMA table_info(pochta)")}
    if "tarqatma_id" not in ustun:
        conn.execute("ALTER TABLE pochta ADD COLUMN tarqatma_id INTEGER")
    # Shaxsiy xabar xati: kimdan (uid), ismi va oxirgi xabarning boshi
    # ochirildi: odam xatni ilovadagi pochtadan o'chirgan (panel hisobida qoladi, ro'yxatda ko'rinmaydi)
    for nom, tur in (("kimdan", "INTEGER"), ("ism", "TEXT"), ("matn", "TEXT"), ("ochirildi", "TEXT")):
        if nom not in ustun:
            conn.execute("ALTER TABLE pochta ADD COLUMN %s %s" % (nom, tur))
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
        eslatma = {}     # (odam, kutilayotgan qadam) -> (nechta eslatma, oxirgisi qachon)
        for r in conn.execute("SELECT user_id, qadam, COUNT(*) AS n, MAX(yaratildi) AS oxiri FROM pochta "
                              "WHERE tur='onb' GROUP BY user_id, qadam"):
            eslatma[(r["user_id"], r["qadam"])] = (r["n"], r["oxiri"])
        uylar = {r["user_id"] for r in conn.execute("SELECT user_id FROM users WHERE house IS NOT NULL")}
    finally:
        conn.close()

    out = []
    for uid, q in qadamlar.items():
        if uid <= 0 or "letter" not in q or "house" in q or uid in uylar:
            continue
        keyingi = next((s for s in YOL if s not in q), None)
        if not keyingi:
            continue
        n, oxiri = eslatma.get((uid, keyingi), (0, None))
        jim = hozir - max(hpcup._parse_iso(v) for v in q.values())
        if n == 0 and jim >= BIRINCHI:
            out.append((uid, keyingi, 1))
        elif n == 1 and jim >= IKKINCHI and hozir - hpcup._parse_iso(oxiri) >= ORALIQ:
            out.append((uid, keyingi, 2))
        elif n >= 2 and hozir - hpcup._parse_iso(oxiri) >= HAFTA:
            out.append((uid, keyingi, n + 1))
    return out


def _yarat(uid, keyingi, n, vaqt=None):
    conn = _ulan()
    try:
        cur = conn.execute("INSERT INTO pochta (user_id, tur, qadam, n, yaratildi) VALUES (?,?,?,?,?)",
                           (uid, "onb", keyingi, n, vaqt or _hozir()))
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


async def _botga(bot, uid, pid, matn_ol, tugma=None, ovozsiz=False):
    """Bot xabari (o'chirmagan bo'lsa). matn_ol(lang) -> HTML matn. Holatni qaytaradi.
    tugma: (kalit, havola qo'shimchasi) - masalan ("reply", "&dm=5")."""
    if not await asyncio.to_thread(_bot_yoqmi, uid):
        await asyncio.to_thread(_bot_holat, pid, "ochirilgan")
        return "ochirilgan"
    lang = (await hpcup.get_lang(uid)) or "uz"
    t = MATN.get(lang) or MATN["uz"]
    kalit, qosh = tugma or ("open", "")
    # Bot xabarida "Telegramda kerak emas" tugmasi YO'Q (egasi, 2026-10-03): o'chirish faqat
    # ilovadagi pochta sozlamasidan. Eski xabarlardagi tugma ishlayveradi (owl_off).
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=t[kalit], web_app=WebAppInfo(
            url="%s?lang=%s&owl=1%s" % (_cfg.get("webapp_url", ""), lang, qosh)))]])
    holat = "xato"
    for urinish in range(2):
        try:
            await bot.send_message(uid, matn_ol(lang), parse_mode="HTML", reply_markup=kb,
                                   disable_notification=ovozsiz)
            holat = "yuborildi"
            break
        except TelegramRetryAfter as e:          # Telegram "sekinroq" desa - kutib, bir marta qayta
            await asyncio.sleep(min(int(e.retry_after) + 1, 60))
        except TelegramForbiddenError:
            holat = "bloklagan"
            break
        except Exception as e:
            logging.error("Pochta xabarini yuborishda xato (%s): %s", uid, e)
            break
    await asyncio.to_thread(_bot_holat, pid, holat)
    return holat


async def _yubor(bot, uid, pid, keyingi, n):
    return await _botga(bot, uid, pid, lambda lang: bot_matni(lang, keyingi, n))


async def aylana(bot, hozir=None):
    """Bitta tekshiruv: eslatma kerak bo'lganlarga xat yaratib, botdan yuboradi."""
    hozir = hozir or hpcup.now_tk()
    tk = hozir.astimezone(hpcup.TASHKENT)
    if not (SOAT_BOSH <= tk.hour < SOAT_OXIR):
        return []
    natija = []
    for uid, keyingi, n in await asyncio.to_thread(_nomzodlar, hozir.astimezone(timezone.utc)):
        pid = await asyncio.to_thread(_yarat, uid, keyingi, n, hpcup._utc_iso(hozir))
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
        try:
            await kubok_tekshir(bot)
        except Exception as e:
            logging.error("Kubok natijasi xatida xato: %s", e)
        await asyncio.sleep(interval)


# ---------------------------------------------------------------- ilova uchun

def _royxat(uid):
    conn = _ulan()
    try:
        rows = conn.execute("SELECT p.id, p.tur, p.qadam, p.n, p.yaratildi, p.oqildi, p.bajarildi, "
                            "p.kimdan, p.ism, p.matn AS dm_matn, "
                            "t.sarlavha, t.matn FROM pochta p LEFT JOIN tarqatma t ON t.id = p.tarqatma_id "
                            "WHERE p.user_id=? AND p.ochirildi IS NULL ORDER BY p.id DESC LIMIT 50",
                            (int(uid),)).fetchall()
    finally:
        conn.close()
    items = []
    for r in rows:
        x = {"id": r["id"], "tur": r["tur"], "qadam": r["qadam"], "n": r["n"], "t": r["yaratildi"],
             "read": bool(r["oqildi"]), "done": bool(r["bajarildi"])}
        if r["tur"] == "xabar":
            x["title"], x["text"] = r["sarlavha"] or "", r["matn"] or ""
        elif r["tur"] == "kubok":
            try:
                x["cup"] = json.loads(r["dm_matn"] or "{}")
            except ValueError:
                x["cup"] = {}
        elif r["tur"] == "dm":
            x["from"], x["name"], x["text"] = r["kimdan"], r["ism"] or "", r["dm_matn"] or ""
        items.append(x)
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


def _ochir(uid, ids):
    """Odam o'z xatlarini pochtadan o'chiradi (yumshoq: qator qoladi, ro'yxatda ko'rinmaydi)."""
    if not ids:
        return
    conn = _ulan()
    try:
        v = _hozir()
        q = ",".join("?" * len(ids))
        conn.execute("UPDATE pochta SET ochirildi=?, oqildi=COALESCE(oqildi, ?) "
                     "WHERE user_id=? AND ochirildi IS NULL AND id IN (%s)" % q,
                     [v, v, int(uid)] + [int(i) for i in ids])
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
        elif amal == "delete":
            ids = body.get("ids")
            ids = [int(i) for i in ids][:100] if isinstance(ids, list) else []
            await asyncio.to_thread(_ochir, uid, ids)
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


# ---------------------------------------------------------------- shaxsiy xabar

DM_KUT = 60                         # shuncha soniyada o'qilmasa - xat
DM_BOT_ORALIQ = timedelta(hours=1)  # bitta suhbatdan bot xabari soatiga bir marta
_dm_qulf = {}


def _dm_oqildimi(room, uid, msg_id):
    conn = _ulan()
    try:
        r = conn.execute("SELECT last_id FROM chat_reads WHERE user_id=? AND room=?", (int(uid), room)).fetchone()
        return bool(r and r["last_id"] >= int(msg_id))
    finally:
        conn.close()


def _dm_yoz(uid, kimdan, ism, matn, hozir):
    """Xat yaratadi yoki o'qilmaganini yangilaydi. (pid, n, bot_kerakmi) qaytaradi."""
    conn = _ulan()
    try:
        r = conn.execute("SELECT id, n FROM pochta WHERE user_id=? AND tur='dm' AND kimdan=? "
                         "AND oqildi IS NULL AND bajarildi IS NULL AND ochirildi IS NULL ORDER BY id DESC LIMIT 1",
                         (int(uid), int(kimdan))).fetchone()
        if r:
            conn.execute("UPDATE pochta SET n=n+1, ism=?, matn=? WHERE id=?", (ism, matn, r["id"]))
            conn.commit()
            return r["id"], r["n"] + 1, False
        oxirgi = conn.execute("SELECT MAX(bot_vaqt) FROM pochta WHERE user_id=? AND tur='dm' AND kimdan=? "
                              "AND bot_holat='yuborildi'", (int(uid), int(kimdan))).fetchone()[0]
        cur = conn.execute("INSERT INTO pochta (user_id, tur, n, yaratildi, kimdan, ism, matn) VALUES (?,?,?,?,?,?,?)",
                           (int(uid), "dm", 1, hpcup._utc_iso(hozir), int(kimdan), ism, matn))
        conn.commit()
        bot_kerak = not oxirgi or hozir - hpcup._parse_iso(oxirgi) >= DM_BOT_ORALIQ
        return cur.lastrowid, 1, bot_kerak
    finally:
        conn.close()


def dm_bot_matni(lang, ism, matn, n, chess=False):
    t = MATN.get(lang) or MATN["uz"]
    bosh = (t["dmN"] % (_esc(ism), n)) if n > 1 else (t["dm"] % _esc(ism))
    return t["kick"] + "\n\n" + bosh + "\n<i>«" + _esc(t["dmChess"] if chess else matn) + "»</i>"


async def shaxsiy_ishla(peer, kimdan, ism, matn, room, msg_id, chess=False, kut=DM_KUT, hozir=None):
    """Shaxsiy xabardan keyin chaqiriladi (fonda). O'qilmasa - xat va bot xabari."""
    if int(peer) <= 0 or int(kimdan) <= 0:
        return None
    await asyncio.sleep(kut)
    if await asyncio.to_thread(_dm_oqildimi, room, peer, msg_id):
        return None                              # chatda turib o'qidi - xat kerak emas
    matn = ("♟️" if chess else (matn or "").strip())[:140]
    qulf = _dm_qulf.setdefault((int(peer), int(kimdan)), asyncio.Lock())
    async with qulf:
        hozir = hozir or hpcup.now_tk()
        pid, n, bot_kerak = await asyncio.to_thread(_dm_yoz, peer, kimdan, ism or "Sehrgar", matn, hozir)
    if not bot_kerak or not _cfg.get("bot"):
        return "ilovada"
    soat = hozir.astimezone(hpcup.TASHKENT).hour
    return await _botga(_cfg["bot"], int(peer), pid,
                        lambda lang: dm_bot_matni(lang, ism or "Sehrgar", matn, n, chess),
                        tugma=("reply", "&dm=%d" % int(kimdan)), ovozsiz=not (8 <= soat < 22))


def shaxsiy(peer, kimdan, ism, matn, room, msg_id, chess=False):
    """hpbot shaxsiy xabar yozilganda chaqiradi - kutmaydi, fonda ishlaydi."""
    try:
        asyncio.get_running_loop().create_task(
            shaxsiy_ishla(peer, kimdan, ism, matn, room, msg_id, chess))
    except Exception as e:
        logging.error("Shaxsiy xabar xatida xato: %s", e)


def _dm_oqidi(uid, kimdan):
    conn = _ulan()
    try:
        v = _hozir()
        conn.execute("UPDATE pochta SET oqildi=COALESCE(oqildi, ?), bajarildi=? WHERE user_id=? AND tur='dm' "
                     "AND kimdan=? AND bajarildi IS NULL", (v, v, int(uid), int(kimdan)))
        conn.commit()
    finally:
        conn.close()


async def dm_oqidi(uid, kimdan):
    """Suhbatni ochib o'qidi yoki javob yozdi - o'sha odamdan kelgan xat yopiladi."""
    if not kimdan or int(uid) <= 0:
        return
    try:
        await asyncio.to_thread(_dm_oqidi, uid, kimdan)
    except Exception as e:
        logging.error("Shaxsiy xatni yopishda xato: %s", e)


# ---------------------------------------------------------------- kubok natijasi

def _esc(x):
    """HTML uchun: < > & qochiriladi, o'zbekcha tutuq belgisi (') o'z holicha qoladi."""
    return html.escape(x, quote=False)


def _son(n):
    return "{:,}".format(int(n)).replace(",", " ")


def kubok_matni(lang, d):
    """d: {g: g'olib|None, uy, orin, uy_ball, ball, nish: [...]} -> (sarlavha, matn)."""
    t = MATN.get(lang) or MATN["uz"]
    uy = t["houses"].get(d.get("uy"), d.get("uy") or "")
    if not d.get("g"):
        sar, qator = t["cupNone"], [t["cupNoneB"]]
    elif d.get("g") == d.get("uy"):
        sar, qator = t["cupWin"] % uy, [t["cupWinYou"] % _son(d.get("uy_ball", 0))]
    else:
        sar = t["cupLost"] % t["houses"].get(d["g"], d["g"])
        qator = [t["cupPlace"] % (uy, d.get("orin") or 0, _son(d.get("uy_ball", 0)))]
    qator.append(t["cupMe"] % _son(d["ball"]) if d.get("ball") else t["cupZero"])
    for b in d.get("nish") or []:
        qator.append("🎖 " + t["cupBadge"] % t["badges"].get(b, b))
    if d.get("gal"):
        qator.append("🪙 " + t["cupGal"] % _son(d["gal"]))
    return sar, "\n".join(qator)


def _kubok_yangi(birinchi=False):
    """Hali xat yozilmagan yopiq mavsumlar. Birinchi ishga tushishda eskilari o'tkazib yuboriladi."""
    conn = _ulan()
    try:
        r = conn.execute("SELECT v FROM pochta_meta WHERE k='kubok_oxirgi'").fetchone()
        eng = conn.execute("SELECT COALESCE(MAX(id), 0) FROM seasons WHERE status='closed'").fetchone()[0]
        if r is None:
            conn.execute("INSERT OR REPLACE INTO pochta_meta (k, v) VALUES ('kubok_oxirgi', ?)", (str(eng),))
            conn.commit()
            return []
        return [x[0] for x in conn.execute(
            "SELECT id FROM seasons WHERE status='closed' AND id > ? ORDER BY id", (int(r["v"]),))]
    finally:
        conn.close()


def _kubok_yoz(season_id):
    """Mavsum uchun har saralangan odamga xat. Yozilgan xatlar soni."""
    jadval = hpcup._leaderboard(season_id)
    conn = _ulan()
    try:
        g = conn.execute("SELECT winner_house FROM seasons WHERE id=?", (season_id,)).fetchone()[0]
        orin = {x["house"]: (i + 1, x["total_points"]) for i, x in enumerate(jadval)}
        ball = {r[0]: r[1] for r in conn.execute(
            "SELECT user_id, SUM(points) FROM points WHERE season_id=? GROUP BY user_id", (season_id,))}
        nish = {}
        for r in conn.execute("SELECT user_id, code FROM badges WHERE season_id=?", (season_id,)):
            nish.setdefault(r[0], []).append(r[1])
        gal = {r[0]: r[1] for r in conn.execute(
            "SELECT user_id, jami FROM galleon_mukofot WHERE season_id=?", (season_id,))}
        v, n = _hozir(), 0
        for uid, uy in conn.execute("SELECT user_id, house FROM users WHERE house IS NOT NULL AND user_id > 0"):
            o, ub = orin.get(uy, (None, 0))
            d = {"s": season_id, "g": g, "uy": uy, "orin": o, "uy_ball": ub,
                 "ball": int(ball.get(uid) or 0), "nish": nish.get(uid, []), "gal": int(gal.get(uid) or 0)}
            # Bot xabari faqat shu hafta ball to'plaganlarga; qolganlarga faqat ilovada
            conn.execute("INSERT INTO pochta (user_id, tur, qadam, n, yaratildi, matn, bot_holat) VALUES (?,?,?,?,?,?,?)",
                         (uid, "kubok", str(season_id), 1, v, json.dumps(d), None if d["ball"] else "jim"))
            n += 1
        conn.execute("INSERT OR REPLACE INTO pochta_meta (k, v) VALUES ('kubok_oxirgi', ?)", (str(season_id),))
        conn.commit()
        return n
    finally:
        conn.close()


def _kubok_kutayotgan(limit=2000):
    conn = _ulan()
    try:
        chegara = hpcup._utc_iso(hpcup.now_tk() - timedelta(days=2))
        return [(r["id"], r["user_id"], json.loads(r["matn"])) for r in conn.execute(
            "SELECT id, user_id, matn FROM pochta WHERE tur='kubok' AND bot_holat IS NULL AND yaratildi >= ? "
            "ORDER BY id LIMIT ?", (chegara, limit))]
    finally:
        conn.close()


async def kubok_tekshir(bot, hozir=None):
    """Yangi yopilgan hafta bo'lsa - xatlar; kunduzi - kutib turgan bot xabarlari."""
    for sid in await asyncio.to_thread(_kubok_yangi):
        n = await asyncio.to_thread(_kubok_yoz, sid)
        logging.info("Kubok natijasi pochtaga: mavsum %s, %d ta xat", sid, n)
    tk = (hozir or hpcup.now_tk()).astimezone(hpcup.TASHKENT)
    if not (SOAT_BOSH <= tk.hour < SOAT_OXIR):
        return 0
    yuborildi = 0
    for pid, uid, d in await asyncio.to_thread(_kubok_kutayotgan):
        def matn_ol(lang, d=d):
            sar, m = kubok_matni(lang, d)
            t = MATN.get(lang) or MATN["uz"]
            return t["kick"] + "\n\n<b>" + _esc(sar) + "</b>\n" + _esc(m)
        await _botga(bot, uid, pid, matn_ol, tugma=("cupGo", "&cup=1"))
        yuborildi += 1
        await asyncio.sleep(0.05)
    return yuborildi


# ---------------------------------------------------------------- qo'lda xat (tarqatma)

TILLAR = ("uz", "ru", "en")
FAKULTETLAR = ("gryffindor", "slytherin", "ravenclaw", "hufflepuff")
_tarqatma_band = {"id": None}


def _kimlar(kimga):
    """Kimga qoidasi -> uid ro'yxati. Noto'g'ri qoida bo'lsa ValueError."""
    tur = str(kimga.get("tur", ""))
    til = str(kimga.get("til") or "")
    if til and til not in TILLAR:
        raise ValueError("til")
    if tur == "men":
        return sorted(int(i) for i in _cfg.get("admin_ids", ()) if int(i) > 0)
    if tur == "odam":
        try:
            uid = int(kimga.get("uid"))
        except (TypeError, ValueError):
            raise ValueError("uid")
        return [uid] if uid > 0 else []
    sql, arg = "SELECT user_id FROM users WHERE user_id > 0", []
    if tur == "fakultet":
        if kimga.get("fakultet") not in FAKULTETLAR:
            raise ValueError("fakultet")
        sql += " AND house = ?"
        arg.append(kimga["fakultet"])
    elif tur == "saralanmagan":
        sql += " AND house IS NULL"
    elif tur != "hamma":
        raise ValueError("tur")
    if til:
        sql += " AND COALESCE(lang, 'uz') = ?"
        arg.append(til)
    conn = _ulan()
    try:
        return [r[0] for r in conn.execute(sql + " ORDER BY user_id", arg)]
    finally:
        conn.close()


def _tarqatma_yarat(sarlavha, matn, kimga, bot, sinov, uidlar):
    conn = _ulan()
    try:
        cur = conn.execute("INSERT INTO tarqatma (sarlavha, matn, kimga, bot, sinov, yaratildi, jami) "
                           "VALUES (?,?,?,?,?,?,?)",
                           (sarlavha, matn, json.dumps(kimga, ensure_ascii=False), 1 if bot else 0,
                            1 if sinov else 0, _hozir(), len(uidlar)))
        tid = cur.lastrowid
        conn.executemany("INSERT INTO pochta (user_id, tur, n, yaratildi, tarqatma_id) VALUES (?,?,?,?,?)",
                         [(u, "xabar", 1, _hozir(), tid) for u in uidlar])
        conn.commit()
        pidlar = [(r["id"], r["user_id"]) for r in
                  conn.execute("SELECT id, user_id FROM pochta WHERE tarqatma_id=? ORDER BY id", (tid,))]
        return tid, pidlar
    finally:
        conn.close()


def _tarqatma_sana(tid, tugadi=False):
    conn = _ulan()
    try:
        s = {r["bot_holat"]: r["n"] for r in conn.execute(
            "SELECT bot_holat, COUNT(*) AS n FROM pochta WHERE tarqatma_id=? GROUP BY bot_holat", (tid,))}
        conn.execute("UPDATE tarqatma SET yetdi=?, bloklagan=?, ochirilgan=?, xato=?" +
                     (", tugadi=?" if tugadi else "") + " WHERE id=?",
                     [s.get("yuborildi", 0), s.get("bloklagan", 0), s.get("ochirilgan", 0), s.get("xato", 0)] +
                     ([_hozir()] if tugadi else []) + [tid])
        conn.commit()
    finally:
        conn.close()


def xabar_matni(sarlavha, matn, lang):
    t = MATN.get(lang) or MATN["uz"]
    return (t["kick"] + "\n\n<b>" + _esc(sarlavha) + "</b>" +
            ("\n" + _esc(matn) if matn else ""))


async def _tarqat(bot, tid, pidlar, sarlavha, matn, botga):
    try:
        if botga:
            for i, (pid, uid) in enumerate(pidlar):
                await _botga(bot, uid, pid, lambda lang: xabar_matni(sarlavha, matn, lang))
                if i % 25 == 24:
                    await asyncio.to_thread(_tarqatma_sana, tid)
                await asyncio.sleep(0.05)     # Telegram chegarasi: soniyasiga ~20 ta
        await asyncio.to_thread(_tarqatma_sana, tid, True)
        logging.info("Tarqatma #%s tugadi: %d kishi", tid, len(pidlar))
    except Exception as e:
        logging.error("Tarqatma #%s da xato: %s", tid, e)
        await asyncio.to_thread(_tarqatma_sana, tid, True)
    finally:
        _tarqatma_band["id"] = None


async def odamga_xat(uid, matnlar, botga=True):
    """Bitta odamga o'z tilida xat (va bot xabari): matnlar = {til: (sarlavha, matn)}. Duel eslatmalari uchun."""
    lang = (await hpcup.get_lang(uid)) or "uz"
    sarlavha, matn = matnlar.get(lang) or matnlar["uz"]
    tid, pidlar = await asyncio.to_thread(_tarqatma_yarat, sarlavha, matn, {"tur": "odam", "uid": int(uid)}, botga, False, [int(uid)])
    if botga:
        for pid, u in pidlar:
            await _botga(_cfg["bot"], u, pid, lambda l: xabar_matni(sarlavha, matn, l))
    await asyncio.to_thread(_tarqatma_sana, tid, True)


async def tilda_tarqat(matnlar, botga=True):
    """{til: (sarlavha, matn)} - har tildagi odamlarga o'z tilida xat (va bot xabari).
    Ketma-ket yuboradi; boshqa tarqatma ketayotgan bo'lsa navbat kutadi. Serial e'loni uchun."""
    for til, (sarlavha, matn) in matnlar.items():
        while _tarqatma_band["id"]:
            await asyncio.sleep(2)
        kimga = {"tur": "hamma", "til": til}
        uidlar = await asyncio.to_thread(_kimlar, kimga)
        if not uidlar:
            continue
        tid, pidlar = await asyncio.to_thread(_tarqatma_yarat, sarlavha, matn, kimga, botga, False, uidlar)
        _tarqatma_band["id"] = tid
        await _tarqat(_cfg["bot"], tid, pidlar, sarlavha, matn, botga)


def _tarqatmalar():
    conn = _ulan()
    try:
        out = []
        for r in conn.execute("SELECT * FROM tarqatma ORDER BY id DESC LIMIT 100"):
            q = conn.execute("SELECT SUM(oqildi IS NOT NULL) AS oq, SUM(bosildi IS NOT NULL) AS bos "
                             "FROM pochta WHERE tarqatma_id=?", (r["id"],)).fetchone()
            out.append({"id": r["id"], "sarlavha": r["sarlavha"], "matn": r["matn"],
                        "kimga": json.loads(r["kimga"]), "bot": bool(r["bot"]), "sinov": bool(r["sinov"]),
                        "t": r["yaratildi"], "tugadi": r["tugadi"], "jami": r["jami"], "yetdi": r["yetdi"],
                        "bloklagan": r["bloklagan"], "ochirilgan": r["ochirilgan"], "xato": r["xato"],
                        "oqidi": q["oq"] or 0, "bosdi": q["bos"] or 0})
        return out
    finally:
        conn.close()


async def api_tarqatma(request):
    """Panel: hisob (nechta odamga boradi), yubor, royxat. Kalit - X-Dash-Token."""
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    if not _cfg["dash_ok"](request):
        return cors(web.json_response({"ok": False}, status=403))
    try:
        body = await request.json() if request.method == "POST" else {}
    except Exception:
        body = {}
    amal = str(body.get("action", "royxat"))
    try:
        if amal == "royxat":
            return cors(web.json_response({"ok": True, "tarqatmalar": await asyncio.to_thread(_tarqatmalar),
                                           "band": _tarqatma_band["id"]}))
        kimga = body.get("kimga") if isinstance(body.get("kimga"), dict) else {}
        try:
            uidlar = await asyncio.to_thread(_kimlar, kimga)
        except ValueError as e:
            return cors(web.json_response({"ok": False, "error": "kimga_" + str(e)}, status=400))
        if amal == "hisob":
            return cors(web.json_response({"ok": True, "soni": len(uidlar)}))
        if amal != "yubor":
            return cors(web.json_response({"ok": False, "error": "amal"}, status=400))
        sarlavha = str(body.get("sarlavha", "")).strip()[:120]
        matn = str(body.get("matn", "")).strip()[:2000]
        if not sarlavha:
            return cors(web.json_response({"ok": False, "error": "sarlavha"}, status=400))
        if not uidlar:
            return cors(web.json_response({"ok": False, "error": "hech_kim"}, status=400))
        if _tarqatma_band["id"]:
            return cors(web.json_response({"ok": False, "error": "band", "band": _tarqatma_band["id"]}, status=409))
        botga = bool(body.get("bot", True))
        tid, pidlar = await asyncio.to_thread(_tarqatma_yarat, sarlavha, matn, kimga, botga,
                                              kimga.get("tur") == "men", uidlar)
        _tarqatma_band["id"] = tid
        asyncio.create_task(_tarqat(_cfg["bot"], tid, pidlar, sarlavha, matn, botga))
        return cors(web.json_response({"ok": True, "id": tid, "soni": len(uidlar)}))
    except Exception as e:
        logging.error("Tarqatma amalida xato (%s): %s", amal, e)
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
    """cfg: bot, cors, verify_init_data, dash_ok, webapp_url, admin_ids."""
    _cfg.update(cfg)
    _ulan().close()
    app.router.add_route('*', '/api/pochta', api_pochta)
    app.router.add_route('*', '/api/pochtapanel', api_pochtapanel)
    app.router.add_route('*', '/api/pochta/tarqatma', api_tarqatma)
    dp.callback_query.register(owl_off, F.data == "owl_off")
