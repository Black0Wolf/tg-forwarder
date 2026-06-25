"""Routes package init — registers every router."""
from .admins import router as admins_router
from .channels import router as channels_router
from .connections import router as connections_router
from .dashboard import router as dashboard_router
from .history import router as history_router
from .logs import router as logs_router
from .settings import router as settings_router

__all__ = [
    "admins_router", "channels_router", "connections_router",
    "dashboard_router", "history_router", "logs_router",
    "settings_router",
]
