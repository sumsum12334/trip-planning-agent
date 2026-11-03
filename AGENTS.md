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
- Keep the trip plan as the focal browser UI: a wide panel beside a smaller chat
  pane, a collapsible sidebar, and a separate Live workflow panel that names the
  agent currently working and the handover between agents. Keep it theme-aware
  (light/dark) and responsive, and keep Travel history organized by country.
- Build the trip plan with several small tools (`start_trip_plan`, `set_trip_day`
  per day, `set_trip_budget`, `set_trip_references`, `remove_trip_day`,
  `get_trip_plan`) instead of one large payload, so follow-up edits stay small
  and the UI renders the plan part by part. Keep the contract consistent: the
  arrival `airport` is the first point of the map route, each day carries a
  per-day `budget`, the estimated total is independent of the `budget_items`
  breakdown, and categories should be concrete rather than a vague "other".
  Each day card merges its route with its itemized budget so both are viewed and
  edited together. Validate these fields in `shared/trip_plan.py` and return
  tool-argument errors as labeled results rather than aborting the turn.

## Engineering standards

- Keep changes incremental and traceable. Prefer one focused commit per
  feature or behavior change, with tests and documentation updated in the
  same commit when they are directly related.
- Preserve the application boundaries: FastAPI owns HTTP contracts and
  streaming, agent modules own domain behavior, `TACCClient` owns the
  OpenAI-compatible model protocol, `ConversationStore` owns chat persistence,
  and React owns presentation and user interaction.
- Treat tool calls as typed workflow events. Persist tool arguments, results,
  errors, pending questions, and user selections; never infer durable state
  from display text alone.
- User questions must be resumable: validate the conversation and selected
  option server-side, disable duplicate submissions in the UI, preserve a
  retryable pending state after continuation failures, and mark the question
  answered only after successful model continuation.
- Structured UI tools (the trip-plan tools in `shared/trip_plan.py` and the
  agent tools in `agents/chat_tools.py`) must validate their payloads before
  emitting events. Render structured data in dedicated components rather than
  relying on model-formatted prose, never derive the estimated budget from the
  item breakdown, and return tool-argument errors as labeled results so one bad
  call cannot abort the turn.
- Keep streaming behavior observable without exposing private chain-of-thought.
  Emit concise lifecycle, tool, retry, and failure events; label local stubs,
  estimates, and unavailable integrations explicitly.
- For frontend changes, verify both the production Vite build and the
  responsive layout. Keep pending input, status, retry, and error states
  understandable without relying on the Live workflow panel.
- For Python changes, run syntax compilation and a focused runtime or
  persistence check covering the changed behavior. Do not claim validation
  that was not actually run.

## Development

- Prefer small, typed Python changes that follow the existing Pydantic and FastAPI patterns.
- Keep browser UI behavior usable on narrow screens and fit the available viewport without requiring a full-screen mode.
- Update [README.md](README.md) when public endpoints, configuration, or architecture direction changes.
- Validate Python syntax and run focused tests or API checks after changes.
- Make the project work end-to-end: implement real, testable behavior across
  backend, agents, persistence, streaming events, and UI rather than stopping
  at scaffolding or mock-looking success responses.
- Do not cheat: do not fabricate tool results, live availability, benchmark
  outcomes, test passes, or completed work. Keep model reasoning private,
  expose only safe workflow events, and label stubs and estimates clearly.
- When requirements, behavior, or architecture are ambiguous, ask the user a focused clarifying question before choosing a consequential direction. Do not silently guess when multiple reasonable options exist.

## TODOs

- Write TODOs as concrete, actionable work items that describe the intended outcome.
- Include the affected component or file when it is known, for example `TODO(ui): add streaming activity updates`.
- Do not leave TODOs for unfinished work that is part of the current change; complete it or report the limitation explicitly.
- Keep TODOs compatible with the current FastAPI, LangGraph, React/Vite, and SQLite direction. Avoid TODOs that propose replacing the core architecture without a separate design decision.
- Remove or update TODOs when the work is completed, superseded, or no longer valid.
