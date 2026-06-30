"""Map google.genai API failures to operator-facing HTTP errors."""

from __future__ import annotations

from fastapi import HTTPException

try:
    from google.genai.errors import APIError, ServerError
except ImportError:  # pragma: no cover - optional llm extra
    APIError = None  # type: ignore[assignment,misc]
    ServerError = None  # type: ignore[assignment,misc]


def http_exception_for_gemini_api_error(exc: BaseException) -> HTTPException | None:
    """Return HTTPException for Gemini genai SDK errors, or None if not applicable."""
    if ServerError is not None and isinstance(exc, ServerError):
        msg = exc.message or str(exc)
        return HTTPException(
            status_code=503,
            detail=(
                f"Gemini API temporarily unavailable: {msg}. "
                "Retry in a few minutes, switch LLM to Cursor/mock, or set GOOGLE_MODEL to another model."
            ),
        )
    if APIError is not None and isinstance(exc, APIError):
        code = int(exc.code or 502)
        msg = exc.message or str(exc)
        if code == 429:
            return HTTPException(
                status_code=429,
                detail=f"Gemini API rate limited: {msg}",
            )
        if code >= 500:
            return HTTPException(
                status_code=503,
                detail=f"Gemini API error ({code}): {msg}",
            )
        return HTTPException(status_code=502, detail=f"Gemini API error ({code}): {msg}")
    return None
