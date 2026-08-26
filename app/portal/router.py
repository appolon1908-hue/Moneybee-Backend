from fastapi import APIRouter

from app.portal.borrower import router as borrower_router
from app.portal.foundation import router as foundation_router


router = APIRouter()
router.include_router(foundation_router)
router.include_router(borrower_router)
