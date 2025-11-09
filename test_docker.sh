#!/bin/bash

# Скрипт для тестирования Docker контейнера с ограничениями памяти

echo "Building Docker image..."
docker build -t currency-scraper .

echo ""
echo "Testing with 2GB memory limit (similar to Yandex Cloud)..."
docker run --rm \
  --memory="2g" \
  --memory-swap="2g" \
  --shm-size="2g" \
  --cpus="1" \
  --env-file .env \
  currency-scraper

echo ""
echo "Test completed!"
