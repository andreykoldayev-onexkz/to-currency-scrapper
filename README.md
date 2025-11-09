# to-currency-scrapper

Скрапер курсов валют туроператоров с использованием Playwright и requests.

## Проблема с Yandex Cloud

При запуске в контейнере Yandex Cloud Playwright падал с ошибкой:
```
WARNING:scraper:Playwright error: Page.goto: Page crashed
```

## Решение

### 1. Оптимизация запуска Chromium
Добавлены аргументы для работы в контейнере с ограниченными ресурсами:
- `--disable-dev-shm-usage` - отключает использование /dev/shm
- `--no-sandbox` - отключает sandbox (безопасно в контейнере)
- `--no-zygote` - оптимизация для контейнеров
- `--disable-gpu` - отключает GPU рендеринг
- Другие оптимизации для снижения потребления ресурсов

### 2. Требования к ресурсам в Yandex Cloud
- **Память**: 2 GB (рекомендуется)
- **CPU**: 1 vCPU
- **Timeout**: 120+ секунд
- **SHM Size**: 2 GB

### 3. Локальное тестирование
```bash
# Тестирование с ограничениями как в облаке
./test_docker.sh
```

## Установка

```bash
pip install -r requirements.txt
playwright install chromium
```

## Использование

```bash
python app.py
```

## Переменные окружения

Создайте файл `.env` на основе `.env.example`:

```bash
OUTLOOK_EMAIL=your_email@example.com
OUTLOOK_PASSWORD=your_password
TARGET_EMAIL=recipient@example.com
API_URL=https://your-api-url.com
STORAGE_ENDPOINT=https://storage.yandexcloud.net
STORAGE_BUCKET=your-bucket
STORAGE_STATE_KEY=playwright/storage_state.json
STORAGE_ACCESS_KEY=your_access_key
STORAGE_SECRET_KEY=your_secret_key
```

## Подробная документация

См. [YANDEX_CLOUD_SETUP.md](YANDEX_CLOUD_SETUP.md) для детальной настройки в Yandex Cloud.

