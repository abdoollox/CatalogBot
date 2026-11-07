# -*- coding: utf-8 -*-
"""Kunlik kuzatuv hisoboti (egasi, 2026-11-07): «Nima o'zgardi».

Har kuni ertalab (SOAT, Toshkent) adminlarga bot orqali qisqa xabar: KECHAGI kun
oldingi 7 kunning o'rtachasi bilan solishtiriladi, odatdagidan sezilarli farq
qilganlari yuqorida. AI'siz - faqat hisob, raqamlar aniq. Kuzatuv panelidagi
«Nima o'zgardi» kartasi (dash/v2) bilan bir xil qoida.

Yana: /ai kalit <kalit> - bepul Gemini kalitini serverda saqlash (xabar o'chiriladi,
repoga yozilmaydi); /ai - holati; /hisobot - hisobotni hozir olish.
"""

import asyncio
import json
import logging
import os
import re
from datetime import datetime, timedelta

from aiogram import types
from aiogram.filters import Command
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import hpcup

SOAT = 9
PANEL_URL = "https://abdoollox.github.io/CatalogWebApp/dash/v2/"
AI_PATH = os.getenv("HP_AI_PATH", "/data/ai.json")
YOMON_SABAB = ("bot_broken", "many_posts", "not_interesting")      # panel: LEAVE[..].bad
YOL = [("onb_letter", "Xatni ochdi"), ("onb_alley", "Gringottsga kirdi"), ("onb_gringotts", "Galleon oldi"),
       ("wand", "Tayoqcha oldi"), ("onb_ticket", "Platformada bilet"), ("onb_train", "Katta zalga yetdi"),
       ("sort_start", "Saralanish boshlandi"), ("house", "Fakultetga tushdi")]
KORSATKICH = [
    ("yangi", "Yangi odamlar", 1), ("faol", "Faol odamlar", 1),
    ("kqosh", "Kanalga qo'shilganlar", 1), ("kchiq", "Kanaldan chiqqanlar", -1),
    ("sabab", "Norozi bo'lib chiqqanlar", -1), ("blok", "Botni bloklaganlar", -1),
    ("film", "Olingan filmlar", 1), ("dars", "Dars o'tganlar", 1), ("bell", "Bellashuvda qatnashganlar", 1),
] + [("y_" + k, "Yo'l: " + n, 1) for k, n in YOL]
# Bazada film «hp1_uz» (ba'zan «web_/bot_» bilan) bo'lib yoziladi; «pleyer_» - ilovada tomosha, sanalmaydi (panel ham)
_FILM = re.compile(r"^(?:web_|bot_)?[a-z]{2}\d+_(uz|ru|en)")
OYLAR = ["yanvar", "fevral", "mart", "aprel", "may", "iyun", "iyul", "avgust", "sentabr", "oktabr", "noyabr", "dekabr"]

_cfg = {}


# ---------------------------------------------------------------- hisob

def _tk_kun(ts):
    """Server vaqti (UTC, "YYYY-MM-DD HH:MM:SS" yoki ISO) -> Toshkent sanasi."""
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00").replace("T", " ")[:19])
    except ValueError:
        return None
    return (t + timedelta(hours=5)).date()


def _yol_qadam(p):
    for k, _ in YOL:
        if k in ("wand", "house"):
            if p.startswith(k + "_"):
                return k
        elif p == k:
            return k
    return None


def hisob(bugun=None):
    """Kechagi kun va oldingi 7 kun bo'yicha ko'rsatkichlar."""
    bugun = bugun or hpcup.now_tk().date()
    kecha = bugun - timedelta(days=1)
    kunlar = [bugun - timedelta(days=i) for i in range(1, 9)]          # kecha + 7 kun
    kerak = set(kunlar)
    bosh_utc = (datetime.combine(kunlar[-1], datetime.min.time()) - timedelta(hours=5)).strftime("%Y-%m-%d %H:%M:%S")
    M = {}

    def qosh(m, kun, kim):
        if kun in kerak:
            M.setdefault(m, {}).setdefault(kun, set()).add(kim)

    conn = hpcup._connect()
    try:
        for r in conn.execute("SELECT user_id, MIN(ts) AS t FROM events GROUP BY user_id HAVING MIN(ts) >= ?", (bosh_utc,)):
            qosh("yangi", _tk_kun(r["t"]), r["user_id"])
        for i, r in enumerate(conn.execute("SELECT user_id, payload, ts FROM events WHERE ts >= ?", (bosh_utc,))):
            kun = _tk_kun(r["ts"])
            if kun not in kerak:
                continue
            p, u = r["payload"], r["user_id"]
            qosh("faol", kun, u)
            if p == "blocked":
                qosh("blok", kun, u)
            elif _FILM.match(p):
                qosh("film", kun, ("f", i))
            elif p.startswith("dars_"):
                qosh("dars", kun, u)
            elif p.startswith("bellashuv_"):
                qosh("bell", kun, u)
            q = _yol_qadam(p)
            if q:
                qosh("y_" + q, kun, u)
        # Kanal: takroriy yozuvlarsiz haqiqiy o'zgarishlar (panel kanalHajmi bilan bir xil)
        holat = {}
        for r in conn.execute("SELECT user_id, payload, ts FROM events WHERE payload IN ('subscribed','left') ORDER BY id"):
            e = r["payload"]
            if holat.get(r["user_id"]) == e:
                continue
            holat[r["user_id"]] = e
            qosh("kqosh" if e == "subscribed" else "kchiq", _tk_kun(r["ts"]), r["user_id"])
        try:
            for r in conn.execute("SELECT user_id, left_at, reason FROM leave_survey WHERE reason IN (%s)" %
                                  ",".join("?" * len(YOMON_SABAB)), YOMON_SABAB):
                qosh("sabab", _tk_kun(r["left_at"]), r["user_id"])
        except Exception:
            pass
        goya = []
        try:
            goya = [r["vaqt"] for r in conn.execute("SELECT vaqt FROM goya WHERE holat='yangi'")]
        except Exception:
            pass
    finally:
        conn.close()

    natija = []
    for k, n, yax in KORSATKICH:
        son = lambda kun: len(M.get(k, {}).get(kun, ()))
        y = son(kecha)
        o = [son(d) for d in kunlar[1:]]
        mu = sum(o) / len(o)
        farq = y - mu
        belgi = (mu >= 4 and abs(farq) / mu >= .35 and abs(farq) >= 3) or (mu < 4 and abs(farq) >= 4)
        natija.append({"k": k, "n": n, "y": y, "mu": mu, "min": min(o), "max": max(o), "farq": farq,
                       "belgi": belgi, "kuch": abs(farq) / max(mu, 2), "yaxshi": (farq > 0) == (yax > 0)})
    # Yo'lda eng ko'p yo'qotiladigan qadam (8 kun ichida qadamni qilganlar)
    qadam = []
    for k, n in YOL:
        odam = set()
        for s in M.get("y_" + k, {}).values():
            odam |= s
        qadam.append((n, len(odam)))
    eng = None
    for i in range(1, len(qadam)):
        if qadam[i - 1][1] < 5:
            continue
        yoq = 1 - qadam[i][1] / qadam[i - 1][1]
        if eng is None or yoq > eng["yoq"]:
            eng = {"dan": qadam[i - 1], "ga": qadam[i], "yoq": yoq}
    eski = None
    if goya:
        try:
            eski = min(datetime.fromisoformat(str(v).replace("Z", "+00:00")) for v in goya)
        except ValueError:
            eski = None
    return {"kecha": kecha, "natija": natija, "eng": eng, "goya": len(goya), "goya_eski": eski}


def _son(n):
    return "{:,}".format(int(round(n))).replace(",", " ")


def matn(h):
    k = h["kecha"]
    q = ["📊 <b>Kuzatuv: kecha, %d-%s</b>" % (k.day, OYLAR[k.month - 1]),
         "<i>oldingi 7 kunning o'rtachasi bilan solishtirildi</i>", ""]
    belgili = sorted([m for m in h["natija"] if m["belgi"]], key=lambda m: -m["kuch"])
    for m in belgili:
        foiz = ("%+d%%" % round(m["farq"] / m["mu"] * 100)).replace("-", "−") if m["mu"] else "yangi"
        q.append("%s %s: <b>%s</b> · odatda ≈%s (%s–%s) · %s" % (
            "🟢" if m["yaxshi"] else "🔴", m["n"], _son(m["y"]), _son(m["mu"]), m["min"], m["max"], foiz))
    if not belgili:
        q.append("✅ Kecha hammasi odatdagidek edi.")
    if h["goya"]:
        kun = None
        if h["goya_eski"]:
            kun = (datetime.now(h["goya_eski"].tzinfo) - h["goya_eski"]).days if h["goya_eski"].tzinfo else None
        q.append("💡 Javob kutayotgan g'oyalar: <b>%d</b>%s" % (h["goya"], " (eng eskisi %d kunlik)" % kun if kun else ""))
    e = h["eng"]
    if e and e["yoq"] > .2:
        q.append("🧭 Yo'lda eng ko'p yo'qotish: %s → %s (8 kunda %d kishidan %d kishi, −%d%%)" % (
            e["dan"][0], e["ga"][0], e["dan"][1], e["ga"][1], round(e["yoq"] * 100)))
    oddiy = [m for m in h["natija"] if not m["belgi"] and (m["y"] or m["mu"])]
    if oddiy:
        q += ["", "<i>Odatdagidek: " + " · ".join("%s %s" % (m["n"].replace("Yo'l: ", ""), _son(m["y"])) for m in oddiy) + "</i>"]
    return "\n".join(q)


async def yubor(bot, kimga):
    h = await asyncio.to_thread(hisob)
    kb = InlineKeyboardMarkup(inline_keyboard=[[InlineKeyboardButton(text="Panelni ochish", url=PANEL_URL)]])
    for uid in kimga:
        try:
            await bot.send_message(uid, matn(h), parse_mode="HTML", reply_markup=kb, disable_web_page_preview=True)
        except Exception as e:
            logging.error("Kunlik hisobot yuborilmadi (%s): %s", uid, e)


# ---------------------------------------------------------------- jadval

def _oxirgi():
    conn = hpcup._connect()
    try:
        r = conn.execute("SELECT value FROM settings WHERE key='hisobot_oxirgi'").fetchone()
        return r["value"] if r else None
    finally:
        conn.close()


def _belgila(kun):
    conn = hpcup._connect()
    try:
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('hisobot_oxirgi', ?)", (kun,))
        conn.commit()
    finally:
        conn.close()


async def kuzatuvchi(bot):
    """Har kuni SOAT dan keyin bir marta (bot qayta ishga tushsa ham takrorlanmaydi)."""
    while True:
        try:
            hozir = hpcup.now_tk()
            bugun = hozir.date().isoformat()
            if hozir.hour >= SOAT and await asyncio.to_thread(_oxirgi) != bugun:
                await asyncio.to_thread(_belgila, bugun)
                await yubor(bot, sorted(int(x) for x in _cfg.get("admin_ids", ()) if int(x) > 0))
                logging.info("Kunlik hisobot yuborildi (%s)", bugun)
        except Exception as e:
            logging.error("Kunlik hisobot: %s", e)
        await asyncio.sleep(300)


# ---------------------------------------------------------------- AI kaliti (bepul Gemini)

def ai_kalit():
    try:
        with open(AI_PATH, encoding="utf-8") as f:
            return json.load(f).get("gemini")
    except Exception:
        return None


def _ai_saqla(kalit):
    os.makedirs(os.path.dirname(AI_PATH) or ".", exist_ok=True)
    with open(AI_PATH, "w", encoding="utf-8") as f:
        json.dump({"gemini": kalit, "saqlandi": hpcup.now_tk().isoformat()}, f)
    try:
        os.chmod(AI_PATH, 0o600)
    except OSError:
        pass


async def _ai_tekshir(kalit):
    """Kalit ishlaydimi: Gemini modellar ro'yxatini so'raydi (kalit sarlavhada, URL'da emas)."""
    import aiohttp
    try:
        async with aiohttp.ClientSession() as s:
            async with s.get("https://generativelanguage.googleapis.com/v1beta/models",
                             headers={"x-goog-api-key": kalit}, timeout=aiohttp.ClientTimeout(total=15)) as r:
                return r.status
    except Exception:
        return None


def _admin(message):
    u = message.from_user
    return u and u.id in _cfg.get("admin_ids", ()) and message.chat.type == "private"


async def on_ai(message: types.Message):
    if not _admin(message):
        return
    bolak = (message.text or "").split()
    if len(bolak) > 1 and bolak[1].lower() == "kalit":
        try:
            await message.delete()                      # kalit chatda qolmasin
        except Exception:
            pass
        if len(bolak) != 3 or not re.match(r"^AIza[0-9A-Za-z_\-]{30,}$", bolak[2]):
            await message.answer("Yozilishi: /ai kalit <kalit>\nKalit «AIza» bilan boshlanadi (Google AI Studio → Get API key).")
            return
        await asyncio.to_thread(_ai_saqla, bolak[2])
        st = await _ai_tekshir(bolak[2])
        await message.answer("Kalit saqlandi ✅ va ishlayapti." if st == 200 else
                             "Kalit saqlandi, lekin Google uni qabul qilmadi (javob: %s). Kalitni tekshiring." % st)
        return
    k = ai_kalit()
    await message.answer(("AI kaliti: bor (…%s)" % k[-4:] if k else "AI kaliti: yo'q") +
                         "\n\nBuyruqlar: /ai kalit <kalit>  |  /hisobot — kunlik hisobotni hozir olish")


async def on_hisobot(message: types.Message):
    if not _admin(message):
        return
    await yubor(_cfg["bot"], [message.from_user.id])


def register(dp, bot, cfg):
    _cfg.update(cfg)
    _cfg["bot"] = bot
    dp.message.register(on_ai, Command("ai"))
    dp.message.register(on_hisobot, Command("hisobot"))
    asyncio.get_event_loop().create_task(kuzatuvchi(bot))
