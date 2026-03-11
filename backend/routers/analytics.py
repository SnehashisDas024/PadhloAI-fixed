# routers/analytics.py – /api/analytics
#
# GET /api/analytics/summary  – aggregated stats for analytics.html dashboard

import logging

from fastapi import APIRouter, Depends
from pydantic import BaseModel
from sqlalchemy import func
from sqlalchemy.orm import Session

from database import get_db
from models import Document, QuizResult, User
from routers.auth import get_current_user

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["Analytics"])


class AnalyticsSummary(BaseModel):
    total_documents: int
    total_quizzes_taken: int
    average_score: float
    best_score: float
    recent_scores: list[float]   # last 10 scores for a trend chart


@router.get("/summary", response_model=AnalyticsSummary)
def get_summary(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    Return aggregated learning analytics for the current user.
    Powers the analytics.html dashboard charts.
    """
    total_docs = db.query(func.count(Document.id)).filter(
        Document.user_id == current_user.id
    ).scalar() or 0

    quiz_stats = db.query(
        func.count(QuizResult.id),
        func.avg(QuizResult.score),
        func.max(QuizResult.score),
    ).filter(QuizResult.user_id == current_user.id).first()

    total_quizzes = quiz_stats[0] or 0
    avg_score     = round(float(quiz_stats[1] or 0), 1)
    best_score    = round(float(quiz_stats[2] or 0), 1)

    recent = (
        db.query(QuizResult.score)
        .filter(QuizResult.user_id == current_user.id)
        .order_by(QuizResult.taken_at.desc())
        .limit(10)
        .all()
    )
    recent_scores = [round(r.score, 1) for r in recent]

    return AnalyticsSummary(
        total_documents=total_docs,
        total_quizzes_taken=total_quizzes,
        average_score=avg_score,
        best_score=best_score,
        recent_scores=recent_scores,
    )
