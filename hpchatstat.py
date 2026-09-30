"""Chat monitoringi — kuzatuv panelining "Chat" bo'limi uchun.

GET /api/chatpanel (X-Dash-Token) - chatdagi barcha xabarlar (Katta zal va
fakultet xonalari MATNI bilan; shaxsiy yozishmalarning faqat vaqti va kimligi,
matni yuborilmaydi), reaksiyalar soni, kim qaysi xonani ochgani, fakultetlar
a'zolari soni va onlayn tarixi.

Onlayn: /api/presence va chat so'rovlari faqat xotirada turadi. Bu modul har
5 daqiqada "so'nggi 5 daqiqada ilovada bo'lganlar" va "chatni ochganlar" sonini
`onlayn_log` jadvaliga yozib boradi - panel grafigi shundan chiziladi.
O'chirilgan xabarning matni ham yuborilmaydi (egasi uni o'chirgan).
"""
import time
import asyncio
import logging

from aiohttp import web

import hpcup

ORALIQ = 300               # onlayn o'lchovi har 5 daqiqada
SAQLASH_KUN = 120          # onlayn tarixi shuncha kun saqlanadi
KESH = 60                  # panel javobi shuncha soniya keshlanadi
_cfg = {}
_kesh = {"vaqt": 0.0, "javob": None}


def _ulan():
    conn = hpcup._connect()
    conn.execute(
        "CREATE TABLE IF NOT EXISTS onlayn_log ("
        " vaqt TEXT PRIMARY KEY,"       # o'lchov vaqti, UTC ISO (daqiqagacha)
        " ilova INTEGER NOT NULL,"      # so'nggi 5 daqiqada ilovani ochganlar
        " chat INTEGER NOT NULL)")      # shulardan chatni ochganlar
    return conn


def _olchov():
    now = time.time()
    chegara = now - ORALIQ
    ilova = sum(1 for uid, ts in list(hpcup._seen_wall.items()) if uid > 0 and ts >= chegara)
    chat = hpcup.chat_seen_count(ORALIQ)
    return ilova, chat


def _yoz(ilova, chat):
    t = hpcup.now_tk()
    conn = _ulan()
    try:
        conn.execute("INSERT OR REPLACE INTO onlayn_log (vaqt, ilova, chat) VALUES (?,?,?)",
                     (hpcup._utc_iso(t)[:16] + "Z", ilova, chat))
        conn.execute("DELETE FROM onlayn_log WHERE vaqt < ?",
                     (hpcup._utc_iso(t - hpcup.timedelta(days=SAQLASH_KUN)),))
        conn.commit()
    finally:
        conn.close()


async def kuzatuvchi():
    """Har 5 daqiqada onlayn sonini yozadi. Soat boshiga moslanadi (:00, :05, ...)."""
    await asyncio.sleep(ORALIQ - time.time() % ORALIQ)
    while True:
        try:
            ilova, chat = _olchov()
            await asyncio.to_thread(_yoz, ilova, chat)
        except Exception:
            logging.exception("Onlayn o'lchovi yozilmadi")
        await asyncio.sleep(ORALIQ - time.time() % ORALIQ)


def _xona(room):
    return "dm" if room.startswith("dm:") else room


def _yig():
    conn = _ulan()
    try:
        msgs, uids = [], set()
        for r in conn.execute(
                "SELECT id, house, user_id, message, created_at, reply_to, edited_at, deleted, chess, kind "
                "FROM chat_messages WHERE user_id > 0 ORDER BY id"):
            xona = _xona(r["house"])
            flag = (1 if r["deleted"] else 0) | (2 if r["edited_at"] else 0) | (4 if r["kind"] == "join" else 0)
            matn = None if (xona == "dm" or r["deleted"]) else r["message"]
            msgs.append([r["id"], r["created_at"], xona, str(r["user_id"]), r["reply_to"], flag,
                         1 if r["chess"] else 0, matn])
            uids.add(r["user_id"])
        reacts = [[r[0], r[1]] for r in conn.execute(
            "SELECT message_id, COUNT(*) FROM chat_reactions WHERE user_id > 0 GROUP BY message_id")]
        reads = set()
        for r in conn.execute("SELECT user_id, room FROM chat_reads WHERE user_id > 0"):
            reads.add((str(r["user_id"]), _xona(r["room"])))
            uids.add(r["user_id"])
        users = {}
        for i in range(0, len(uids), 500):
            part = list(uids)[i:i + 500]
            for r in conn.execute(
                    "SELECT user_id, first_name, username, house FROM users WHERE user_id IN (%s)"
                    % ",".join("?" * len(part)), part):
                users[str(r["user_id"])] = [r["first_name"] or "", r["username"] or "", r["house"] or ""]
        houses = {r[0]: r[1] for r in conn.execute(
            "SELECT house, COUNT(*) FROM users WHERE user_id > 0 AND house IS NOT NULL GROUP BY house")}
        online = [[r[0], r[1], r[2]] for r in conn.execute(
            "SELECT vaqt, ilova, chat FROM onlayn_log ORDER BY vaqt")]
        return {"ok": True, "msgs": msgs, "reacts": reacts, "reads": [list(x) for x in sorted(reads)],
                "users": users, "houses": houses, "online": online,
                "now": hpcup._utc_iso(hpcup.now_tk())}
    finally:
        conn.close()


async def api_panel(request):
    cors = _cfg["cors"]
    if request.method == "OPTIONS":
        return cors(web.Response(status=204))
    if not _cfg.get("dash_ok", lambda r: False)(request):
        return cors(web.json_response({"ok": False, "error": "bad_token"}, status=403))
    if _kesh["javob"] is None or time.monotonic() - _kesh["vaqt"] > KESH:
        try:
            _kesh["javob"] = await asyncio.to_thread(_yig)
            _kesh["vaqt"] = time.monotonic()
        except Exception as e:
            logging.error("Chat statistikasi o'qilmadi: %s", e)
            return cors(web.json_response({"ok": False, "error": "server"}, status=500))
    return cors(web.json_response(_kesh["javob"]))


def register(app, cfg):
    _cfg.update(cfg)
    _ulan().close()
    app.router.add_route("*", "/api/chatpanel", api_panel)
