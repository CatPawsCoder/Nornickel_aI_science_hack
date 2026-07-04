# Научный клубок — HF Space (CPU, лайт-режим: SQLite FTS5 + Kùzu)
FROM python:3.11-slim

WORKDIR /app

COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

COPY backend/ backend/
COPY ontology/ ontology/
COPY frontend/ frontend/
COPY certs/ certs/
# предсобранные данные: граф + лёгкий индекс (LFS)
COPY data/ data/

# HF запускает контейнер не от root — открываем чтение и даём писать в data
RUN chmod -R a+rX /app && chmod -R a+w /app/data

ENV PYTHONUNBUFFERED=1 \
    KLUBOK_LIGHT=1 \
    KUZU_BUFFER_MB=1024

EXPOSE 8017
CMD ["python", "-m", "uvicorn", "backend.app:app", "--host", "0.0.0.0", "--port", "8017"]
