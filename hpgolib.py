"""Turnir g'oliblari kartasi (egasi, 2026-10-12: o'quvchilar so'radi - g'oliblar hafta davomida turnir sahifasida ko'rinib tursin,
kim nechanchi o'rin va necha ball olgani bilan). To'rt turnir (poyga, shaxmat, viktorina, duel) shu yordamchilardan foydalanadi.

Har modul holat javobiga `champs` qo'shadi: {"n": ishtirokchilar, "ts": turnir vaqti, "top": [{uid, name, house, place, points, me}]}
- eng oxirgi TUGAGAN turnir (keyingisi tugaguncha turadi). Ball - haqiqatan berilgani (points jadvalidan).
"""

import hpdars


def ballar(conn, uidlar, andoza):
    """{uid: shu turnirdan olgan jami bali}; andoza - source_ref uchun LIKE (masalan 'duel:2026-10-05:%')."""
    out = {}
    uidlar = [u for u in uidlar if u]
    if not uidlar:
        return out
    belgi = ",".join("?" * len(uidlar))
    for jadval in ("points", "points_arxiv"):
        try:
            for r in conn.execute("SELECT user_id, SUM(points) AS p FROM %s WHERE source_ref LIKE ? AND user_id IN (%s) GROUP BY user_id" % (jadval, belgi),
                                  [andoza] + uidlar):
                out[r["user_id"]] = out.get(r["user_id"], 0) + (r["p"] or 0)
        except Exception:
            pass
    return out


def karta(conn, orinlar, andoza, uid, soni, ts):
    """orinlar: [(user_id, o'rin)] - tartib bilan. Qaytaradi: javobga qo'yiladigan lug'at yoki None."""
    orinlar = [(u, o) for u, o in orinlar if u and u > 0]
    if not orinlar:
        return None
    b = ballar(conn, [u for u, _ in orinlar], andoza)
    top = []
    for u, o in orinlar:
        r = conn.execute("SELECT COALESCE(first_name, 'Sehrgar') AS name, house FROM users WHERE user_id=?", (u,)).fetchone()
        top.append({"uid": u, "name": hpdars._ism(r["name"]) if r else "Sehrgar", "house": r["house"] if r else None,
                    "place": o, "points": int(b.get(u, 0)), "me": u == uid})
    return {"n": soni, "ts": ts, "top": top}


def tor(conn, jadval, hafta_gacha, andoza_bosh, uid, soni_sql, vaqt_fn):
    """To'rli turnir (duel, shaxmat): final g'olibi - 1, finalda yutqazgan - 2, yarim finalda yutqazganlar - 3.
    jadval - uchrashuvlar jadvali (hafta, bosqich, a, b, golib, holat); final bosqichi = 2, yarim final = 4."""
    f = conn.execute("SELECT * FROM %s WHERE bosqich=2 AND holat='tugadi' AND golib IS NOT NULL AND hafta LIKE '20%%' AND hafta <= ? "
                     "ORDER BY hafta DESC LIMIT 1" % jadval, (hafta_gacha,)).fetchone()
    if not f:
        return None
    h = f["hafta"]
    orinlar = [(f["golib"], 1)]
    ikkinchi = f["b"] if f["golib"] == f["a"] else f["a"]
    if ikkinchi:
        orinlar.append((ikkinchi, 2))
    for m in conn.execute("SELECT * FROM %s WHERE hafta=? AND bosqich=4 AND holat='tugadi' AND golib IS NOT NULL ORDER BY joy" % jadval, (h,)).fetchall():
        yutqazgan = m["b"] if m["golib"] == m["a"] else m["a"]
        if yutqazgan:
            orinlar.append((yutqazgan, 3))
    soni = conn.execute(soni_sql, (h,)).fetchone()[0]
    return karta(conn, orinlar, "%s:%s:%%" % (andoza_bosh, h), uid, soni, vaqt_fn(h))
