from fastapi import APIRouter

from app.portal.foundation import router as foundation_router


router = APIRouter()
router.include_router(foundation_router)
