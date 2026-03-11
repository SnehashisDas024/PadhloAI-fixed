# routers/documents.py – /api/documents
#
# POST /api/documents/upload  – full ingestion pipeline
# GET  /api/documents/        – list user's documents
# DELETE /api/documents/{id}  – delete a document + its vectors

import uuid
import logging
from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, chroma_collection
from models import Document, User
from routers.auth import get_current_user
from services.file_service import compress_file, extract_text, chunk_text
from services.ai_service import embed_texts

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/documents", tags=["Documents"])

ALLOWED_TYPES = {"application/pdf", "text/plain", "text/markdown"}
MAX_FILE_SIZE = 20 * 1024 * 1024  # 20 MB


# ─── Response schemas ──────────────────────────────────────────────

class DocumentOut(BaseModel):
    id: int
    filename: str
    original_size: int
    compressed_size: int
    chunk_count: int
    doc_type: str

    model_config = {"from_attributes": True}


class UploadResponse(BaseModel):
    message: str
    document: DocumentOut


# ─── Endpoints ────────────────────────────────────────────────────

@router.post("/upload", response_model=UploadResponse, status_code=status.HTTP_201_CREATED)
async def upload_document(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Full ingestion pipeline:
      1. Validate file type & size
      2. Compress via ScaleDown (mock until API key is set)
      3. Extract text
      4. Chunk text (~500 tokens/chunk)
      5. Embed chunks with local HuggingFace model
      6. Store embeddings in ChromaDB
      7. Store metadata in SQLite
    """
    # ── Step 1: Validate ──────────────────────────────────────────
    content_type = file.content_type or ""
    if content_type not in ALLOWED_TYPES and not file.filename.lower().endswith((".pdf", ".txt", ".md")):
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {content_type}")

    raw_bytes = await file.read()
    if len(raw_bytes) > MAX_FILE_SIZE:
        raise HTTPException(status_code=413, detail="File exceeds 20 MB limit.")
    if len(raw_bytes) == 0:
        raise HTTPException(status_code=400, detail="Uploaded file is empty.")

    original_size = len(raw_bytes)
    logger.info("User %d uploading '%s' (%d bytes)", current_user.id, file.filename, original_size)

    # ── Step 2: Compress via ScaleDown ────────────────────────────
    compressed_bytes, compressed_size = await compress_file(raw_bytes, file.filename)

    # ── Step 3: Extract text ──────────────────────────────────────
    text = extract_text(compressed_bytes, file.filename)
    if not text.strip():
        raise HTTPException(
            status_code=422,
            detail="Could not extract text from the file. "
                   "If it's a scanned PDF, text extraction is not yet supported.",
        )

    # ── Step 4: Chunk ─────────────────────────────────────────────
    chunks = chunk_text(text)
    if not chunks:
        raise HTTPException(status_code=422, detail="File appears to contain no readable text.")

    # ── Step 5: Embed (local HuggingFace model) ───────────────────
    logger.info("Embedding %d chunks for '%s'…", len(chunks), file.filename)
    embeddings = embed_texts(chunks)   # returns list[list[float]]

    # ── Step 6: Store in ChromaDB ────────────────────────────────
    # Each chunk gets a unique ID scoped to this document + user.
    doc_uuid = str(uuid.uuid4())       # temporary ID used to name ChromaDB records
    chunk_ids = [f"{doc_uuid}_chunk_{i}" for i in range(len(chunks))]
    metadatas = [
        {
            "user_id": str(current_user.id),
            "doc_uuid": doc_uuid,
            "chunk_index": i,
            "filename": file.filename,
        }
        for i in range(len(chunks))
    ]

    chroma_collection.add(
        ids=chunk_ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas,
    )

    # ── Step 7: Persist metadata to SQLite ───────────────────────
    doc_type = "pdf" if file.filename.lower().endswith(".pdf") else "txt"
    db_doc = Document(
        user_id=current_user.id,
        filename=file.filename,
        original_size=original_size,
        compressed_size=compressed_size,
        chunk_count=len(chunks),
        doc_type=doc_type,
    )
    # Store the ChromaDB UUID so we can filter/delete later
    # We reuse the `filename` column pattern by storing doc_uuid in a
    # dedicated field – alternatively add a `chroma_uuid` column to the model.
    # For simplicity we prefix: "uuid:<doc_uuid>" so we can parse it back.
    db_doc.filename = file.filename   # keep the real filename for display
    db.add(db_doc)
    db.commit()
    db.refresh(db_doc)

    # Patch the ChromaDB metadata with the real SQLite document ID so
    # we can cross-reference later (e.g. delete all chunks for a doc).
    # ChromaDB doesn't support bulk update, so we delete + re-add.
    chroma_collection.delete(ids=chunk_ids)
    metadatas_with_db_id = [
        {**m, "document_id": str(db_doc.id)} for m in metadatas
    ]
    chroma_collection.add(
        ids=chunk_ids,
        embeddings=embeddings,
        documents=chunks,
        metadatas=metadatas_with_db_id,
    )

    logger.info("Document %d ingested successfully (%d chunks).", db_doc.id, len(chunks))
    return UploadResponse(
        message=f"'{file.filename}' uploaded and indexed successfully.",
        document=db_doc,
    )


@router.get("/", response_model=list[DocumentOut])
def list_documents(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return all documents belonging to the authenticated user."""
    return db.query(Document).filter(Document.user_id == current_user.id).all()


@router.delete("/{document_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_document(
    document_id: int,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Delete a document's metadata from SQLite and its embeddings from ChromaDB."""
    doc = db.query(Document).filter(
        Document.id == document_id,
        Document.user_id == current_user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Remove all ChromaDB chunks belonging to this document
    results = chroma_collection.get(
        where={"document_id": str(document_id)}
    )
    if results["ids"]:
        chroma_collection.delete(ids=results["ids"])
        logger.info("Deleted %d ChromaDB chunks for document %d.", len(results["ids"]), document_id)

    db.delete(doc)
    db.commit()
