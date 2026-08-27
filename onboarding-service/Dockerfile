FROM python:3.12-slim

WORKDIR /app

# Build context e a raiz do monorepo (nao este diretorio) - necessario
# para incluir shared/risk_engine e shared/test_safety, dependencias
# locais editable instaladas via requirements.txt (ver docker-compose.yml,
# issue #8, specs/tech/testing.md).
COPY shared/risk_engine /shared/risk_engine
COPY shared/test_safety /shared/test_safety
COPY onboarding-service/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY onboarding-service/app ./app

ENV PORT=8001
EXPOSE 8001

CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${PORT}"]
