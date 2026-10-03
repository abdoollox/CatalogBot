"""Serial: nomdan fasl/qism tanish, sinov rejimi, ro'yxat, yuborish va e'lon.

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import json
import os
import sys
import tempfile
import types

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-serial-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["BOT_TOKEN"] = "123456:TEST-token"

import hpserial   # noqa: E402

hpserial.STORE = os.path.join(TMP, "serial.json")
hpserial.COVER_DIR = os.path.join(TMP, "rasm")

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


class Req:
    def __init__(self, body=None, init="", method="POST"):
        self._b, self.method = body or {}, method
        self.headers = {"X-Telegram-Init-Data": init}
    async def json(self):
        return self._b


class FakeBot:
    def __init__(self):
        self.sent, self.copied = [], []
    async def send_message(self, uid, text, **kw):
        self.sent.append((uid, text, kw.get("reply_markup")))
    async def download(self, fid, destination=None):
        with open(destination, "wb") as f:
            f.write(b"jpg:" + fid.encode())
    async def copy_message(self, **kw):
        self.copied.append(kw)
        return types.SimpleNamespace(message_id=777)


class Msg:
    """Guruhdagi video xabar (mavzuda)."""
    def __init__(self, mid, thread, name="", cap="", dur=3600):
        self.message_id, self.message_thread_id, self.is_topic_message = mid, thread, True
        self.chat = types.SimpleNamespace(id=-100, type="supergroup")
        self.video = types.SimpleNamespace(file_name=name, file_size=10, duration=dur)
        self.document, self.caption, self.photo = None, cap, None


async def main():
    e = hpserial.ep_of
    check("S01E03", e("Harry.Potter.S01E03.1080p.x264.mkv") == (1, 3))
    check("s2e10 bo'sh joy bilan", e("hp s2 e10") == (2, 10))
    check("1x03", e("Harry Potter 1x03") == (1, 3))
    check("1-fasl 3-qism", e("Garri Potter 1-fasl 3-qism") == (1, 3))
    check("2 mavsum 5 qism", e("2 mavsum 5 qism") == (2, 5))
    check("faqat 3-qism -> 1-fasl", e("Garri Potter 3-qism (o'zbek tilida)") == (1, 3))
    check("Сезон 1 серия 4", e("Гарри Поттер. Сезон 1 серия 4") == (1, 4))
    check("2 сезон 7 серия", e("2 сезон 7 серия") == (2, 7))
    check("Season 1 Episode 8", e("Season 1 Episode 8") == (1, 8))
    check("E05", e("HP.E05.2026.2160p.mp4") == (1, 5))
    check("yil va sifat qism emas", e("Harry Potter 2026 1080p.mp4") is None)
    check("bo'sh matn", e("") is None and e(None) is None)
    check("kalit", hpserial.parse_key("S1E3_uz") == (1, 3, "uz") and hpserial.parse_key("hp1_uz") is None)

    bot = FakeBot()
    elonlar = []
    async def elon(matnlar):
        elonlar.append(matnlar)
    async def sub(chat):
        return True
    hpserial._cfg.update({"bot": bot, "admin_ids": {42}, "cors": lambda r: r, "elon": elon,
                          "verify_init_data": lambda d: {"id": int(d)} if d.lstrip("-").isdigit() else None,
                          "is_subscribed": sub, "tg_chat_id": lambda u: u})
    hpserial._data.update({"group": -100, "topics": {"7": "uz", "9": "ru"}})

    await hpserial.on_group_video(Msg(50, 7, name="HP.S01E01.mp4"))
    check("sinov rejimida bog'landi va adminga aytildi",
          "s1e1_uz" in hpserial._data["eps"] and "sinov" in bot.sent[-1][1] and bot.sent[-1][2] is None)
    check("sinovda oddiy odam ko'rmaydi", hpserial.public_list(5) == [])
    check("sinovda admin ko'radi", [x["e"] for x in hpserial.public_list(42)] == [1])
    r = await hpserial.api_list(Req(init="5", method="GET"))
    check("api: oddiy odamga bo'sh", json.loads(r.body) == {"ok": True, "eps": [], "covers": {}, "test": False})
    r = await hpserial.api_list(Req(init="42", method="GET"))
    check("api: adminga qism va sinov belgisi", json.loads(r.body)["test"] and len(json.loads(r.body)["eps"]) == 1)
    r = await hpserial.api_send(Req({"s": 1, "e": 1, "lang": "uz"}, init="5"))
    check("sinovda oddiy odamga yuborilmaydi", json.loads(r.body)["error"] == "not_ready" and not bot.copied)

    await hpserial.on_group_video(Msg(51, 7, name="clip.mp4"))
    check("tanilmagan video - qo'lda buyruq aytiladi", "/qism s1e1_uz 51" in bot.sent[-1][1])

    hpserial._data["ochiq"] = True
    await hpserial.on_group_video(Msg(60, 7, cap="1-fasl 2-qism"))
    check("ochiq rejimda yangi qismda e'lon tugmasi", bot.sent[-1][2] is not None)
    await hpserial.on_group_video(Msg(61, 9, cap="Сезон 1 серия 2"))
    check("ruscha mavzu -> ru", hpserial.source(1, 2, "ru") == (-100, 61))
    check("ochiqda hamma ko'radi", len(hpserial.public_list(5)) == 3)
    await hpserial.on_group_video(Msg(62, 7, cap="1-fasl 2-qism"))
    check("qayta tashlansa yangilanadi", hpserial.source(1, 2, "uz") == (-100, 62))

    r = await hpserial.api_send(Req({"s": 1, "e": 2, "lang": "uz", "ui": "uz"}, init="5"))
    check("qism yuborildi (himoyalangan nusxa)", json.loads(r.body)["ok"] and bot.copied[-1]["message_id"] == 62
          and bot.copied[-1]["protect_content"] and "1-fasl, 2-qism" in bot.copied[-1]["caption"])
    r = await hpserial.api_send(Req({"s": 1, "e": 2, "lang": "uz"}, init="5"))
    check("ketma-ket bosish - slow", json.loads(r.body)["error"] == "slow")
    r = await hpserial.api_send(Req({"s": 1, "e": 9, "lang": "uz"}, init="6"))
    check("yo'q qism - not_ready", json.loads(r.body)["error"] == "not_ready")
    r = await hpserial.api_send(Req({"s": 1, "e": 2, "lang": "uz"}, init="yolgon"))
    check("imzosiz - 403", r.status == 403)

    class Call:
        def __init__(self, uid, data):
            self.from_user, self.data, self.javob = types.SimpleNamespace(id=uid), data, None
            self.message = types.SimpleNamespace(edit_reply_markup=self._edit)
        async def _edit(self, **kw): pass
        async def answer(self, text=None, **kw): self.javob = text
    await hpserial.on_elon(Call(5, "srl_elon:1:2"))
    await asyncio.sleep(0)
    check("admin bo'lmagan e'lon qila olmaydi", elonlar == [])
    await hpserial.on_elon(Call(42, "srl_elon:1:2"))
    await asyncio.sleep(0)
    check("e'lon faqat qismi bor tillarga", len(elonlar) == 1 and sorted(elonlar[0]) == ["ru", "uz"]
          and "2-qism" in elonlar[0]["uz"][0])
    await hpserial.on_elon(Call(42, "srl_elon:1:2"))
    await asyncio.sleep(0)
    check("bir qism ikki marta e'lon qilinmaydi", len(elonlar) == 1)

    # Qism rasmi: mavzuga rasm + izoh
    rasm = Msg(80, 9, cap="1-fasl 2-qism")
    rasm.video = None
    rasm.photo = [types.SimpleNamespace(file_id="kichik", width=90, height=50),
                  types.SimpleNamespace(file_id="katta", width=1280, height=720)]
    check("rasm filtri: rasm ha, video yo'q", hpserial._in_serial_photo(rasm) and not hpserial._in_serial_photo(Msg(81, 7)))
    await hpserial.on_group_photo(rasm)
    check("rasm saqlandi (eng kattasi)", open(hpserial.cover_path(1, 2), "rb").read() == b"jpg:katta"
          and "s1e2" in hpserial.covers())
    r = await hpserial.api_list(Req(init="5", method="GET"))
    check("api: rasm versiyasi beriladi", "s1e2" in json.loads(r.body)["covers"])
    rasm2 = Msg(82, 7, cap="chiroyli rasm")
    rasm2.video, rasm2.photo = None, rasm.photo
    await hpserial.on_group_photo(rasm2)
    check("raqamsiz rasm - adminga aytiladi", "tanilmadi" in bot.sent[-1][1])

    hpserial._place({"mid": 99}, 1, 2, "uz", "qolda")
    await hpserial.on_group_video(Msg(70, 7, cap="1-fasl 2-qism"))
    check("qo'lda bog'langan avtomatik bilan almashmaydi", hpserial.source(1, 2, "uz") == (-100, 99))

    hpserial._data.update({"eps": {}, "ochiq": False})
    hpserial.load()
    check("fayldan qayta o'qiladi", "s1e1_uz" in hpserial._data["eps"] and hpserial._data["ochiq"] is True)

    print("O'tdi: %d, xato: %d" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(main()) else 0)
