"""One async engine for the RAG, built lazily from the settings (importing this module opens no connection)."""
from __future__ import annotations

from functools import lru_cache

from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from src.paper_rag.helpers.config import get_settings


@lru_cache(maxsize=1)
def engine():
    s = get_settings()
    return create_async_engine(f"postgresql+asyncpg://{s.POSTGRES_USER}:{s.POSTGRES_PASSWORD}@{s.POSTGRES_HOST}:{s.POSTGRES_PORT}/{s.POSTGRES_MAIN_DB}", pool_size=5)


@lru_cache(maxsize=1)
def db_client():
    return sessionmaker(engine(), class_=AsyncSession, expire_on_commit=False)
