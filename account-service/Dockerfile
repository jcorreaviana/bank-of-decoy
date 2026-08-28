FROM python:3.12-slim

WORKDIR /app

# Build context e a raiz do monorepo (nao este diretorio) - necessario
# para incluir shared/test_safety, shared/chaos e shared/kafka_dlt,
# dependencias locais editable instaladas via requirements.txt (ver
# docker-compose.yml, specs/tech/testing.md,
# specs/business/11-camada-caos.md, specs/business/22-poison-message-kafka.md).
COPY shared/test_safety /shared/test_safety
COPY shared/chaos /shared/chaos
COPY shared/kafka_dlt /shared/kafka_dlt
COPY account-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY account-service/app ./app

ENV PORT=8002
EXPOSE 8002

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
