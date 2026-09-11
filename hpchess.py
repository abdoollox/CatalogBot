"""Sehrgar shaxmati — jonli o'yinlarda server hakam.

Ilgari butun o'yin brauzerda hisoblanardi: ilova taxtani o'zi yuritib,
serverga tayyor holatni va natijani yuborardi, server esa hech narsani
tekshirmasdi (aldash oson edi, taslim bo'lgan durang olardi, soat har
telefonda alohida yurardi). Endi:

  - ilova faqat yurishni yuboradi ("e2e4", piyoda aylansa "e7e8n");
    server uni python-chess bilan tekshiradi va qo'llaydi;
  - soat serverda: sarflangan vaqt server vaqti bo'yicha ayiriladi,
    vaqt tugashini server taymeri o'zi aniqlaydi - hech kim ilovani
    ochib turmasa ham;
  - mot, pat, uch marta takror, 50 yurish, mot uchun dona yetmasligi,
    taslim, durang taklifi, bekor qilish - hammasi serverda;
  - ball o'yin tugagan zahoti server tomonidan beriladi;
  - o'zgarish kutib turganlarga darhol yetadi (chatdagi kabi: so'rov
    o'zgarish bo'lguncha ushlab turiladi).

Soat chess.com dagidek: ikkala tomon birinchi yurishini qilguncha soat
yurmaydi, lekin har biriga FIRST_MOVE soniya beriladi - ulgurmasa o'yin
bekor qilinadi (ball yo'q).

Brauzer hisoblagan eski o'yinlar (v=1) davom ettirilmaydi: tugamaganlari
ishga tushishda bekor qilinadi, tugaganlari tarix uchun qoladi.
"""

import asyncio
import logging
import secrets
import sqlite3
import time
from collections import deque
from datetime import timedelta

import chess

import hpcup

FIRST_MOVE = 60             # birinchi yurish uchun soniya
WAIT_TTL = 24 * 3600        # do'st kutilayotgan o'yin shuncha yashaydi
POLL_WAIT = 25              # jonli so'rov shuncha ushlab turiladi
ONLINE = 40                 # so'nggi 40 soniyada so'rov yuborgan - aloqada
BASES = (60, 180, 300, 600, 900, 1800)
MAX_INC = 30
CREATE_LIMIT, CREATE_WINDOW = 5, 60     # daqiqada 5 tadan ko'p o'yin ochilmaydi

COLUMNS = (
    ("v", "INTEGER NOT NULL DEFAULT 1"),
    ("moves", "TEXT NOT NULL DEFAULT ''"),
    ("base", "INTEGER NOT NULL DEFAULT 300"),
    ("inc", "INTEGER NOT NULL DEFAULT 0"),
    ("white_ms", "INTEGER"),
    ("black_ms", "INTEGER"),
    ("turn_started", "REAL"),
    ("rev", "INTEGER NOT NULL DEFAULT 0"),
    ("draw_offer", "TEXT"),
    ("offer_ply_w", "INTEGER NOT NULL DEFAULT -2"),
    ("offer_ply_b", "INTEGER NOT NULL DEFAULT -2"),
    ("result", "TEXT"),
    ("finished_at", "TEXT"),
)

_locks = {}         # o'yin -> asyncio.Lock; bir o'yinga ikki yurish bir vaqtda tushmasin
_events = {}        # o'yin -> asyncio.Event; kutib turgan so'rovlarni uyg'otadi
_timers = {}        # o'yin -> call_later; vaqt tugashi / birinchi yurish muddati
_seen = {}          # (o'yin, uid) -> vaqt; raqib aloqadami
_created = {}       # uid -> oxirgi o'yin ochish vaqtlari
_fresh = set()      # hozirgina tugagan o'yinlar - ball faqat shularga beriladi
_hooks = {}         # "changed": o'yin boshlandi/tugadi -> chatdagi taklif kartasi yangilanadi
_seeks = {}         # uid -> tasodifiy raqib qidirayotgan (xotirada)
SEEK_TTL = 35       # shuncha soniya so'rov yubormagan qidiruvchi navbatdan chiqadi


# ---------------------------------------------------------------- baza

def migrate():
    conn = hpcup._connect()
    try:
        have = {r[1] for r in conn.execute("PRAGMA table_info(chess_games)")}
        for name, ddl in COLUMNS:
            if name not in have:
                conn.execute("ALTER TABLE chess_games ADD COLUMN %s %s" % (name, ddl))
        old = conn.execute(
            "UPDATE chess_games SET status='aborted', win_reason='expired' "
            "WHERE v=1 AND status IN ('waiting','active')").rowcount
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chess_white ON chess_games(white_uid, status)")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_chess_black ON chess_games(black_uid, status)")
        conn.commit()
        if old:
            logging.info("Shaxmat: %d ta eski tugamagan o'yin bekor qilindi", old)
    finally:
        conn.close()


def _row(conn, gid):
    return conn.execute("SELECT * FROM chess_games WHERE id=?", (str(gid or ""),)).fetchone()


def _moves(row):
    return row["moves"].split() if row["moves"] else []


def _color_of(row, uid):
    if uid == row["white_uid"]:
        return "w"
    if row["black_uid"] and uid == row["black_uid"]:
        return "b"
    return None


def _other(color):
    return "b" if color == "w" else "w"


def _board(moves):
    board = chess.Board()
    for u in moves:
        board.push(chess.Move.from_uci(u))
    return board


def _clock(row, now):
    """(oq_ms, qora_ms, soat yuryaptimi) - hozirgi paytga."""
    w, b = row["white_ms"] or 0, row["black_ms"] or 0
    ply = len(_moves(row))
    running = row["status"] == "active" and ply >= 2 and row["turn_started"] is not None
    if running:
        spent = int((now - row["turn_started"]) * 1000)
        if ply % 2 == 0:
            w = max(0, w - spent)
        else:
            b = max(0, b - spent)
    return w, b, running


def _expiry(row):
    """O'yin o'z-o'zidan tugaydigan payt (epoch soniya) yoki None."""
    if row["status"] != "active" or row["turn_started"] is None:
        return None
    ply = len(_moves(row))
    if ply < 2:
        return row["turn_started"] + FIRST_MOVE
    ms = row["white_ms"] if ply % 2 == 0 else row["black_ms"]
    return row["turn_started"] + (ms or 0) / 1000.0


def _finish(conn, row, winner, reason, now, aborted=False):
    """O'yinni yopadi. winner: 'w' / 'b' / None (durang)."""
    w, b, _ = _clock(row, now)
    if aborted:
        status, result, winner_uid = "aborted", None, None
    else:
        status = "finished"
        result = {"w": "1-0", "b": "0-1"}.get(winner, "1/2-1/2")
        winner_uid = {"w": row["white_uid"], "b": row["black_uid"]}.get(winner)
    # rev sharti: qator o'qilgandan beri o'yin o'zgargan bo'lsa (masalan,
    # boshqa so'rov uni allaqachon yopgan), hech narsa qilinmaydi.
    cur = conn.execute(
        "UPDATE chess_games SET status=?, result=?, winner_uid=?, win_reason=?, "
        "white_ms=?, black_ms=?, turn_started=NULL, draw_offer=NULL, "
        "finished_at=?, rev=rev+1 WHERE id=? AND rev=?",
        (status, result, winner_uid, reason, w, b,
         hpcup._utc_iso(hpcup.now_tk()), row["id"], row["rev"]))
    if cur.rowcount and not aborted:
        _fresh.add(row["id"])
    return _row(conn, row["id"])


def _settle(conn, row, now):
    """Vaqt tugagan bo'lsa o'yinni yopadi. Yangilangan qatorni qaytaradi."""
    end = _expiry(row)
    if end is None or end > now:
        return row
    moves = _moves(row)
    if len(moves) < 2:
        return _finish(conn, row, None, "aborted", now, aborted=True)
    loser = "w" if len(moves) % 2 == 0 else "b"
    winner = _other(loser)
    # Vaqti tugaganning raqibida mot qilishga dona yetmasa - durang.
    if _board(moves).has_insufficient_material(chess.WHITE if winner == "w" else chess.BLACK):
        return _finish(conn, row, None, "timeout_draw", now)
    return _finish(conn, row, winner, "timeout", now)


def _award(row):
    """Tugagan o'yin uchun ball (bazaga yozilgandan KEYIN chaqiriladi)."""
    if not row or row["status"] != "finished":
        return
    if row["result"] == "1-0":
        pairs = [(row["white_uid"], "win")]
    elif row["result"] == "0-1":
        pairs = [(row["black_uid"], "win")]
    else:
        pairs = [(row["white_uid"], "draw"), (row["black_uid"], "draw")]
    for uid, res in pairs:
        try:
            hpcup._award_chess(uid, row["id"], res)
        except Exception as e:
            logging.error("Shaxmat balli berilmadi (%s): %s", row["id"], e)


def _award_info(conn, row, uid):
    got = conn.execute(
        "SELECT COALESCE(SUM(points),0) FROM points WHERE user_id=? AND source_ref=? "
        "AND source_type IN ('chess_win','chess_draw')", (uid, row["id"])).fetchone()[0]
    color = _color_of(row, uid)
    mine = row["result"] == "1/2-1/2" or (row["result"] == ("1-0" if color == "w" else "0-1"))
    info = {"points": got, "limit": hpcup.CHESS_MAX_PER_SEASON, "limit_reached": False}
    if mine and not got:
        season = hpcup._ensure_season(conn)
        used = conn.execute(
            "SELECT COUNT(*) FROM points WHERE user_id=? AND season_id=? "
            "AND source_type IN ('chess_win','chess_draw')", (uid, season["id"])).fetchone()[0]
        info["limit_reached"] = used >= hpcup.CHESS_MAX_PER_SEASON
    return info


def _player(conn, uid, gid):
    if not uid:
        return None
    u = conn.execute("SELECT first_name, house FROM users WHERE user_id=?", (uid,)).fetchone()
    return {"uid": uid, "name": (u and u["first_name"]) or "Sehrgar",
            "house": u and u["house"],
            "online": time.monotonic() - _seen.get((gid, uid), -1e9) < ONLINE}


def _view(conn, row, uid, now):
    if row["v"] != 2:
        return {"id": row["id"], "v": row["v"], "status": row["status"],
                "reason": row["win_reason"], "winner_uid": row["winner_uid"]}
    if row["id"] in _fresh:
        # Hozirgina tugadi: ball shu javobda ko'rinsin (baza allaqachon yozilgan).
        _fresh.discard(row["id"])
        _award(row)
    moves = _moves(row)
    board = chess.Board()
    san = []
    for u in moves:
        m = chess.Move.from_uci(u)
        san.append(board.san(m))
        board.push(m)
    w, b, running = _clock(row, now)
    color = _color_of(row, uid)
    ply = len(moves)
    turn = "w" if ply % 2 == 0 else "b"
    active = row["status"] == "active"
    view = {
        "id": row["id"], "v": 2, "status": row["status"], "rev": row["rev"],
        "fen": board.fen(), "moves": moves, "san": san, "ply": ply, "turn": turn,
        "white": _player(conn, row["white_uid"], row["id"]),
        "black": _player(conn, row["black_uid"], row["id"]),
        "you": color, "base": row["base"], "inc": row["inc"],
        "clock": {"w": w, "b": b, "running": running},
        "first_move_left": None,
        "check": board.is_check(),
        "legal": [m.uci() for m in board.legal_moves] if active and color == turn else [],
        "last": moves[-1] if moves else None,
        "draw_offer": row["draw_offer"] if active else None,
        "can_offer": bool(active and color and ply >= 2 and not row["draw_offer"]
                          and ply >= row["offer_ply_" + color] + 2),
        "result": row["result"], "reason": row["win_reason"],
        "winner_uid": row["winner_uid"],
    }
    if active and ply < 2 and row["turn_started"] is not None:
        view["first_move_left"] = max(0, int((row["turn_started"] + FIRST_MOVE - now) * 1000))
    if row["status"] == "finished" and color:
        view["award"] = _award_info(conn, row, uid)
    return view


def _active_of(conn, uid, now, skip=None):
    """Foydalanuvchining davom etayotgan o'yini (vaqti tugaganlari yopiladi)."""
    rows = conn.execute(
        "SELECT * FROM chess_games WHERE v=2 AND status='active' "
        "AND (white_uid=? OR black_uid=?)", (uid, uid)).fetchall()
    found, closed = None, []
    for r in rows:
        if r["id"] == skip:
            continue
        r2 = _settle(conn, r, now)
        if r2["status"] == "active":
            found = found or r2
        else:
            closed.append(r2)
    return found, closed


def _cancel_waiting(conn, uid, now, skip=None):
    rows = conn.execute(
        "SELECT * FROM chess_games WHERE v=2 AND status='waiting' AND white_uid=?",
        (uid,)).fetchall()
    return [_finish(conn, r, None, "cancelled", now, aborted=True)
            for r in rows if r["id"] != skip]


# ---------------------------------------------------------------- amallar (sinxron)
# Har biri (javob, o'zgargan qatorlar) qaytaradi: qatorlar bo'yicha kutib
# turganlar uyg'otiladi, taymer qayta qo'yiladi va ball beriladi.

def _create(uid, name, base, inc):
    now = time.time()
    conn = hpcup._connect()
    try:
        hpcup._touch_user(conn, uid, name)
        active, changed = _active_of(conn, uid, now)
        if active:
            conn.commit()
            return {"ok": False, "error": "has_active", "game_id": active["id"]}, changed
        changed += _cancel_waiting(conn, uid, now)
        stamp = hpcup._utc_iso(hpcup.now_tk())
        for _ in range(5):
            gid = secrets.token_hex(4)
            try:
                conn.execute(
                    "INSERT INTO chess_games (id, white_uid, black_uid, fen, turn, status, "
                    "white_time, black_time, last_move_at, created_at, v, moves, base, inc, "
                    "white_ms, black_ms, rev) VALUES (?,?,NULL,?,'w','waiting',?,?,?,?,2,'',?,?,?,?,1)",
                    (gid, uid, chess.STARTING_FEN, base, base, stamp, stamp, base, inc,
                     base * 1000, base * 1000))
                break
            except sqlite3.IntegrityError:
                continue
        conn.commit()
        return {"ok": True, "game_id": gid,
                "game": _view(conn, _row(conn, gid), uid, now)}, changed
    finally:
        conn.close()


def _join(gid, uid, name):
    now = time.time()
    conn = hpcup._connect()
    try:
        row = _row(conn, gid)
        if not row or row["v"] != 2:
            return {"ok": False, "error": "not_found"}, []
        hpcup._touch_user(conn, uid, name)
        row = _settle(conn, row, now)
        changed = [row]
        if _color_of(row, uid):
            conn.commit()
            return {"ok": True, "game_id": row["id"], "game": _view(conn, row, uid, now)}, changed
        if row["status"] != "waiting":
            conn.commit()
            return {"ok": False, "error": "game_already_started"}, changed
        active, closed = _active_of(conn, uid, now)
        changed += closed
        if active:
            conn.commit()
            return {"ok": False, "error": "has_active", "game_id": active["id"]}, changed
        changed += _cancel_waiting(conn, uid, now)
        cur = conn.execute(
            "UPDATE chess_games SET black_uid=?, status='active', turn_started=?, "
            "last_move_at=?, rev=rev+1 WHERE id=? AND status='waiting'",
            (uid, now, hpcup._utc_iso(hpcup.now_tk()), row["id"]))
        conn.commit()
        if not cur.rowcount:
            return {"ok": False, "error": "game_already_started"}, changed
        row = _row(conn, gid)
        return {"ok": True, "game_id": row["id"], "game": _view(conn, row, uid, now)}, changed + [row]
    finally:
        conn.close()


def _move(gid, uid, uci, ply):
    now = time.time()
    conn = hpcup._connect()
    try:
        row = _row(conn, gid)
        if not row or row["v"] != 2:
            return {"ok": False, "error": "not_found"}, []
        color = _color_of(row, uid)
        if not color:
            return {"ok": False, "error": "not_a_player"}, []
        row = _settle(conn, row, now)
        changed = [row]

        def fail(code):
            conn.commit()
            return {"ok": False, "error": code, "game": _view(conn, row, uid, now)}, changed

        if row["status"] != "active":
            return fail("not_active")
        moves = _moves(row)
        if ply is not None and ply != len(moves):
            # Javob yo'lda yo'qolib, ilova yurishni qayta yubordi - u allaqachon qabul qilingan.
            last_by_me = (len(moves) % 2 == 1) == (color == "w")
            if ply == len(moves) - 1 and moves[-1] == uci and last_by_me:
                conn.commit()
                return {"ok": True, "game": _view(conn, row, uid, now)}, changed
            return fail("stale")
        if ("w" if len(moves) % 2 == 0 else "b") != color:
            return fail("not_your_turn")
        board = _board(moves)
        try:
            mv = chess.Move.from_uci(str(uci or ""))
        except ValueError:
            return fail("illegal")
        if mv not in board.legal_moves:
            return fail("illegal")
        board.push(mv)
        moves.append(mv.uci())

        w, b = row["white_ms"], row["black_ms"]
        if len(moves) - 1 >= 2:     # yurgan tomonning soati yurib turgan edi
            spent = int((now - row["turn_started"]) * 1000)
            bonus = row["inc"] * 1000
            if color == "w":
                w = max(0, w - spent) + bonus
            else:
                b = max(0, b - spent) + bonus
        offer = row["draw_offer"]
        if offer and offer != color:
            offer = None            # raqibning taklifiga yurish bilan javob - rad etildi
        conn.execute(
            "UPDATE chess_games SET moves=?, fen=?, turn=?, white_ms=?, black_ms=?, "
            "turn_started=?, draw_offer=?, last_move_at=?, rev=rev+1 WHERE id=?",
            (" ".join(moves), board.fen(), "w" if board.turn else "b", w, b, now, offer,
             hpcup._utc_iso(hpcup.now_tk()), row["id"]))
        row = _row(conn, gid)
        if board.is_checkmate():
            row = _finish(conn, row, color, "mate", now)
        elif board.is_stalemate():
            row = _finish(conn, row, None, "stalemate", now)
        elif board.is_insufficient_material():
            row = _finish(conn, row, None, "insufficient", now)
        elif board.halfmove_clock >= 100:
            row = _finish(conn, row, None, "fifty", now)
        elif board.is_repetition(3):
            row = _finish(conn, row, None, "repetition", now)
        conn.commit()
        changed.append(row)
        return {"ok": True, "game": _view(conn, row, uid, now)}, changed
    finally:
        conn.close()


def _action(gid, uid, action):
    now = time.time()
    conn = hpcup._connect()
    try:
        row = _row(conn, gid)
        if not row or row["v"] != 2:
            return {"ok": False, "error": "not_found"}, []
        color = _color_of(row, uid)
        if not color:
            return {"ok": False, "error": "not_a_player"}, []
        row = _settle(conn, row, now)
        changed = [row]
        ply = len(_moves(row))
        opp = _other(color)
        error = None

        if row["status"] == "waiting" and action in ("abort", "resign"):
            row = _finish(conn, row, None, "cancelled", now, aborted=True)
        elif row["status"] != "active":
            error = "not_active"
        elif action == "abort" or (action == "resign" and ply < 2):
            if ply >= 2:
                error = "too_late"
            else:
                row = _finish(conn, row, None, "aborted", now, aborted=True)
        elif action == "resign":
            row = _finish(conn, row, opp, "resign", now)
        elif action == "draw_offer":
            if row["draw_offer"] == opp:
                row = _finish(conn, row, None, "agreement", now)
            elif row["draw_offer"] == color:
                error = "already"
            elif ply < 2 or ply < row["offer_ply_" + color] + 2:
                error = "offer_limit"
            else:
                conn.execute(
                    "UPDATE chess_games SET draw_offer=?, offer_ply_%s=?, rev=rev+1 WHERE id=?" % color,
                    (color, ply, row["id"]))
                row = _row(conn, gid)
        elif action in ("draw_accept", "draw_decline"):
            if row["draw_offer"] != opp:
                error = "no_offer"
            elif action == "draw_accept":
                row = _finish(conn, row, None, "agreement", now)
            else:
                conn.execute("UPDATE chess_games SET draw_offer=NULL, rev=rev+1 WHERE id=?",
                             (row["id"],))
                row = _row(conn, gid)
        else:
            error = "bad_action"
        conn.commit()
        changed.append(row)
        res = {"ok": not error, "game": _view(conn, row, uid, now)}
        if error:
            res["error"] = error
        return res, changed
    finally:
        conn.close()


def _state(gid, uid):
    now = time.time()
    conn = hpcup._connect()
    try:
        row = _row(conn, gid)
        if not row:
            return None, []
        row2 = _settle(conn, row, now)
        conn.commit()
        return _view(conn, row2, uid, now), ([row2] if row2 is not row else [])
    finally:
        conn.close()


def _mine(uid):
    now = time.time()
    conn = hpcup._connect()
    try:
        _, changed = _active_of(conn, uid, now)
        conn.commit()
        rows = conn.execute(
            "SELECT * FROM chess_games WHERE v=2 AND status IN ('active','waiting') "
            "AND (white_uid=? OR black_uid=?) ORDER BY status='active' DESC, created_at DESC",
            (uid, uid)).fetchall()
        season = hpcup._ensure_season(conn)
        used = conn.execute(
            "SELECT COUNT(*) FROM points WHERE user_id=? AND season_id=? "
            "AND source_type IN ('chess_win','chess_draw')", (uid, season["id"])).fetchone()[0]
        conn.commit()
        return ({"games": [_view(conn, r, uid, now) for r in rows],
                 "season": {"used": used, "limit": hpcup.CHESS_MAX_PER_SEASON}}, changed)
    finally:
        conn.close()


def _match(white, black, names, base, inc):
    """Qidiruvda uchrashgan ikki kishi uchun darhol boshlangan o'yin."""
    now = time.time()
    conn = hpcup._connect()
    try:
        changed = []
        for uid in (white, black):
            hpcup._touch_user(conn, uid, names.get(uid))
            active, closed = _active_of(conn, uid, now)
            changed += closed
            if active:
                conn.commit()
                return {"ok": False, "error": "has_active", "uid": uid}, changed
        for uid in (white, black):
            changed += _cancel_waiting(conn, uid, now)
        stamp = hpcup._utc_iso(hpcup.now_tk())
        for _ in range(5):
            gid = secrets.token_hex(4)
            try:
                conn.execute(
                    "INSERT INTO chess_games (id, white_uid, black_uid, fen, turn, status, "
                    "white_time, black_time, last_move_at, created_at, v, moves, base, inc, "
                    "white_ms, black_ms, turn_started, rev) "
                    "VALUES (?,?,?,?,'w','active',?,?,?,?,2,'',?,?,?,?,?,1)",
                    (gid, white, black, chess.STARTING_FEN, base, base, stamp, stamp, base, inc,
                     base * 1000, base * 1000, now))
                break
            except sqlite3.IntegrityError:
                continue
        conn.commit()
        return {"ok": True, "game_id": gid}, changed + [_row(conn, gid)]
    finally:
        conn.close()


def _active_id(uid):
    conn = hpcup._connect()
    try:
        active, changed = _active_of(conn, uid, time.time())
        conn.commit()
        return (active["id"] if active else None), changed
    finally:
        conn.close()


def _seek_purge():
    now = time.monotonic()
    for uid in [k for k, v in _seeks.items() if now - v["seen"] > SEEK_TTL and not v.get("game")]:
        _seeks.pop(uid, None)


def seek_counts(skip=None):
    """Har vaqt nazorati bo'yicha hozir qidirayotganlar soni ("300+0": 2)."""
    _seek_purge()
    out = {}
    for uid, v in _seeks.items():
        if uid != skip and not v.get("game"):
            k = "%d+%d" % v["tc"]
            out[k] = out.get(k, 0) + 1
    return out


async def seek(uid, name, base, inc, wait):
    """Tasodifiy raqib: shu vaqtni tanlagan boshqa qidiruvchi bo'lsa - darhol
    o'yin, bo'lmasa navbatda kutadi (so'rov 25 soniyagacha ushlab turiladi)."""
    e = _seeks.get(uid)
    if e and e.get("game"):
        _seeks.pop(uid, None)
        return {"ok": True, "game_id": e["game"]}
    if not e:
        # Tugallanmagan o'yini bor odam navbatga turmaydi - avval o'shani tugatsin.
        active = await _run("mine:%d" % uid, _active_id, uid)
        if active:
            return {"ok": False, "error": "has_active", "game_id": active}
    _seek_purge()
    if not e:
        e = _seeks[uid] = {"ev": asyncio.Event(), "tc": (base, inc)}
    e.update(tc=(base, inc), name=name, seen=time.monotonic())
    partner = None
    for k, v in _seeks.items():
        if k != uid and not v.get("game") and not v.get("busy") and v["tc"] == (base, inc):
            partner = k
            break
    if partner is not None and not e.get("busy"):
        pe = _seeks[partner]
        pe["busy"] = e["busy"] = True
        white, black = (uid, partner) if secrets.randbelow(2) else (partner, uid)
        try:
            res, changed = await asyncio.to_thread(
                _match, white, black, {uid: name, partner: pe.get("name")}, base, inc)
        finally:
            pe.pop("busy", None)
            e.pop("busy", None)
        await _after(changed)
        if res.get("ok"):
            pe["game"] = res["game_id"]
            pe["ev"].set()
            _seeks.pop(uid, None)
            return {"ok": True, "game_id": res["game_id"]}
        # Kimdadir tugallanmagan o'yin chiqib qoldi - u navbatdan chiqadi.
        _seeks.pop(res.get("uid"), None)
        if res.get("uid") == uid:
            return {"ok": False, "error": "has_active"}
    if wait:
        try:
            await asyncio.wait_for(e["ev"].wait(), POLL_WAIT)
        except asyncio.TimeoutError:
            pass
        e2 = _seeks.get(uid)
        if e2 and e2.get("game"):
            _seeks.pop(uid, None)
            return {"ok": True, "game_id": e2["game"]}
        if e2:
            e2["seen"] = time.monotonic()
    return {"ok": True, "searching": True, "counts": seek_counts(uid)}


def seek_cancel(uid):
    e = _seeks.pop(uid, None)
    if e and e.get("game"):
        return e["game"]          # juftlik allaqachon topilgan - o'yin baribir boshlangan
    return None


def _brief(gid):
    conn = hpcup._connect()
    try:
        row = conn.execute(
            "SELECT g.id, g.status, g.base, g.inc, g.v, COALESCE(u.first_name, 'Sehrgar') AS name "
            "FROM chess_games g LEFT JOIN users u ON u.user_id = g.white_uid WHERE g.id=?",
            (str(gid or ""),)).fetchone()
        if not row or row["v"] != 2:
            return None
        return {"id": row["id"], "status": row["status"], "name": row["name"],
                "base": row["base"], "inc": row["inc"]}
    finally:
        conn.close()


async def create_game(uid, name, base, inc):
    """Kutilayotgan o'yin (do'st yoki chatdagi taklif uchun)."""
    base = base if base in BASES else 300
    inc = min(max(int(inc or 0), 0), MAX_INC)
    return await _run("create:%d" % uid, _create, uid, name, base, inc)


async def brief(gid):
    """Taklif kartasi uchun: kim chaqiryapti, vaqt nazorati, holati."""
    return await asyncio.to_thread(_brief, gid)


def _sweep():
    """Kutilgan, lekin hech kim qo'shilmagan eski takliflarni yopadi."""
    now = time.time()
    cutoff = hpcup._utc_iso(hpcup.now_tk() - timedelta(seconds=WAIT_TTL))
    conn = hpcup._connect()
    try:
        rows = conn.execute(
            "SELECT * FROM chess_games WHERE v=2 AND status='waiting' AND created_at < ?",
            (cutoff,)).fetchall()
        changed = [_finish(conn, r, None, "expired", now, aborted=True) for r in rows]
        live = conn.execute("SELECT * FROM chess_games WHERE v=2 AND status='active'").fetchall()
        conn.commit()
        return changed, live
    finally:
        conn.close()


# ---------------------------------------------------------------- async qatlam

def _lock(gid):
    lock = _locks.get(gid)
    if lock is None:
        lock = _locks[gid] = asyncio.Lock()
    return lock


def _wake(gid):
    ev = _events.pop(gid, None)
    if ev:
        ev.set()


def _arm(row):
    """Vaqt tugashi / birinchi yurish muddati uchun taymer qo'yadi."""
    gid = row["id"]
    old = _timers.pop(gid, None)
    if old:
        old.cancel()
    end = _expiry(row)
    if end is None:
        if row["status"] in ("finished", "aborted"):
            _locks.pop(gid, None)
        return
    delay = max(0.0, end - time.time()) + 0.05
    loop = asyncio.get_running_loop()
    _timers[gid] = loop.call_later(delay, lambda: asyncio.ensure_future(_on_timer(gid)))


async def _after(changed):
    for row in changed:
        if row is None:
            continue
        _arm(row)
        _wake(row["id"])
        if row["id"] in _fresh:
            # Ball faqat o'yin yopilgan zahoti beriladi (odatda javob tuzilayotganda,
            # _view da): keyinroq, masalan yangi mavsumda, qayta berilmaydi.
            _fresh.discard(row["id"])
            await asyncio.to_thread(_award, row)
        hook = _hooks.get("changed")
        if hook and (row["status"] in ("finished", "aborted") or (row["status"] == "active" and not row["moves"])):
            try:
                await hook(row["id"])
            except Exception as e:
                logging.error("Shaxmat kartasini yangilashda xato (%s): %s", row["id"], e)


async def _run(gid, fn, *args):
    async with _lock(gid):
        res, changed = await asyncio.to_thread(fn, *args)
        await _after(changed)
    return res


async def _on_timer(gid):
    _timers.pop(gid, None)
    try:
        await _run(gid, _state, gid, 0)
    except Exception as e:
        logging.error("Shaxmat taymeri (%s): %s", gid, e)


async def _watcher():
    """Ishga tushganda davom etayotgan o'yinlarga taymer qo'yadi, keyin har
    10 daqiqada eski takliflarni tozalaydi."""
    first = True
    while True:
        try:
            changed, live = await asyncio.to_thread(_sweep)
            await _after(changed)
            if first:
                for row in live:
                    _arm(row)
                first = False
        except Exception as e:
            logging.error("Shaxmat kuzatuvchisi: %s", e)
        await asyncio.sleep(600)


# ---------------------------------------------------------------- HTTP

def register(app, cfg):
    from aiohttp import web

    verify = cfg["verify_init_data"]
    cors = cfg["cors"]

    async def auth(request):
        body = None
        if request.method == "POST":
            try:
                body = await request.json()
            except Exception:
                body = None
        body = body if isinstance(body, dict) else {}
        init = request.headers.get("X-Telegram-Init-Data", "") or str(body.get("initData", ""))
        return verify(init), body

    def reply(data, status=200):
        return cors(web.json_response(data, status=status))

    def game_id(value):
        return str(value or "").strip().lower()[:16]

    async def share_card(uid, gid, lang):
        """Do'stga yuboriladigan tayyor karta (Telegram "Ulashish" oynasi uchun).
        Bot tomoni (main.py) bo'lmasa yoki xato bo'lsa - None: ilova inline yo'lga o'tadi."""
        maker = cfg.get("chess_share")
        if not maker:
            return None
        info = await brief(gid)
        if not info or info["status"] != "waiting":
            return None
        try:
            return await maker(uid, gid, lang, info)
        except Exception as e:
            logging.error("Shaxmat kartasi tayyorlanmadi (%s): %s", gid, e)
            return None

    def seen(gid, uid):
        _seen[(gid, uid)] = time.monotonic()
        if len(_seen) > 2000:
            old = time.monotonic() - ONLINE
            for k in [k for k, t in _seen.items() if t < old]:
                del _seen[k]

    async def handler(request):
        if request.method == "OPTIONS":
            return cors(web.Response(status=204))
        user, body = await auth(request)
        if not user:
            return reply({"error": "unauthorized"}, 403)
        uid = int(user["id"])
        name = user.get("first_name")
        what = request.match_info["what"]

        if what == "create":
            sent = _created.setdefault(uid, deque())
            now = time.monotonic()
            while sent and now - sent[0] > CREATE_WINDOW:
                sent.popleft()
            if len(sent) >= CREATE_LIMIT:
                return reply({"ok": False, "error": "slow"}, 429)
            sent.append(now)
            try:
                base = int(body.get("base") or body.get("time_control") or 300)
                inc = int(body.get("inc") or 0)
            except (TypeError, ValueError):
                base, inc = 300, 0
            if base not in BASES:
                base = 300
            inc = min(max(inc, 0), MAX_INC)
            res = await _run("create:%d" % uid, _create, uid, name, base, inc)
            if res.get("ok"):
                seen(res["game_id"], uid)
                res["share_id"] = await share_card(uid, res["game_id"], body.get("lang"))
            return reply(res)

        if what == "mine":
            res = await _run("mine:%d" % uid, _mine, uid)
            res["ok"] = True
            res["seeking"] = seek_counts(uid)
            return reply(res)

        if what == "seek":
            if body.get("cancel"):
                gid = seek_cancel(uid)
                return reply({"ok": True, "game_id": gid} if gid else {"ok": True})
            if request.method != "POST":
                return reply({"ok": True, "counts": seek_counts(uid)})
            try:
                base, inc = int(body.get("base") or 300), int(body.get("inc") or 0)
            except (TypeError, ValueError):
                base, inc = 300, 0
            if base not in BASES:
                base = 300
            inc = min(max(inc, 0), MAX_INC)
            res = await seek(uid, name, base, inc, bool(body.get("wait")))
            if res.get("game_id"):
                seen(res["game_id"], uid)
            return reply(res)

        gid = game_id(body.get("game_id") or request.query.get("game_id"))
        if not gid:
            return reply({"ok": False, "error": "not_found"}, 404)
        seen(gid, uid)

        if what == "share":
            share_id = await share_card(uid, gid, body.get("lang"))
            return reply({"ok": bool(share_id), "id": share_id})

        if what == "join":
            return reply(await _run(gid, _join, gid, uid, name))

        if what == "move":
            if "fen" in body and "uci" not in body:
                # Eski ilova taxtani o'zi yuborardi - endi qabul qilinmaydi.
                return reply({"ok": False, "error": "old_client"}, 409)
            try:
                ply = int(body["ply"]) if body.get("ply") is not None else None
            except (TypeError, ValueError):
                ply = None
            return reply(await _run(gid, _move, gid, uid, str(body.get("uci") or ""), ply))

        if what == "action":
            return reply(await _run(gid, _action, gid, uid, str(body.get("action") or "")))

        if what == "finish":
            # Eski ilova: taslim/chiqish - taslim; qolganini (mot, vaqt) server o'zi biladi.
            if body.get("reason") in ("resign", "left"):
                res = await _run(gid, _action, gid, uid, "resign")
            else:
                res = {"game": await _run(gid, _state, gid, uid)}
            g = res.get("game") or {}
            out = {"ok": True, "rated": g.get("status") == "finished", "points": 0}
            if g.get("status") == "finished":
                out["result"] = ("draw" if g.get("result") == "1/2-1/2" else
                                 "win" if g.get("winner_uid") == uid else "loss")
                out["points"] = (g.get("award") or {}).get("points", 0)
            return reply(out)

        if what == "state":
            try:
                since = int(request.query.get("since"))
            except (TypeError, ValueError):
                since = None
            # Hodisani so'rovdan OLDIN olamiz: oradagi o'zgarish ham uni uyg'otadi.
            ev = _events.setdefault(gid, asyncio.Event())
            game = await _run(gid, _state, gid, uid)
            if game is None:
                return reply({"ok": False, "error": "not_found"}, 404)
            if (since is not None and request.query.get("wait") and game.get("v") == 2
                    and game["rev"] <= since and game["status"] in ("waiting", "active")):
                try:
                    await asyncio.wait_for(ev.wait(), POLL_WAIT)
                except asyncio.TimeoutError:
                    pass
                seen(gid, uid)
                game = await _run(gid, _state, gid, uid)
            return reply({"ok": True, "game": game})

        return reply({"error": "not_found"}, 404)

    migrate()
    _hooks["changed"] = cfg.get("chess_changed")
    app.router.add_route("*", "/api/chess/{what:(create|join|state|move|action|finish|mine|share|seek)}", handler)
    asyncio.ensure_future(_watcher())
    logging.info("Sehrgar shaxmati: server hakam ulandi")
