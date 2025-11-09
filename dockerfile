# Используем официальный образ Python с поддержкой Playwright
FROM mcr.microsoft.com/playwright/python:v1.49.0-jammy

# Устанавливаем рабочую директорию
WORKDIR /app

# Копируем файлы проекта
COPY app.py /app/app.py
COPY requirements.txt /app/requirements.txt

# Устанавливаем зависимости
RUN pip install --no-cache-dir -r requirements.txt

# Устанавливаем только Chromium (экономим место)
RUN playwright install chromium

# Создаем директорию для временных файлов
RUN mkdir -p /tmp/.X11-unix && chmod 1777 /tmp/.X11-unix

# Устанавливаем базовые переменные окружения
# ВАЖНО: Секретные данные (пароли, ключи) должны передаваться через docker run -e или docker-compose
ENV PYTHONUNBUFFERED=1 \
    PLAYWRIGHT_HEADLESS=1 \
    PLAYWRIGHT_BROWSERS_PATH=/ms-playwright

# Запуск приложения
CMD ["python", "app.py"]
