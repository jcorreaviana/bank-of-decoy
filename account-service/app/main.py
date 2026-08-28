import threading
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

from chaos import ChaosMiddleware
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import engine
from app.core.errors import register_exception_handlers
from app.core.kafka_consumer import run_onboarding_aprovado_consumer
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.core.metrics import MetricsMiddleware, register_db_pool_gauge
from app.routers import account, health, metrics

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)

_consumer_stop_event = threading.Event()


@asynccontextmanager
async def lifespan(_app: FastAPI) -> AsyncGenerator[None, None]:
    consumer_thread = threading.Thread(
        target=run_onboarding_aprovado_consumer, args=(_consumer_stop_event,), daemon=True
    )
    consumer_thread.start()
    try:
        yield
    finally:
        _consumer_stop_event.set()
        consumer_thread.join(timeout=10)


app = FastAPI(title=settings.service_name, lifespan=lifespan)
# ChaosMiddleware precisa ser o PRIMEIRO add_middleware (fica na camada mais
# interna) - ver docstring de shared/chaos/chaos/middleware.py.
app.add_middleware(ChaosMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(MetricsMiddleware)
register_exception_handlers(app)
register_db_pool_gauge(engine)
app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(account.router)
