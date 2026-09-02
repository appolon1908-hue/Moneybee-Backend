from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """Model metadata without constructing a runtime database engine."""
