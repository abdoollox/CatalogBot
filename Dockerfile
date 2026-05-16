# Python'ning rasmiy yengil versiyasini yuklab olish
FROM python:3.11-slim

# Server ichida /app degan ishchi papka yaratish
WORKDIR /app

# Kutubxonalar ro'yxatini serverga ko'chirish va o'rnatish
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Qolgan barcha kodlarni serverga ko'chirish
COPY . .

# Botni ishga tushirish buyrug'i (main.py o'rniga o'zingizning asosiy faylingiz nomini yozing)
CMD ["python", "main.py"]