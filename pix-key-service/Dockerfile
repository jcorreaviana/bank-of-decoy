FROM python:3.12-slim

WORKDIR /app

# Build context e a raiz do monorepo (nao este diretorio) - necessario
# para incluir shared/test_safety e shared/chaos, dependencias locais
# editable instaladas via requirements.txt (ver docker-compose.yml,
# specs/tech/testing.md, specs/business/11-camada-caos.md).
COPY shared/test_safety /shared/test_safety
COPY shared/chaos /shared/chaos
COPY pix-key-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY pix-key-service/app ./app

ENV PORT=8003
EXPOSE 8003

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
