# Agent 1 - Search Stays

Accommodation candidates come from `tools.py` via `TOOL_STAYS_MODE`. Four modes
are supported: `stub` (default, offline-safe), `overpass` (OpenStreetMap, no
auth), `web` (live web-search results — the preferred live mode), and `api`
(OBO Travel MCP — legacy, kept for rollback).

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

### web (web search — preferred live mode)

Runs 1–3 bounded DuckDuckGo queries per search (via the shared
[`agents/web_search`](../web_search) tool, ~15s per-request timeout, 5-minute
TTL cache) such as `"{destination} hotels price per night"`, then maps each
result to a stay candidate:

- **Name** from the result title, **source URL** from the result link
  (DuckDuckGo redirect wrappers are unwrapped), **location** = destination
  plus any neighborhood hint extracted from the snippet (e.g. "Tokyo
  Shibuya").
- **Nightly cost** is set only when a price is confidently parsed from the
  title/snippet (`$120`, `US$120`, `USD 120`, `from ¥18,000`, `1,200 THB`,
  …). Amounts outside a plausible per-night range for the currency, and
  monthly/weekly rates or stay totals, are rejected. Non-USD prices are
  normalized to **approximate USD with a static fixed rate** and the original
  listing is kept in the notes. When nothing is parseable, `nightly_cost`
  stays `None` and `pricing.apply_estimates` fills a labeled heuristic
  estimate, like the overpass path.
- Results that don't read as lodging or clearly don't match the destination
  are filtered out. Priced candidates above the per-night budget cap are
  dropped; unpriced candidates are kept but sorted last. At most 10 results.
- Every result carries provenance in its notes: `web search: <host>` plus
  how the price was derived.

Requires `WEB_SEARCH_MODE=duckduckgo`. When the web-search tool is in stub
mode, the network fails, or no usable results come back, the curated stub
catalog is returned with a labeled note (`web: web search unavailable;
showing stub catalog`) — results are never fabricated. Provider failures
surface as a single `Provider error` candidate, never an exception.

```
TOOL_STAYS_MODE=web
WEB_SEARCH_MODE=duckduckgo
```

### api (OBO Travel — legacy)

> **Deprecated:** kept for rollback. Prefer `TOOL_STAYS_MODE=web`.

Calls the [OBO Travel MCP API](https://onebookingonline.com/mcp) via JSON-RPC
2.0 for live hotel availability and pricing. Returns real nightly rates,
booking URLs, star ratings, free-cancellation windows, and hotel tokens for
follow-up calls.

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

For `web` mode, `provider` reports `web_search` with the active
`engine_mode` (`stub` falls back to the catalog, `duckduckgo` is live). For
`api` mode, `provider_configured` is `false` until `STAYS_API_BASE_URL` is
set, and `provider` reports `api_key_configured` and `endpoint`.

## Tests

```bash
pytest tests/test_search_stays.py tests/test_search_stays_web.py -v
```

Covers: budget caps, city matching, generic fallback, excluded locations, API
mode labeled errors, overpass geocode-failure handling, and the web mode
(price parsing, destination/budget filtering, stub fallback).
