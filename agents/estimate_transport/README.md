# Agent 2 - Estimate Transport

Travel time and cost between two places via `tools.py` (curated stub route
catalog for HK / Tokyo / Amsterdam + generic scaled fallback) controlled by
`TOOL_MAPS_MODE`.

`run(request, from_place, to_place)` delegates to `tools.estimate_transport`,
using `TripRequest.destination` (or origin) to improve stub city matching.
Same-place labels return a short walk. Direct HTTP: `POST /agents/estimate_transport`.
`api` mode raises `NotImplementedError` until a maps provider is wired.
