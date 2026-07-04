# Научный клубок — рантайм-образ (CPU-only, без GPU)
# Сборка:  docker build -t nauchny-klubok .
# Запуск:  docker compose up  (данные подтянутся по DATA_BUNDLE_URL при первом старте)
FROM python:3.11-slim

WORKDIR /app

# зависимости рантайма (все — manylinux wheels, компилятор не нужен)
COPY requirements-docker.txt .
RUN pip install --no-cache-dir -r requirements-docker.txt

# код
COPY backend/ backend/
COPY ontology/ ontology/
COPY frontend/ frontend/
COPY certs/ certs/
COPY docker-entrypoint.sh .
RUN chmod +x docker-entrypoint.sh && mkdir -p data/cache

EXPOSE 8017
# лайт-режим по умолчанию: SQLite FTS5 из бандла, <1ГБ RAM, без pickle
ENV PYTHONUNBUFFERED=1 \
    KLUBOK_LIGHT=1

# entrypoint: докачивает предсобранные данные (граф + индекс), затем uvicorn
ENTRYPOINT ["./docker-entrypoint.sh"]
