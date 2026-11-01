# Agent 4 - Travel History
Previously visited locations stored in the configured SQLite `DATABASE_URL`.
Each entry includes country, city, and the specific location visited.
The agent is gated by `ENABLE_TRAVEL_HISTORY` (0 = Baseline A), and records
are scoped to `TripRequest.user_id`.

Use `TravelHistoryStore.record_visit(user_id, place)` to add a visit from
application code or evaluation fixtures. The agent returns distinct places in
most-recent-first order.

Chat also records explicit past-visit statements such as "I went to the Peak
before." It uses the conversation ID as the chat user's memory key and maps
"the Peak" to "Victoria Peak"; unrelated chat text is not treated as memory.
The chat model can invoke the `search_travel_history` tool when it needs to
check related locations. Results are returned only for the tool query.
