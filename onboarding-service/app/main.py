from chaos import ChaosMiddleware, register_chaos_router
from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import engine
from app.core.errors import register_exception_handlers
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.core.metrics import MetricsMiddleware, register_db_pool_gauge
from app.routers import health, metrics, onboarding

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)

app = FastAPI(title=settings.service_name)
# ChaosMiddleware precisa ser o PRIMEIRO add_middleware (fica na camada mais
# interna) - ver docstring de shared/chaos/chaos/middleware.py.
app.add_middleware(ChaosMiddleware)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(MetricsMiddleware)
register_exception_handlers(app)
register_chaos_router(app)
register_db_pool_gauge(engine)
app.include_router(health.router)
app.include_router(metrics.router)
app.include_router(onboarding.router)
