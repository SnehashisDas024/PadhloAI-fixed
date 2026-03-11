# services/file_service.py
#
# Responsibilities:
#   1. ScaleDown API integration (currently MOCKED – see instructions below)
#   2. Text extraction from PDF and plain-text files
#   3. Text chunking (~500 tokens per chunk, with overlap)

import io
import logging
from typing import Optional

import httpx

from config import settings

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════
#  ScaleDown API – Compression Service
# ═══════════════════════════════════════════════════════════════════
#
#  HOW TO HOOK UP THE REAL SCALEDOWN API
#  ──────────────────────────────────────
#  1. Set SCALEDOWN_API_KEY and SCALEDOWN_API_URL in your .env file.
#  2. The function `compress_file` below checks for a non-empty key.
#     If found, it calls the real API; otherwise it falls through to
#     the mock.
#  3. Adjust the multipart field names (`file`, `apikey`) to match
#     the actual ScaleDown API documentation once you have access.
#  4. If ScaleDown returns a download URL instead of raw bytes, replace
#     the `return response.content` line with an httpx GET to that URL.
#
# ═══════════════════════════════════════════════════════════════════

async def compress_file(file_bytes: bytes, filename: str) -> tuple[bytes, int]:
    """
    Send a file to the ScaleDown API for compression.

    Returns:
        (compressed_bytes, compressed_size_in_bytes)

    If SCALEDOWN_API_KEY is not set, the mock is used (returns unchanged bytes).
    """
    if settings.SCALEDOWN_API_KEY:
        return await _compress_via_scaledown(file_bytes, filename)
    else:
        logger.info("ScaleDown API key not set – using mock (no-op) compression.")
        return await _mock_compress(file_bytes, filename)


async def _compress_via_scaledown(file_bytes: bytes, filename: str) -> tuple[bytes, int]:
    """
    Real ScaleDown API call.
    ─────────────────────────────────────────────────────────────────
    Adjust the field names / headers below to match the ScaleDown
    documentation once you have your API credentials.
    ─────────────────────────────────────────────────────────────────
    """
    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            response = await client.post(
                settings.SCALEDOWN_API_URL,
                # ↓ Adjust field names to match ScaleDown's API spec
                files={"file": (filename, file_bytes, "application/octet-stream")},
                headers={"Authorization": f"Bearer {settings.SCALEDOWN_API_KEY}"},
            )
            response.raise_for_status()

            compressed_bytes = response.content   # or follow a URL if needed
            logger.info(
                "ScaleDown compressed '%s': %d → %d bytes (%.1f%% reduction)",
                filename,
                len(file_bytes),
                len(compressed_bytes),
                (1 - len(compressed_bytes) / max(len(file_bytes), 1)) * 100,
            )
            return compressed_bytes, len(compressed_bytes)

    except httpx.HTTPStatusError as exc:
        logger.warning(
            "ScaleDown returned HTTP %d – falling back to uncompressed file. Error: %s",
            exc.response.status_code, exc,
        )
        return file_bytes, len(file_bytes)
    except httpx.RequestError as exc:
        logger.warning("ScaleDown unreachable – falling back to uncompressed file. Error: %s", exc)
        return file_bytes, len(file_bytes)


async def _mock_compress(file_bytes: bytes, filename: str) -> tuple[bytes, int]:
    """
    Mock implementation: returns the original bytes unchanged.
    Simulates a successful compression call for development purposes.
    """
    logger.debug("Mock compression: returning %d bytes unchanged for '%s'", len(file_bytes), filename)
    return file_bytes, len(file_bytes)


# ═══════════════════════════════════════════════════════════════════
#  Text Extraction
# ═══════════════════════════════════════════════════════════════════

def extract_text(file_bytes: bytes, filename: str) -> str:
    """
    Extract plain text from a PDF or text-based file.

    Supports:
      .pdf  → PyPDF2 page-by-page extraction
      .txt / .md / other text → UTF-8 decode with fallback to latin-1
    """
    lower = filename.lower()

    if lower.endswith(".pdf"):
        return _extract_from_pdf(file_bytes)
    else:
        # Plain text / markdown / other UTF-8 files
        try:
            return file_bytes.decode("utf-8")
        except UnicodeDecodeError:
            return file_bytes.decode("latin-1", errors="replace")


def _extract_from_pdf(file_bytes: bytes) -> str:
    """Extract text from a PDF using PyPDF2."""
    try:
        import PyPDF2

        reader = PyPDF2.PdfReader(io.BytesIO(file_bytes))
        pages_text = []
        for page_num, page in enumerate(reader.pages):
            text = page.extract_text()
            if text:
                pages_text.append(f"[Page {page_num + 1}]\n{text.strip()}")

        full_text = "\n\n".join(pages_text)
        if not full_text.strip():
            logger.warning("PyPDF2 extracted no text – document may be image-based or encrypted.")
        return full_text

    except Exception as exc:
        logger.error("PDF extraction failed: %s", exc)
        return ""


# ═══════════════════════════════════════════════════════════════════
#  Text Chunking
# ═══════════════════════════════════════════════════════════════════

def chunk_text(
    text: str,
    chunk_size: int = 500,
    overlap: int = 50,
) -> list[str]:
    """
    Split text into overlapping chunks of approximately `chunk_size` tokens.

    We approximate 1 token ≈ 4 characters (rough but fast, avoids loading
    a tokeniser just for chunking).

    Args:
        text:       The full document text.
        chunk_size: Target size in tokens (~500 recommended for MiniLM-L6).
        overlap:    Number of tokens shared between consecutive chunks
                    to avoid losing context at boundaries.

    Returns:
        List of text strings (chunks).
    """
    if not text.strip():
        return []

    char_size    = chunk_size * 4   # 500 tokens × 4 chars/token = 2000 chars
    char_overlap = overlap * 4      # 50 tokens × 4 chars/token  = 200 chars

    chunks = []
    start = 0
    text_len = len(text)

    while start < text_len:
        end = start + char_size

        # Try to break at a sentence or paragraph boundary within a small window
        if end < text_len:
            # Look for the last newline or period in the last 200 chars of the chunk
            break_search = text[end - 200 : end]
            best_break = max(
                break_search.rfind("\n"),
                break_search.rfind(". "),
            )
            if best_break > 0:
                end = end - 200 + best_break + 1   # +1 to include the delimiter

        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)

        start = end - char_overlap   # slide back by overlap amount

    logger.debug("Chunked document into %d chunks (size=%d tokens, overlap=%d tokens)", len(chunks), chunk_size, overlap)
    return chunks
