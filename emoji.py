# -*- coding: utf-8 -*-
"""Custom emoji — bot matnlarini bezash uchun.

To'plamlar tayyor, o'zimiz yaratmadik: tgiosicons va TgAndroidIcons.
Ikkalasi ham "adaptiv": Telegram bu belgilarni MATN RANGIGA bo'yaydi,
ya'ni qorong'i va yorug' mavzuda bir xil o'qiladi.

SHART: custom emoji faqat bot EGASIDA Telegram Premium bo'lsa ishlaydi.
Premium tugasa Telegram odatda zaxira belgini ko'rsatadi, lekin ba'zi
holatlarda butun xabarni rad etishi ham mumkin - shuning uchun main.py
dagi send_html() xato bo'lsa oddiy belgilar bilan qayta yuboradi.

Kanallarda ishlamaydi (hujjatda faqat "private, group and supergroup").
Bizda barcha xabarlar shaxsiy chatda - muammo yo'q.

Har bir raqam getCustomEmojiStickers orqali tekshirilgan (2026-09-09).
"""

import re

# nom -> (custom_emoji_id, zaxira belgi)
ICONS = {
    "kolleksiya": ("5888799736508454231", "🖼"),
    "qidiruv":    ("6032850693348399258", "🔎"),
    "tomosha":    ("5773626993010546707", "▶️"),
    "til":        ("5776233299424843260", "🌐"),
    "yopiq":      ("6037249452824072506", "🔒"),
    "tasdiq":     ("5774022692642492953", "✅"),
    "sifat":      ("5942734685976138521", "🖥"),
    "yil":        ("5890937706803894250", "📅"),
    "dostlar":    ("6032609071373226027", "👥"),
}

_TEG = re.compile(r'<tg-emoji emoji-id="\d+">(.*?)</tg-emoji>', re.S)


def tag(name):
    """Matn ichida ishlatiladigan HTML.

    Zaxira belgi teg ICHIDA turadi - Telegram uni custom emoji
    ko'rsatib bo'lmaydigan joyda (bildirishnoma, Premium yo'q) o'zi
    ishlatadi, kod o'zgartirish shart emas.
    """
    item = ICONS.get(name)
    if not item:
        return ""
    return '<tg-emoji emoji-id="%s">%s</tg-emoji>' % item


def icon(name):
    """Tugmaning `icon_custom_emoji_id` maydoni uchun (Bot API 9.4+).

    Tugma matnida HTML ishlamaydi - u yerda faqat shu maydon orqali
    custom emoji qo'yish mumkin. Zaxira mexanizmi yo'q: belgi
    ko'rsatilmasa tugma shunchaki belgisiz qoladi.
    """
    item = ICONS.get(name)
    return item[0] if item else None


def strip_tags(text):
    """Custom emoji teglarini olib tashlab, faqat zaxira belgilarni qoldiradi.

    Xabar custom emoji bilan yuborilmasa - shu variant yuboriladi.
    """
    return _TEG.sub(r"\1", text or "")
