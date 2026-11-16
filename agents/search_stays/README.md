# Agent 1 - Search Stays

Accommodation candidates come from `tools.py` via `TOOL_STAYS_MODE`. Three modes
are supported: `stub` (default, offline-safe), `overpass` (OpenStreetMap, no
auth), and `api` (OBO Travel MCP, live prices + booking URLs).

## Modes

### stub (default)

A curated local catalog of ~12 stays across Tokyo, Hong Kong, and Amsterdam,
plus generic fallback entries for unknown cities. Ordered by nightly cost under
the derived per-night budget cap. Offline-safe — no network required.

```
TOOL_STAYS_MODE=stub
```

### overpass

Queries the [OpenStreetMap Overpass API](https://overpass-api.de/) for
`tourism=hotel/motel/guest_house/hostel` nodes near the geocoded destination.
Returns real names, coordinates, addresses, star ratings, and amenities. Does
**not** return nightly cost or real-time availability — see the pricing module
for heuristic estimates.

No API key or signup required. Public instances can be rate-limited; multiple
mirrors are tried in order.

```
TOOL_STAYS_MODE=overpass
OVERPASS_API_URL=https://overpass-api.de/api/interpreter,https://overpass.kumi.systems/api/interpreter
OVERPASS_TIMEOUT=30
OVERPASS_RADIUS_METERS=5000
```

### api (OBO Travel)

Calls the [OBO Travel MCP API](https://onebookingonline.com/mcp) via JSON-RPC
2.0 for live hotel availability and pricing. Returns real nightly rates,
booking URLs, star ratings, free-cancellation windows, and hotel tokens for
follow-up calls. This is the only mode that returns actual bookable prices.

No API key required for keyless access (30 req/min, 500 req/day). Optional
`STAYS_API_KEY` for higher limits (60 req/min, 2000 req/day).

```
TOOL_STAYS_MODE=api
STAYS_API_BASE_URL=https://onebookingonline.com/mcp
STAYS_API_KEY=          # optional, for higher rate limits
STAYS_API_TIMEOUT=30
```

## How dates work

`search_stays` accepts `check_in` and `check_out` (ISO `YYYY-MM-DD`). If omitted:
- check-in defaults to tomorrow
- check-out defaults to 3 nights after check-in
- When `days` is provided but no dates, check-out = check-in + days

## Run

Direct probe via HTTP:

```bash
curl -X POST http://127.0.0.1:8000/agents/search_stays \
  -H "Content-Type: application/json" \
  -d '{"destination":"Tokyo","budget":500,"days":3,"interests":["temples","food"]}'
```

Tool mode (chat model calls `search_stays` directly):

```json
{
  "name": "search_stays",
  "arguments": {
    "destination": "Tokyo",
    "budget": 500,
    "days": 3,
    "interests": ["temples", "food"],
    "check_in": "2026-12-10",
    "check_out": "2026-12-13"
  }
}
```

## Health

`GET /health` reports:

```json
{
  "agent": "search_stays",
  "tool_mode": "stub",
  "provider_configured": true,
  "catalog": "stub",
  "provider": {
    "provider": "stub",
    "offline_safe": true
  }
}
```

For `api` mode, `provider_configured` is `false` until `STAYS_API_BASE_URL` is
set, and `provider` reports `api_key_configured` and `endpoint`.

## Tests

```bash
pytest tests/test_search_stays.py -v
```

Covers: budget caps, city matching, generic fallback, excluded locations, API
mode labeled errors, and overpass geocode-failure handling.
