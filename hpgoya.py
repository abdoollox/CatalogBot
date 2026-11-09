"""G'oyalar qutisi (egasi, 2026-11-04): Notion'dagi g'oya so'rovnomasi endi ilova ichida, nazorati - kuzatuv panelida.

Har foydalanuvchi (saralanmagan ham) g'oya yozadi: qisqa nomi (majburiy), batafsil, bo'lim. Holati: yangi -> korildi ->
qabul / rad -> bajarildi. Egasi paneldan holat va javob qo'yadi; holat o'zgarsa yoki javob yozilsa muallifga FOKS xati
boradi (boyo'g'li pochtasida, alohida ko'rinishda; botga emas). O'quvchi «Mening g'oyalarim»da holatni ko'radi.
So'rovlar - POST /api/goya: {} o'z g'oyalari, {yangi: {nom, batafsil, bolim}} yangi g'oya.
Panel - POST /api/goya/panel (X-Dash-Token): {} ro'yxat, {id, holat?, javob?} yangilash.
"""

import asyncio
import logging

from aiohttp import web

import hpcup

YOQIQ = True                   # False - faqat adminlarga (ko'rik); hammaga ochish: True (egasi, 2026-11-05)
BOLIMLAR = ("filmlar", "kutubxona", "xogvarts", "boshqa")
HOLATLAR = ("yangi", "korildi", "qabul", "rad", "bajarildi")
KUNIGA = 5                     # bir odam kuniga nechta g'oya yubora oladi
NOM_MAX, MATN_MAX, JAVOB_MAX = 120, 1500, 600

# muallifga xat (holat o'zgarganda); javob bo'lsa matn oxiriga qo'shiladi
XAT = {
    "uz": ("G'oyangiz ko'rib chiqildi", "«%s» g'oyangiz holati: %s.", {"korildi": "ko'rib chiqilmoqda", "qabul": "qabul qilindi", "rad": "hozircha qabul qilinmadi", "bajarildi": "bajarildi, ilovada!"}, "Javob: "),
    "ru": ("Ваша идея рассмотрена", "Статус идеи «%s»: %s.", {"korildi": "на рассмотрении", "qabul": "принята", "rad": "пока не принята", "bajarildi": "реализована, уже в приложении!"}, "Ответ: "),
    "en": ("Your idea was reviewed", "Status of your idea «%s»: %s.", {"korildi": "under review", "qabul": "accepted", "rad": "not accepted for now", "bajarildi": "done, it's in the app!"}, "Reply: "),
}

_cfg = {}


def _init():
    conn = hpcup._connect()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS goya (id INTEGER PRIMARY KEY AUTOINCREMENT, user_id INTEGER NOT NULL, nom TEXT NOT NULL,"
                     " batafsil TEXT, bolim TEXT, til TEXT, holat TEXT NOT NULL DEFAULT 'yangi', javob TEXT,"
                     " vaqt TEXT NOT NULL, yangilandi TEXT)")
        conn.commit()
    finally:
        conn.close()


def _qator(r):
    return {"id": r["id"], "nom": r["nom"], "batafsil": r["batafsil"] or "", "bolim": r["bolim"], "holat": r["holat"],
            "javob": r["javob"] or "", "vaqt": r["vaqt"], "yangilandi": r["yangilandi"]}


def meniki(uid):
    conn = hpcup._connect()
    try:
        return [_qator(r) for r in conn.execute("SELECT * FROM goya WHERE user_id=? ORDER BY id DESC LIMIT 50", (int(uid),))]
    finally:
        conn.close()


def yangi(uid, nom, batafsil, bolim, til):
    """Yangi g'oya. Natija: (ok, xato)."""
    nom = str(nom or "").strip()[:NOM_MAX]
    if len(nom) < 3:
        return False, "nom"
    bolim = bolim if bolim in BOLIMLAR else "boshqa"
    boshi = hpcup._utc_iso(hpcup.now_tk().replace(hour=0, minute=0, second=0, microsecond=0))     # Toshkent yarim tuni
    conn = hpcup._connect()
    try:
        if conn.execute("SELECT COUNT(*) FROM goya WHERE user_id=? AND vaqt>=?", (int(uid), boshi)).fetchone()[0] >= KUNIGA:
            return False, "kop"
        conn.execute("INSERT INTO goya (user_id, nom, batafsil, bolim, til, vaqt) VALUES (?,?,?,?,?,?)",
                     (int(uid), nom, str(batafsil or "").strip()[:MATN_MAX] or None, bolim, str(til or "")[:2], hpcup._utc_iso(hpcup.now_tk())))
        conn.commit()
        return True, None
    finally:
        conn.close()


def panel_royxat(admin_ids=()):
    conn = hpcup._connect()
    try:
        rows = conn.execute("SELECT g.*, u.first_name, u.username, u.house FROM goya g LEFT JOIN users u ON u.user_id = g.user_id ORDER BY g.id DESC").fetchall()
    finally:
        conn.close()
    adm = {int(a) for a in admin_ids}
    out = []
    for r in rows:
        q = _qator(r)
        q.update(uid=r["user_id"], ism=r["first_name"] or "", username=r["username"] or "", house=r["house"], til=r["til"], admin=r["user_id"] in adm)
        out.append(q)
    return out


def devor(cheklov=40):
    """Hammaga ko'rinadigan ro'yxatlar (Direktor xonasi): «stol» - qabul qilinganlar (ustida ishlanmoqda), «devor» - bajarilganlar.
    Muallif ismi bilan (egasi, 2026-11-05: ko'rinsin). Batafsil matn va javob ham (egasi, 2026-11-05: bosilsa batafsil
    ko'rinsin; formada «qabul qilingan g'oyalar boshqalarga ham ko'rinadi» deb ogohlantiriladi). Rad etilgan/yangi - faqat muallifga."""
    conn = hpcup._connect()
    try:
        rows = conn.execute("SELECT g.id, g.nom, g.batafsil, g.javob, g.bolim, g.holat, g.yangilandi, g.vaqt, u.first_name, u.house FROM goya g"
                            " LEFT JOIN users u ON u.user_id = g.user_id WHERE g.holat IN ('qabul', 'bajarildi')"
                            " ORDER BY COALESCE(g.yangilandi, g.vaqt) DESC LIMIT ?", (int(cheklov) * 2,)).fetchall()
    finally:
        conn.close()
    stol, dev = [], []
    for r in rows:
        q = {"id": r["id"], "nom": r["nom"], "bolim": r["bolim"], "ism": hpcup.ism(r["first_name"] or "") or "Sehrgar",
             "house": r["house"] if r["house"] in hpcup.UYLAR else None, "vaqt": r["vaqt"],
             "batafsil": r["batafsil"] or "", "javob": r["javob"] or ""}
        (dev if r["holat"] == "bajarildi" else stol).append(q)
    return {"stol": stol[:cheklov], "devor": dev[:cheklov]}


def ozgartir(gid, holat=None, javob=None):
    """Holat va/yoki javob. Natija: o'zgargan qator (muallifga xat uchun) yoki None."""
    if holat is not None and holat not in HOLATLAR:
        return None
    conn = hpcup._connect()
    try:
        r = conn.execute("SELECT * FROM goya WHERE id=?", (int(gid),)).fetchone()
        if not r:
            return None
        h = holat or r["holat"]
        j = r["javob"] if javob is None else (str(javob).strip()[:JAVOB_MAX] or None)
        conn.execute("UPDATE goya SET holat=?, javob=?, yangilandi=? WHERE id=?", (h, j, hpcup._utc_iso(hpcup.now_tk()), int(gid)))
        conn.commit()
        return {"id": r["id"], "uid": r["user_id"], "nom": r["nom"], "holat": h, "javob": j,
                "xat": (h != r["holat"] and h != "yangi") or (javob is not None and (j or "") != (r["javob"] or ""))}
    finally:
        conn.close()


def xat_matni(nom, holat, javob):
    out = {}
    for til, (sar, qolip, nomlar, jb) in XAT.items():
        m = qolip % (nom, nomlar.get(holat, holat))
        if javob:
            m += "\n\n" + jb + javob
        out[til] = (sar, m)
    return out


async def _user(request, body):
    return _cfg["verify_init_data"](request.headers.get("X-Telegram-Init-Data", "") or str(body.get("initData", "")))


async def api_goya(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    try:
        body = await request.json()
    except Exception:
        body = {}
    user = await _user(request, body)
    if not user:
        return cors(web.json_response({"ok": False, "error": "bad_auth"}, status=403))
    uid = int(user["id"])
    admin = uid in _cfg.get("admin_ids", ())
    if not YOQIQ and not admin:
        return cors(web.json_response({"ok": True, "on": False}))
    if isinstance(body.get("yangi"), dict):
        y = body["yangi"]
        ok, xato = await asyncio.to_thread(yangi, uid, y.get("nom"), y.get("batafsil"), y.get("bolim"), body.get("lang"))
        if not ok:
            return cors(web.json_response({"ok": False, "error": xato}))
        if _cfg.get("log"):
            try:
                await _cfg["log"](user, "goya_yubordi")
            except Exception:
                pass
    royxat = await asyncio.to_thread(meniki, uid)
    umumiy = await asyncio.to_thread(devor)
    try:
        import hpdonat
        donat = hpdonat.havola_kimga(admin)
    except Exception:
        donat = None
    return cors(web.json_response(dict(umumiy, ok=True, on=True, preview=not YOQIQ, list=royxat, bolimlar=BOLIMLAR, kuniga=KUNIGA, donat=donat)))


async def api_panel(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    if not _cfg["dash_ok"](request):
        return cors(web.json_response({"ok": False, "error": "bad_token"}, status=403))
    try:
        body = await request.json() if request.method == "POST" else {}
    except Exception:
        body = {}
    if body.get("id"):
        r = await asyncio.to_thread(ozgartir, body["id"], body.get("holat"), body.get("javob"))
        if r is None:
            return cors(web.json_response({"ok": False, "error": "topilmadi"}, status=400))
        if r["xat"] and _cfg.get("xat"):
            try:
                await _cfg["xat"](r["uid"], {"id": r["id"], "nom": r["nom"], "holat": r["holat"], "javob": r["javob"] or ""})
            except Exception as e:
                logging.warning("G'oya xati ketmadi (%s): %s", r["uid"], e)
    rows = await asyncio.to_thread(panel_royxat, tuple(_cfg.get("admin_ids", ())))
    return cors(web.json_response({"ok": True, "rows": rows, "holatlar": HOLATLAR, "bolimlar": BOLIMLAR}))


def register(app, cfg):
    """cfg: verify_init_data, cors, log, admin_ids, dash_ok, xat (uid, {id, nom, holat, javob}) - Foks xati (hppochta.foks_xat)."""
    _cfg.update(cfg)
    _init()
    app.router.add_route("*", "/api/goya", api_goya)
    app.router.add_route("*", "/api/goya/panel", api_panel)
    logging.info("G'oyalar qutisi ulandi")
