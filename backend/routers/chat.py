# routers/chat.py – /api/chat
#
# POST /api/chat/message
#
# Full RAG flow:
#   1. Embed the user's query with the LOCAL HuggingFace model (no Gemini quota used)
#   2. Query ChromaDB for the top-3 most similar chunks from the user's documents
#   3. Build a grounded prompt and call Gemini-2.5-flash (with Tenacity retries)
#   4. Return the AI's answer + the source chunks for transparency

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, chroma_collection
from models import User
from routers.auth import get_current_user
from services.ai_service import embed_query, build_rag_prompt, call_gemini

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/chat", tags=["Chat"])


# ─── Pydantic schemas ──────────────────────────────────────────────

class MessageRequest(BaseModel):
    message: str
    document_id: Optional[int] = None   # if set, search only this document's chunks


class SourceChunk(BaseModel):
    chunk_text: str
    document_filename: str
    chunk_index: int


class MessageResponse(BaseModel):
    answer: str
    sources: list[SourceChunk]


# ─── Endpoint ──────────────────────────────────────────────────────

@router.post("/message", response_model=MessageResponse)
async def send_message(
    body: MessageRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    RAG chat endpoint.

    The client sends a plain text message.  We:
      1. Embed it locally (free, no API call)
      2. Retrieve the 3 most relevant chunks from this user's documents
      3. Pass the context to Gemini and return the grounded answer

    Optional: pass `document_id` to restrict retrieval to a single document.
    This is useful on chat.html when a user is studying a specific file.
    """
    if not body.message.strip():
        raise HTTPException(status_code=400, detail="Message cannot be empty.")

    # ── Step 1: Embed the query locally ───────────────────────────
    query_embedding = embed_query(body.message)

    # ── Step 2: Retrieve top-3 chunks from ChromaDB ───────────────
    # Filter by user_id so users only see their own documents.
    where_filter: dict = {"user_id": str(current_user.id)}
    if body.document_id:
        where_filter = {
            "$and": [
                {"user_id": {"$eq": str(current_user.id)}},
                {"document_id": {"$eq": str(body.document_id)}},
            ]
        }

    try:
        results = chroma_collection.query(
            query_embeddings=[query_embedding],
            n_results=3,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )
    except Exception as exc:
        logger.error("ChromaDB query failed: %s", exc)
        raise HTTPException(status_code=500, detail="Vector search failed.")

    retrieved_docs   = results.get("documents", [[]])[0]   # list of chunk texts
    retrieved_metas  = results.get("metadatas",  [[]])[0]

    if not retrieved_docs:
        return MessageResponse(
            answer=(
                "I don't have any uploaded documents to reference yet. "
                "Please upload your notes or PDFs first, then ask me your question!"
            ),
            sources=[],
        )

    # ── Step 3: Build RAG prompt and call Gemini ──────────────────
    # call_gemini() handles Tenacity retries + raises HTTPException(429) on exhaustion
    prompt = build_rag_prompt(body.message, retrieved_docs)
    answer = call_gemini(prompt)   # may raise HTTPException(429)

    # ── Step 4: Build source citations for the frontend ───────────
    sources = []
    for chunk_text, meta in zip(retrieved_docs, retrieved_metas):
        sources.append(SourceChunk(
            chunk_text=chunk_text[:300] + "…" if len(chunk_text) > 300 else chunk_text,
            document_filename=meta.get("filename", "Unknown"),
            chunk_index=int(meta.get("chunk_index", 0)),
        ))

    return MessageResponse(answer=answer, sources=sources)
