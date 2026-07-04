# Научный клубок — HF Space (CPU, лайт-режим: SQLite FTS5 + Kùzu)
# Данные НЕ хранятся в репозитории Space (лимит 1 ГБ на LFS):
# они скачиваются из dataset-репозитория на этапе СБОРКИ и вшиваются в образ.
FROM python:3.11-slim

WORKDIR /app

COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY backend/ backend/
COPY ontology/ ontology/
COPY frontend/ frontend/
COPY certs/ certs/

# --- данные: граф Kùzu + FTS5-индекс + метаданные (меняй DATA_VERSION для сброса кеша) ---
ARG DATA_VERSION=v4
RUN python - <<'PY'
import hashlib, os, tarfile, urllib.request
url = "https://huggingface.co/datasets/catpawws/nornickel-hack-demo/resolve/main/klubok-data-v4.tar.gz"
WANT_SHA256 = "ddbfd805e546c055097e46480b426827a00690bf2700ea7071100297252c8c81"
fn = "/tmp/data.tgz"
print("downloading", url)
urllib.request.urlretrieve(url, fn)
print("size:", os.path.getsize(fn)//(1<<20), "MB")
h = hashlib.sha256()
with open(fn, "rb") as f:
    for chunk in iter(lambda: f.read(1 << 20), b""):
        h.update(chunk)
assert h.hexdigest() == WANT_SHA256, f"SHA256 mismatch: {h.hexdigest()}"
print("sha256 ok")
with tarfile.open(fn) as t:
    for m in t.getmembers():
        n = m.name.replace("\\", "/")
        assert not n.startswith("/") and ".." not in n.split("/"), n
        assert m.isreg() or m.isdir(), n
    t.extractall(".")
os.remove(fn)
print("data extracted")
PY

RUN chmod -R a+rX /app && chmod -R a+w /app/data

ENV PYTHONUNBUFFERED=1 \
    KLUBOK_LIGHT=1 \
    KUZU_BUFFER_MB=1024

EXPOSE 8017
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8017"]
