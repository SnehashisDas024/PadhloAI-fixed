# services/ai_service.py
#
# Responsibilities:
#   1. Local HuggingFace embeddings  (sentence-transformers/all-MiniLM-L6-v2)
#      → used for both indexing and query embedding to preserve Gemini quota.
#   2. Gemini API calls (chat + quiz generation)
#      → wrapped with Tenacity for robust exponential-backoff retry logic
#        that respects the free-tier 15 RPM limit.

import json
import logging
from functools import lru_cache

import google.generativeai as genai
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
    before_sleep_log,
)
from fastapi import HTTPException

from config import settings

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────
# Gemini initialisation
# ─────────────────────────────────────────────

genai.configure(api_key=settings.GEMINI_API_KEY)
gemini_model = genai.GenerativeModel("gemini-2.5-flash")


# ─────────────────────────────────────────────
# HuggingFace local embeddings
# ─────────────────────────────────────────────

@lru_cache(maxsize=1)
def _get_embedding_model():
    """
    Load the sentence-transformer model once and cache it for the
    lifetime of the process.  The first call (~2 s) downloads the model
    to ~/.cache/huggingface if not already present.
    """
    from sentence_transformers import SentenceTransformer
    logger.info("Loading local embedding model (all-MiniLM-L6-v2)…")
    return SentenceTransformer("sentence-transformers/all-MiniLM-L6-v2")


def embed_texts(texts: list[str]) -> list[list[float]]:
    """
    Embed a list of strings and return a list of float vectors.
    Runs on CPU; typically <100 ms for a handful of chunks.
    """
    model = _get_embedding_model()
    embeddings = model.encode(texts, show_progress_bar=False)
    return embeddings.tolist()


def embed_query(query: str) -> list[float]:
    """Convenience wrapper for single-string embedding (used at query time)."""
    return embed_texts([query])[0]


# ─────────────────────────────────────────────
# Tenacity retry decorator for Gemini calls
# ─────────────────────────────────────────────
#
# Strategy:
#   • Retry up to 5 times on ResourceExhausted (429) or transient errors.
#   • Exponential back-off: waits 4 s, 8 s, 16 s, 32 s between retries.
#   • If all 5 attempts fail, we raise a clean FastAPI 429 HTTPException
#     so the frontend receives a human-readable error instead of a crash.

class GeminiRateLimitError(Exception):
    """Raised when all Tenacity retry attempts are exhausted."""
    pass


def _is_retryable(exc: BaseException) -> bool:
    """Return True for errors that are worth retrying."""
    # google.api_core.exceptions.ResourceExhausted → rate limit
    # google.api_core.exceptions.ServiceUnavailable → transient server error
    retryable_names = {"ResourceExhausted", "ServiceUnavailable", "InternalServerError"}
    return type(exc).__name__ in retryable_names


@retry(
    retry=retry_if_exception_type(Exception),
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=2, min=4, max=32),
    before_sleep=before_sleep_log(logger, logging.WARNING),
    reraise=False,          # we handle the final failure ourselves below
)
def _call_gemini_with_retry(prompt: str) -> str:
    """
    Internal function that calls Gemini and is decorated with Tenacity.
    Do NOT call this directly – use call_gemini() instead.
    """
    response = gemini_model.generate_content(prompt)
    return response.text


def call_gemini(prompt: str) -> str:
    """
    Public interface for all Gemini calls.
    Wraps _call_gemini_with_retry and converts final failures to
    an HTTPException(429) for clean FastAPI error responses.
    """
    try:
        return _call_gemini_with_retry(prompt)
    except Exception as exc:
        logger.error("Gemini call failed after all retries: %s", exc)
        raise HTTPException(
            status_code=429,
            detail=(
                "The AI service is currently rate-limited (Gemini free tier: 15 RPM). "
                "Please wait 60 seconds and try again. "
                f"Original error: {type(exc).__name__}"
            ),
        )


# ─────────────────────────────────────────────
# RAG – build the Gemini prompt with context
# ─────────────────────────────────────────────

def build_rag_prompt(query: str, context_chunks: list[str]) -> str:
    """
    Construct a RAG prompt that instructs Gemini to answer ONLY from
    the provided context, reducing hallucination.
    """
    context_block = "\n\n---\n\n".join(
        f"[Chunk {i + 1}]\n{chunk}" for i, chunk in enumerate(context_chunks)
    )
    return f"""You are PathShalaAI, a helpful study assistant for students.
Answer the student's question using ONLY the context excerpts provided below.
If the answer cannot be found in the context, say:
"I couldn't find that in your uploaded materials. Please check the document or rephrase your question."

=== CONTEXT FROM STUDENT'S DOCUMENTS ===
{context_block}

=== STUDENT'S QUESTION ===
{query}

=== YOUR ANSWER ==="""


# ─────────────────────────────────────────────
# Quiz generation
# ─────────────────────────────────────────────

QUIZ_PROMPT_TEMPLATE = """You are an expert educator creating a multiple-choice quiz.
Based on the following study material, generate exactly 5 multiple-choice questions.

RULES:
- Each question must have exactly 4 options (A, B, C, D).
- Exactly one option is correct.
- Questions should test understanding, not just memorisation.
- Return ONLY a valid JSON array. No markdown, no explanations, no extra text.

JSON FORMAT (follow exactly):
[
  {{
    "question": "Question text here?",
    "options": {{
      "A": "First option",
      "B": "Second option",
      "C": "Third option",
      "D": "Fourth option"
    }},
    "correct_answer": "A",
    "explanation": "Brief explanation of why A is correct."
  }}
]

=== STUDY MATERIAL ===
{text}

=== JSON QUIZ (5 questions, no other text) ==="""


def generate_quiz(document_text: str) -> list[dict]:
    """
    Ask Gemini to generate 5 MCQs from the given document text.
    Returns a Python list of question dicts.
    Raises HTTPException on parse failure or rate-limit exhaustion.
    """
    # Trim to ~3000 tokens to stay within context limits on free tier
    trimmed_text = document_text[:12000]
    prompt = QUIZ_PROMPT_TEMPLATE.format(text=trimmed_text)

    raw_response = call_gemini(prompt)  # already handles retries + 429

    # Strip potential markdown code fences that Gemini sometimes adds
    cleaned = raw_response.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.split("```")[1]
        if cleaned.startswith("json"):
            cleaned = cleaned[4:]
    cleaned = cleaned.strip()

    try:
        questions = json.loads(cleaned)
        if not isinstance(questions, list) or len(questions) == 0:
            raise ValueError("Parsed JSON is not a non-empty list")
        return questions
    except (json.JSONDecodeError, ValueError) as exc:
        logger.error("Failed to parse quiz JSON from Gemini: %s\nRaw: %s", exc, raw_response)
        raise HTTPException(
            status_code=502,
            detail="AI returned an unexpected format for the quiz. Please try again.",
        )
