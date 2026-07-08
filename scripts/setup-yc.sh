#!/usr/bin/env bash
set -euo pipefail

if [ -z "${YC_SERVICE_ACCOUNT_KEY:-}" ]; then
  echo "YC_SERVICE_ACCOUNT_KEY is not set"
  exit 1
fi

if [ -z "${YC_CLOUD_ID:-}" ]; then
  echo "YC_CLOUD_ID is not set"
  exit 1
fi

if [ -z "${YC_FOLDER_ID:-}" ]; then
  echo "YC_FOLDER_ID is not set"
  exit 1
fi

mkdir -p ~/.config/yandex-cloud
echo "$YC_SERVICE_ACCOUNT_KEY" > ~/.config/yandex-cloud/key.json
chmod 600 ~/.config/yandex-cloud/key.json

yc config profile create mt-admin || yc config profile activate mt-admin
yc config set service-account-key ~/.config/yandex-cloud/key.json
yc config set cloud-id "$YC_CLOUD_ID"
yc config set folder-id "$YC_FOLDER_ID"

yc config list