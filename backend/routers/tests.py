# routers/tests.py – /api/tests
#
# POST /api/tests/generate      – generate 5 MCQs from a document
# POST /api/tests/submit        – submit answers, calculate score, persist result
# GET  /api/tests/results       – list past quiz attempts (for analytics.html)

import json
import logging

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db, chroma_collection
from models import Document, QuizResult, User
from routers.auth import get_current_user
from services.ai_service import generate_quiz

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tests", tags=["Tests / Quizzes"])


# ─── Pydantic schemas ──────────────────────────────────────────────

class GenerateRequest(BaseModel):
    document_id: int


class QuizOption(BaseModel):
    A: str
    B: str
    C: str
    D: str


class QuizQuestion(BaseModel):
    question: str
    options: QuizOption
    correct_answer: str
    explanation: str


class GenerateResponse(BaseModel):
    document_id: int
    questions: list[QuizQuestion]


class SubmitAnswers(BaseModel):
    document_id: int
    answers: dict[int, str]   # {question_index: "A" | "B" | "C" | "D"}
    questions: list[dict]     # the original questions list (from generate response)


class SubmitResponse(BaseModel):
    score: float              # percentage 0–100
    correct: int
    total: int
    result_id: int


class QuizResultOut(BaseModel):
    id: int
    document_id: int
    score: float
    total_questions: int
    taken_at: str

    model_config = {"from_attributes": True}


# ─── Endpoints ────────────────────────────────────────────────────

@router.post("/generate", response_model=GenerateResponse)
def generate_quiz_endpoint(
    body: GenerateRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Generate 5 multiple-choice questions from a specific document.

    Retrieves all ChromaDB chunks for the document, joins them into a
    single text blob, then asks Gemini to produce structured MCQs.
    """
    # Verify the document belongs to this user
    doc = db.query(Document).filter(
        Document.id == body.document_id,
        Document.user_id == current_user.id,
    ).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found.")

    # Retrieve all chunks for this document from ChromaDB
    results = chroma_collection.get(
        where={"document_id": str(body.document_id)},
        include=["documents", "metadatas"],
    )

    all_chunks = results.get("documents", [])
    if not all_chunks:
        raise HTTPException(
            status_code=422,
            detail="No text content found for this document. Try re-uploading it.",
        )

    # Sort chunks by chunk_index so the text is in reading order
    paired = sorted(
        zip(results["metadatas"], all_chunks),
        key=lambda x: int(x[0].get("chunk_index", 0)),
    )
    full_text = "\n\n".join(chunk for _, chunk in paired)

    # generate_quiz() calls Gemini with Tenacity retries
    # Raises HTTPException(429) if rate-limited, HTTPException(502) if parse fails
    questions = generate_quiz(full_text)

    return GenerateResponse(document_id=body.document_id, questions=questions)


@router.post("/submit", response_model=SubmitResponse)
def submit_quiz(
    body: SubmitAnswers,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Accept the student's answers, calculate the score, and persist the result.
    The frontend sends back the original questions list so we can grade without
    another Gemini call (saving quota).
    """
    correct_count = 0
    total = len(body.questions)

    for idx, question in enumerate(body.questions):
        student_answer = body.answers.get(idx)
        if student_answer and student_answer.upper() == question.get("correct_answer", "").upper():
            correct_count += 1

    score = round((correct_count / total) * 100, 1) if total > 0 else 0.0

    result = QuizResult(
        user_id=current_user.id,
        document_id=body.document_id,
        score=score,
        total_questions=total,
        questions_json=json.dumps(body.questions),
    )
    db.add(result)
    db.commit()
    db.refresh(result)

    return SubmitResponse(
        score=score,
        correct=correct_count,
        total=total,
        result_id=result.id,
    )


@router.get("/results", response_model=list[QuizResultOut])
def list_results(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return all past quiz attempts for the current user.
    Used by analytics.html to display score history and trends.
    """
    results = (
        db.query(QuizResult)
        .filter(QuizResult.user_id == current_user.id)
        .order_by(QuizResult.taken_at.desc())
        .all()
    )
    return [
        QuizResultOut(
            id=r.id,
            document_id=r.document_id,
            score=r.score,
            total_questions=r.total_questions,
            taken_at=r.taken_at.isoformat(),
        )
        for r in results
    ]
