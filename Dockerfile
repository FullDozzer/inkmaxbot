FROM python:3.11-slim

WORKDIR /app

ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

COPY requirements.txt .

RUN pip install --no-cache-dir -r requirements.txt

COPY bot.py .
COPY staff_directory.py .
COPY fonts ./fonts
# Корневые сертификаты УЦ Минцифры: бот подхватывает их сам
# (certs/max_ca_bundle.crt), системное хранилище не трогается.
COPY certs ./certs

RUN mkdir -p /app/data
RUN mkdir -p /app/data/images

# Проверяем наличие шрифтов и CA-бандла во время сборки
RUN test -f /app/fonts/DejaVuSans.ttf
RUN test -f /app/fonts/DejaVuSans-Bold.ttf
RUN test -f /app/certs/max_ca_bundle.crt

CMD ["python", "-u", "bot.py"]
