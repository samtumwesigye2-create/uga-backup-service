import os
from urllib.parse import urlparse

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker


def _normalize(url: str) -> str:
    url = (url or "").strip()
    if url.startswith("postgres://"):
        url = url.replace("postgres://", "postgresql://", 1)
    return url


def _pick_database_url() -> str:
    # Highest priority: an explicitly configured same-project private URL.
    # This allows Railway private networking without replacing the legacy
    # public backup URL, which can be retained for later recovery/forensics.
    private_override = _normalize(os.environ.get("BACKUP_DATABASE_PRIVATE_URL", ""))
    if private_override:
        return private_override

    candidates = [
        os.environ.get("BACKUP_DATABASE_PUBLIC_URL", ""),
        os.environ.get("DATABASE_PUBLIC_URL", ""),
        os.environ.get("BACKUP_DATABASE_URL", ""),
        os.environ.get("DATABASE_URL", ""),
    ]

    for raw in candidates:
        url = _normalize(raw)
        if not url:
            continue
        try:
            host = (urlparse(url).hostname or "").lower()
        except Exception:
            host = ""
        if host.endswith(".railway.internal"):
            continue
        return url

    fallback = _normalize(os.environ.get("BACKUP_DATABASE_URL", ""))
    if fallback:
        return fallback

    fallback = _normalize(os.environ.get("DATABASE_URL", ""))
    if fallback:
        return fallback

    raise RuntimeError(
        "No database URL configured. Set BACKUP_DATABASE_PRIVATE_URL, "
        "BACKUP_DATABASE_PUBLIC_URL, DATABASE_PUBLIC_URL, "
        "BACKUP_DATABASE_URL, or DATABASE_URL."
    )


DATABASE_URL = _pick_database_url()

engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=300,
    connect_args={"connect_timeout": 10},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    pass


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
