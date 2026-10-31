# Shared schemas (draft)

- `TripRequest`: destination, start/end dates (or days), budget, interests, optional origin, optional avoid_visited / user_id
- `StayCandidate`, `TransportLeg`, `DayPlan`, `Itinerary`

Pydantic mirrors live in `shared/schemas.py`. Agent 1 receives visited-place
exclusions from the graph when `avoid_visited=true`; Agent 4 reads the
user-scoped SQLite travel-history table.
