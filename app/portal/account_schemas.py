import uuid
from typing import Literal

from pydantic import BaseModel, EmailStr


class AccountBootstrapRead(BaseModel):
    created: bool
    user_id: uuid.UUID
    organization_id: uuid.UUID
    username: str
    email: EmailStr
    email_verified: bool
    membership_type: Literal["BORROWER", "LENDER", "MONEYBEE", "AFFILIATE"]
    registration_source: Literal["KEYCLOAK_PASSWORD", "GOOGLE", "BROKERED"]
    welcome_event_status: Literal["PENDING", "EXISTING", "NOT_APPLICABLE"]
    request_id: str
