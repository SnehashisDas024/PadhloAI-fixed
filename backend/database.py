# database.py – SQLAlchemy + ChromaDB initialisation
#
# Two storage layers:
#   1. SQLite (via SQLAlchemy) – relational data: users, documents, quiz results
#   2. ChromaDB (local)        – vector store for document chunk embeddings

import os
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker, DeclarativeBase
import chromadb
from chromadb.config import Settings as ChromaSettings

from config import settings

# ─────────────────────────────────────────────
# 1.  SQLite / SQLAlchemy
# ─────────────────────────────────────────────

# Ensure the data directory exists before SQLite tries to create the file
os.makedirs("data", exist_ok=True)

engine = create_engine(
    settings.DATABASE_URL,
    # check_same_thread=False is required for SQLite when used with FastAPI
    # because multiple threads may share the same connection during async ops.
    connect_args={"check_same_thread": False},
)

SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


class Base(DeclarativeBase):
    """Shared declarative base – all ORM models inherit from this."""
    pass


def get_db():
    """
    FastAPI dependency that yields a SQLAlchemy session and guarantees
    the session is closed after the request completes.

    Usage in a router:
        db: Session = Depends(get_db)
    """
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


# ─────────────────────────────────────────────
# 2.  ChromaDB (local vector store)
# ─────────────────────────────────────────────

os.makedirs(settings.CHROMA_DB_PATH, exist_ok=True)

# PersistentClient stores data on disk so embeddings survive server restarts.
chroma_client = chromadb.PersistentClient(
    path=settings.CHROMA_DB_PATH,
    settings=ChromaSettings(anonymized_telemetry=False),
)

# One collection holds ALL document chunks for ALL users.
# We filter by document_id / user_id metadata at query time.
chroma_collection = chroma_client.get_or_create_collection(
    name="pathshala_documents",
    metadata={"hnsw:space": "cosine"},   # cosine similarity is better for text
)