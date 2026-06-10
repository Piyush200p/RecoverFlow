"""
RecoverFlow AI — Database Engine & Session Manager
=====================================================
Provides both async (FastAPI) and sync (Celery) SQLAlchemy
engines, session factories, and dependencies.
"""

from contextlib import contextmanager
from typing import AsyncGenerator, Generator

from sqlalchemy import create_engine
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from config import get_settings

settings = get_settings()

# ═════════════════════════════════════════════════════════════
#  ASYNC ENGINE (FastAPI)
# ═════════════════════════════════════════════════════════════
engine = create_async_engine(
    settings.DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=20,
    max_overflow=10,
    pool_pre_ping=True,
    pool_recycle=3600,
)

async_session_factory = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
)


# ═════════════════════════════════════════════════════════════
#  SYNC ENGINE (Celery Workers)
# ═════════════════════════════════════════════════════════════
sync_engine = create_engine(
    settings.SYNC_DATABASE_URL,
    echo=settings.DEBUG,
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,
    pool_recycle=3600,
)

sync_session_factory = sessionmaker(
    bind=sync_engine,
    class_=Session,
    expire_on_commit=False,
)


# ── Declarative Base ─────────────────────────────────────────
class Base(DeclarativeBase):
    """All ORM models inherit from this base."""
    pass


# ═════════════════════════════════════════════════════════════
#  DEPENDENCIES
# ═════════════════════════════════════════════════════════════

# ── FastAPI Dependency (async) ───────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    Yields a scoped async session per request.
    Automatically commits on success or rolls back on exception.
    """
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# ── Celery Dependency (sync) ────────────────────────────────
@contextmanager
def get_sync_db() -> Generator[Session, None, None]:
    """
    Context manager for synchronous sessions in Celery workers.
    Usage:
        with get_sync_db() as db:
            store = db.query(Store).get(domain)
    """
    session = sync_session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
