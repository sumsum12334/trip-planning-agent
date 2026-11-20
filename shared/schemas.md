# Shared schemas (draft)

- `TripRequest`: destination (required, non-empty), start/end dates (or days), budget, interests, optional origin, optional avoid_visited / user_id
- `StayCandidate`, `TransportLeg` (cost + currency), `DayPlan`, `Itinerary` (total + single plan currency)
- `PlanReviseRequest`: previous `Itinerary` plus the updated `TripRequest` for the `POST /plan/revise` loop

Pydantic mirrors live in `shared/schemas.py`. Agent 1 receives visited-place
exclusions from the graph when `avoid_visited=true`; Agent 4 reads the
user-scoped SQLite travel-history table. The coordinator derives one plan
currency from the costed components and fails closed on mixed currencies.
