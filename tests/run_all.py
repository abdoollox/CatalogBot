"""Barcha sinovlarni ishga tushiradi. HAR DEPLOYDAN OLDIN:

    python tests/run_all.py

Har sinov o'z vaqtinchalik papkasida ishlaydi (haqiqiy bazaga tegmaydi).
Kerakli kutubxonalar: requirements.txt + aiofiles.
"""
import os
import shutil
import subprocess
import sys
import tempfile

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
TESTS = ["test_poydevor.py", "test_music.py", "test_v3.py", "test_http_api.py", "test_hamyon.py", "test_pochta.py", "test_serial.py"]

natija = []
for t in TESTS:
    ish = tempfile.mkdtemp(prefix="hp-run-")
    shutil.copytree(os.path.join(ROOT, "questions"), os.path.join(ish, "questions"))
    env = dict(os.environ, PYTHONWARNINGS="ignore", PYTHONIOENCODING="utf-8")
    r = subprocess.run([sys.executable, os.path.join(HERE, t)], cwd=ish, env=env,
                       capture_output=True, text=True)
    qatorlar = [l for l in r.stdout.splitlines() if l.strip() and set(l.strip()) != {"="}]
    oxiri = qatorlar[-1:] or [""]
    natija.append((t, r.returncode == 0, oxiri[0]))
    if r.returncode != 0:
        print((r.stdout + r.stderr)[-3000:])
    shutil.rmtree(ish, ignore_errors=True)

for t, ok, oxiri in natija:
    print("%s %-20s %s" % ("✅" if ok else "❌", t, oxiri[:90]))
sys.exit(0 if all(ok for _, ok, _ in natija) else 1)
