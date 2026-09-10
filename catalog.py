# -*- coding: utf-8 -*-
"""Garri Potter katalogi — filmlar ro'yxati va ularning kanaldagi manzillari.

Bu fayl loyihaning YAGONA ma'lumot manbai. Film qo'shish yoki o'zgartirish
uchun faqat shu yerga tegiladi.

Ilgari bu ro'yxat ikki joyda turardi: shu yerda (bot uchun) va WebApp'ning
index.html fayli ichida (kartalar uchun). Bittasini tuzatib ikkinchisini
unutish oson edi va bu noto'g'ri film yuborilishiga olib kelardi.

Endi WebApp'dagi ro'yxat shu fayldan GENERATSIYA qilinadi:

    python3 tools/webappdata.py            # index.html ni yangilaydi
    python3 tools/webappdata.py --korish   # faqat ko'rsatadi, tegmaydi

(bu buyruq CatalogWebApp papkasida ishlatiladi)

Har bir film qanday saqlanadi:

    "hp1": {
        "kind": "hp",       # "hp" = asosiy seriya, "fb" = Fantastik Maxluqlar
        "order": 1,         # seriya ichidagi tartib raqami
        "num": "I",         # kartada ko'rinadigan rim raqami
        "year": 2001,
        "uz": {"title": ..., "caption": ..., "message_id": 40},
        "ru": {...},
        "en": {...},
    }

MUHIM — `message_id`:

    Bu filmning YOPIQ kanaldagi xabar raqami. Bot filmni o'sha yerdan
    nusxalab yuboradi.

    `message_id = 0` degani — film bu tilda HALI YUKLANMAGAN. Bunday film:
      * bot tomonidan yuborilmaydi ("tez orada" deb javob beradi);
      * WebApp'da kulrang, bosilmaydigan karta bo'lib ko'rinadi.

    Ya'ni katalogni to'liq yozib qo'yib, fayllarni asta-sekin yuklash
    mumkin — hech narsa buzilmaydi va foydalanuvchi oldindan biladi.

`title` va `caption` farqi:
    `title`   — kartadagi qisqa nom ("Hikmatlar Toshi")
    `caption` — film ostidagi to'liq yozuv ("<b>1. Garri Potter va ...</b>")

`vk_url` — ixtiyoriy. Bo'lsa, film ostida "4K formatda ko'rish" tugmasi
chiqadi. Hozir faqat Fantastik Maxluqlarning o'zbekcha versiyalarida bor.
"""

# Qo'llab-quvvatlanadigan tillar. Chuqur havoladagi til shu ro'yxatga
# qarab tekshiriladi (`hp1_uz` dagi `uz`).
LANGS = ("uz", "ru", "en")

# Seriyalar — WebApp'dagi bo'limlar bilan bir xil tartibda
SERIES = {
    "hp": "Garri Potter",
    "fb": "Fantastik Maxluqlar",
}


FILMS = {
    "hp1": {
        "kind": "hp", "order": 1, "num": "I", "year": 2001,
        "uz": {"title": "Hikmatlar Toshi", "caption": "<b>1. Garri Potter va Hikmatlar Toshi</b>", "message_id": 40},
        "ru": {"title": "Философский Камень", "caption": "<b>1. Гарри Поттер и Философский Камень</b>", "message_id": 18},
        "en": {"title": "Philosopher's Stone", "caption": "<b>1. Harry Potter and the Philosopher's Stone</b>", "message_id": 10},
    },
    "hp2": {
        "kind": "hp", "order": 2, "num": "II", "year": 2002,
        "uz": {"title": "Maxfiy Hujra", "caption": "<b>2. Garri Potter va Maxfiy Hujra</b>", "message_id": 27},
        "ru": {"title": "Тайная Комната", "caption": "<b>2. Гарри Поттер и Тайная Комната</b>", "message_id": 19},
        "en": {"title": "Chamber of Secrets", "caption": "<b>2. Harry Potter and the Chamber of Secrets</b>", "message_id": 11},
    },
    "hp3": {
        "kind": "hp", "order": 3, "num": "III", "year": 2004,
        "uz": {"title": "Azkaban Mahbusi", "caption": "<b>3. Garri Potter va Azkaban Mahbusi</b>", "message_id": 28},
        "ru": {"title": "Узник Азкабана", "caption": "<b>3. Гарри Поттер и Узник Азкабана</b>", "message_id": 20},
        "en": {"title": "Prisoner of Azkaban", "caption": "<b>3. Harry Potter and the Prisoner of Azkaban</b>", "message_id": 12},
    },
    "hp4": {
        "kind": "hp", "order": 4, "num": "IV", "year": 2005,
        "uz": {"title": "Alanga Kubogi", "caption": "<b>4. Garri Potter va Alanga Kubogi</b>", "message_id": 29},
        "ru": {"title": "Кубок Огня", "caption": "<b>4. Гарри Поттер и Кубок Огня</b>", "message_id": 21},
        "en": {"title": "Goblet of Fire", "caption": "<b>4. Harry Potter and the Goblet of Fire</b>", "message_id": 13},
    },
    "hp5": {
        "kind": "hp", "order": 5, "num": "V", "year": 2007,
        "uz": {"title": "Feniks Jamiyati", "caption": "<b>5. Garri Potter va Feniks Jamiyati</b>", "message_id": 30},
        "ru": {"title": "Орден Феникса", "caption": "<b>5. Гарри Поттер и Орден Феникса</b>", "message_id": 22},
        "en": {"title": "Order of the Phoenix", "caption": "<b>5. Harry Potter and the Order of the Phoenix</b>", "message_id": 14},
    },
    "hp6": {
        "kind": "hp", "order": 6, "num": "VI", "year": 2009,
        "uz": {"title": "Tilsim Shaxzodasi", "caption": "<b>6. Garri Potter va Tilsim Shaxzodasi</b>", "message_id": 31},
        "ru": {"title": "Принц Полукровка", "caption": "<b>6. Гарри Поттер и Принц Полукровка</b>", "message_id": 23},
        "en": {"title": "Half-Blood Prince", "caption": "<b>6. Harry Potter and the Half-Blood Prince</b>", "message_id": 15},
    },
    "hp7": {
        "kind": "hp", "order": 7, "num": "VII", "year": 2010,
        "uz": {"title": "Ajal Tuhfasi 1", "caption": "<b>7. Garri Potter va Ajal Tuhfasi 1</b>", "message_id": 32},
        "ru": {"title": "Дары Смерти 1", "caption": "<b>7. Гарри Поттер и Дары Смерти Часть I</b>", "message_id": 24},
        "en": {"title": "Deathly Hallows 1", "caption": "<b>7. Harry Potter and the Deathly Hallows Part 1</b>", "message_id": 16},
    },
    "hp8": {
        "kind": "hp", "order": 8, "num": "VIII", "year": 2011,
        "uz": {"title": "Ajal Tuhfasi 2", "caption": "<b>8. Garri Potter va Ajal Tuhfasi 2</b>", "message_id": 33},
        "ru": {"title": "Дары Смерти 2", "caption": "<b>8. Гарри Поттер и Дары Смерти Часть II</b>", "message_id": 25},
        "en": {"title": "Deathly Hallows 2", "caption": "<b>8. Harry Potter and the Deathly Hallows Part 2</b>", "message_id": 17},
    },

    "fb1": {
        "kind": "fb", "order": 1, "num": "I", "year": 2016,
        "uz": {"title": "Fantastik Maxluqlar", "caption": "<b>1. Fantastik Maxluqlar</b>", "message_id": 34, "vk_url": "https://vkvideo.ru/video-229969354_456239029?list=pykesy7vje26j5qv"},
        "ru": {"title": "Фантастические твари 1", "caption": "<b>1. Фантастические твари и где они обитают</b>", "message_id": 0},
        "en": {"title": "Fantastic Beasts 1", "caption": "<b>1. Fantastic Beasts and Where to Find Them</b>", "message_id": 37},
    },
    "fb2": {
        "kind": "fb", "order": 2, "num": "II", "year": 2018,
        "uz": {"title": "Fantastik Maxluqlar 2", "caption": "<b>2. Fantastik Maxluqlar: Grindelvaldning jinoyatlari</b>", "message_id": 35, "vk_url": "https://vkvideo.ru/video-229969354_456239030?list=6lwnawgzdaa2jnwg"},
        "ru": {"title": "Фантастические твари 2", "caption": "<b>2. Фантастические твари: Преступления Грин-де-Вальда</b>", "message_id": 0},
        "en": {"title": "Fantastic Beasts 2", "caption": "<b>2. Fantastic Beasts: The Crimes of Grindelwald</b>", "message_id": 38},
    },
    "fb3": {
        "kind": "fb", "order": 3, "num": "III", "year": 2022,
        "uz": {"title": "Fantastik Maxluqlar 3", "caption": "<b>3. Fantastik Maxluqlar: Dambldor sirlari</b>", "message_id": 36, "vk_url": "https://vkvideo.ru/video-229969354_456239031?list=mrfufjbjfcc3gujn"},
        "ru": {"title": "Фантастические твари 3", "caption": "<b>3. Фантастические твари: Тайны Дамблдора</b>", "message_id": 0},
        "en": {"title": "Fantastic Beasts 3", "caption": "<b>3. Fantastic Beasts: The Secrets of Dumbledore</b>", "message_id": 39},
    },}


# Kanaldagi fayllar sifati. Hozir BARCHA filmlar bitta sifatda. Keyinroq
# 2160p / 720p / 480p qo'shilganda bu har film-til uchun ro'yxatga aylanadi.
QUALITY = "1080p"

# Kinoteatr versiyasining davomiyligi, daqiqada.
RUNTIME = {
    "hp1": 152, "hp2": 161, "hp3": 142, "hp4": 157,
    "hp5": 138, "hp6": 153, "hp7": 146, "hp8": 130,
    "fb1": 133, "fb2": 134, "fb3": 142,
}

# IMDb reytinglari (2026-09 holati). Bir-ikki yilda 0.1 ga siljishi mumkin.
IMDB = {
    "hp1": 7.7, "hp2": 7.4, "hp3": 7.9, "hp4": 7.7,
    "hp5": 7.5, "hp6": 7.6, "hp7": 7.7, "hp8": 8.1,
    "fb1": 7.2, "fb2": 6.5, "fb3": 6.2,
}


# ---------------------------------------------------------------- yordamchi

def ordered():
    """Filmlarni katalogdagi tartibda qaytaradi: (id, film) juftliklari."""
    return list(FILMS.items())


def series(kind):
    """Bitta seriyaning filmlari: kind = "hp" yoki "fb"."""
    return [(fid, f) for fid, f in FILMS.items() if f["kind"] == kind]


def get(film_id, lang):
    """Film ma'lumotini beradi. Topilmasa yoki til noto'g'ri bo'lsa - None."""
    film = FILMS.get(film_id)
    if not film or lang not in LANGS:
        return None
    return film.get(lang)


def is_ready(film_id, lang):
    """Shu film shu tilda yuklanganmi? (message_id = 0 - yuklanmagan)"""
    data = get(film_id, lang)
    return bool(data and data.get("message_id", 0))


def not_ready(lang):
    """Shu tilda hali yuklanmagan filmlar ro'yxati (id lar)."""
    return [fid for fid in FILMS if not is_ready(fid, lang)]


# ---------------------------------------------------------------- qidiruv

# Lotin va kirill harflarini yaqinlashtirish. Foydalanuvchi "Азкабан" deb
# ham, "azkaban" deb ham yozishi mumkin - ikkalasi bir xil topilsin.
_TRANSLIT = {
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "e",
    "ж": "j", "з": "z", "и": "i", "й": "y", "к": "k", "л": "l", "м": "m",
    "н": "n", "о": "o", "п": "p", "р": "r", "с": "s", "т": "t", "у": "u",
    "ф": "f", "х": "x", "ц": "s", "ч": "ch", "ш": "sh", "щ": "sh",
    "ъ": "", "ы": "i", "ь": "", "э": "e", "ю": "yu", "я": "ya",
    # O'zbek lotinidagi shakllar ham bir ko'rinishga keltiriladi
    "'": "", "\u2018": "", "\u2019": "", "`": "", "-": " ",
}


def _oddiy(matn):
    """Qidiruv uchun matnni soddalashtiradi: kichik harf, translit, bo'shliq."""
    matn = (matn or "").lower()
    out = []
    for ch in matn:
        out.append(_TRANSLIT.get(ch, ch))
    matn = "".join(out)
    # h va x ni tenglashtiramiz: "Mahbusi" va "Maxbusi" ikkalasi ham yozilgan
    matn = matn.replace("h", "x")
    return " ".join(matn.split())


def _kalitlar(film_id, film):
    """Shu film uchun qidirilishi mumkin bo'lgan barcha matnlar."""
    s = [film_id, str(film["order"]), film["num"], str(film["year"])]
    for lang in LANGS:
        d = film[lang]
        s.append(d["title"])
        # caption ichida to'liq nom bor: "Garri Potter va Azkaban Maxbusi"
        s.append(d["caption"].replace("<b>", " ").replace("</b>", " "))
    return [_oddiy(x) for x in s]


def search(query, limit=10):
    """So'rov bo'yicha filmlarni topadi. (id, film) juftliklari qaytadi.

    Uch tilda ham qidiradi: nom, to'liq sarlavha, id, tartib raqami, yil.
    Bo'sh so'rov - butun katalog.
    """
    q = _oddiy(query)
    items = list(FILMS.items())
    if not q:
        return items[:limit]

    aniq, qisman = [], []
    for fid, film in items:
        keys = _kalitlar(fid, film)
        if any(k == q for k in keys):
            aniq.append((fid, film))
        elif any(q in k for k in keys):
            qisman.append((fid, film))

    return (aniq + qisman)[:limit]
