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
import hashlib, os, sys, urllib.request, tarfile
url = os.environ["DATA_BUNDLE_URL"]
print("GET", url[:100])
fn = "/tmp/data-bundle.tar.gz"
urllib.request.urlretrieve(url, fn)
print("size:", os.path.getsize(fn) // 1024 // 1024, "MB")

# контрольная сумма (если задана DATA_BUNDLE_SHA256) — защита от подмены бандла
want = os.environ.get("DATA_BUNDLE_SHA256", "").lower()
if want:
    h = hashlib.sha256()
    with open(fn, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    if h.hexdigest() != want:
        sys.exit(f"SHA256 не совпал: {h.hexdigest()} != {want}")
    print("SHA256 ok")

# защита от path traversal: только относительные пути без '..'
with tarfile.open(fn) as t:
    for m in t.getmembers():
        name = m.name.replace("\\", "/")
        if name.startswith("/") or ".." in name.split("/"):
            sys.exit(f"опасный путь в архиве: {m.name}")
    t.extractall(".")
os.remove(fn)
print("данные распакованы")
PY
fi

echo "Старт сервера: http://0.0.0.0:8017"
exec python -m uvicorn backend.app:app --host 0.0.0.0 --port 8017
