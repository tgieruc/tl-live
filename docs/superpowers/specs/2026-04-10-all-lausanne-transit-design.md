# All-Lausanne Multimodal Transit Dashboard

**Date**: 2026-04-10
**Status**: Draft

## Summary

Extend the TL Live transit dashboard from 3 hardcoded bus lines to all public transport in the greater Lausanne area: all TL buses (46 lines), metro (M1/M2), regional trains (S-Bahn), intercity trains (IR/IC/ICE), and neighboring operators (MBC, LEB, etc.). Route geometries are OSRM-snapped for buses and OSM-extracted for rail. The map shows all routes with active-line emphasis based on the selected stop.

## Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Geographic scope | Radius ~12 km from Lausanne Gare | Captures the full agglomeration without pulling in distant cities |
| GTFS source | Single national feed (opentransportdata.swiss) | One source, all operators, one filter |
| Bus geometry | OSRM road-snapping (existing approach) | Accurate road-following geometry |
| Rail geometry | OSM rail network extraction via Overpass API | OSRM can't route on rails; OSM has accurate rail data |
| Map display | All routes visible; active lines emphasized, inactive faded | Full network context with focus on selected stop |
| Pipeline approach | Single Python script, manually triggered | Runs a few times per year; simplicity over automation |
| Runtime generation | No — static pre-computed files | OSRM + OSM processing takes minutes; not suitable for startup |

## Architecture

### Data Pipeline

**Script**: `data/extract_routes_v3.py`
**Wrapper**: `scripts/generate_data.sh`

#### Processing Steps

1. **Download & extract** national GTFS zip from opentransportdata.swiss to `data/gtfs_national/`
2. **Filter by radius** — parse `stops.txt`, keep stops within 12 km of Lausanne Gare (lat=46.516, lon=6.629) using haversine distance. Build a set of relevant `stop_id`s.
3. **Filter routes** — using `stop_times.txt`, find all `trip_id`s that visit at least one relevant stop. Map back to `route_id`s via `trips.txt`, then to route metadata via `routes.txt`.
4. **Classify by mode** — use GTFS `route_type`:
   - 0 = Tram / Light Rail
   - 1 = Subway / Metro
   - 2 = Rail (regional + intercity)
   - 3 = Bus
   - Other types as encountered
5. **Pick best trip** per (route_short_name, headsign) — trip with most stops (existing logic).
6. **Generate bus geometries** — for `route_type == 3`: snap stop sequences to roads via OSRM (`router.project-osrm.org`), 1 req/sec rate limit, retry with backoff on failure.
7. **Generate rail geometries** — for `route_type in {0, 1, 2}`:
   - Fetch OSM rail/subway/light_rail network for the Lausanne bounding box via Overpass API
   - Build a networkx graph from the OSM ways
   - For each route's stop sequence, find the shortest path through the rail graph between consecutive stops
   - Combine path segments into a LineString geometry
   - Fallback: straight line between stops if graph routing fails for a segment
8. **Output** three files to `backend/tl_backend/priv/static/`:
   - `routes.geojson` — FeatureCollection of LineStrings. Properties: `{line, headsign, route_type, color, num_stops}`
   - `route_stops.json` — dict keyed by `"{line}_{headsign}"`. Values: array of `{stop_id, name, lat, lon, arrival, departure}`
   - `stops.geojson` — FeatureCollection of Points. Properties: `{stop_id, name}`

#### Shell Wrapper (`scripts/generate_data.sh`)

```
#!/bin/bash
set -euo pipefail

# 1. Download national GTFS (no API key required, updated twice/week)
# Dataset page: https://data.opentransportdata.swiss/dataset/timetable-2026-gtfs2020
GTFS_URL="https://data.opentransportdata.swiss/dataset/timetable-2026-gtfs2020"
# Resolve latest resource URL from dataset page, or pin a known version:
curl -L -o data/gtfs_national.zip "${GTFS_URL}" 
unzip -o data/gtfs_national.zip -d data/gtfs_national/

# 2. Run extraction
python3 data/extract_routes_v3.py

# 3. Copy to backend static dir
cp data/routes.geojson backend/tl_backend/priv/static/
cp data/route_stops.json backend/tl_backend/priv/static/
cp data/stops.geojson backend/tl_backend/priv/static/

echo "Done. Restart backend to pick up new data."
```

#### Dependencies

- Python 3.10+
- `osmnx` (OSM network extraction + graph routing)
- `networkx` (graph algorithms, comes with osmnx)
- `requests` (HTTP for OSRM + Overpass)
- `shapely` (geometry operations)

#### Expected Scale

| Metric | Current (3 bus lines) | Estimated (all Lausanne) |
|--------|----------------------|--------------------------|
| Routes in geojson | 6 features | ~150-200 features |
| Unique stops | 87 | ~1,500-2,000 |
| route_stops.json | 36 KB | ~500-800 KB |
| routes.geojson | 52 KB | ~1-2 MB |
| Pipeline runtime | ~10s | ~5-10 min |

### Backend

**No code changes required.**

The backend is fully line-agnostic:
- `/api/routes` serves `routes.geojson` as-is (static file)
- `/api/stops` serves `stops.geojson` as-is (static file)
- `/api/positions` matches departures to `route_stops.json` by line + headsign — works for any mode
- `/api/departures` fetches from transport.opendata.ch — already supports all modes/stops
- `/api/search` proxies to transport.opendata.ch — already searches all Swiss stations

The only "change" is replacing the three static files in `priv/static/` with the new, larger versions.

### Frontend

#### Map.svelte — Route Emphasis

Current behavior: all routes rendered equally. New behavior:

- **All routes loaded at startup** from `/api/routes` (full geojson, ~1-2 MB)
- **Two rendering states** driven by the set of active lines (lines serving the selected stop):
  - **Active lines**: full opacity, normal stroke width, glow effect
  - **Inactive lines**: ~0.15 opacity, thinner stroke, no glow
- **Mode-based styling** using the `route_type` property:
  - Bus (`route_type: 3`): solid line
  - Metro (`route_type: 1`): solid line, slightly thicker
  - Tram (`route_type: 0`): solid line
  - Rail (`route_type: 2`): dashed line pattern
- **Implementation**: Maplibre GL `filter` and `paint` expressions on existing line layers, driven by a reactive `activeLines` set

#### Data Flow for Active Lines

```
DepartureBoard fetches /api/departures
  → extracts set of line names from departure response (e.g., {"25", "33", "S1"})
  → writes to activeLines writable store (Set<string>)
Map subscribes to activeLines store
  → updates Maplibre layer paint properties using data-driven expressions
  → active lines: opacity 1.0, normal stroke width, glow
  → inactive lines: opacity 0.15, thinner stroke, no glow
```

The `activeLines` store is a `writable<Set<string>>` in `src/lib/stores/activeLines.ts`, exported and shared between DepartureBoard (writer) and Map (reader).

#### types.ts — Color Map Extension

- Add explicit colors for: M1, M2, N1-N6, S-lines, IR, IC, Bus-LEB
- Existing hash-based fallback handles any unmapped line
- Add `ROUTE_TYPE_STYLE` constant for mode-based line dash patterns

#### +page.svelte

- Wire the `activeLines` store between DepartureBoard and Map components

### Edge Cases & Fallbacks

1. **OSRM rate limits**: 1 req/sec with exponential backoff on 429/5xx. ~90s for all bus routes.
2. **OSM rail graph gaps**: if shortest-path fails between two consecutive stops, fall back to a straight line segment for that pair.
3. **Large GTFS parsing**: parse `stops.txt` first (small), build stop ID set, then stream `stop_times.txt` filtering by stop ID — avoids loading 500+ MB into memory.
4. **Route matching ambiguity**: keying by `"{line}_{headsign}"` handles shared-track scenarios (each train direction is distinct).
5. **Frontend performance**: 1-2 MB GeoJSON with ~200 features is well within Maplibre's capability. Geometry precomputation (cumulative distances) runs once on load.
6. **opentransportdata.swiss access**: no API key required. Dataset is publicly downloadable at https://data.opentransportdata.swiss/dataset/timetable-2026-gtfs2020 (updated twice/week).

## What Does NOT Change

- Backend API endpoints (paths, parameters, response shapes)
- DepartureBoard.svelte (already generic)
- StopSelector.svelte (already generic)
- Bus dot animation logic in Map.svelte (data-driven, mode-agnostic)
- Stop store structure
- CORS / caching configuration

## Out of Scope

- Vector tiles (optimization for >3 MB geojson — not needed yet)
- Automatic GTFS feed updates (manual refresh is sufficient)
- Runtime geometry generation in Gleam
- Historical data or analytics
