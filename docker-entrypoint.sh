#!/bin/sh
# При первом старте докачивает предсобранные артефакты (граф Kùzu + BM25-индекс),
# чтобы жюри не пересобирало корпус (сборка полного корпуса требует исходного
# архива данных кейса и ~10 минут CPU).
set -e

if [ ! -d "data/kg.kuzu" ] || [ ! -f "data/cache/bm25.pkl" ]; then
    if [ -z "$DATA_BUNDLE_URL" ]; then
        echo "ОШИБКА: данные не найдены и DATA_BUNDLE_URL не задан."
        echo "Укажите в docker-compose.yml переменную DATA_BUNDLE_URL —"
        echo "прямую ссылку на data-bundle.tar.gz (см. SUBMISSION.md)."
        exit 1
    fi
    echo "Скачиваю предсобранные данные из DATA_BUNDLE_URL ..."
    python - <<'PY'
import os, sys, urllib.request, tarfile
url = os.environ["DATA_BUNDLE_URL"]
print("GET", url[:100])
fn = "/tmp/data-bundle.tar.gz"
urllib.request.urlretrieve(url, fn)
print("size:", os.path.getsize(fn) // 1024 // 1024, "MB, распаковка...")
with tarfile.open(fn) as t:
    t.extractall(".")
os.remove(fn)
print("данные распакованы")
PY
fi

echo "Старт сервера: http://0.0.0.0:8017"
exec python -m uvicorn backend.app:app --host 0.0.0.0 --port 8017
