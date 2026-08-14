from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker, declarative_base

from .config import DB_PATH

engine = create_engine(
    f"sqlite:///{DB_PATH}",
    connect_args={"check_same_thread": False},
)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def init_db():
    from . import models  # noqa: F401  (asegura que los modelos se registran)
    Base.metadata.create_all(bind=engine)
    # Migración ligera para instalaciones existentes. create_all no añade
    # columnas a tablas SQLite ya creadas.
    with engine.begin() as connection:
        columns = {row[1] for row in connection.execute(text("PRAGMA table_info(comics)"))}
        if "comicinfo_written" not in columns:
            connection.execute(text("ALTER TABLE comics ADD COLUMN comicinfo_written BOOLEAN NOT NULL DEFAULT 0"))
            connection.execute(text("UPDATE comics SET comicinfo_written = 1 WHERE comicinfo_synced_at IS NOT NULL"))
        if "metadata_dirty" not in columns:
            connection.execute(text("ALTER TABLE comics ADD COLUMN metadata_dirty BOOLEAN NOT NULL DEFAULT 0"))
        if "operation_status" not in columns:
            connection.execute(text("ALTER TABLE comics ADD COLUMN operation_status VARCHAR NOT NULL DEFAULT 'idle'"))
        if "operation_error" not in columns:
            connection.execute(text("ALTER TABLE comics ADD COLUMN operation_error TEXT"))
