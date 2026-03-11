# models.py – SQLAlchemy ORM models
#
# Tables:
#   users      – registered students
#   documents  – uploaded PDF / note metadata
#   quiz_results – stored quiz attempts (for analytics.html)

import datetime
from sqlalchemy import (
    Column, Integer, String, DateTime, ForeignKey, Float, Text, Boolean
)
from sqlalchemy.orm import relationship

from database import Base


class User(Base):
    __tablename__ = "users"

    id            = Column(Integer, primary_key=True, index=True)
    username      = Column(String(50), unique=True, index=True, nullable=False)
    email         = Column(String(120), unique=True, index=True, nullable=False)
    hashed_password = Column(String(200), nullable=False)
    created_at    = Column(DateTime, default=datetime.datetime.utcnow)
    is_active     = Column(Boolean, default=True)

    # Relationships
    documents    = relationship("Document", back_populates="owner", cascade="all, delete-orphan")
    quiz_results = relationship("QuizResult", back_populates="user", cascade="all, delete-orphan")


class Document(Base):
    __tablename__ = "documents"

    id              = Column(Integer, primary_key=True, index=True)
    user_id         = Column(Integer, ForeignKey("users.id"), nullable=False)
    filename        = Column(String(255), nullable=False)
    original_size   = Column(Integer)          # bytes
    compressed_size = Column(Integer)          # bytes – after ScaleDown
    chunk_count     = Column(Integer, default=0)
    doc_type        = Column(String(10))        # "pdf" | "txt" | "md"
    uploaded_at     = Column(DateTime, default=datetime.datetime.utcnow)

    # Relationships
    owner        = relationship("User", back_populates="documents")
    quiz_results = relationship("QuizResult", back_populates="document", cascade="all, delete-orphan")


class QuizResult(Base):
    __tablename__ = "quiz_results"

    id          = Column(Integer, primary_key=True, index=True)
    user_id     = Column(Integer, ForeignKey("users.id"), nullable=False)
    document_id = Column(Integer, ForeignKey("documents.id"), nullable=False)
    score       = Column(Float)            # percentage 0-100
    total_questions = Column(Integer, default=5)
    taken_at    = Column(DateTime, default=datetime.datetime.utcnow)
    # Store the full Q&A JSON as text for replay on analytics.html
    questions_json = Column(Text)

    # Relationships
    user     = relationship("User", back_populates="quiz_results")
    document = relationship("Document", back_populates="quiz_results")