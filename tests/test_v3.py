import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Xogvarts kubogi 3.0 — Avtomatlashtirilgan to'liq test sinovi."""

import os
import sys
import json
import sqlite3
import asyncio
import logging
from datetime import datetime, timezone

# Test muhiti uchun test bazasini belgilaymiz
TEST_DB = "test_hp.db"
if os.path.exists(TEST_DB):
    try:
        os.remove(TEST_DB)
    except Exception:
        pass

os.environ["HP_DB_PATH"] = os.path.abspath(TEST_DB)
os.environ["HP_QUESTIONS_DIR"] = os.path.abspath("questions")

import hpcup
import hpbot

async def run_tests():
    print("==================================================")
    print("XOGVARTS KUBOGI 3.0 — TESTLARNI BOSHLASH")
    print("==================================================")

    # 1. Baza initsializatsiyasi va savollarni avto-yuklash
    print("\n[1] Baza va savollarni avtomatik yuklash...")
    sample_users = {
        "1001": {
            "nickname": "Alisher Qodirov",
            "username": "@alisher",
            "clicks": {"house_gryffindor": ["2026-08-20 10:00:00"]}
        },
        "1002": {
            "nickname": "Madina Rahimova",
            "username": "@madina",
            "clicks": {"house_slytherin": ["2026-08-21 12:00:00"]}
        }
    }
    sample_json_path = "test_users_db.json"
    with open(sample_json_path, "w", encoding="utf-8") as f:
        json.dump(sample_users, f)

    await hpcup.init(sample_json_path)
    
    counts = await hpcup.counts()
    print("Counts:", counts)
    assert counts["questions"] == 108, f"Kutilgan 108 ta savol, topildi: {counts['questions']}"
    assert counts["sorted_users"] == 2, f"Kutilgan 2 ta saralangan, topildi: {counts['sorted_users']}"
    assert counts["named_users"] == 2, f"Kutilgan 2 ta ismli, topildi: {counts['named_users']}"
    print("✅ [1] Baza va savollar muvaffaqiyatli yuklandi (108 ta savol).")

    # 2. Foydalanuvchilar ismlari va birinchi ism ajratilishi
    print("\n[2] Foydalanuvchi ismi va touch_user...")
    await hpcup.touch_user(1003, "Jasur Saidov")
    await hpcup.set_house(1003, "ravenclaw", "Jasur Saidov")
    house = await hpcup.get_house(1003)
    assert house == "ravenclaw", f"Kutilgan ravenclaw, topildi: {house}"
    
    # Fakultet umrbod ekanini tekshirish (qayta saralanish rad etilishi kerak)
    # Muhlat ochiq emas deb hisoblasak
    resort_ok = await hpcup.set_house(1003, "slytherin", "Jasur")
    assert not resort_ok, "Fakultet o'zgarishi rad etilishi kerak edi!"
    print("✅ [2] Fakultet umrbod qulflanishi to'g'ri ishladi.")

    # 3. exam_pending tekshiruvi
    print("\n[3] exam_pending tekshiruvi...")
    season = await hpcup.current_season()
    pending = await hpcup.exam_pending(1003, season["id"])
    print("Dastlabki exam_pending (1003):", pending)
    assert pending == [1, 2, 3, 4, 5, 6, 7, 8], f"Kutilgan barcha 8 ta film, topildi: {pending}"

    # 1-qism savollarini olamiz va 3 tasiga ham javob beramiz
    qs = await hpcup.film_questions(1003, season["id"], 1)
    assert len(qs) == 3, f"Kutilgan 3 ta savol, topildi: {len(qs)}"
    for q in qs:
        # Javob beramiz
        await hpcup.record_answer(1003, season["id"], q["id"], True)
        await hpcup.award(1003, "film_quiz", str(q["id"]), hpcup.PTS_FILM_QUIZ)

    pending_after = await hpcup.exam_pending(1003, season["id"])
    print("1-qism topshirilgandan keyingi exam_pending:", pending_after)
    assert 1 not in pending_after, "1-qism exam_pending dan chiqishi kerak edi!"
    assert pending_after == [2, 3, 4, 5, 6, 7, 8]
    print("✅ [3] exam_pending to'g'ri hisoblanmoqda.")

    # 4. Ballar va Faol a'zo (30 ball ostona)
    print("\n[4] Faol a'zo va reyting...")
    stats = await hpcup.user_stats(1003, season["id"])
    print(f"1003 foydalanuvchi bali: {stats['points']}, is_active: {stats['is_active']}")
    assert stats["points"] == 30, f"Kutilgan 30 ball (3x10), topildi: {stats['points']}"
    assert stats["is_active"] is True, "30 ball bilan is_active True bo'lishi kerak!"
    print("✅ [4] Faol a'zo ostonasi (30 ball) to'g'ri ishladi.")

    # 5. Hall (Fakultet zali) tekshiruvi
    print("\n[5] Fakultet zali (hall) tekshiruvi...")
    hall_data = await hpcup.hall("ravenclaw", 1003, season["id"])
    print("Ravenclaw zali:", json.dumps(hall_data, ensure_ascii=False, indent=2))
    assert hall_data["total"] >= 1
    assert hall_data["active"] == 1
    assert len(hall_data["members"]) == 1
    assert hall_data["members"][0]["name"] == "Jasur"
    assert hall_data["members"][0]["points"] == 30
    assert hall_data["members"][0]["me"] is True
    print("✅ [5] Fakultet zali (hall) formati to'g'ri.")

    # 6. Feed (Jonli tasma) tekshiruvi
    print("\n[6] Jonli tasma (feed) tekshiruvi...")
    feed_data = await hpcup.feed(limit=5)
    print("Jonli tasma:", json.dumps(feed_data, ensure_ascii=False, indent=2))
    assert len(feed_data) >= 1
    assert feed_data[0]["name"] == "Jasur"
    assert feed_data[0]["house"] == "ravenclaw"
    assert isinstance(feed_data[0]["ago_minutes"], int)
    print("✅ [6] Jonli tasma (feed) formati to'g'ri.")

    # 7. Savol variantlarini aralashtirish (Shuffle) tekshiruvi
    print("\n[7] Savollarni aralashtirish (Shuffle)...")
    sample_q = {
        "id": 999,
        "body": "Sinov savoli?",
        "options": ["Birinchi", "Ikkinchi", "Uchinchi", "To'rtinchi"],
        "correct_index": 0
    }
    seen_first_options = set()
    for _ in range(30):
        kb = hpbot._question_kb("hpa:1", sample_q)
        buttons = kb.inline_keyboard
        # Birinchi tugma (A) ning matni va callback'i
        first_btn = buttons[0][0]
        assert first_btn.text.startswith("A) ")
        parts = first_btn.callback_data.split(":")
        orig_idx = int(parts[3])
        # Tugmadagi matn options[orig_idx] ga mos kelishi kerak
        assert first_btn.text == f"A) {sample_q['options'][orig_idx]}"
        seen_first_options.add(orig_idx)

    print("30 ta generatsiyada 'A' tugmasiga tushgan asl indekslar:", seen_first_options)
    assert len(seen_first_options) > 1, "Variantlar aralashtirilmadi!"
    print("✅ [7] Savollar muvaffaqiyatli tasodifiy aralashtirilmoqda va callback to'g'ri indeksni ushlamoqda.")

    # 8. closable va remaining_today tekshiruvi
    print("\n[8] remaining_today va closable...")
    rem = stats["remaining_today"]
    print("1003 uchun bugun qolgan olinishi mumkin bo'lgan ballar:", rem)
    # 7 ta film imtihoni (7 * 3 * 10 = 210) + kunlik savol (10) = 220 ball
    assert rem == 220, f"Kutilgan 220 ball, topildi: {rem}"
    print("✅ [8] remaining_today to'g'ri hisoblandi.")

    # Tozalash
    try:
        os.remove(sample_json_path)
        os.remove(TEST_DB)
        if os.path.exists(TEST_DB + "-wal"):
            os.remove(TEST_DB + "-wal")
        if os.path.exists(TEST_DB + "-shm"):
            os.remove(TEST_DB + "-shm")
    except Exception:
        pass

    print("\n==================================================")
    print("BARCHA TESTLAR 100% MUVAFFAQIYATLI O'TDI! 🎉")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_tests())