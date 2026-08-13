import os, json
import gspread
from google.oauth2.service_account import Credentials

SHEET_ID = os.getenv("SHEET_ID")
KEY_PATH = os.getenv("GOOGLE_KEY_PATH", "google_key.json")

scopes = ["https://www.googleapis.com/auth/spreadsheets",
          "https://www.googleapis.com/auth/drive"]
creds = Credentials.from_service_account_file(KEY_PATH, scopes=scopes)
ws = gspread.authorize(creds).open_by_key(SHEET_ID).get_worksheet(0)

# Jadvalda hozir nima borligini o'qiymiz
mavjud = set()
for r in ws.get_all_values()[1:]:
    if len(r) >= 5:
        mavjud.add((r[0].strip(), r[3].strip(), r[4].strip()))
print(f"Jadvalda hozir {len(mavjud)} ta yozuv bor.")

with open("users_db.json", encoding="utf-8") as f:
    db = json.load(f)

yangi = []
for uid, u in db.items():
    nick = u.get("nickname", "")
    uname = u.get("username", "")
    for payload, times in u.get("clicks", {}).items():
        for t in times:
            kalit = (str(uid).strip(), payload.strip(), t.strip())
            if kalit not in mavjud:
                yangi.append([str(uid), nick, uname, payload, t])
                mavjud.add(kalit)

yangi.sort(key=lambda x: x[4])
print(f"Qo'shiladigan yangi yozuvlar: {len(yangi)} ta")

if yangi:
    for i in range(0, len(yangi), 500):
        ws.append_rows(yangi[i:i+500], value_input_option="USER_ENTERED")
    print("Muvaffaqiyatli ko'chirildi!")
else:
    print("Yangi yozuv yo'q, hammasi allaqachon jadvalda.")
