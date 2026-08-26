from fastapi import APIRouter

from app.portal.admin import router as admin_router
from app.portal.borrower import router as borrower_router
from app.portal.foundation import router as foundation_router
from app.portal.lender import router as lender_router


router = APIRouter()
router.include_router(foundation_router)
router.include_router(admin_router)
router.include_router(borrower_router)
router.include_router(lender_router)
