from fastapi import APIRouter
from app.api.v2.system import router as system_router

router = APIRouter()
router.include_router(system_router, prefix="/system", tags=["system"])
