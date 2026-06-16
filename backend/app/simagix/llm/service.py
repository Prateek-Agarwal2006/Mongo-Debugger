from __future__ import annotations

import json
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings, get_settings
from backend.app.simagix.llm.cursor_provider import CursorLLMProvider
from backend.app.simagix.llm.gemini_adk_provider import GeminiAdkLLMProvider
from backend.app.simagix.llm.llm_paths import llm_folder_name, list_llm_sessions, update_llm_index
from backend.app.simagix.llm.mock_provider import MockLLMProvider
from backend.app.simagix.llm.chatbot_attachments import (
    format_user_content_with_attachments,
    save_chatbot_attachment,
    validate_attachment_refs,
)
from backend.app.simagix.llm.prompts import (
    build_chatbot_prompt,
    build_clarify_user_message,
    build_investigate_user_message,
    build_phase2_user_message,
)
from backend.app.simagix.llm.provider import LLMProvider, Phase2RunResult
from backend.app.simagix.llm.session import Phase2Session, phase2_session_store
from backend.app.simagix.output_schema import (
    ClarifyingAnswers,
    ClarifyingQuestionsBlock,
    InvestigationSummary,
)

LLM_PROVIDER_IDS = frozenset({"default", "cursor", "gemini", "mock"})


def normalize_llm_provider_choice(llm_provider: str | None, settings: Settings | None = None) -> str:
    settings = settings or get_settings()
    if not llm_provider or llm_provider.strip().lower() in {"", "default"}:
        return (settings.llm_provider or "cursor").strip().lower()
    return llm_provider.strip().lower()


def llm_provider_options(settings: Settings | None = None) -> list[dict[str, object]]:
    settings = settings or get_settings()
    default = normalize_llm_provider_choice(None, settings)
    return [
        {"id": "mock", "label": "Mock (no API key)", "available": True},
        {"id": "cursor", "label": "Cursor SDK", "available": bool(settings.cursor_api_key)},
        {"id": "gemini", "label": "Gemini ADK", "available": bool(settings.google_api_key)},
        {"id": "default", "label": f"Default ({default})", "available": True},
    ]


def resolve_run_llm_provider(
    *,
    llm_provider: str | None = None,
    force_mock: bool = False,
    state: dict[str, Any] | None = None,
) -> str | None:
    if force_mock:
        return "mock"
    if llm_provider:
        return llm_provider
    if state and state.get("llm_provider"):
        return str(state["llm_provider"])
    if state and state.get("llm"):
        return str(state["llm"])
    return None


def resolve_llm_folder(
    *,
    llm: str | None = None,
    llm_provider: str | None = None,
    force_mock: bool = False,
    state: dict[str, Any] | None = None,
) -> str:
    if llm:
        return llm_folder_name(llm)
    provider = resolve_run_llm_provider(
        llm_provider=llm_provider,
        force_mock=force_mock,
        state=state,
    )
    if not provider:
        raise RuntimeError("llm is required (mock, cursor, or gemini)")
    return llm_folder_name(normalize_llm_provider_choice(provider))


def get_llm_provider(
    settings: Settings | None = None,
    *,
    force_mock: bool = False,
    llm_provider: str | None = None,
    llm: str | None = None,
) -> LLMProvider:
    settings = settings or get_settings()
    if force_mock or llm == "mock":
        return MockLLMProvider()

    provider_input = llm_provider or llm
    explicit = provider_input is not None and str(provider_input).strip().lower() not in {"", "default"}
    provider = normalize_llm_provider_choice(provider_input, settings)
    if provider not in LLM_PROVIDER_IDS - {"default"}:
        if explicit:
            raise RuntimeError(f"Unknown LLM provider: {provider_input}")
        provider = normalize_llm_provider_choice(None, settings)

    if provider == "mock":
        return MockLLMProvider()
    if provider == "gemini":
        return GeminiAdkLLMProvider(settings)
    if provider == "cursor":
        if settings.cursor_api_key:
            return CursorLLMProvider(settings)
        if explicit:
            raise RuntimeError(
                "CURSOR_API_KEY is not configured. Choose another provider or set the key in .env."
            )
        return MockLLMProvider()

    if settings.google_api_key:
        return GeminiAdkLLMProvider(settings)
    if settings.cursor_api_key:
        return CursorLLMProvider(settings)
    return MockLLMProvider()


def prepare_phase2_run(
    workspace_root: Path,
    run_id: str,
    *,
    llm: str,
    max_tool_calls: int | None = None,
    user_answers: dict[str, str] | None = None,
    investigation: InvestigationSummary | None = None,
) -> tuple[Phase2Session, str]:
    settings = get_settings()
    session = phase2_session_store.get_or_create(
        run_id,
        workspace_root,
        llm=llm,
        max_tool_calls=max_tool_calls or settings.phase2_rca_max_tool_calls,
    )
    if not session.evidence.loader.exists():
        raise FileNotFoundError(f"Simagix run bundle not found: {run_id}")
    inv = investigation or session.load_investigation()
    package = session.evidence.build_phase2_llm_package()
    user_message = build_phase2_user_message(
        package,
        user_answers=user_answers,
        investigation=inv,
    )
    return session, user_message


def prepare_investigation_run(
    workspace_root: Path,
    run_id: str,
    *,
    llm: str,
    max_tool_calls: int | None = None,
) -> tuple[Phase2Session, str]:
    settings = get_settings()
    session = phase2_session_store.get_or_create(
        run_id,
        workspace_root,
        llm=llm,
        max_tool_calls=max_tool_calls or settings.phase2_investigation_max_tool_calls,
    )
    if not session.evidence.loader.exists():
        raise FileNotFoundError(f"Simagix run bundle not found: {run_id}")
    session.configure_budget(
        max_tool_calls or settings.phase2_investigation_max_tool_calls,
        reset=True,
    )
    package = session.evidence.build_phase2_llm_package()
    user_message = build_investigate_user_message(package)
    return session, user_message


def run_investigation(
    workspace_root: Path,
    run_id: str,
    *,
    llm: str,
    provider: LLMProvider | None = None,
    force_mock: bool = False,
    llm_provider: str | None = None,
) -> InvestigationSummary:
    settings = get_settings()
    session, user_message = prepare_investigation_run(
        workspace_root,
        run_id,
        llm=llm,
        max_tool_calls=settings.phase2_investigation_max_tool_calls,
    )
    llm_backend = provider or get_llm_provider(
        force_mock=force_mock,
        llm_provider=llm_provider,
        llm=llm,
    )
    investigation = llm_backend.run_investigation(session, user_message)
    session.persist_investigation(investigation)
    return investigation


def generate_clarifying_questions_for_run(
    workspace_root: Path,
    run_id: str,
    *,
    llm: str,
    force_mock: bool = False,
    llm_provider: str | None = None,
    investigation: InvestigationSummary | None = None,
) -> ClarifyingQuestionsBlock:
    settings = get_settings()
    session, _ = prepare_phase2_run(workspace_root, run_id, llm=llm)
    inv = investigation or session.load_investigation()
    if inv is None:
        raise RuntimeError("Investigation must complete before generating clarifying questions")
    package = session.evidence.build_phase2_llm_package()
    user_message = build_clarify_user_message(
        package,
        max_questions=settings.phase2_max_clarifying_questions,
        investigation=inv,
    )
    provider = get_llm_provider(force_mock=force_mock, llm_provider=llm_provider, llm=llm)
    return provider.generate_clarifying_questions(
        session,
        user_message,
        max_questions=settings.phase2_max_clarifying_questions,
    )


def save_iterative_state(session: Phase2Session, state: dict[str, Any]) -> None:
    path = session.session_dir / "iterative_state.json"
    path.write_text(json.dumps(state, indent=2), encoding="utf-8")


def load_iterative_state(session: Phase2Session) -> dict[str, Any] | None:
    path = session.session_dir / "iterative_state.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def start_phase2_run(
    workspace_root: Path,
    run_id: str,
    *,
    force_mock: bool = False,
    llm_provider: str | None = None,
    llm: str | None = None,
) -> dict[str, Any]:
    folder = resolve_llm_folder(llm=llm, llm_provider=llm_provider, force_mock=force_mock)
    provider_choice = resolve_run_llm_provider(
        llm_provider=llm_provider,
        force_mock=force_mock,
    ) or folder

    investigation = run_investigation(
        workspace_root,
        run_id,
        llm=folder,
        force_mock=force_mock,
        llm_provider=llm_provider or folder,
    )
    questions = generate_clarifying_questions_for_run(
        workspace_root,
        run_id,
        llm=folder,
        force_mock=force_mock,
        llm_provider=llm_provider or folder,
        investigation=investigation,
    )
    session = phase2_session_store.get_or_create(run_id, workspace_root, llm=folder)
    save_iterative_state(
        session,
        {
            "status": "awaiting_clarifications",
            "llm": folder,
            "llm_provider": normalize_llm_provider_choice(provider_choice),
            "investigation": investigation.model_dump(),
            "questions": questions.model_dump(),
            "answers": {},
        },
    )
    update_llm_index(workspace_root, run_id, folder, status="awaiting_clarifications")
    return {
        "run_id": run_id,
        "llm": folder,
        "status": "awaiting_clarifications",
        "llm_provider": normalize_llm_provider_choice(provider_choice),
        "investigation": investigation.model_dump(),
        "clarifying_questions": questions.model_dump(),
    }


def submit_clarifications_and_run(
    workspace_root: Path,
    run_id: str,
    answers: ClarifyingAnswers,
    *,
    force_mock: bool = False,
    llm_provider: str | None = None,
    llm: str | None = None,
) -> dict[str, Any]:
    folder = resolve_llm_folder(
        llm=llm,
        llm_provider=llm_provider,
        force_mock=force_mock,
    )
    session = phase2_session_store.get_or_create(run_id, workspace_root, llm=folder)
    state = load_iterative_state(session) or {}
    resolved_provider = resolve_run_llm_provider(
        llm_provider=llm_provider,
        force_mock=force_mock,
        state=state,
    ) or folder
    investigation_payload = state.get("investigation")
    investigation = (
        InvestigationSummary.model_validate(investigation_payload)
        if investigation_payload
        else session.load_investigation()
    )
    state["answers"] = answers.answers
    state["status"] = "running_rca"
    save_iterative_state(session, state)

    result = run_phase2(
        workspace_root,
        run_id,
        llm=folder,
        force_mock=force_mock,
        llm_provider=resolved_provider,
        user_answers=answers.answers or None,
        investigation=investigation,
    )

    save_iterative_state(
        session,
        {
            "status": "completed",
            "llm": folder,
            "llm_provider": normalize_llm_provider_choice(resolved_provider),
            "investigation": investigation.model_dump() if investigation else state.get("investigation"),
            "questions": state.get("questions"),
            "answers": answers.answers,
            "report_run_id": run_id,
        },
    )
    update_llm_index(workspace_root, run_id, folder, status="completed")
    return {
        "run_id": run_id,
        "llm": folder,
        "status": "completed",
        "llm_provider": normalize_llm_provider_choice(resolved_provider),
        "report": result.report.model_dump(),
        "tool_calls_used": result.tool_calls_used,
        "duration_seconds": result.duration_seconds,
    }


def run_phase2(
    workspace_root: Path,
    run_id: str,
    *,
    llm: str,
    provider: LLMProvider | None = None,
    force_mock: bool = False,
    llm_provider: str | None = None,
    user_answers: dict[str, str] | None = None,
    investigation: InvestigationSummary | None = None,
) -> Phase2RunResult:
    settings = get_settings()
    session = phase2_session_store.get_or_create(
        run_id,
        workspace_root,
        llm=llm,
        max_tool_calls=settings.phase2_rca_max_tool_calls,
    )
    session.configure_budget(settings.phase2_rca_max_tool_calls, reset=True)
    inv = investigation or session.load_investigation()
    session, user_message = prepare_phase2_run(
        workspace_root,
        run_id,
        llm=llm,
        max_tool_calls=settings.phase2_rca_max_tool_calls,
        user_answers=user_answers,
        investigation=inv,
    )
    llm_backend = provider or get_llm_provider(
        force_mock=force_mock,
        llm_provider=llm_provider,
        llm=llm,
    )
    result = llm_backend.run(session, user_message)
    session.persist_report(result.report, agent_id=result.agent_id, provider=llm_backend.provider_name)
    session.last_run_at = time.time()
    return result


def list_run_llm_sessions(workspace_root: Path, run_id: str) -> list[dict[str, Any]]:
    return list_llm_sessions(workspace_root, run_id)


def _empty_chatbot_state() -> dict[str, Any]:
    return {
        "updated_at": None,
        "summary_of_older": None,
        "messages": [],
    }


def load_chatbot(session: Phase2Session) -> dict[str, Any]:
    path = session.chatbot_chat_path
    if not path.exists():
        return _empty_chatbot_state()
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data.get("messages"), list):
        data["messages"] = []
    return data


def save_chatbot(session: Phase2Session, data: dict[str, Any]) -> None:
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    session.chatbot_chat_path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _chat_message(
    role: str,
    content: str,
    *,
    attachments: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    return {
        "id": str(uuid.uuid4()),
        "role": role,
        "content": content,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "attachments": attachments or [],
    }


def maybe_summarize_chatbot(session: Phase2Session, provider: LLMProvider) -> None:
    settings = get_settings()
    data = load_chatbot(session)
    messages = data.get("messages") or []
    threshold = settings.phase2_chatbot_summarize_after_messages
    replay_n = settings.phase2_chatbot_max_replay_messages
    if len(messages) <= threshold:
        return
    fold_count = max(0, len(messages) - replay_n)
    if fold_count <= 0:
        return
    to_fold = messages[:fold_count]
    fold_payload = [{"role": m.get("role", ""), "content": m.get("content", "")} for m in to_fold]
    prior = data.get("summary_of_older")
    summary = provider.summarize_chat_history(session, fold_payload, prior_summary=prior)
    data["summary_of_older"] = summary
    save_chatbot(session, data)


def get_chatbot_history(
    workspace_root: Path,
    run_id: str,
    *,
    llm: str,
) -> dict[str, Any]:
    session = phase2_session_store.get_or_load(run_id, workspace_root, llm)
    if session is None or session.load_persisted_report() is None:
        raise FileNotFoundError(f"No report for chatbot: {run_id} llm={llm}")
    data = load_chatbot(session)
    return {
        "run_id": run_id,
        "llm": llm,
        "updated_at": data.get("updated_at"),
        "summary_of_older": data.get("summary_of_older"),
        "messages": data.get("messages", []),
    }


def post_chatbot_message(
    workspace_root: Path,
    run_id: str,
    *,
    llm: str,
    content: str,
    attachments: list[dict[str, Any]] | None = None,
    force_mock: bool = False,
    llm_provider: str | None = None,
) -> dict[str, Any]:
    settings = get_settings()
    session = phase2_session_store.get_or_create(
        run_id,
        workspace_root,
        llm=llm,
        max_tool_calls=settings.phase2_chatbot_max_tool_calls,
    )
    report = session.load_persisted_report()
    if report is None:
        raise FileNotFoundError(f"No report for chatbot: {run_id} llm={llm}")

    trimmed = content.strip()
    attachment_refs = validate_attachment_refs(session, list(attachments or []))
    if not trimmed and not attachment_refs:
        raise ValueError("content or attachments required")
    if not trimmed:
        trimmed = "Please analyze the attached file(s)."

    prompt_user_text = format_user_content_with_attachments(trimmed, attachment_refs)

    data = load_chatbot(session)
    messages = list(data.get("messages") or [])
    messages.append(_chat_message("user", trimmed, attachments=attachment_refs))
    data["messages"] = messages
    save_chatbot(session, data)

    investigation = session.load_investigation()
    replay_n = settings.phase2_chatbot_max_replay_messages
    recent = messages[-replay_n:] if replay_n > 0 else []
    recent_payload = [
        {
            "role": m.get("role", ""),
            "content": format_user_content_with_attachments(
                str(m.get("content", "")),
                list(m.get("attachments") or []),
            )
            if m.get("role") == "user"
            else str(m.get("content", "")),
        }
        for m in recent[:-1]
    ]
    prompt = build_chatbot_prompt(
        report=report.model_dump(),
        investigation=investigation.model_dump() if investigation else None,
        summary_of_older=data.get("summary_of_older"),
        recent_messages=recent_payload,
        user_message=prompt_user_text,
        scratch_dir=str(session.ensure_chatbot_scratch_dir()),
    )

    provider = get_llm_provider(force_mock=force_mock, llm_provider=llm_provider, llm=llm)
    result = provider.run_chatbot(session, prompt)
    messages.append(_chat_message("assistant", result.content))
    data["messages"] = messages
    save_chatbot(session, data)
    maybe_summarize_chatbot(session, provider)

    return {
        "run_id": run_id,
        "llm": llm,
        "message": messages[-1],
        "tool_calls_used": result.tool_calls_used,
    }


def upload_chatbot_attachment(
    workspace_root: Path,
    run_id: str,
    *,
    llm: str,
    filename: str,
    data: bytes,
) -> dict[str, Any]:
    session = phase2_session_store.get_or_create(
        run_id,
        workspace_root,
        llm=llm,
        max_tool_calls=get_settings().phase2_chatbot_max_tool_calls,
    )
    if session.load_persisted_report() is None:
        raise FileNotFoundError(f"No report for chatbot: {run_id} llm={llm}")
    saved = save_chatbot_attachment(session, filename, data)
    return {"run_id": run_id, "llm": llm, **saved}
