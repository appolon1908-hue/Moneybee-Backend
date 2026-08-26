from __future__ import annotations

import importlib
import importlib.util

from fastapi import APIRouter

from app.portal_core import router as core_router

router = APIRouter()
router.include_router(core_router)

_OPTIONAL_PORTAL_MODULES = (
    "app.borrower_portal",
    "app.lender_portal",
    "app.admin_portal",
    "app.webhook_gateway",
)

for module_name in _OPTIONAL_PORTAL_MODULES:
    if importlib.util.find_spec(module_name) is None:
        continue
    module = importlib.import_module(module_name)
    feature_router = getattr(module, "router", None)
    if feature_router is None:
        raise RuntimeError(f"{module_name} does not expose a FastAPI router")
    router.include_router(feature_router)
