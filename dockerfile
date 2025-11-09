# Используем официальный образ Python с поддержкой Playwright
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы проекта
COPY app.py /app/app.py
COPY requirements.txt /app/requirements.txt

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# (Опционально) — можно установить только нужные браузеры
RUN playwright install chromium --with-deps

# Устанавливаем переменные окружения (при необходимости можно переопределить в docker run / compose)
ENV PYTHONUNBUFFERED=1 \
    OUTLOOK_EMAIL=andrey.koldayev@r-express.ru \
    OUTLOOK_PASSWORD=fUsVzN99! \
    TARGET_EMAIL=andrey.koldayev@r-express.ru \
    API_URL=https://megapolus.bitrix24.ru/rest/11/pbjl5ed8q1303lh0/bizproc.workflow.start \
    STORAGE_ENDPOINT=https://storage.yandexcloud.net \
    STORAGE_BUCKET=cdn.mt-app.ru \
    STORAGE_STATE_KEY=playwright/storage_state.json \
    STORAGE_ACCESS_KEY=YCAJEeWXehH3VGs3lWYglf2rH \
    STORAGE_SECRET_KEY=YCNSM6PNZ2bXop1KrwM_9Ko181cjHMUYxZx4gDhR

# Запуск приложения
CMD ["python", "app.py"]
