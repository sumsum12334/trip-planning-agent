# Project Guidelines

## Direction

- Keep the existing FastAPI, multi-agent modules, and TACC-compatible model client as the product architecture.
- Use React with Vite for the browser UI; keep API calls aligned with the FastAPI endpoints.
- Use LangGraph as the orchestration foundation; introduce new graph nodes incrementally without replacing stable agent behavior.
- Treat model activity as observable workflow events (requests, tool calls, results, and errors). Never expose private chain-of-thought.
- Save user turns before model execution and preserve failure events so requests can be retried.
- Keep conversation persistence behind a storage abstraction and use the configured SQLite data volume for local development.
- Preserve the Qwen-only environment contract: `QWEN_BASE_URL`, `QWEN_MODEL`, and `QWEN_API_KEY`.
- Reuse `shared/prompts.py` for model system prompts; keep trip-planning
  behavior, uncertainty handling, clarification guidance, Markdown formatting,
  and hidden chain-of-thought boundaries consistent across chat and agents.

## Development

- Prefer small, typed Python changes that follow the existing Pydantic and FastAPI patterns.
- Keep browser UI behavior usable on narrow screens and fit the available viewport without requiring a full-screen mode.
- Update [README.md](README.md) when public endpoints, configuration, or architecture direction changes.
- Validate Python syntax and run focused tests or API checks after changes.
- When requirements, behavior, or architecture are ambiguous, ask the user a focused clarifying question before choosing a consequential direction. Do not silently guess when multiple reasonable options exist.

## TODOs

- Write TODOs as concrete, actionable work items that describe the intended outcome.
- Include the affected component or file when it is known, for example `TODO(ui): add streaming activity updates`.
- Do not leave TODOs for unfinished work that is part of the current change; complete it or report the limitation explicitly.
- Keep TODOs compatible with the current FastAPI, LangGraph, React/Vite, and SQLite direction. Avoid TODOs that propose replacing the core architecture without a separate design decision.
- Remove or update TODOs when the work is completed, superseded, or no longer valid.
