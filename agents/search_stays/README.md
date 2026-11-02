# Agent 1 - Search Stays

Accommodation candidates come from `tools.py` (curated stub catalog with city
match + generic fallback, ordered by nightly cost) via `TOOL_STAYS_MODE`.

`run(request, excluded_locations=...)` calls `tools.search_stays`, then drops
candidates whose name/location overlaps Agent 4 exclusions (casefold). Direct
HTTP: `POST /agents/search_stays`. `api` mode fails explicitly until a provider
is wired.
