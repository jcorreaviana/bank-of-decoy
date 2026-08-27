FROM python:3.12-slim

WORKDIR /app

# Build context e a raiz do monorepo (nao este diretorio) - necessario
# para incluir shared/test_safety, dependencia local editable instalada
# via requirements.txt (ver docker-compose.yml, specs/tech/testing.md).
COPY shared/test_safety /shared/test_safety
COPY account-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY account-service/app ./app

ENV PORT=8002
EXPOSE 8002

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
