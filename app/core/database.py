"""Process-wide engine/session factory built from settings (lazy, created on first use).

Never creates schema: run Alembic migrations before starting the application.
"""

from functools import lru_cache

from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import settings
from app.db.session import make_engine, make_session_factory


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    return make_engine(settings.database_url, pool_pre_ping=True)


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    return make_session_factory(get_engine())
