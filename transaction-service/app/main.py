from fastapi import FastAPI

from app.core.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import RequestLoggingMiddleware, configure_logging
from app.routers import health

settings = get_settings()
configure_logging(settings.service_name, settings.log_level)

app = FastAPI(title=settings.service_name)
app.add_middleware(RequestLoggingMiddleware)
register_exception_handlers(app)
app.include_router(health.router)
