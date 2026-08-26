import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
"""Xogvarts kubogi 3.0 вЂ” aiohttp HTTP Endpointlarini to'liq test qilish."""

import os
import hmac
import hashlib
import json
import urllib.parse
import aiohttp
from aiohttp import web
import asyncio
from datetime import datetime, timezone

TEST_DB = "test_http_hp.db"
if os.path.exists(TEST_DB):
    try:
        os.remove(TEST_DB)
    except Exception:
        pass

os.environ["HP_DB_PATH"] = os.path.abspath(TEST_DB)
os.environ["HP_QUESTIONS_DIR"] = os.path.abspath("questions")
os.environ["BOT_TOKEN"] = "123456:ABC-DEF1234ghIkl-zyx57W2v1u123ew11"

import hpcup
import hpbot

def make_test_init_data(token, user_dict):
    data = {
        "auth_date": str(int(datetime.now(timezone.utc).timestamp())),
        "query_id": "AAHdF6IQAAAAAN0XohDhrOrc",
        "user": json.dumps(user_dict, ensure_ascii=False)
    }
    check_string = "\n".join(f"{k}={data[k]}" for k in sorted(data.keys()))
    secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
    hash_val = hmac.new(secret, check_string.encode(), hashlib.sha256).hexdigest()
    data["hash"] = hash_val
    return urllib.parse.urlencode(data)

async def run_http_tests():
    print("==================================================")
    print("XOGVARTS KUBOGI 3.0 вЂ” HTTP API TESTLARI")
    print("==================================================")

    # Initsializatsiya
    await hpcup.init()
    token = os.environ["BOT_TOKEN"]

    app = web.Application()
    
    def _cors(resp):
        resp.headers["Access-Control-Allow-Origin"] = "*"
        resp.headers["Access-Control-Allow-Methods"] = "GET, POST, OPTIONS"
        resp.headers["Access-Control-Allow-Headers"] = "Content-Type, X-Telegram-Init-Data"
        return resp

    def verify_init_data(init_data):
        if not init_data or not token:
            return None
        try:
            pairs = dict(urllib.parse.parse_qsl(init_data, strict_parsing=True))
        except Exception:
            return None
        got = pairs.pop("hash", None)
        if not got:
            return None
        check = "\n".join("%s=%s" % (k, pairs[k]) for k in sorted(pairs))
        secret = hmac.new(b"WebAppData", token.encode(), hashlib.sha256).digest()
        calc = hmac.new(secret, check.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(calc, got):
            return None
        try:
            user = json.loads(pairs.get("user", "{}"))
        except Exception:
            return None
        return user if user.get("id") else None

    from aiogram import Dispatcher
    dp = Dispatcher()
    hpbot.register(dp, None, app, {
        "channel_id": -1001234567,
        "verify_init_data": verify_init_data,
        "cors": _cors,
    })

    # Test foydalanuvchini yaratamiz va fakultetga saralaymiz
    user_data = {"id": 777001, "first_name": "Sardor", "username": "sardor_dev"}
    init_data_str = make_test_init_data(token, user_data)
    
    await hpcup.touch_user(777001, "Sardor")
    await hpcup.set_house(777001, "gryffindor", "Sardor")
    season = await hpcup.current_season()
    
    # 1-qism imtihonini yechamiz va 30 ball qilamiz
    qs = await hpcup.film_questions(777001, season["id"], 1)
    for q in qs:
        await hpcup.record_answer(777001, season["id"], q["id"], True)
        await hpcup.award(777001, "film_quiz", str(q["id"]), hpcup.PTS_FILM_QUIZ)

    # aiohttp test serverini ishga tushiramiz
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "127.0.0.1", 8899)
    await site.start()

    async with aiohttp.ClientSession() as session:
        # 1. GET /api/leaderboard header bilan
        print("\n[1] GET /api/leaderboard chaqiruv...")
        headers = {"X-Telegram-Init-Data": init_data_str}
        async with session.get("http://127.0.0.1:8899/api/leaderboard", headers=headers) as resp:
            assert resp.status == 200, f"Status 200 bo'lishi kerak, keldi: {resp.status}"
            data = await resp.json()
            print("Leaderboard javobi:")
            print(json.dumps(data, ensure_ascii=False, indent=2))
            
            # Yangi maydonlarni tekshirish
            assert "season" in data
            assert "houses" in data
            assert "me" in data
            assert "exam_pending" in data["me"]
            assert data["me"]["exam_pending"] == [2, 3, 4, 5, 6, 7, 8], f"exam_pending xato: {data['me']['exam_pending']}"
            assert "hall" in data, "hall bloki yo'q!"
            assert data["hall"]["total"] >= 1
            assert data["hall"]["active"] == 1
            assert data["hall"]["members"][0]["name"] == "Sardor"
            assert data["hall"]["members"][0]["me"] is True
            assert "feed" in data, "feed bloki yo'q!"
            assert data["feed"][0]["name"] == "Sardor"
            assert data["feed"][0]["house"] == "gryffindor"
            print("вњ… GET /api/leaderboard barcha yangi maydonlari bilan 100% to'g'ri ishladi.")

        # 2. POST /api/leaderboard body bilan
        print("\n[2] POST /api/leaderboard chaqiruv...")
        payload = {"initData": init_data_str}
        async with session.post("http://127.0.0.1:8899/api/leaderboard", json=payload) as resp:
            assert resp.status == 200
            data2 = await resp.json()
            assert data2["me"]["exam_pending"] == [2, 3, 4, 5, 6, 7, 8]
            print("вњ… POST /api/leaderboard ham to'liq ishladi.")

    await runner.cleanup()
    
    # Tozalash
    try:
        os.remove(TEST_DB)
        if os.path.exists(TEST_DB + "-wal"):
            os.remove(TEST_DB + "-wal")
        if os.path.exists(TEST_DB + "-shm"):
            os.remove(TEST_DB + "-shm")
    except Exception:
        pass

    print("\n==================================================")
    print("HTTP API TESTLARI 100% MUVAFFAQIYATLI O'TDI! рџЋ‰")
    print("==================================================")

if __name__ == "__main__":
    asyncio.run(run_http_tests())