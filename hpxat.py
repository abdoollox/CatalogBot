"""Xogvartsdan maktubning rasmi (Telegram Stories uchun).

Ilovadagi "Xatni ulashish" tugmasi shu yerga keladi: pergament foniga
odamning ismi bilan xat yoziladi va 1080x1920 (9:16) JPEG qaytariladi.

Fon rasmi `img/xat_bg.jpg` - generator chizgan bo'sh pergament (matn yo'q,
hamma yozuv shu yerda PIL bilan qo'yiladi). Shrift `fonts/Cormorant*` -
OFL litsenziyasi, lotin va kirill harflari bor.

Fayl `/data/xat/<token>.jpg` ga saqlanadi va bir marta yasalgach qayta
ishlatiladi (token = odam + ism + til).
"""

import hashlib
import logging
import os
import re
import time
import unicodedata

from PIL import Image, ImageDraw, ImageFont

HERE = os.path.dirname(os.path.abspath(__file__))
BG_PATH = os.path.join(HERE, "img", "xat_bg.jpg")
FONT_MAIN = os.path.join(HERE, "fonts", "Cormorant-var.ttf")
FONT_ITALIC = os.path.join(HERE, "fonts", "Cormorant-italic-var.ttf")
OUT_DIR = os.getenv("HP_XAT_DIR", "/data/xat")

W, H = 1080, 1920
INK = (58, 41, 26)          # asosiy siyoh
INK_SOFT = (107, 78, 46)    # sarlavha va imzo
RULE = (137, 111, 74)

# Pergamentning ichki chegarasi (fon rasmiga qarab o'lchangan)
LEFT, RIGHT = 158, 922
TOP = 330
FOOT_Y = 1300          # pergamentning yorug' qismida qolsin

MAX_AGE = 14 * 24 * 3600    # eski rasmlar shuncha vaqtdan keyin o'chadi

TEXTS = {
    "uz": {
        "school": "XOGVARTS JODUGARLIK VA\nSEHRGARLIK MAKTABI",
        "hi": "Hurmatli %s,",
        "body": "Xogvarts maktabida siz uchun joy ajratilganini mamnuniyat bilan "
                "ma'lum qilamiz.",
        "body2": "Darslar sentabrning birinchi kunida boshlanadi. Javobingizni "
                 "iyul oxirigacha boyo'g'li bilan kutamiz.",
        "sign": "Minerva Makgonagall,",
        "sign2": "direktor o'rinbosari",
        "foot": "Garri Potter Kolleksiyasi · t.me/garripotterkinobot",
    },
    "ru": {
        "school": "ШКОЛА ЧАРОДЕЙСТВА И\nВОЛШЕБСТВА «ХОГВАРТС»",
        "hi": "Дорогой(ая) %s!",
        "body": "С удовольствием сообщаем, что вам предоставлено место в школе "
                "«Хогвартс».",
        "body2": "Занятия начинаются первого сентября. Ответ совой ждём "
                 "до конца июля.",
        "sign": "Минерва Макгонагалл,",
        "sign2": "заместитель директора",
        "foot": "Коллекция «Гарри Поттер» · t.me/garripotterkinobot",
    },
    "en": {
        "school": "HOGWARTS SCHOOL OF\nWITCHCRAFT AND WIZARDRY",
        "hi": "Dear %s,",
        "body": "We are pleased to inform you that a place has been reserved for "
                "you at Hogwarts.",
        "body2": "Term begins on the first of September. We await your owl "
                 "before the end of July.",
        "sign": "Minerva McGonagall,",
        "sign2": "Deputy Headmistress",
        "foot": "Harry Potter Collection · t.me/garripotterkinobot",
    },
}


def _font(path, size, weight=None):
    f = ImageFont.truetype(path, size)
    if weight:
        try:
            f.set_variation_by_axes([weight])
        except Exception:
            pass        # o'zgaruvchan o'qi bo'lmasa - oddiy holicha
    return f


def clean_name(raw):
    """Ismni rasmga yozishga yaroqli holga keltiradi.

    Emoji va boshqa belgilar shriftda yo'q - ular kvadrat bo'lib chiqadi,
    shuning uchun faqat harf, raqam, bo'shliq va oddiy tinish qoldiriladi.
    """
    text = unicodedata.normalize("NFC", str(raw or "")).strip()
    kept = [ch for ch in text
            if unicodedata.category(ch)[0] in ("L", "N")
            or ch in " '-.’ʻʼ"]
    out = re.sub(r"\s+", " ", "".join(kept)).strip(" -.")
    return out[:20] or None


def _wrap(draw, text, font, width):
    """Matnni berilgan kenglikka sig'diradi (so'z bo'yicha)."""
    lines, line = [], ""
    for word in text.split():
        probe = (line + " " + word).strip()
        if draw.textlength(probe, font=font) <= width or not line:
            line = probe
        else:
            lines.append(line)
            line = word
    if line:
        lines.append(line)
    return lines


def _spaced(draw, text, font, cx, y, gap=6, fill=INK_SOFT):
    """Harflar orasi kengaytirilgan sarlavha (markazdan)."""
    total = sum(draw.textlength(ch, font=font) + gap for ch in text) - gap
    x = cx - total / 2
    for ch in text:
        draw.text((x, y), ch, font=font, fill=fill)
        x += draw.textlength(ch, font=font) + gap


def render(name, lang, path):
    """Xat rasmini yasab, `path` ga PNG qilib saqlaydi."""
    t = TEXTS.get(lang) or TEXTS["uz"]
    im = Image.open(BG_PATH).convert("RGB")
    if im.size != (W, H):
        im = im.resize((W, H), Image.LANCZOS)
    d = ImageDraw.Draw(im)

    f_school = _font(FONT_MAIN, 30, 600)
    f_hi = _font(FONT_MAIN, 62, 600)
    f_body = _font(FONT_MAIN, 46, 400)
    f_sign = _font(FONT_ITALIC, 44, 500)
    f_foot = _font(FONT_MAIN, 28, 500)

    cx = (LEFT + RIGHT) / 2
    y = TOP
    for line in t["school"].split("\n"):
        _spaced(d, line, f_school, cx, y)
        y += 44
    y += 26
    d.line([(LEFT + 40, y), (RIGHT - 40, y)], fill=RULE, width=2)
    y += 60

    d.text((LEFT, y), t["hi"] % (name or "sehrgar"), font=f_hi, fill=INK)
    y += 96

    for block in (t["body"], t["body2"]):
        for line in _wrap(d, block, f_body, RIGHT - LEFT):
            d.text((LEFT, y), line, font=f_body, fill=INK)
            y += 62
        y += 26

    y += 40
    for line, font in ((t["sign"], f_sign), (t["sign2"], f_sign)):
        w = d.textlength(line, font=font)
        d.text((RIGHT - w, y), line, font=font, fill=INK_SOFT)
        y += 56

    foot_w = d.textlength(t["foot"], font=f_foot)
    d.text((cx - foot_w / 2, FOOT_Y), t["foot"], font=f_foot, fill=INK)

    tmp = path + ".tmp"
    # JPEG: PNG ~3 MB chiqadi, Stories uchun ortiqcha - bu ~400 KB
    im.save(tmp, "JPEG", quality=88, optimize=True, progressive=True)
    os.replace(tmp, path)
    return path


def token_for(user_id, name, lang):
    raw = "%s|%s|%s" % (user_id, name or "", lang)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def _cleanup():
    """Eski rasmlarni o'chiradi - disk to'lib ketmasin."""
    try:
        chegara = time.time() - MAX_AGE
        for nom in os.listdir(OUT_DIR):
            yol = os.path.join(OUT_DIR, nom)
            if os.path.isfile(yol) and os.path.getmtime(yol) < chegara:
                os.remove(yol)
    except Exception as e:
        logging.warning("Xat rasmlarini tozalashda xato: %s", e)


def path_of(token):
    return os.path.join(OUT_DIR, token + ".jpg")


def ensure(user_id, name, lang):
    """Rasmni (kerak bo'lsa) yasaydi va tokenini qaytaradi. Sinxron - to_thread ichida chaqiring."""
    lang = lang if lang in TEXTS else "uz"
    name = clean_name(name)
    os.makedirs(OUT_DIR, exist_ok=True)
    token = token_for(user_id, name, lang)
    yol = path_of(token)
    if not os.path.exists(yol):
        _cleanup()
        render(name, lang, yol)
    return token
