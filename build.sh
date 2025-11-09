#!/bin/bash
set -e

# === Настройки ===
REGISTRY_ID="crpqihuhrng1p49hcd0i"
IMAGE_NAME="currency-scraper"
TAG="latest"
FULL_IMAGE="cr.yandex/${REGISTRY_ID}/${IMAGE_NAME}:${TAG}"

echo "🚀 Сборка образа: ${FULL_IMAGE}"
echo "---------------------------------------------"

# Авторизация (требуется один раз)
yc container registry configure-docker

# Проверяем, что билд-платформа готова
docker buildx inspect ycrbuilder >/dev/null 2>&1 || docker buildx create --use --name ycrbuilder
docker buildx inspect --bootstrap

# === Сборка и пуш ===
docker buildx build \
  --platform linux/amd64 \
  -t "${FULL_IMAGE}" \
  --push \
  .

echo "✅ Образ отправлен в Yandex Container Registry."
echo "---------------------------------------------"
echo "🔍 Проверяем тип манифеста..."

# Проверяем формат манифеста
MEDIA_TYPE=$(docker buildx imagetools inspect "${FULL_IMAGE}" | grep mediaType | head -n 1 | awk -F'"' '{print $4}')

if [[ "$MEDIA_TYPE" == "application/vnd.docker.distribution.manifest.v2+json" ]]; then
  echo "✅ Формат корректный: ${MEDIA_TYPE}"
else
  echo "⚠️ ВНИМАНИЕ: формат ${MEDIA_TYPE} — это OCI, Yandex может не принять."
fi

echo "---------------------------------------------"
echo "🏁 Готово!"
