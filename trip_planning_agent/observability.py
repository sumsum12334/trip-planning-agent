"""Optional Langfuse and LangSmith tracking for model requests."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from types import SimpleNamespace
from typing import Any, Iterator, Optional

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_langfuse_client_cache: dict[tuple[str, str, str], Any] = {}
_langsmith_client_cache: dict[tuple[str, str, str], Any] = {}
_client_lock = Lock()


def _langfuse_enabled(settings: Settings) -> bool:
    return bool(
        settings.langfuse_enabled
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    )


def _langsmith_enabled(settings: Settings) -> bool:
    return bool(settings.langsmith_api_key)


def _langfuse_client(settings: Settings) -> Optional[Any]:
    if not _langfuse_enabled(settings):
        return None
    key = (
        settings.langfuse_public_key,
        settings.langfuse_secret_key,
        settings.langfuse_host,
    )
    with _client_lock:
        if key in _langfuse_client_cache:
            return _langfuse_client_cache[key]
        try:
            from langfuse import Langfuse
        except ImportError:
            logger.warning(
                "Langfuse tracking is enabled but the langfuse package is not installed."
            )
            return None
        try:
            client = Langfuse(
                public_key=settings.langfuse_public_key,
                secret_key=settings.langfuse_secret_key,
                host=settings.langfuse_host,
            )
        except Exception:
            logger.exception("Could not initialize Langfuse tracking.")
            return None
        _langfuse_client_cache[key] = client
        return client


def _langsmith_client(settings: Settings) -> Optional[Any]:
    if not _langsmith_enabled(settings):
        return None
    key = (
        settings.langsmith_api_key,
        settings.langsmith_endpoint,
        settings.langsmith_project,
    )
    with _client_lock:
        if key in _langsmith_client_cache:
            return _langsmith_client_cache[key]
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
        _langsmith_client_cache[key] = client
        return client


@dataclass
class TraceHandle:
    """Identify one root trace so child observations/runs can attach to it."""

    trace_id: str
    span_id: str
    observation: Any
    client: Any
    langsmith_run_id: Optional[str] = None
    langsmith_client: Optional[Any] = None
    ended: bool = False


def trace_context_for(trace: TraceHandle | None) -> dict[str, str] | None:
    """Return the trace context understood by observations/runs."""
    if trace is None:
        return None
    ctx: dict[str, str] = {"trace_id": trace.trace_id, "parent_span_id": trace.span_id}
    if trace.langsmith_run_id:
        ctx["run_id"] = trace.langsmith_run_id
    return ctx


def start_trace(
    *,
    name: str,
    input: Any | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> TraceHandle | None:
    """Start one root trace for a user turn and keep it open for child calls."""
    s = settings or get_settings()
    lf_client = _langfuse_client(s)
    ls_client = _langsmith_client(s)
    if lf_client is None and ls_client is None:
        return None

    observation: Any = None
    ls_run: Any = None
    try:
        if lf_client is not None:
            from langfuse import propagate_attributes

            with propagate_attributes(
                session_id=session_id,
                metadata=metadata or {},
                trace_name=name,
            ):
                observation = lf_client.start_observation(
                    name=name,
                    as_type="span",
                    input=input,
                    metadata=metadata or {},
                )

        if ls_client is not None:
            ls_inputs: dict[str, Any] = input if isinstance(input, dict) else {}
            ls_run = ls_client.create_run(
                name=name,
                run_type="chain",
                inputs=ls_inputs,
                project_name=s.langsmith_project,
                tags=["trip-planning-agent", "chat-turn"],
                metadata=metadata or {},
            )
    except Exception:
        logger.exception("Could not start trace %s.", name)

    return TraceHandle(
        trace_id=getattr(observation, "trace_id", "") or str(getattr(ls_run, "id", "")),
        span_id=getattr(observation, "id", ""),
        observation=observation,
        client=lf_client,
        langsmith_run_id=str(getattr(ls_run, "id", "")) if ls_run else None,
        langsmith_client=ls_client,
    )


def end_trace(
    trace: TraceHandle | None,
    *,
    output: Any | None = None,
    error: Exception | None = None,
) -> None:
    """Finish a root trace and flush it without affecting the request result."""
    if trace is None or trace.ended:
        return
    trace.ended = True
    try:
        if trace.observation is not None:
            trace.observation.update(
                output=output,
                level="ERROR" if error else "DEFAULT",
                status_message=str(error) if error else None,
            )
            trace.observation.end()
    except Exception:
        logger.exception("Could not finish Langfuse trace %s.", trace.trace_id)
    try:
        if trace.client is not None:
            trace.client.flush()
    except Exception:
        logger.exception("Could not flush Langfuse trace %s.", trace.trace_id)

    # LangSmith trace
    try:
        if trace.langsmith_client is not None and trace.langsmith_run_id:
            trace.langsmith_client.update_run(
                run_id=trace.langsmith_run_id,
                outputs=output or {},
                error=str(error) if error else None,
                end_time=_now_iso(),
            )
    except Exception:
        logger.exception("Could not finish LangSmith trace %s.", trace.langsmith_run_id)
    try:
        if trace.langsmith_client is not None:
            trace.langsmith_client.flush()
    except Exception:
        logger.exception("Could not flush LangSmith trace %s.", trace.langsmith_run_id)


_ENDED_MARKER = "_trip_planner_ended"


@contextmanager
def model_generation(
    *,
    name: str,
    model: str,
    prompt: str,
    system: str | None,
    input: Any | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    trace_context: Optional[dict[str, str]] = None,
    settings: Settings | None = None,
) -> Iterator[Any | None]:
    """Track one model request without allowing telemetry to break the request.

    Yields an observation object that callers can pass to
    :func:`finish_generation` / :func:`update_generation`, or ``None`` if
    neither Langfuse nor LangSmith is configured.
    """
    s = settings or get_settings()
    lf_client = _langfuse_client(s)
    ls_client = _langsmith_client(s)
    if lf_client is None and ls_client is None:
        yield None
        return

    observation: Any | None = None
    ls_run: Any | None = None
    attributes = None
    try:
        if lf_client is not None:
            from langfuse import propagate_attributes

            attributes = propagate_attributes(
                session_id=session_id,
                metadata=metadata or {},
            )
            attributes.__enter__()
            observation = lf_client.start_observation(
                trace_context=trace_context,
                name=name,
                as_type="generation",
                input=(
                    input
                    if input is not None
                    else {"prompt": prompt, "system": system or ""}
                ),
                model=model,
                metadata=metadata or {},
            )

        if ls_client is not None:
            parent_run_id = None
            if trace_context and trace_context.get("run_id"):
                parent_run_id = trace_context["run_id"]
            # Separate the current user input from full conversation history
            # so LangSmith does not mix user input with previous model outputs.
            ls_inputs: dict[str, Any] = {"system": system or ""}
            if isinstance(input, list):
                user_messages = [
                    m.get("content", "")
                    for m in input
                    if isinstance(m, dict) and m.get("role") == "user"
                ]
                if user_messages:
                    ls_inputs["prompt"] = user_messages[-1]
                ls_inputs["messages"] = input
            elif isinstance(input, dict):
                ls_inputs.update(input)
            elif prompt:
                ls_inputs["prompt"] = prompt
            ls_run = ls_client.create_run(
                name=name,
                run_type="llm",
                inputs=ls_inputs,
                project_name=s.langsmith_project,
                parent_run_id=parent_run_id,
                tags=["trip-planning-agent", "llm-call", model],
                metadata={"model": model, **(metadata or {})},
            )

        # Expose the LangSmith run on the observation so callers that only
        # call finish_generation() also complete the LangSmith trace.
        if observation is not None and ls_run is not None:
            observation._langsmith_run = ls_run  # type: ignore[attr-defined]

    except Exception:
        logger.exception("Tracking failed for model request %s.", name)
        observation = None
        ls_run = None

    # When Langfuse is disabled but LangSmith is enabled, observation is None.
    # Wrap the run in a minimal object so finish_generation() can find it.
    if observation is None and ls_run is not None:
        observation = SimpleNamespace(_langsmith_run=ls_run)

    try:
        yield observation
    finally:
        try:
            # Callers that exit early (retry paths, cancellation) may never call
            # finish_generation; close the generation so telemetry sees it end.
            if observation is not None and not getattr(observation, _ENDED_MARKER, False):
                finish_generation(observation)
            elif ls_run is not None and not getattr(ls_run, "_trip_planner_langsmith_ended", False):
                ls_finish_generation(ls_run)
        finally:
            try:
                if lf_client is not None:
                    lf_client.flush()
            except Exception:
                logger.exception("Could not flush Langfuse model tracking.")
            finally:
                if attributes is not None:
                    attributes.__exit__(None, None, None)
            try:
                if ls_client is not None:
                    ls_client.flush()
            except Exception:
                logger.exception("Could not flush LangSmith model tracking.")


def ls_finish_generation(
    run: Any,
    *,
    output: Any | None = None,
    error: Exception | None = None,
) -> None:
    """Finish a LangSmith LLM run with end_time so it is not stuck loading."""
    if run is None:
        return
    try:
        ls_client = getattr(run, "client", None)
        run_id = str(getattr(run, "id", ""))
        if ls_client is not None and run_id:
            ls_client.update_run(
                run_id=run_id,
                outputs=output or {},
                error=str(error) if error else None,
                end_time=_now_iso(),
            )
        try:
            setattr(run, "_trip_planner_langsmith_ended", True)
        except Exception:
            pass
    except Exception:
        logger.exception("Could not finish LangSmith model tracking.")


def _now_iso() -> str:
    """Return current UTC time in ISO 8601 format for LangSmith end_time."""
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def ls_update_generation(
    run: Any,
    *,
    output: Any | None = None,
    error: Exception | None = None,
) -> None:
    """Update a LangSmith LLM run output."""
    if run is None:
        return
    try:
        ls_client = getattr(run, "client", None)
        run_id = str(getattr(run, "id", ""))
        if ls_client is not None and run_id:
            ls_client.update_run(
                run_id=run_id,
                outputs=output or {},
                error=str(error) if error else None,
            )
    except Exception:
        logger.exception("Could not update LangSmith model tracking.")


def finish_generation(
    observation: Any | None,
    *,
    output: Any | None = None,
    error: Exception | None = None,
) -> None:
    """Update an observation while keeping telemetry failures isolated."""
    if observation is None:
        return
    try:
        update_generation(observation, output=output, error=error)
        observation.end()
        try:
            setattr(observation, _ENDED_MARKER, True)
        except Exception:
            pass
    except Exception:
        logger.exception("Could not finish Langfuse model tracking.")
    # Also finish the LangSmith run attached to this observation.
    ls_run = getattr(observation, "_langsmith_run", None)
    if ls_run is not None:
        ls_finish_generation(ls_run, output=output, error=error)


def update_generation(
    observation: Any | None,
    *,
    output: Any | None = None,
    error: Exception | None = None,
) -> None:
    """Persist the current model output without ending the observation."""
    if observation is None:
        return
    try:
        observation.update(
            output=output,
            level="ERROR" if error else "DEFAULT",
            status_message=str(error) if error else None,
        )
    except Exception:
        logger.exception("Could not update Langfuse model tracking.")
    # Also update the LangSmith run attached to this observation.
    ls_run = getattr(observation, "_langsmith_run", None)
    if ls_run is not None:
        ls_update_generation(ls_run, output=output, error=error)
