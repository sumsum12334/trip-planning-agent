# Agent 1 - Search Stays
Accommodation candidates are produced through the `TOOL_STAYS_MODE` contract.

The current `stub` mode is deterministic and filters candidates by the
per-night budget. The coordinator passes Agent 4's visited places when
`avoid_visited=true`. `api` mode fails explicitly until a provider is wired;
it never silently returns an empty result.
