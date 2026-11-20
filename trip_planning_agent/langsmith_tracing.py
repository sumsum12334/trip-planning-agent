"""Optional LangSmith tracing for model requests.

Traces every LLM call made through :class:`trip_planning_agent.tacc_client.TACCClient`
so requests, tool calls, results, and errors are visible in LangSmith.
"""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any, Iterator, Optional

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_client_cache: dict[tuple[str, str, str], Any] = {}
_client_lock = Lock()


def _enabled(settings: Settings) -> bool:
    return bool(settings.langsmith_api_key)


def _client(settings: Settings) -> Optional[Any]:
    if not _enabled(settings):
        return None
    key = (
        settings.langsmith_api_key,
        settings.langsmith_endpoint,
        settings.langsmith_project,
    )
    with _client_lock:
        if key in _client_cache:
            return _client_cache[key]
        try:
            from langsmith import Client
        except ImportError:
            logger.warning(
                "LangSmith tracking is enabled but the langsmith package is not installed."
            )
            return None
        try:
            client = Client(
                api_key=settings.langsmith_api_key,
                api_url=settings.langsmith_endpoint,
            )
        except Exception:
            logger.exception("Could not initialize LangSmith tracking.")
            return None
        _client_cache[key] = client
        return client


@dataclass
class TraceHandle:
    """Identify one LangSmith trace so child runs can attach to it."""

    trace_id: str
    run_id: str
    client: Any
    ended: bool = False


def start_trace(
    *,
    name: str,
    input: Any | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> Optional[TraceHandle]:
    """Start one root trace for a user turn and keep it open for child runs."""
    client = _client(settings or get_settings())
    if client is None:
        return None
    try:
        run = client.create_run(
            name=name,
            run_type="chain",
            inputs=input or {},
            project_name=settings.langsmith_project if settings else "trip-planning-agent",
            tags=["trip-planning-agent", "chat-turn"],
            metadata=metadata or {},
        )
        return TraceHandle(
            trace_id=str(run.id),
            run_id=str(run.id),
            client=client,
        )
    except Exception:
        logger.exception("Could not start LangSmith trace %s.", name)
        return None


def end_trace(
    trace: Optional[TraceHandle],
    *,
    output: Any | None = None,
    error: Exception | None = None,
) -> None:
    """Finish a root trace and flush it without affecting the request result."""
    if trace is None or trace.ended:
        return
    trace.ended = True
    try:
        trace.client.update_run(
            run_id=trace.run_id,
            outputs=output or {},
            error=str(error) if error else None,
        )
    except Exception:
        logger.exception("Could not finish LangSmith trace %s.", trace.run_id)


@contextmanager
def model_generation(
    *,
    name: str,
    model: str,
    prompt: str,
    system: Optional[str],
    input: Any | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    trace_context: Optional[dict[str, str]] = None,
    settings: Settings | None = None,
) -> Iterator[Optional[Any]]:
    """Track one model request without allowing telemetry to break the request.

    Yields a run object that callers can pass to :func:`finish_generation` /
    :func:`update_generation`, or ``None`` if LangSmith is not configured.
    """
    client = _client(settings or get_settings())
    if client is None:
        yield None
        return

    project_name = (
        settings.langsmith_project
        if settings
        else get_settings().langsmith_project
    )

    run: Optional[Any] = None
    try:
        parent_run_id = None
        if trace_context and trace_context.get("run_id"):
            parent_run_id = trace_context["run_id"]

        run = client.create_run(
            name=name,
            run_type="llm",
            inputs={
                "prompt": prompt,
                "system": system or "",
                **(input or {}),
            },
            project_name=project_name,
            parent_run_id=parent_run_id,
            tags=["trip-planning-agent", "llm-call", model],
            metadata={"model": model, **(metadata or {})},
        )
    except Exception:
        logger.exception("LangSmith tracking failed for model request %s.", name)
        run = None

    try:
        yield run
    finally:
        try:
            if run is not None and not getattr(run, "_trip_planner_langsmith_ended", False):
                finish_generation(run)
        finally:
            try:
                client.flush()
            except Exception:
                logger.exception("Could not flush LangSmith model tracking.")


def finish_generation(
    run: Optional[Any],
    *,
    output: Any | None = None,
    error: Exception | None = None,
) -> None:
    """Update an LLM run while keeping telemetry failures isolated."""
    if run is None:
        return
    try:
        update_generation(run, output=output, error=error)
        try:
            run.end()
        except Exception:
            pass
        try:
            setattr(run, "_trip_planner_langsmith_ended", True)
        except Exception:
            pass
    except Exception:
        logger.exception("Could not finish LangSmith model tracking.")


def update_generation(
    run: Optional[Any],
    *,
    output: Any | None = None,
    error: Exception | None = None,
) -> None:
    """Persist the current model output without ending the run."""
    if run is None:
        return
    try:
        run.client.update_run(
            run_id=str(run.id),
            outputs=output or {},
            error=str(error) if error else None,
        )
    except Exception:
        logger.exception("Could not update LangSmith model tracking.")
