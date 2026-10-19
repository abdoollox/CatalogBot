"""Kubok g'olibi rasmi (Telegram Stories / chatga ulashish uchun) - hpuy.py namunasida.

Kubok marosimidagi (ilova, js/09-kubok-marosim.js) «Ulashish» shu yerga keladi: katta Xogvarts kubogi (img/kubok.jpg - Gemini,
dizayn tizimi uslubida), g'olib fakultet rangidagi yog'du, gerb, fakultet nomi, hafta va ballar, odamning o'z hissasi.
1080x1920 (9:16) JPEG. Faqat g'olib fakultet o'quvchisi uchun (main.api_kubok tekshiradi).
Fayl `/data/kubok/<token>.jpg`.
"""

import hashlib
import os

from PIL import Image, ImageDraw, ImageFilter

import hpuy
import hpxat

HERE = os.path.dirname(os.path.abspath(__file__))
CUP = os.path.join(HERE, "img", "kubok.jpg")
OUT_DIR = os.getenv("HP_KUBOK_DIR", "/data/kubok")

W, H = 1080, 1920
BG = (10, 12, 17)
TEXT = (238, 241, 245)
DIM = (152, 162, 179)
GOLD = (243, 213, 143)

TEXTS = {
    "uz": {"top": "XOGVARTS KUBOGI · %d-HAFTA", "oldi": "kubokni qo'lga kiritdi!", "ball": "%s ball",
           "hissa": "%s ham g'alabaga hissa qo'shdi: +%s ball", "anon": "Men",
           "foot1": "Sizning fakultetingiz kubokni ola oladimi?", "foot2": "t.me/garripotterkinobot"},
    "ru": {"top": "КУБОК ХОГВАРТСА · НЕДЕЛЯ %d", "oldi": "завоевал кубок!", "ball": "%s очков",
           "hissa": "%s тоже внёс вклад: +%s очков", "anon": "Я",
           "foot1": "А ваш факультет сможет взять кубок?", "foot2": "t.me/garripotterkinobot"},
    "en": {"top": "HOGWARTS HOUSE CUP · WEEK %d", "oldi": "wins the House Cup!", "ball": "%s points",
           "hissa": "%s helped win it: +%s points", "anon": "I",
           "foot1": "Can your house win the Cup?", "foot2": "t.me/garripotterkinobot"},
}


def _son(n):
    return "{:,}".format(int(n or 0)).replace(",", " ")


def _center(d, text, font, y, fill):
    w = d.textlength(text, font=font)
    d.text(((W - w) / 2, y), text, font=font, fill=fill)


def render(name, lang, house, number, total, mine, path):
    t = TEXTS.get(lang) or TEXTS["uz"]
    h = hpuy.HOUSES[house]
    rang = h["rang"]
    im = Image.new("RGB", (W, H), BG)

    # fakultet rangidagi yog'du - kubok atrofida
    glow = Image.new("RGB", (W, H), BG)
    ImageDraw.Draw(glow).ellipse([-160, -120, W + 160, 1260], fill=tuple(int(c * 0.5) for c in rang))
    glow = glow.filter(ImageFilter.GaussianBlur(170))
    im = Image.blend(im, glow, 0.9)
    d = ImageDraw.Draw(im)
    hpxat._spaced(d, t["top"] % int(number or 0), hpxat._font(hpxat.FONT_MAIN, 30, 600), W / 2, 120, gap=7, fill=GOLD)

    # kubok: chetlari yumshoq eriydigan doira
    cw, cy = 820, 180
    cup = Image.open(CUP).convert("RGB").resize((cw, cw), Image.LANCZOS)
    mask = Image.new("L", (cw, cw), 0)
    ImageDraw.Draw(mask).ellipse([cw * 0.1, cw * 0.1, cw * 0.9, cw * 0.9], fill=255)
    mask = mask.filter(ImageFilter.GaussianBlur(cw * 0.06))
    im.paste(cup, ((W - cw) // 2, cy), mask)

    # gerb kubok ostiga chiqib turadi
    crest = Image.open(os.path.join(hpuy.ART_DIR, house + ".png")).convert("RGBA")
    gw = 210
    crest = crest.resize((gw, int(crest.height * gw / crest.width)), Image.LANCZOS)
    gy = cy + cw - 170
    soya = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    ImageDraw.Draw(soya).ellipse([W // 2 - 150, gy + 10, W // 2 + 150, gy + crest.height + 30], fill=(0, 0, 0, 190))
    soya = soya.filter(ImageFilter.GaussianBlur(34))
    im.paste(soya, (0, 0), soya)
    im.paste(crest, ((W - gw) // 2, gy), crest)
    d = ImageDraw.Draw(im)

    y = gy + crest.height + 34
    nom = h[lang] if lang in h else h["uz"]
    f_nom = hpuy._fit(d, nom, hpxat.FONT_MAIN, 170, 600, W - 120)
    _center(d, nom, f_nom, y, rang)
    y += f_nom.size + 28
    _center(d, t["oldi"], hpxat._font(hpxat.FONT_ITALIC, 58, 500), y, TEXT)
    y += 96
    _center(d, t["ball"] % _son(total), hpxat._font(hpxat.FONT_MAIN, 66, 700), y, GOLD)
    y += 112
    d.line([(W / 2 - 70, y), (W / 2 + 70, y)], fill=rang, width=3)
    y += 40
    if mine and mine > 0:
        kim = (name or t["anon"])
        matn = t["hissa"] % (kim, _son(mine))
        f_h = hpxat._font(hpxat.FONT_ITALIC, 44, 500)
        for line in hpxat._wrap(d, matn, f_h, W - 200):
            _center(d, line, f_h, y, TEXT)
            y += 58

    _center(d, t["foot1"], hpxat._font(hpxat.FONT_MAIN, 40, 600), H - 210, GOLD)
    _center(d, t["foot2"], hpxat._font(hpxat.FONT_MAIN, 30, 500), H - 150, DIM)

    tmp = path + ".tmp"
    im.save(tmp, "JPEG", quality=88, optimize=True, progressive=True)
    os.replace(tmp, path)
    return path


def token_for(user_id, name, lang, house, season_id, total, mine):
    raw = "kubok|%s|%s|%s|%s|%s|%s|%s" % (user_id, name or "", lang, house, season_id, total, mine)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:20]


def path_of(token):
    return os.path.join(OUT_DIR, token + ".jpg")


def ensure(user_id, name, lang, house, season_id, number, total, mine):
    """Rasmni (kerak bo'lsa) yasaydi va tokenini qaytaradi. Sinxron - to_thread ichida chaqiring."""
    if house not in hpuy.HOUSES:
        raise ValueError("fakultet")
    lang = lang if lang in TEXTS else "uz"
    name = hpxat.clean_name(name)
    os.makedirs(OUT_DIR, exist_ok=True)
    token = token_for(user_id, name, lang, house, season_id, total, mine)
    yol = path_of(token)
    if not os.path.exists(yol):
        render(name, lang, house, number, total, mine, yol)
    return token
