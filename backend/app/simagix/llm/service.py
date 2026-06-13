from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

from backend.app.core.config import Settings, get_settings
from backend.app.simagix.llm.cursor_provider import CursorLLMProvider
from backend.app.simagix.llm.mock_provider import MockLLMProvider
from backend.app.simagix.llm.prompts import (
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


def get_llm_provider(settings: Settings | None = None, *, force_mock: bool = False) -> LLMProvider:
    settings = settings or get_settings()
    has_key = bool(settings.cursor_api_key)
    use_mock = force_mock or not has_key
    if use_mock:
        return MockLLMProvider()
    return CursorLLMProvider(settings)


def prepare_phase2_run(
    workspace_root: Path,
    run_id: str,
    *,
    max_tool_calls: int | None = None,
    user_answers: dict[str, str] | None = None,
    investigation: InvestigationSummary | None = None,
) -> tuple[Phase2Session, str]:
    settings = get_settings()
    session = phase2_session_store.get_or_create(
        run_id,
        workspace_root,
        max_tool_calls=max_tool_calls or settings.phase2_rca_max_tool_calls,
    )
    if not session.orchestrator.loader.exists():
        raise FileNotFoundError(f"Simagix run bundle not found: {run_id}")
    inv = investigation or session.load_investigation()
    package = session.orchestrator.build_phase2_llm_package()
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
    max_tool_calls: int | None = None,
) -> tuple[Phase2Session, str]:
    settings = get_settings()
    session = phase2_session_store.get_or_create(
        run_id,
        workspace_root,
        max_tool_calls=max_tool_calls or settings.phase2_investigation_max_tool_calls,
    )
    if not session.orchestrator.loader.exists():
        raise FileNotFoundError(f"Simagix run bundle not found: {run_id}")
    session.configure_budget(
        max_tool_calls or settings.phase2_investigation_max_tool_calls,
        reset=True,
    )
    package = session.orchestrator.build_phase2_llm_package()
    user_message = build_investigate_user_message(package)
    return session, user_message


def run_investigation(
    workspace_root: Path,
    run_id: str,
    *,
    provider: LLMProvider | None = None,
    force_mock: bool = False,
) -> InvestigationSummary:
    settings = get_settings()
    session, user_message = prepare_investigation_run(
        workspace_root,
        run_id,
        max_tool_calls=settings.phase2_investigation_max_tool_calls,
    )
    llm = provider or get_llm_provider(force_mock=force_mock)
    investigation = llm.run_investigation(session, user_message)
    session.persist_investigation(investigation)
    return investigation


def generate_clarifying_questions_for_run(
    workspace_root: Path,
    run_id: str,
    *,
    force_mock: bool = False,
    investigation: InvestigationSummary | None = None,
) -> ClarifyingQuestionsBlock:
    settings = get_settings()
    session, _ = prepare_phase2_run(workspace_root, run_id)
    inv = investigation or session.load_investigation()
    if inv is None:
        raise RuntimeError("Investigation must complete before generating clarifying questions")
    package = session.orchestrator.build_phase2_llm_package()
    user_message = build_clarify_user_message(
        package,
        max_questions=settings.phase2_max_clarifying_questions,
        investigation=inv,
    )
    provider = get_llm_provider(force_mock=force_mock)
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


def start_phase2_run(workspace_root: Path, run_id: str, *, force_mock: bool = False) -> dict[str, Any]:
    investigation = run_investigation(workspace_root, run_id, force_mock=force_mock)
    questions = generate_clarifying_questions_for_run(
        workspace_root,
        run_id,
        force_mock=force_mock,
        investigation=investigation,
    )
    session = phase2_session_store.get_or_create(run_id, workspace_root)
    save_iterative_state(
        session,
        {
            "status": "awaiting_clarifications",
            "investigation": investigation.model_dump(),
            "questions": questions.model_dump(),
            "answers": {},
        },
    )
    return {
        "run_id": run_id,
        "status": "awaiting_clarifications",
        "investigation": investigation.model_dump(),
        "clarifying_questions": questions.model_dump(),
    }


def submit_clarifications_and_run(
    workspace_root: Path,
    run_id: str,
    answers: ClarifyingAnswers,
    *,
    force_mock: bool = False,
) -> dict[str, Any]:
    session = phase2_session_store.get_or_create(run_id, workspace_root)
    state = load_iterative_state(session) or {}
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
        force_mock=force_mock,
        user_answers=answers.answers or None,
        investigation=investigation,
    )

    save_iterative_state(
        session,
        {
            "status": "completed",
            "investigation": investigation.model_dump() if investigation else state.get("investigation"),
            "questions": state.get("questions"),
            "answers": answers.answers,
            "report_run_id": run_id,
        },
    )
    return {
        "run_id": run_id,
        "status": "completed",
        "report": result.report.model_dump(),
        "tool_calls_used": result.tool_calls_used,
        "duration_seconds": result.duration_seconds,
    }


def run_phase2(
    workspace_root: Path,
    run_id: str,
    *,
    provider: LLMProvider | None = None,
    force_mock: bool = False,
    user_answers: dict[str, str] | None = None,
    investigation: InvestigationSummary | None = None,
) -> Phase2RunResult:
    settings = get_settings()
    session = phase2_session_store.get_or_create(
        run_id,
        workspace_root,
        max_tool_calls=settings.phase2_rca_max_tool_calls,
    )
    combined_max = (
        settings.phase2_investigation_max_tool_calls + settings.phase2_rca_max_tool_calls
    )
    session.configure_budget(combined_max, reset=False)
    inv = investigation or session.load_investigation()
    session, user_message = prepare_phase2_run(
        workspace_root,
        run_id,
        max_tool_calls=settings.phase2_rca_max_tool_calls,
        user_answers=user_answers,
        investigation=inv,
    )
    llm = provider or get_llm_provider(force_mock=force_mock)
    result = llm.run(session, user_message)
    session.persist_report(result.report, agent_id=result.agent_id, provider=llm.provider_name)
    session.last_run_at = time.time()
    return result
