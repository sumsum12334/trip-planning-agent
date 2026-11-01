"""Optional Langfuse tracking for model requests."""

from __future__ import annotations

import logging
from contextlib import contextmanager
from dataclasses import dataclass
from threading import Lock
from typing import Any, Iterator

from config.settings import Settings, get_settings

logger = logging.getLogger(__name__)

_client_cache: dict[tuple[str, str, str], Any] = {}
_client_lock = Lock()


def _enabled(settings: Settings) -> bool:
    return bool(
        settings.langfuse_enabled
        and settings.langfuse_public_key
        and settings.langfuse_secret_key
    )


def _client(settings: Settings) -> Any | None:
    if not _enabled(settings):
        return None
    key = (
        settings.langfuse_public_key,
        settings.langfuse_secret_key,
        settings.langfuse_host,
    )
    with _client_lock:
        if key in _client_cache:
            return _client_cache[key]
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
        _client_cache[key] = client
        return client


@dataclass
class TraceHandle:
    """Identify one Langfuse trace so worker threads can attach child observations."""

    trace_id: str
    span_id: str
    observation: Any
    client: Any
    ended: bool = False


def trace_context_for(trace: TraceHandle | None) -> dict[str, str] | None:
    """Return the trace context understood by Langfuse observations."""
    if trace is None:
        return None
    return {"trace_id": trace.trace_id, "parent_span_id": trace.span_id}


def start_trace(
    *,
    name: str,
    input: Any | None = None,
    session_id: str | None = None,
    metadata: dict[str, Any] | None = None,
    settings: Settings | None = None,
) -> TraceHandle | None:
    """Start one root span for a user turn and keep it open for child calls."""
    client = _client(settings or get_settings())
    if client is None:
        return None
    try:
        from langfuse import propagate_attributes

        with propagate_attributes(
            session_id=session_id,
            metadata=metadata or {},
            trace_name=name,
        ):
            observation = client.start_observation(
                name=name,
                as_type="span",
                input=input,
                metadata=metadata or {},
            )
        return TraceHandle(
            trace_id=observation.trace_id,
            span_id=observation.id,
            observation=observation,
            client=client,
        )
    except Exception:
        logger.exception("Could not start Langfuse trace %s.", name)
        return None


def end_trace(
    trace: TraceHandle | None,
    *,
    output: Any | None = None,
    error: Exception | None = None,
) -> None:
    """Finish a root span and flush it without affecting the request result."""
    if trace is None or trace.ended:
        return
    trace.ended = True
    try:
        trace.observation.update(
            output=output,
            level="ERROR" if error else "DEFAULT",
            status_message=str(error) if error else None,
        )
        trace.observation.end()
    except Exception:
        logger.exception("Could not finish Langfuse trace %s.", trace.trace_id)
    try:
        trace.client.flush()
    except Exception:
        logger.exception("Could not flush Langfuse trace %s.", trace.trace_id)


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
    trace_context: dict[str, str] | None = None,
    settings: Settings | None = None,
) -> Iterator[Any | None]:
    """Track one model request without allowing telemetry to break the request."""
    client = _client(settings or get_settings())
    if client is None:
        yield None
        return

    observation: Any | None = None
    attributes = None
    try:
        from langfuse import propagate_attributes

        attributes = propagate_attributes(
            session_id=session_id,
            metadata=metadata or {},
        )
        attributes.__enter__()
        observation = client.start_observation(
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
    except Exception:
        logger.exception("Langfuse tracking failed for model request %s.", name)
        observation = None
    try:
        yield observation
    finally:
        try:
            client.flush()
        except Exception:
            logger.exception("Could not flush Langfuse model tracking.")
        finally:
            if attributes is not None:
                attributes.__exit__(None, None, None)


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
    except Exception:
        logger.exception("Could not finish Langfuse model tracking.")


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
