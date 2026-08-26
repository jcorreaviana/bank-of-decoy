from fastapi import FastAPI

from app.core.config import get_settings
from app.core.db import engine
from app.core.errors import register_exception_handlers
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.core.metrics import MetricsMiddleware, register_db_pool_gauge
from app.routers import health, metrics

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)

app = FastAPI(title=settings.service_name)
app.add_middleware(RequestLoggingMiddleware)
app.add_middleware(MetricsMiddleware)
register_exception_handlers(app)
register_db_pool_gauge(engine)
app.include_router(health.router)
app.include_router(metrics.router)
