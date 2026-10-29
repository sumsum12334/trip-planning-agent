# Shared schemas (draft)

- `TripRequest`: destination, start/end dates (or days), budget, interests, optional origin, optional avoid_visited / user_id
- `StayCandidate` (optional: currency, rating, amenities), `TransportLeg`, `DayPlan`, `Itinerary`

Pydantic mirrors live in `shared/schemas.py`.