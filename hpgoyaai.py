# -*- coding: utf-8 -*-
"""G'oyalarni AI bilan tahlil qilish (egasi, 2026-11-07; bepul Gemini kaliti - hphisobot /ai kalit).

1) g'oyalar mavzularga ajratiladi; 2) ma'nosi bir xil g'oyalar topiladi (har biri guruhning
eng birinchi g'oyasiga «asosiy» bilan bog'lanadi); 3) javob kutayotgan («yangi», javobsiz)
g'oyalarga Albus Dambldor nomidan javob QORALAMASI yoziladi. Qoralama hech qachon o'zi
yuborilmaydi - egasi panelda ko'rib, tahrirlab, «Saqlash» bilan yuboradi (Foks xati).

AI'ga faqat g'oya matni, tili va holati yuboriladi - odam ismi, username, id YUBORILMAYDI.
Panel: POST /api/goya/ai ({} - holat va natija, {yangila: 1} - tahlilni boshlash), X-Dash-Token.
Yangi (tahlil qilinmagan) g'oya paydo bo'lsa, fon soatda bir marta o'zi tahlil qiladi.
"""

import asyncio
import json
import logging
import time

from aiohttp import web

import hpcup
import hphisobot

MODELLAR = ("gemini-3.5-flash", "gemini-flash-lite-latest")     # birinchisi ishlamasa - keyingisi
SOAT_ORALIQ = 3600
ENG_KOP = 300                                                  # bir tahlilda eng ko'pi (eng yangilari)
PROMPT = """Sen Garri Potter ruhidagi Telegram ilovasi («Garri Potter kolleksiyasi») egasining yordamchisisan.
O'quvchilar ilovaning «Direktor xonasi»ga g'oya yuborishgan. Vazifang:
1) G'oyalarni 5-12 ta mavzuga ajrat. Mavzu nomi o'zbekcha (lotin), 2-4 so'z, aniq (masalan «Audio kitoblar»).
   Har g'oyaning «mavzu» maydoniga AYNAN shu ro'yxatdagi nomlardan birini yoz.
2) Takrorlar: faqat AYNAN BIR XIL narsani so'ragan g'oyalar takror (masalan, uch kishi «kitoblarni ovozli qiling» deb yozgan).
   Shunchaki bir mavzudagi har xil takliflar takror EMAS. Takror bo'lsa, «asosiy» ga guruhdagi ENG KICHIK id ni yoz;
   g'oyaning o'zi eng kichik bo'lsa yoki takror bo'lmasa - null.
3) «qoralama_kerak» true bo'lgan har g'oyaga Albus Dambldor (Xogvarts direktori) nomidan javob qoralamasi yoz:
   1-3 jumla, g'oya tilida (til: uz - o'zbek lotin, ru - rus, en - ingliz), iliq va hurmatli, g'oyaning o'ziga xos
   tomonini tilga ol. Hech narsa va'da qilma (qarorni ilova egasi qiladi): «ko'rib chiqamiz», «yozib qo'ydik» ruhida.
   Mavjud bo'lmagan narsalarni (kengash, vazirlik, muddat, sana) to'qima. Ismlar imlosi: Dambldor, Foks (feniks),
   Xogvarts, Grifindor, Slizerin, Reyvenklo, Xaffelpaff. «qoralama_kerak» false bo'lsa qoralama null.
Javob faqat JSON."""
SCHEMA = {"type": "OBJECT", "properties": {
    "mavzular": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "nom": {"type": "STRING"}, "tavsif": {"type": "STRING"}}, "required": ["nom"]}},
    "goyalar": {"type": "ARRAY", "items": {"type": "OBJECT", "properties": {
        "id": {"type": "INTEGER"}, "mavzu": {"type": "STRING"},
        "asosiy": {"type": "INTEGER", "nullable": True}, "qoralama": {"type": "STRING", "nullable": True}},
        "required": ["id", "mavzu"]}}},
    "required": ["mavzular", "goyalar"]}

_cfg = {}
_holat = {"ish": False, "xato": None}


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS goya_ai (goya_id INTEGER PRIMARY KEY, mavzu TEXT, asosiy INTEGER,"
                     " qoralama TEXT, vaqt TEXT)")
        conn.commit()
    finally:
        conn.close()


def _sozlama(kalit, qiymat=None):
    conn = hpcup._connect()
    try:
        if qiymat is None:
            r = conn.execute("SELECT value FROM settings WHERE key=?", (kalit,)).fetchone()
            return r["value"] if r else None
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)", (kalit, qiymat))
        conn.commit()
    finally:
        conn.close()


def _goyalar():
    conn = hpcup._connect()
    try:
        rows = conn.execute("SELECT g.id, g.nom, g.batafsil, g.til, g.holat, g.javob, a.qoralama FROM goya g"
                            " LEFT JOIN goya_ai a ON a.goya_id = g.id ORDER BY g.id DESC LIMIT ?", (ENG_KOP,)).fetchall()
        return [dict(r) for r in rows][::-1]
    finally:
        conn.close()


def _yangi_bormi():
    conn = hpcup._connect()
    try:
        return conn.execute("SELECT 1 FROM goya g LEFT JOIN goya_ai a ON a.goya_id = g.id"
                            " WHERE a.goya_id IS NULL LIMIT 1").fetchone() is not None
    finally:
        conn.close()


def tozala(natija, goyalar):
    """AI javobini tekshirish: noma'lum mavzu - «Boshqa», asosiy - mavjud, kichikroq id, zanjirsiz."""
    ids = {g["id"] for g in goyalar}
    mavzular = []
    for m in natija.get("mavzular") or []:
        nom = str(m.get("nom") or "").strip()[:60]
        if nom and nom not in [x["nom"] for x in mavzular]:
            mavzular.append({"nom": nom, "tavsif": str(m.get("tavsif") or "").strip()[:200]})
    nomlar = {m["nom"] for m in mavzular}
    chiq = {}
    for g in natija.get("goyalar") or []:
        try:
            i = int(g.get("id"))
        except (TypeError, ValueError):
            continue
        if i not in ids:
            continue
        mz = str(g.get("mavzu") or "").strip()
        if mz not in nomlar:
            mz = "Boshqa"
        a = g.get("asosiy")
        try:
            a = int(a) if a is not None else None
        except (TypeError, ValueError):
            a = None
        if a is not None and (a not in ids or a >= i):
            a = None
        q = g.get("qoralama")
        q = str(q).strip()[:600] if q else None
        chiq[i] = {"mavzu": mz, "asosiy": a, "qoralama": q}
    # Zanjir: asosiyning ham asosiysi bo'lsa - eng boshiga bog'laymiz
    for i, v in chiq.items():
        seen = set()
        while v["asosiy"] in chiq and chiq[v["asosiy"]]["asosiy"] is not None and v["asosiy"] not in seen:
            seen.add(v["asosiy"])
            v["asosiy"] = chiq[v["asosiy"]]["asosiy"]
    if any(v["mavzu"] == "Boshqa" for v in chiq.values()) and "Boshqa" not in nomlar:
        mavzular.append({"nom": "Boshqa", "tavsif": ""})
    return mavzular, chiq


def _saqla(mavzular, chiq, goyalar):
    eski = {g["id"]: g.get("qoralama") for g in goyalar}
    hozir = hpcup.now_tk().isoformat()
    conn = hpcup._connect()
    try:
        for i, v in chiq.items():
            q = v["qoralama"] or eski.get(i)          # oldingi qoralama saqlanib qoladi
            conn.execute("INSERT OR REPLACE INTO goya_ai (goya_id, mavzu, asosiy, qoralama, vaqt) VALUES (?,?,?,?,?)",
                         (i, v["mavzu"], v["asosiy"], q, hozir))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('goya_ai_mavzular', ?)",
                     (json.dumps(mavzular, ensure_ascii=False),))
        conn.execute("INSERT OR REPLACE INTO settings (key, value) VALUES ('goya_ai_vaqt', ?)", (hozir,))
        conn.commit()
    finally:
        conn.close()


async def _gemini(matn):
    import aiohttp
    kalit = hphisobot.ai_kalit()
    if not kalit:
        raise RuntimeError("kalit_yoq")
    body = {"contents": [{"role": "user", "parts": [{"text": matn}]}],
            "generationConfig": {"responseMimeType": "application/json", "responseSchema": SCHEMA,
                                 "temperature": 0.3, "thinkingConfig": {"thinkingLevel": "low"}}}
    oxirgi = None
    async with aiohttp.ClientSession() as s:
        for m in MODELLAR:
            try:
                async with s.post("https://generativelanguage.googleapis.com/v1beta/models/%s:generateContent" % m,
                                  json=body, headers={"x-goog-api-key": kalit},
                                  timeout=aiohttp.ClientTimeout(total=150)) as r:
                    if r.status != 200:
                        oxirgi = "%s: %s" % (m, r.status)
                        continue
                    j = await r.json()
                    return json.loads(j["candidates"][0]["content"]["parts"][0]["text"])
            except Exception as e:
                oxirgi = "%s: %s" % (m, type(e).__name__)
    raise RuntimeError(oxirgi or "javob_yoq")


async def tahlil():
    """To'liq tahlil (bir vaqtda bittasi)."""
    if _holat["ish"]:
        return False
    _holat["ish"], _holat["xato"] = True, None
    t = time.time()
    try:
        goyalar = await asyncio.to_thread(_goyalar)
        if not goyalar:
            return True
        kirish = [{"id": g["id"], "nom": (g["nom"] or "")[:150], "batafsil": (g["batafsil"] or "")[:400],
                   "til": g["til"] or "uz", "holat": g["holat"],
                   "qoralama_kerak": g["holat"] == "yangi" and not (g["javob"] or "").strip() and not g.get("qoralama")}
                  for g in goyalar]
        natija = await _gemini(PROMPT + "\n\nG'oyalar (JSON):\n" + json.dumps(kirish, ensure_ascii=False))
        mavzular, chiq = tozala(natija, goyalar)
        await asyncio.to_thread(_saqla, mavzular, chiq, goyalar)
        logging.info("G'oyalar AI tahlili: %d g'oya, %d mavzu, %.1f s", len(chiq), len(mavzular), time.time() - t)
        return True
    except Exception as e:
        _holat["xato"] = str(e)[:200]
        logging.error("G'oyalar AI tahlili: %s", e)
        return False
    finally:
        _holat["ish"] = False


def natija():
    conn = hpcup._connect()
    try:
        goy = {str(r["goya_id"]): {"mavzu": r["mavzu"], "asosiy": r["asosiy"], "qoralama": r["qoralama"]}
               for r in conn.execute("SELECT * FROM goya_ai")}
    finally:
        conn.close()
    try:
        mavzular = json.loads(_sozlama("goya_ai_mavzular") or "[]")
    except ValueError:
        mavzular = []
    return {"mavzular": mavzular, "goyalar": goy, "vaqt": _sozlama("goya_ai_vaqt")}


async def api(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    if not _cfg["dash_ok"](request):
        return cors(web.json_response({"ok": False}, status=403))
    try:
        body = await request.json() if request.method == "POST" else {}
    except Exception:
        body = {}
    kalit = bool(hphisobot.ai_kalit())
    if body.get("yangila") and kalit and not _holat["ish"]:
        asyncio.get_event_loop().create_task(tahlil())
        await asyncio.sleep(0)
    d = await asyncio.to_thread(natija)
    d.update({"ok": True, "kalit": kalit, "ishlamoqda": _holat["ish"], "xato": _holat["xato"]})
    return cors(web.json_response(d))


async def kuzatuvchi():
    """Tahlil qilinmagan g'oya bo'lsa - soatda bir marta o'zi tahlil qiladi."""
    await asyncio.sleep(120)
    while True:
        try:
            if hphisobot.ai_kalit() and await asyncio.to_thread(_yangi_bormi):
                await tahlil()
        except Exception as e:
            logging.error("G'oyalar AI kuzatuvchisi: %s", e)
        await asyncio.sleep(SOAT_ORALIQ)


def register(app, cfg):
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/goya/ai", api)
    asyncio.get_event_loop().create_task(kuzatuvchi())
