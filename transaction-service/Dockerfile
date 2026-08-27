FROM python:3.12-slim

WORKDIR /app

# Build context e a raiz do monorepo (nao este diretorio) - necessario
# para incluir shared/risk_engine, dependencia local editable instalada
# via requirements.txt (ver docker-compose.yml, issue #8).
COPY shared/risk_engine /shared/risk_engine
COPY transaction-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY transaction-service/app ./app

ENV PORT=8004
EXPOSE 8004

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
