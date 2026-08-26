from importlib import import_module
from importlib.util import find_spec

from fastapi import APIRouter

router = APIRouter()

_PORTAL_MODULES = (
    "app.shared_portal_routes",
    "app.borrower_portal_routes",
    "app.lender_portal_routes",
    "app.admin_portal_routes",
    "app.webhook_gateway_routes",
)

for module_name in _PORTAL_MODULES:
    if find_spec(module_name) is None:
        continue
    module = import_module(module_name)
    router.include_router(module.router)
