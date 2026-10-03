"""Fakultet rasmi (Telegram Stories / chatga ulashish uchun) - hpxat.py namunasida.

Ilovadagi "Fakultetimni ulashish" shu yerga keladi: qorong'i fon, fakultet bayrami
sahnasi (img/uy/<fakultet>.jpg - dizayn tizimidagi uslubda), gerb, odamning ismi va
fakultet nomi fakultet rangida. 1080x1920 (9:16) JPEG.

Fakultet SERVERDAN olinadi (hp.db) - ilova yuborgan qiymatga ishonilmaydi.
Fayl `/data/uy/<token>.jpg`, token = odam + ism + til + fakultet.
"""

import hashlib
import os

from PIL import Image, ImageDraw, ImageFilter

import hpxat

HERE = os.path.dirname(os.path.abspath(__file__))
ART_DIR = os.path.join(HERE, "img", "uy")
OUT_DIR = os.getenv("HP_UY_DIR", "/data/uy")

W, H = 1080, 1920
BG = (12, 15, 20)
TEXT = (238, 241, 245)
DIM = (152, 162, 179)
GOLD = (231, 193, 112)

HOUSES = {
    "gryffindor": {"rang": (217, 82, 74), "uz": "Grifindor", "ru": "Гриффиндор", "en": "Gryffindor",
                   "note_uz": "Jasorat, matonat va yurak amri", "note_ru": "Храбрость, стойкость и зов сердца",
                   "note_en": "Courage, nerve and heart"},
    "slytherin": {"rang": (47, 163, 107), "uz": "Sliterin", "ru": "Слизерин", "en": "Slytherin",
                  "note_uz": "Maqsad, zukkolik va o'z yo'li", "note_ru": "Амбиции, хитрость и свой путь",
                  "note_en": "Ambition, cunning and a path of one's own"},
    "ravenclaw": {"rang": (91, 143, 217), "uz": "Reyvenklo", "ru": "Когтевран", "en": "Ravenclaw",
                  "note_uz": "Aql, izlanish va bilimga chanqoqlik", "note_ru": "Ум, любознательность и жажда знаний",
                  "note_en": "Wit, curiosity and a thirst for learning"},
    "hufflepuff": {"rang": (232, 185, 60), "uz": "Xaffelpaff", "ru": "Пуффендуй", "en": "Hufflepuff",
                   "note_uz": "Sadoqat, mehnatsevarlik va adolat", "note_ru": "Верность, трудолюбие и справедливость",
                   "note_en": "Loyalty, hard work and fairness"},
}

TEXTS = {
    "uz": {"top": "XOGVARTS · SARALASH MAROSIMI", "said": "Saralovchi qalpoq qaror qildi",
           "anon": "Men", "foot1": "Siz qaysi fakultetdasiz?", "foot2": "t.me/garripotterkinobot"},
    "ru": {"top": "ХОГВАРТС · ЦЕРЕМОНИЯ РАСПРЕДЕЛЕНИЯ", "said": "Распределяющая шляпа решила",
           "anon": "Я", "foot1": "А вы на каком факультете?", "foot2": "t.me/garripotterkinobot"},
    "en": {"top": "HOGWARTS · THE SORTING CEREMONY", "said": "The Sorting Hat has decided",
           "anon": "Me", "foot1": "Which house are you in?", "foot2": "t.me/garripotterkinobot"},
}


def _center(d, text, font, y, fill):
    w = d.textlength(text, font=font)
    d.text(((W - w) / 2, y), text, font=font, fill=fill)


def _fit(d, text, path, size, weight, width):
    """Shriftni matn berilgan kenglikka sig'guncha kichraytiradi."""
    while size > 40:
        f = hpxat._font(path, size, weight)
        if d.textlength(text, font=f) <= width:
            return f
        size -= 6
    return hpxat._font(path, size, weight)


def render(name, lang, house, path):
    t = TEXTS.get(lang) or TEXTS["uz"]
    h = HOUSES[house]
    rang = h["rang"]
    im = Image.new("RGB", (W, H), BG)

    # Tepadan fakultet rangidagi yumshoq yog'du
    glow = Image.new("RGB", (W, H), BG)
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-200, -520, W + 200, 900], fill=tuple(int(c * 0.42) for c in rang))
    glow = glow.filter(ImageFilter.GaussianBlur(190))
    im = Image.blend(im, glow, 0.85)
    d = ImageDraw.Draw(im)

    hpxat._spaced(d, t["top"], hpxat._font(hpxat.FONT_MAIN, 30, 600), W / 2, 150, gap=7, fill=GOLD)

    # Sahna rasmi: yumaloq burchak, fakultet rangida hoshiya
    art = Image.open(os.path.join(ART_DIR, house + ".jpg")).convert("RGB")
    aw, ah = 960, 536
    art = art.resize((aw, ah), Image.LANCZOS)
    mask = Image.new("L", (aw, ah), 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, aw - 1, ah - 1], 34, fill=255)
    ax, ay = (W - aw) // 2, 240
    d.rounded_rectangle([ax - 5, ay - 5, ax + aw + 4, ay + ah + 4], 38, fill=(11, 12, 16))
    d.rounded_rectangle([ax - 3, ay - 3, ax + aw + 2, ay + ah + 2], 36, outline=rang, width=3)
    im.paste(art, (ax, ay), mask)

    # Gerb: rasm ostki chetiga chiqib turadi
    crest = Image.open(os.path.join(ART_DIR, house + ".png")).convert("RGBA")
    cw = 300
    crest = crest.resize((cw, int(crest.height * cw / crest.width)), Image.LANCZOS)
    cy = ay + ah - 110
    soya = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(soya).ellipse([W // 2 - 190, cy + 20, W // 2 + 190, cy + crest.height + 20], fill=(0, 0, 0, 170))
    soya = soya.filter(ImageFilter.GaussianBlur(40))
    im.paste(soya, (0, 0), soya)
    im.paste(crest, ((W - cw) // 2, cy), crest)
    d = ImageDraw.Draw(im)

    y = cy + crest.height + 70
    _center(d, t["said"], hpxat._font(hpxat.FONT_ITALIC, 46, 500), y, DIM)
    y += 92
    kim = (name or t["anon"]) + " —"
    _center(d, kim, _fit(d, kim, hpxat.FONT_MAIN, 76, 500, W - 160), y, TEXT)
    y += 104
    nom = h[lang] if lang in h else h["uz"]
    f_nom = _fit(d, nom, hpxat.FONT_MAIN, 190, 600, W - 120)
    _center(d, nom, f_nom, y, rang)
    y += 240
    d.line([(W / 2 - 60, y), (W / 2 + 60, y)], fill=rang, width=3)
    y += 44
    note = h.get("note_" + lang) or h["note_uz"]
    f_note = hpxat._font(hpxat.FONT_ITALIC, 44, 500)
    for line in hpxat._wrap(d, note, f_note, W - 240):
        _center(d, line, f_note, y, TEXT)
        y += 58

    _center(d, t["foot1"], hpxat._font(hpxat.FONT_MAIN, 40, 600), H - 250, GOLD)
    _center(d, t["foot2"], hpxat._font(hpxat.FONT_MAIN, 30, 500), H - 190, DIM)

    tmp = path + ".tmp"
    im.save(tmp, "JPEG", quality=88, optimize=True, progressive=True)
    os.replace(tmp, path)
    return path


def token_for(user_id, name, lang, house):
    raw = "uy|%s|%s|%s|%s" % (user_id, name or "", lang, house)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def path_of(token):
    return os.path.join(OUT_DIR, token + ".jpg")


def ensure(user_id, name, lang, house):
    """Rasmni (kerak bo'lsa) yasaydi va tokenini qaytaradi. Sinxron - to_thread ichida chaqiring."""
    if house not in HOUSES:
        raise ValueError("fakultet")
    lang = lang if lang in TEXTS else "uz"
    name = hpxat.clean_name(name)
    os.makedirs(OUT_DIR, exist_ok=True)
    token = token_for(user_id, name, lang, house)
    yol = path_of(token)
    if not os.path.exists(yol):
        render(name, lang, house, yol)
    return token
