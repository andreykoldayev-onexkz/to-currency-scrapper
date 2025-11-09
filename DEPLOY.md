# Деплой в Yandex Cloud

## Быстрый старт

### 1. Локальное тестирование

```bash
# Скопируйте .env.example в .env и заполните своими данными
cp .env.example .env

# Тестирование с Docker Compose
docker-compose up --build

# Или с помощью тестового скрипта
./test_docker.sh
```

### 2. Сборка и загрузка образа в Yandex Container Registry

```bash
# Авторизация в Yandex Cloud
yc container registry configure-docker

# Сборка образа
docker build -t cr.yandex/<registry-id>/currency-scraper:latest .

# Загрузка образа
docker push cr.yandex/<registry-id>/currency-scraper:latest
```

### 3. Создание контейнера в Yandex Cloud

```bash
yc serverless container create --name currency-scraper
```

### 4. Деплой новой ревизии

```bash
yc serverless container revision deploy \
  --container-name currency-scraper \
  --image cr.yandex/<registry-id>/currency-scraper:latest \
  --cores 1 \
  --memory 2GB \
  --execution-timeout 120s \
  --environment OUTLOOK_EMAIL=<your-email> \
  --environment OUTLOOK_PASSWORD=<your-password> \
  --environment TARGET_EMAIL=<target-email> \
  --environment API_URL=<your-api-url> \
  --environment STORAGE_ENDPOINT=https://storage.yandexcloud.net \
  --environment STORAGE_BUCKET=<your-bucket> \
  --environment STORAGE_STATE_KEY=playwright/storage_state.json \
  --environment STORAGE_ACCESS_KEY=<your-access-key> \
  --environment STORAGE_SECRET_KEY=<your-secret-key> \
  --environment PLAYWRIGHT_HEADLESS=1
```

### 5. Настройка триггера (опционально)

Для автоматического запуска по расписанию:

```bash
yc serverless trigger create timer \
  --name currency-scraper-trigger \
  --cron-expression "0 9 * * ? *" \
  --invoke-container-name currency-scraper \
  --invoke-container-service-account-id <service-account-id>
```

## Мониторинг

### Просмотр логов

```bash
yc logging read --group-id=<log-group-id> --follow
```

### Проверка статуса

```bash
yc serverless container revision list --container-name currency-scraper
```

## Устранение проблем

### "Page crashed" ошибка

Если продолжает падать:
1. Увеличьте память до 4GB: `--memory 4GB`
2. Увеличьте timeout: `--execution-timeout 180s`
3. Проверьте логи на наличие "Out of memory"

### Timeout ошибка

Увеличьте execution-timeout:
```bash
--execution-timeout 300s
```

### Проблемы с сетью

Убедитесь, что контейнер имеет доступ к интернету и настроены правильные security groups.
