"""Tests for Vertex AI auth support in GeminiAdkLLMProvider and service layer."""
from __future__ import annotations

import os
import pytest
from unittest.mock import patch


# ── provider init ─────────────────────────────────────────────────────────────

def test_provider_init_rejects_no_auth():
    """No API key AND no Vertex config → RuntimeError."""
    from backend.app.core.config import Settings
    from backend.app.simagix.llm.providers.adk.provider import GeminiAdkLLMProvider

    s = Settings(
        google_api_key=None,
        google_genai_use_vertexai=False,
        google_cloud_project=None,
        google_cloud_location=None,
    )
    with pytest.raises(RuntimeError, match="GOOGLE_API_KEY|Vertex"):
        GeminiAdkLLMProvider(s)


def test_provider_init_accepts_api_key():
    """API key alone is sufficient."""
    from backend.app.core.config import Settings
    from backend.app.simagix.llm.providers.adk.provider import GeminiAdkLLMProvider

    s = Settings(google_api_key="AIza-fake", google_genai_use_vertexai=False)
    provider = GeminiAdkLLMProvider(s)
    assert provider.provider_name == "gemini-adk"


def test_provider_init_accepts_vertex_config():
    """Vertex project+location without API key is accepted."""
    from backend.app.core.config import Settings
    from backend.app.simagix.llm.providers.adk.provider import GeminiAdkLLMProvider

    s = Settings(
        google_api_key=None,
        google_genai_use_vertexai=True,
        google_cloud_project="my-project",
        google_cloud_location="us-central1",
    )
    provider = GeminiAdkLLMProvider(s)
    assert provider.provider_name == "gemini-adk"


def test_provider_init_rejects_vertex_missing_project():
    """Vertex=True but no project → still raises."""
    from backend.app.core.config import Settings
    from backend.app.simagix.llm.providers.adk.provider import GeminiAdkLLMProvider

    s = Settings(
        google_api_key=None,
        google_genai_use_vertexai=True,
        google_cloud_project=None,
        google_cloud_location="us-central1",
    )
    with pytest.raises(RuntimeError):
        GeminiAdkLLMProvider(s)


def test_provider_init_rejects_vertex_missing_location():
    """Vertex=True but no location → still raises."""
    from backend.app.core.config import Settings
    from backend.app.simagix.llm.providers.adk.provider import GeminiAdkLLMProvider

    s = Settings(
        google_api_key=None,
        google_genai_use_vertexai=True,
        google_cloud_project="my-project",
        google_cloud_location=None,
    )
    with pytest.raises(RuntimeError):
        GeminiAdkLLMProvider(s)


# ── service layer ─────────────────────────────────────────────────────────────

def test_service_get_llm_provider_vertex():
    """get_llm_provider returns GeminiAdkLLMProvider when Vertex config is set."""
    from backend.app.core.config import Settings
    from backend.app.simagix.llm.service import get_llm_provider
    from backend.app.simagix.llm.providers.adk.provider import GeminiAdkLLMProvider

    s = Settings(
        google_api_key=None,
        google_genai_use_vertexai=True,
        google_cloud_project="my-project",
        google_cloud_location="us-central1",
        cursor_api_key=None,
    )
    provider = get_llm_provider(settings=s, llm="gemini")
    assert isinstance(provider, GeminiAdkLLMProvider)


def test_service_llm_provider_options_vertex_available():
    """Gemini shows as available in options when Vertex config is set."""
    from backend.app.core.config import Settings
    from backend.app.simagix.llm.service import llm_provider_options

    s = Settings(
        google_api_key=None,
        google_genai_use_vertexai=True,
        google_cloud_project="my-project",
        google_cloud_location="us-central1",
    )
    options = llm_provider_options(s)
    gemini = next(o for o in options if o["id"] == "gemini")
    assert gemini["available"] is True


def test_service_llm_provider_options_vertex_unavailable_without_config():
    """Gemini shows unavailable when neither API key nor Vertex config set."""
    from backend.app.core.config import Settings
    from backend.app.simagix.llm.service import llm_provider_options

    s = Settings(
        google_api_key=None,
        google_genai_use_vertexai=False,
        google_cloud_project=None,
        google_cloud_location=None,
    )
    options = llm_provider_options(s)
    gemini = next(o for o in options if o["id"] == "gemini")
    assert gemini["available"] is False


# ── env application ───────────────────────────────────────────────────────────

def test_apply_google_env_sets_vertex_vars():
    """_apply_google_env writes all three Vertex vars to os.environ."""
    from backend.app.core.config import Settings
    from backend.app.simagix.llm.providers.adk.runner import _apply_google_env

    s = Settings(
        google_api_key=None,
        google_genai_use_vertexai=True,
        google_cloud_project="test-project",
        google_cloud_location="europe-west1",
        google_application_credentials="/var/secrets/gcp-sa.json",
    )
    saved = {
        k: os.environ.get(k)
        for k in ("GOOGLE_GENAI_USE_VERTEXAI", "GOOGLE_CLOUD_PROJECT",
                  "GOOGLE_CLOUD_LOCATION", "GOOGLE_APPLICATION_CREDENTIALS")
    }
    try:
        _apply_google_env(s)
        assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "TRUE"
        assert os.environ["GOOGLE_CLOUD_PROJECT"] == "test-project"
        assert os.environ["GOOGLE_CLOUD_LOCATION"] == "europe-west1"
        assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == "/var/secrets/gcp-sa.json"
    finally:
        for k, v in saved.items():
            if v is None:
                os.environ.pop(k, None)
            else:
                os.environ[k] = v


def test_apply_google_env_false_does_not_set_vertex_vars():
    """When vertexai=False, project/location vars are not written."""
    from backend.app.core.config import Settings
    from backend.app.simagix.llm.providers.adk.runner import _apply_google_env

    s = Settings(
        google_api_key="AIza-fake",
        google_genai_use_vertexai=False,
        google_cloud_project="should-not-appear",
        google_cloud_location="should-not-appear",
    )
    os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
    os.environ.pop("GOOGLE_CLOUD_LOCATION", None)
    try:
        _apply_google_env(s)
        assert os.environ["GOOGLE_GENAI_USE_VERTEXAI"] == "FALSE"
        assert "GOOGLE_CLOUD_PROJECT" not in os.environ
        assert "GOOGLE_CLOUD_LOCATION" not in os.environ
    finally:
        os.environ.pop("GOOGLE_CLOUD_PROJECT", None)
        os.environ.pop("GOOGLE_CLOUD_LOCATION", None)
