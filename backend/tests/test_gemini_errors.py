"""Tests for Gemini API error → HTTP mapping."""

from __future__ import annotations

import pytest

from backend.app.simagix.llm.providers.adk.gemini_errors import http_exception_for_gemini_api_error


def test_http_exception_for_gemini_server_error() -> None:
    try:
        from google.genai.errors import ServerError
    except ImportError:
        pytest.skip("google-genai not installed")

    exc = ServerError(503, {"error": {"message": "high demand"}}, None)
    mapped = http_exception_for_gemini_api_error(exc)
    assert mapped is not None
    assert mapped.status_code == 503
    assert "Gemini API temporarily unavailable" in mapped.detail


def test_http_exception_for_non_gemini_returns_none() -> None:
    assert http_exception_for_gemini_api_error(ValueError("nope")) is None
