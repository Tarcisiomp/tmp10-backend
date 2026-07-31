"""
Conexão e sessão do banco de dados (PostgreSQL via SQLAlchemy).
"""

from collections.abc import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config.settings import settings

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)

SessionLocal = sessionmaker(bind=engine, autocommit=False, autoflush=False, future=True)


class Base(DeclarativeBase):
    """Classe base declarativa para todos os models."""

    pass


def get_db() -> Generator[Session, None, None]:
    """Dependency do FastAPI para injetar uma sessão de banco por request."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
