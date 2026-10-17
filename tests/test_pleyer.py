"""Ilova ichidagi pleyer: nusxalar, imzoli kalit, ruxsat, Range bilan oqim (Telegram o'rnida soxta manba).

Ishga tushirish (CatalogBot papkasida):  python tests/run_all.py
"""
import asyncio
import hashlib
import hmac
import json
import os
import sys
import tempfile
import types
import urllib.parse
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
sys.path.insert(0, ROOT)
TMP = tempfile.mkdtemp(prefix="hp-pleyer-")
os.environ["HP_DB_PATH"] = os.path.join(TMP, "hp.db")
os.environ["HP_QUESTIONS_DIR"] = os.path.join(ROOT, "questions")
os.environ["BOT_TOKEN"] = "123456:TEST-token"
os.environ["ADMIN_IDS"] = "42"

sheets = types.ModuleType("sheets")
async def _none(*a, **k): return None
sheets.append_click = _none
sheets.read_csv = _none
sys.modules["sheets"] = sheets

from aiohttp import web                      # noqa: E402
from aiohttp.test_utils import TestClient, TestServer   # noqa: E402
import hpfilms, hppleyer, main               # noqa: E402

hpfilms.STORE = os.path.join(TMP, "films.json")
hppleyer.STORE = os.path.join(TMP, "pleyer.json")
hppleyer.STAT = os.path.join(TMP, "pleyer_stat.json")
hppleyer.META = os.path.join(TMP, "pleyer_meta.json")

ok = fail = 0
def check(name, cond):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("XATO:", name)


def init_data(uid):
    data = {"auth_date": str(int(datetime.now(timezone.utc).timestamp())), "query_id": "AA",
            "user": json.dumps({"id": uid, "first_name": "T"})}
    chk = "\n".join("%s=%s" % (k, data[k]) for k in sorted(data))
    secret = hmac.new(b"WebAppData", os.environ["BOT_TOKEN"].encode(), hashlib.sha256).digest()
    data["hash"] = hmac.new(secret, chk.encode(), hashlib.sha256).hexdigest()
    return urllib.parse.urlencode(data)


FILE = bytes(range(256)) * 4000           # 1 024 000 bayt - "film"
olindi = []                               # soxta manbadan so'ralgan oraliqlar


async def fake_chunks(item, start, end):
    olindi.append((item["mid"], start, end))
    i = start
    while i <= end:
        j = min(end, i + 99999)
        yield FILE[i:j + 1]
        i = j + 1


async def amain():
    hpfilms._data.update({"group": -1001234567890, "topics": {}, "seen": {}, "map": {
        "hp1_uz": {"mid": 10, "name": "hp1 (1080p).mp4", "size": len(FILE), "dur": 9000, "h": 1080},
        "hp1_uz@hd": {"mid": 11, "name": "hp1 (720p).mp4", "size": len(FILE), "dur": 9000, "h": 720},
        "hp1_uz~zor@hd": {"mid": 12, "name": "hp1 ZOR TV (720p).mp4", "size": len(FILE), "dur": 9000},
        "hp1_ru": {"mid": 13, "name": "hp1 rus.mkv", "size": len(FILE), "dur": 9000},
        "hp1_en@sd": {"mid": 14, "name": "hp1 eng 480p.mp4", "size": len(FILE), "dur": 9000},
        "hp2_uz": {"mid": 20, "name": "hp2.mp4", "size": len(FILE)},
    }})

    hppleyer._cfg.update({"admin_ids": {42}, "token": os.environ["BOT_TOKEN"], "cors": main._cors,
                          "verify_init_data": main.verify_init_data, "public_base": "https://x"})

    # --- Nusxalar ---
    vs = hppleyer.versions("hp1")
    check("hp1 ning beshta nusxasi, boshqa film aralashmaydi", [v["v"] for v in vs] ==
          ["hp1_uz", "hp1_uz@hd", "hp1_uz~zor@hd", "hp1_ru", "hp1_en@sd"])
    zor = [v for v in vs if v["v"] == "hp1_uz~zor@hd"][0]
    check("ZO'R TV nusxasida til, dublyaj, sifat", zor["lang"] == "uz" and zor["dub"] == "zor" and zor["q"] == "hd")
    check("asosiy dublyaj nomi my5", vs[0]["dub"] == "my5" and vs[3]["dub"] == "")
    check("mkv turi", [v for v in vs if v["v"] == "hp1_ru"][0]["mime"] == "video/x-matroska")
    check("noto'g'ri nusxa nomi - yo'q", hppleyer.nusxa("../etc") is None and hppleyer.nusxa("hp9_uz") is None)

    # --- Kalit ---
    k = hppleyer.make_key(42, now=1000)
    check("kalit o'z vaqtida ishlaydi", hppleyer.check_key(k, now=1000 + 3600) == 42)
    check("kalit 6 soatdan keyin eskiradi", hppleyer.check_key(k, now=1000 + 6 * 3600 + 1) is None)
    check("o'zgartirilgan kalit rad etiladi", hppleyer.check_key(k.replace("42.", "43.", 1), now=1000) is None)

    # --- Ruxsat ---
    check("sinov rejimida admin va uning sinov o'quvchisi", hppleyer.allowed(42) and hppleyer.allowed(-42))
    check("sinov rejimida oddiy odam yo'q", not hppleyer.allowed(7))

    # --- Range ---
    pr = hppleyer.parse_range
    check("range: boshi", pr("bytes=0-1", 100) == (0, 1) and pr("bytes=10-", 100) == (10, 99))
    check("range: oxiri", pr("bytes=-10", 100) == (90, 99) and pr(None, 100) is None)
    try:
        pr("bytes=200-", 100)
        check("range: chegaradan tashqari", False)
    except ValueError:
        check("range: chegaradan tashqari", True)

    # --- Parallel bo'laklar: tartib buzilmasin, yopilsa qolganlari bekor ---
    import random
    asl_chunks, asl_blok, asl_client = hppleyer._chunks, hppleyer._blok, hppleyer._get_client
    KATTA = bytes(random.randrange(256) for _ in range(5 * 1024 * 1024 + 12345))
    sorovlar, bekor, kech = [], [], [0]

    async def soxta_blok(c, item, off, n):
        sorovlar.append(off)
        try:
            await asyncio.sleep(kech[0] if off else 0 if kech[0] else random.random() * 0.02)  # har xil tartibda tugaydi
        except asyncio.CancelledError:
            bekor.append(off)
            raise
        return KATTA[off:off + n]

    async def soxta_client():
        return object()
    hppleyer._blok, hppleyer._get_client = soxta_blok, soxta_client
    it_k = {"mid": 1, "size": len(KATTA)}

    async def yig(a, b):
        out = bytearray()
        async for ch in asl_chunks(it_k, a, b):
            out += ch
        return bytes(out)
    togri = True
    for a, b in ((0, 1), (0, len(KATTA) - 1), (1048575, 1048577), (3000000, 5000000), (len(KATTA) - 10, len(KATTA) - 1), (2097152, 2097152)):
        togri = togri and (await yig(a, b)) == KATTA[a:b + 1]
    check("parallel bo'laklar: har qanday oraliq aynan to'g'ri tartibda", togri)
    sorovlar.clear()
    kech[0] = 0.3                     # birinchisidan boshqa bo'laklar sekin keladi
    gen = asl_chunks(it_k, 0, len(KATTA) - 1)
    await gen.__anext__()
    check("oldindan 4 tagacha bo'lak so'raladi", 2 <= len(sorovlar) <= 5)
    await gen.aclose()
    await asyncio.sleep(0.05)
    check("tomoshabin yopsa kutilayotgan bo'laklar bekor qilinadi, yangisi so'ralmaydi",
          sorted(bekor) == sorted(sorovlar[1:]) and len(sorovlar) == 4)
    hppleyer._blok, hppleyer._get_client = asl_blok, asl_client

    # --- HTTP ---
    app = web.Application()
    app.router.add_route("*", "/api/pleyer", hppleyer.api_info)
    app.router.add_route("*", "/api/pleyer/v/{v}", hppleyer.api_video)
    hppleyer._chunks = fake_chunks
    async with TestClient(TestServer(app)) as cl:
        r = await cl.post("/api/pleyer", json={"film": "hp1"}, headers={"X-Telegram-Init-Data": init_data(7)})
        j = await r.json()
        check("oddiy odamga yopiq", j == {"ok": False, "error": "yopiq"})
        r = await cl.post("/api/pleyer", json={"film": "hp1"}, headers={"X-Telegram-Init-Data": init_data(42)})
        j = await r.json()
        check("kalit yo'q - tayyor emas", j.get("ok") and j.get("ready") is False)
        hppleyer._data.update({"api_id": 1, "api_hash": "a" * 32})
        r = await cl.post("/api/pleyer", json={"film": "hp1"}, headers={"X-Telegram-Init-Data": init_data(42)})
        j = await r.json()
        check("admin: nusxalar va kalit", j.get("ready") and len(j["versions"]) == 5 and
              hppleyer.check_key(j["key"]) == 42 and j["base"] == "https://x/api/pleyer/v/")
        r = await cl.post("/api/pleyer", json={"film": "hp1"}, headers={"X-Telegram-Init-Data": "x=1&hash=0"})
        check("imzosiz so'rov rad etiladi", r.status == 403)

        key = j["key"]
        u = "/api/pleyer/v/%s?k=%s" % (urllib.parse.quote("hp1_uz~zor@hd"), key)
        r = await cl.get(u, headers={"Range": "bytes=0-1"})
        b = await r.read()
        check("Safari sinovi: 2 bayt, 206", r.status == 206 and b == FILE[:2] and
              r.headers["Content-Range"] == "bytes 0-1/%d" % len(FILE) and r.headers["Content-Type"] == "video/mp4")
        r = await cl.get(u, headers={"Range": "bytes=500000-600123"})
        b = await r.read()
        check("o'rtasidan sakrash: aynan o'sha baytlar", r.status == 206 and b == FILE[500000:600124]
              and olindi[-1] == (12, 500000, 600123))
        r = await cl.get(u)
        b = await r.read()
        check("butun fayl: 200 va to'liq", r.status == 200 and b == FILE and r.headers["Accept-Ranges"] == "bytes")
        r = await cl.head(u)
        check("HEAD: hajm", r.status == 200 and r.headers["Content-Length"] == str(len(FILE)))
        r = await cl.get(u, headers={"Range": "bytes=%d-" % (len(FILE) + 5)})
        check("noto'g'ri oraliq - 416", r.status == 416)
        r = await cl.get("/api/pleyer/v/hp1_uz?k=" + key.replace(".", "x", 1))
        check("buzilgan kalit - 403", r.status == 403)
        r = await cl.get("/api/pleyer/v/hp1_uz?k=" + hppleyer.make_key(7))
        check("oddiy odamning kaliti sinov rejimida - 403", r.status == 403)
        r = await cl.get("/api/pleyer/v/hp1_en?k=" + key)
        check("yo'q nusxa - 404", r.status == 404)

        # Tomoshabin yarmida yopib ketsa: manba darhol yopiladi
        yopildi = []

        async def sekin(item, start, end):
            try:
                i = start
                while i <= end:
                    yield FILE[i:i + 65536]
                    i += 65536
                    await asyncio.sleep(0.01)
            finally:
                yopildi.append(1)
        hppleyer._chunks = sekin
        r = await cl.get(u)
        await r.content.read(70000)
        r.close()
        for _ in range(100):
            if yopildi:
                break
            await asyncio.sleep(0.02)
        check("yopib ketsa Telegram'dan olish to'xtaydi", yopildi == [1])
        hppleyer._chunks = fake_chunks

    s = hppleyer._stat[hppleyer._kun()]
    check("trafik sanaldi (2 + 100124 + to'liq fayl)", s["b"] >= 2 + 100124 + len(FILE))
    check("tomosha: faqat boshidan katta so'rov sanaladi", s["n"] >= 1 and s["u"] == [42])
    hppleyer._stat_dirty = True
    hppleyer._stat_save()
    check("statistika faylga yozildi", os.path.exists(hppleyer.STAT))

    # --- MP4 ichi: hev1 -> hvc1 (Safari uchun) ---
    import struct

    def box(t, body):
        return struct.pack(">I", 8 + len(body)) + t + body

    def mp4(entry, mdat=300000, moov_oldin=False):
        stsd = box(b"stsd", b"\0" * 4 + struct.pack(">I", 1) + entry)
        moov = box(b"moov", box(b"mvhd", b"\0" * 100) + box(b"trak", box(b"mdia", box(b"minf", box(b"stbl", stsd)))))
        bosh = box(b"ftyp", b"isom" + b"\0" * 4 + b"isomiso2mp41") + box(b"free", b"")
        md = box(b"mdat", bytes(i % 251 for i in range(mdat)))
        return bosh + (moov + md if moov_oldin else md + moov)

    hev = mp4(box(b"hev1", b"\0" * 78 + box(b"hvcC", b"\x01" * 23)))
    avc10 = mp4(box(b"avc1", b"\0" * 78 + box(b"avcC", bytes([1, 110, 0, 40]) + b"\0" * 10)), moov_oldin=True)
    FAYL = {50: hev, 51: avc10}

    async def mp4_chunks(item, start, end):
        d = FAYL[item["mid"]]
        i = start
        while i <= end:
            j = min(end, i + 70000)          # bo'laklar chegarasi "hev1" ni kesib o'tishi ham sinaladi
            yield d[i:j + 1]
            i = j + 1
    hppleyer._chunks = mp4_chunks
    hpfilms._data["map"]["hp3_uz@hd"] = {"mid": 50, "name": "hp3.mp4", "size": len(hev)}
    hpfilms._data["map"]["hp3_uz"] = {"mid": 51, "name": "hp3.mp4", "size": len(avc10)}
    m = await hppleyer.meta("hp3_uz@hd", hppleyer.nusxa("hp3_uz@hd"))
    check("hev1 topildi, joyi aniq (moov fayl oxirida)", m["c"] == "hev1" and hev[m["p"]:m["p"] + 4] == b"hev1")
    m2 = await hppleyer.meta("hp3_uz", hppleyer.nusxa("hp3_uz"))
    check("10 bitli H.264 tanildi (moov boshida), almashtirilmaydi", m2["c"] == "avc1" and m2.get("prof") == 110 and m2["p"] is None)
    vs3 = {v["v"]: v for v in hppleyer.versions("hp3")}
    check("nusxalarda video turi va 10 bit belgisi", vs3["hp3_uz@hd"]["codec"] == "hev1" and vs3["hp3_uz"]["p10"] is True
          and vs3["hp3_uz@hd"]["p10"] is False)
    check("video turi faylga yozildi", json.load(open(hppleyer.META))["hp3_uz@hd"]["p"] == m["p"])
    P = m["p"]
    async with TestClient(TestServer(app)) as cl:
        u3 = "/api/pleyer/v/%s?k=%s" % (urllib.parse.quote("hp3_uz@hd"), hppleyer.make_key(42))
        r = await cl.get(u3)
        b = await r.read()
        check("butun fayl: faqat 4 bayt o'zgardi -> hvc1", len(b) == len(hev) and b[P:P + 4] == b"hvc1"
              and b[:P] == hev[:P] and b[P + 4:] == hev[P + 4:])
        r = await cl.get(u3, headers={"Range": "bytes=%d-%d" % (P + 2, P + 9)})
        b = await r.read()
        check("oraliq belgining o'rtasidan boshlansa ham", b == b"c1" + hev[P + 4:P + 10])
        r = await cl.get(u3, headers={"Range": "bytes=0-99"})
        check("belgiga tegmaydigan oraliq o'zgarmaydi", await r.read() == hev[:100])
        u4 = "/api/pleyer/v/hp3_uz?k=" + hppleyer.make_key(42)
        r = await cl.get(u4)
        check("avc1 fayl o'zgarmasdan uzatiladi", await r.read() == avc10)
    check("_yamoq: bo'lak chegarasida", hppleyer._yamoq(b"xxhe", 10, 12) == b"xxhv" and hppleyer._yamoq(b"v1yy", 14, 12) == b"c1yy")
    hppleyer._chunks = fake_chunks

    # --- Admin buyrug'i: kalit tekshiruvi ---
    javob = []

    class Msg:
        def __init__(self, text):
            self.text = text
            self.from_user = types.SimpleNamespace(id=42)
            self.chat = types.SimpleNamespace(type="private")
            self.ochdi = False
        async def delete(self):
            self.ochdi = True
        async def answer(self, t, **kw):
            javob.append(t)

    hppleyer._data.update({"api_id": 0, "api_hash": ""})
    m = Msg("/pleyer kalit 12 salom")
    await hppleyer.on_pleyer_command(m)
    check("noto'g'ri kalit saqlanmaydi, xabar baribir o'chadi", m.ochdi and not hppleyer.ready() and "Yozilishi" in javob[-1])

    async def ulanmaydi():
        hppleyer._client_err = "sinov"
        return None
    eski = hppleyer._get_client
    hppleyer._get_client = ulanmaydi
    m = Msg("/pleyer kalit 1234567 " + "0123456789abcdef" * 2)
    await hppleyer.on_pleyer_command(m)
    hppleyer._get_client = eski
    check("to'g'ri kalit saqlanadi", m.ochdi and hppleyer.ready() and hppleyer._data["api_id"] == 1234567
          and json.load(open(hppleyer.STORE))["api_id"] == 1234567)
    await hppleyer.on_pleyer_command(Msg("/pleyer ochiq"))
    check("ochiq rejim - oddiy odamga ham", hppleyer.allowed(7) and "OCHIQ" in javob[-1])
    await hppleyer.on_pleyer_command(Msg("/pleyer sinov"))
    check("sinovga qaytdi", not hppleyer.allowed(7))

    print("O'tdi: %d, xato: %d" % (ok, fail))
    return fail


if __name__ == "__main__":
    sys.exit(1 if asyncio.run(amain()) else 0)
