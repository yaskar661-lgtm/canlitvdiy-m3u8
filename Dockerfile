FROM python:3.10-slim

WORKDIR /app

# Bağımlılıkları yükle
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Proje dosyalarını kopyala
COPY . .

# ÖNEMLİ: Bellekteki (CACHE) yapının bozulmaması ve tüm worker'ların 
# aynı veriyi paylaşması için "-w 1" (tek worker) zorunludur.
# 100+ kanalın ThreadPoolExecutor ile paralel taranabilmesi için 
# timeout süresi uzatılmıştır (--timeout 120).
CMD ["gunicorn", "--bind", "0.0.0.0:10000", "-w", "1", "--timeout", "120", "app:app"]
