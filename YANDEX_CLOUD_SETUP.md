# Настройка для Yandex Cloud

## Проблема
Playwright падает с ошибкой "Page crashed" в контейнере из-за нехватки ресурсов.

## Решение

### 1. Изменения в коде (уже применены)
- Добавлены аргументы запуска Chromium для работы в контейнере
- `--no-sandbox`, `--disable-dev-shm-usage`, `--no-zygote` - ключевые флаги
- Отключены GPU и ненужные функции браузера

### 2. Настройки контейнера в Yandex Cloud

При создании контейнера в Yandex Cloud Functions или Container Registry укажите:

**Рекомендуемые ресурсы:**
- Память: **2 GB** (протестировано и работает)
- CPU: **1 vCPU**
- Timeout: **120 секунд** (или больше)
- SHM Size: **2 GB** (важно!)

**Переменные окружения:**
```bash
PLAYWRIGHT_HEADLESS=1
PLAYWRIGHT_BROWSERS_PATH=/ms-playwright
```

### 3. Docker команды для локального тестирования

Тестирование с ограничением памяти (как в облаке):
```bash
docker build -t currency-scraper .
docker run --memory="2g" --shm-size="2g" currency-scraper
```

### 4. Важно: Не используйте --single-process

Флаг `--single-process` вызывает преждевременное закрытие браузера. Вместо этого используйте:
- `--no-zygote` - оптимизация для контейнеров
- `--disable-dev-shm-usage` - использование /tmp вместо /dev/shm
- Увеличьте shm_size до 2GB

### 5. Проверка логов

В Yandex Cloud проверьте логи контейнера:
```bash
yc logging read --group-id=<your-log-group-id>
```

Ищите сообщения:
- "Out of memory"
- "Page crashed"
- "Browser closed"

### 6. Резюме

Текущая конфигурация **протестирована и работает** с:
- 2 GB памяти
- 2 GB shm_size
- 1 vCPU
- Оптимизированными флагами Chromium
