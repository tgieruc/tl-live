# All-Lausanne Multimodal Transit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Extend the transit dashboard from 3 bus lines to all public transport within 12 km of Lausanne (buses, metro, trams, trains) with route emphasis on the map.

**Architecture:** A new Python data pipeline (`extract_routes_v3.py`) downloads the Swiss national GTFS feed, filters by radius, generates OSRM-snapped bus routes and OSM-extracted rail geometries. The frontend adds an `activeLines` store so the map emphasizes routes serving the selected stop while fading others. Mode-based styling distinguishes buses from trains.

**Tech Stack:** Python 3 (osmnx, networkx, requests, shapely), SvelteKit 5, Maplibre GL, Gleam backend (no changes)

---

## File Structure

### New Files
- `data/extract_routes_v3.py` — main data pipeline script
- `data/requirements.txt` — Python dependencies
- `scripts/generate_data.sh` — shell wrapper to download GTFS + run pipeline
- `frontend/tl-dashboard/src/lib/stores/activeLines.ts` — writable store for active line names

### Modified Files
- `frontend/tl-dashboard/src/lib/types.ts` — extend LINE_COLORS, add ROUTE_TYPE_STYLES
- `frontend/tl-dashboard/src/lib/components/DepartureBoard.svelte` — emit active lines to store
- `frontend/tl-dashboard/src/lib/components/Map.svelte` — emphasis logic + mode-based dash patterns

### Generated Files (output of pipeline, committed to repo)
- `backend/tl_backend/priv/static/routes.geojson` — overwritten with all-Lausanne data
- `backend/tl_backend/priv/static/route_stops.json` — overwritten
- `backend/tl_backend/priv/static/stops.geojson` — overwritten

---

### Task 1: Python Dependencies & Skeleton

**Files:**
- Create: `data/requirements.txt`
- Create: `data/extract_routes_v3.py` (skeleton with imports + constants)

- [ ] **Step 1: Create requirements.txt**

```
osmnx>=2.0.0
networkx
requests
shapely
```

- [ ] **Step 2: Create script skeleton with constants and haversine**

Create `data/extract_routes_v3.py`:

```python
"""
Extract all public transport routes within 12 km of Lausanne from the Swiss national GTFS feed.
Bus routes are snapped to roads via OSRM. Rail/tram/metro routes use OSM geometry.
Outputs: routes.geojson, route_stops.json, stops.geojson
"""

import csv
import json
import math
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

import networkx as nx
import osmnx as ox
import requests
from shapely.geometry import Point, LineString
from shapely.ops import nearest_points

# --- Constants ---
LAUSANNE_LAT = 46.516
LAUSANNE_LON = 6.629
RADIUS_KM = 12

SCRIPT_DIR = Path(__file__).parent
GTFS_DIR = SCRIPT_DIR / "gtfs_national"
OUTPUT_DIR = SCRIPT_DIR

# GTFS route_type mapping
MODE_BUS = 3
MODE_TRAM = 0
MODE_METRO = 1
MODE_RAIL = 2
RAIL_MODES = {MODE_TRAM, MODE_METRO, MODE_RAIL}


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


if __name__ == "__main__":
    print("extract_routes_v3: skeleton runs OK")
```

- [ ] **Step 3: Verify skeleton runs**

Run: `cd /Users/tgieruc/Documents/projects/tl/data && pip install -r requirements.txt && python3 extract_routes_v3.py`
Expected: `extract_routes_v3: skeleton runs OK`

- [ ] **Step 4: Commit**

```bash
git add data/requirements.txt data/extract_routes_v3.py
git commit -m "feat: add extract_routes_v3.py skeleton with dependencies"
```

---

### Task 2: GTFS Parsing — Stops & Radius Filter

**Files:**
- Modify: `data/extract_routes_v3.py`

- [ ] **Step 1: Add stop loading and radius filter function**

Add after the `haversine_km` function:

```python
def load_stops_in_radius(gtfs_dir, center_lat, center_lon, radius_km):
    """Load all stops within radius_km of center point. Returns dict of stop_id -> {name, lat, lon}."""
    stops = {}
    with open(gtfs_dir / "stops.txt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            lat = float(row["stop_lat"])
            lon = float(row["stop_lon"])
            if haversine_km(center_lat, center_lon, lat, lon) <= radius_km:
                stops[row["stop_id"]] = {
                    "name": row["stop_name"],
                    "lat": lat,
                    "lon": lon,
                }
    return stops
```

- [ ] **Step 2: Add route/trip filtering functions**

Add after the stops function:

```python
def load_trips_for_stops(gtfs_dir, stop_ids):
    """Find all trip_ids that visit at least one stop in stop_ids. Returns trip_id -> route_id mapping."""
    trip_route = {}
    # First pass: get trip_id -> route_id from trips.txt
    with open(gtfs_dir / "trips.txt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            trip_route[row["trip_id"]] = {
                "route_id": row["route_id"],
                "headsign": row["trip_headsign"],
            }

    # Second pass: scan stop_times.txt for trips that visit our stops
    relevant_trips = set()
    print("  Scanning stop_times.txt (this may take a minute)...")
    with open(gtfs_dir / "stop_times.txt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["stop_id"] in stop_ids and row["trip_id"] in trip_route:
                relevant_trips.add(row["trip_id"])

    # Filter to only relevant trips
    return {tid: info for tid, info in trip_route.items() if tid in relevant_trips}


def load_routes_metadata(gtfs_dir, route_ids):
    """Load route metadata for given route_ids. Returns route_id -> {short_name, route_type, color}."""
    routes = {}
    with open(gtfs_dir / "routes.txt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            if row["route_id"] in route_ids:
                routes[row["route_id"]] = {
                    "short_name": row["route_short_name"],
                    "route_type": int(row["route_type"]),
                    "color": row.get("route_color", ""),
                }
    return routes
```

- [ ] **Step 3: Wire up in main block**

Replace the `if __name__` block:

```python
if __name__ == "__main__":
    if not GTFS_DIR.exists():
        print(f"Error: GTFS directory not found at {GTFS_DIR}")
        print("Run scripts/generate_data.sh first to download the feed.")
        sys.exit(1)

    # Step 1: Load stops within radius
    print(f"Loading stops within {RADIUS_KM} km of Lausanne...")
    stops = load_stops_in_radius(GTFS_DIR, LAUSANNE_LAT, LAUSANNE_LON, RADIUS_KM)
    stop_ids = set(stops.keys())
    print(f"  Found {len(stops)} stops in radius")

    # Step 2: Find trips visiting those stops
    print("Finding trips serving these stops...")
    trip_info = load_trips_for_stops(GTFS_DIR, stop_ids)
    route_ids = set(info["route_id"] for info in trip_info.values())
    print(f"  Found {len(trip_info)} trips across {len(route_ids)} routes")

    # Step 3: Load route metadata
    print("Loading route metadata...")
    routes_meta = load_routes_metadata(GTFS_DIR, route_ids)
    print(f"  Loaded metadata for {len(routes_meta)} routes")

    # Summary by mode
    from collections import Counter
    mode_counts = Counter()
    for meta in routes_meta.values():
        mode_counts[meta["route_type"]] += 1
    mode_names = {0: "Tram", 1: "Metro", 2: "Rail", 3: "Bus"}
    for rt, count in sorted(mode_counts.items()):
        print(f"    {mode_names.get(rt, f'Type {rt}')}: {count} routes")
```

- [ ] **Step 4: Test with current GTFS data**

The national GTFS may not be downloaded yet, but we can test the structure with the existing TL bus feed by temporarily pointing at it.

Run: `cd /Users/tgieruc/Documents/projects/tl/data && GTFS_DIR=gtfs_bus python3 -c "
from extract_routes_v3 import load_stops_in_radius, haversine_km
from pathlib import Path
stops = load_stops_in_radius(Path('gtfs_bus'), 46.516, 6.629, 12)
print(f'Stops in radius: {len(stops)}')
assert len(stops) > 50, 'Expected at least 50 stops near Lausanne'
print('OK')
"`

Expected: A count of stops and `OK`

- [ ] **Step 5: Commit**

```bash
git add data/extract_routes_v3.py
git commit -m "feat: GTFS parsing with radius filter for stops, trips, routes"
```

---

### Task 3: Best Trip Selection & Stop Sequences

**Files:**
- Modify: `data/extract_routes_v3.py`

- [ ] **Step 1: Add stop sequence loading and best trip selection**

Add after `load_routes_metadata`:

```python
def load_stop_sequences(gtfs_dir, trip_ids, stop_ids):
    """Load stop sequences for given trips, filtered to known stops.
    Returns trip_id -> sorted list of {seq, stop_id, arrival, departure}."""
    trip_stops = defaultdict(list)
    print("  Loading stop sequences from stop_times.txt...")
    with open(gtfs_dir / "stop_times.txt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            tid = row["trip_id"]
            if tid in trip_ids and row["stop_id"] in stop_ids:
                trip_stops[tid].append({
                    "seq": int(row["stop_sequence"]),
                    "stop_id": row["stop_id"],
                    "arrival": row["arrival_time"],
                    "departure": row["departure_time"],
                })
    for tid in trip_stops:
        trip_stops[tid].sort(key=lambda x: x["seq"])
    return dict(trip_stops)


def pick_best_trips(trip_info, trip_stops, routes_meta):
    """Pick the best trip (most stops) per (line_name, headsign).
    Returns dict of (line, headsign) -> trip_id."""
    best = {}
    for tid, info in trip_info.items():
        if tid not in trip_stops or not trip_stops[tid]:
            continue
        route_id = info["route_id"]
        if route_id not in routes_meta:
            continue
        meta = routes_meta[route_id]
        line = meta["short_name"]
        headsign = info["headsign"]
        key = (line, headsign)
        if key not in best or len(trip_stops[tid]) > len(trip_stops[best[key]]):
            best[key] = tid
    return best
```

- [ ] **Step 2: Wire into main block**

Add after the route metadata loading in `__main__`:

```python
    # Step 4: Load stop sequences
    print("Loading stop sequences...")
    trip_stops = load_stop_sequences(GTFS_DIR, set(trip_info.keys()), stop_ids)
    print(f"  Loaded sequences for {len(trip_stops)} trips")

    # Step 5: Pick best trip per (line, headsign)
    print("Selecting best trips...")
    best_trips = pick_best_trips(trip_info, trip_stops, routes_meta)
    print(f"  Selected {len(best_trips)} route variants")

    # Build route_type lookup for best trips
    best_trip_modes = {}
    for (line, headsign), tid in best_trips.items():
        route_id = trip_info[tid]["route_id"]
        best_trip_modes[(line, headsign)] = routes_meta[route_id]["route_type"]

    bus_routes = {k: v for k, v in best_trips.items() if best_trip_modes[k] == MODE_BUS}
    rail_routes = {k: v for k, v in best_trips.items() if best_trip_modes[k] in RAIL_MODES}
    print(f"    Bus routes: {len(bus_routes)}")
    print(f"    Rail/tram/metro routes: {len(rail_routes)}")
```

- [ ] **Step 3: Commit**

```bash
git add data/extract_routes_v3.py
git commit -m "feat: best trip selection per line/headsign with mode classification"
```

---

### Task 4: Bus Geometry — OSRM Snapping

**Files:**
- Modify: `data/extract_routes_v3.py`

- [ ] **Step 1: Add OSRM snapping function**

Add after `pick_best_trips`:

```python
def snap_to_roads_osrm(coords, max_retries=3):
    """Snap a sequence of [lon, lat] coordinates to roads via OSRM.
    Returns snapped coordinates or original coords on failure."""
    if len(coords) < 2:
        return coords

    # OSRM has a limit of ~100 coordinates per request
    # Split into chunks if needed and concatenate results
    CHUNK_SIZE = 80
    if len(coords) > CHUNK_SIZE:
        all_snapped = []
        for i in range(0, len(coords), CHUNK_SIZE - 1):  # overlap by 1 for continuity
            chunk = coords[i:i + CHUNK_SIZE]
            if len(chunk) < 2:
                break
            snapped = snap_to_roads_osrm(chunk, max_retries)
            if all_snapped:
                snapped = snapped[1:]  # skip first point (overlap)
            all_snapped.extend(snapped)
        return all_snapped

    coord_str = ";".join(f"{c[0]},{c[1]}" for c in coords)
    url = f"http://router.project-osrm.org/route/v1/driving/{coord_str}?overview=full&geometries=geojson"

    for attempt in range(max_retries):
        try:
            resp = requests.get(url, headers={"User-Agent": "tl-live-dashboard/2.0"}, timeout=15)
            if resp.status_code == 429:
                wait = 2 ** (attempt + 1)
                print(f"    Rate limited, waiting {wait}s...")
                time.sleep(wait)
                continue
            resp.raise_for_status()
            data = resp.json()
            if data.get("code") == "Ok" and data["routes"]:
                snapped = data["routes"][0]["geometry"]["coordinates"]
                print(f"    OSRM: {len(coords)} stops -> {len(snapped)} road points")
                return snapped
        except Exception as e:
            print(f"    OSRM attempt {attempt + 1} failed: {e}")
            if attempt < max_retries - 1:
                time.sleep(2 ** attempt)

    print(f"    OSRM failed, using straight lines")
    return coords


def generate_bus_geometries(bus_routes, trip_stops, stops):
    """Generate OSRM-snapped geometries for bus routes.
    Returns dict of (line, headsign) -> [lon, lat] coordinate list."""
    geometries = {}
    total = len(bus_routes)
    for i, ((line, headsign), tid) in enumerate(sorted(bus_routes.items())):
        print(f"  [{i+1}/{total}] Bus {line} -> {headsign}")
        coords = []
        for stop in trip_stops[tid]:
            s = stops.get(stop["stop_id"])
            if s:
                coords.append([s["lon"], s["lat"]])
        if len(coords) >= 2:
            geometries[(line, headsign)] = snap_to_roads_osrm(coords)
            time.sleep(1)  # rate limit: 1 req/sec to public OSRM
        else:
            print(f"    Skipping (only {len(coords)} coords)")
    return geometries
```

- [ ] **Step 2: Wire bus geometry into main block**

Add after the bus/rail route counts:

```python
    # Step 6: Generate bus geometries via OSRM
    print(f"\nGenerating bus geometries ({len(bus_routes)} routes)...")
    bus_geometries = generate_bus_geometries(bus_routes, trip_stops, stops)
    print(f"  Generated {len(bus_geometries)} bus geometries")
```

- [ ] **Step 3: Commit**

```bash
git add data/extract_routes_v3.py
git commit -m "feat: OSRM road-snapping for bus route geometries"
```

---

### Task 5: Rail Geometry — OSM Network Extraction

**Files:**
- Modify: `data/extract_routes_v3.py`

- [ ] **Step 1: Add OSM rail network fetching and routing**

Add after `generate_bus_geometries`:

```python
def fetch_rail_network(center_lat, center_lon, radius_m=15000):
    """Fetch rail/tram/subway network from OSM via osmnx.
    Returns a networkx MultiDiGraph with rail edges."""
    print("  Downloading OSM rail network...")
    # osmnx custom filter for rail infrastructure
    custom_filter = '["railway"~"rail|light_rail|subway|tram|narrow_gauge|funicular"]'
    try:
        G = ox.graph_from_point(
            (center_lat, center_lon),
            dist=radius_m,
            network_type="all",
            custom_filter=custom_filter,
            retain_all=True,
            truncate_by_edge=True,
        )
        print(f"  OSM rail network: {G.number_of_nodes()} nodes, {G.number_of_edges()} edges")
        return G
    except Exception as e:
        print(f"  Failed to fetch OSM rail network: {e}")
        return None


def snap_point_to_graph(G, lat, lon):
    """Find the nearest node in graph G to the given lat/lon. Returns node id."""
    return ox.nearest_nodes(G, lon, lat)


def route_between_stops_rail(G, stop_coords):
    """Route through rail graph between consecutive stops.
    stop_coords: list of (lat, lon) tuples.
    Returns list of [lon, lat] coordinates for the full route."""
    if G is None or len(stop_coords) < 2:
        # Fallback: straight lines
        return [[lon, lat] for lat, lon in stop_coords]

    all_coords = []
    for i in range(len(stop_coords) - 1):
        lat1, lon1 = stop_coords[i]
        lat2, lon2 = stop_coords[i + 1]
        try:
            node1 = snap_point_to_graph(G, lat1, lon1)
            node2 = snap_point_to_graph(G, lat2, lon2)
            route_nodes = nx.shortest_path(G, node1, node2, weight="length")
            segment_coords = [[G.nodes[n]["x"], G.nodes[n]["y"]] for n in route_nodes]
            if all_coords:
                segment_coords = segment_coords[1:]  # avoid duplicate junction point
            all_coords.extend(segment_coords)
        except (nx.NetworkXNoPath, nx.NodeNotFound):
            # Fallback: straight line for this segment
            if all_coords:
                all_coords.append([lon2, lat2])
            else:
                all_coords.extend([[lon1, lat1], [lon2, lat2]])

    return all_coords if all_coords else [[lon, lat] for lat, lon in stop_coords]


def generate_rail_geometries(rail_routes, trip_stops, stops, rail_graph):
    """Generate OSM-routed geometries for rail/tram/metro routes.
    Returns dict of (line, headsign) -> [lon, lat] coordinate list."""
    geometries = {}
    total = len(rail_routes)
    for i, ((line, headsign), tid) in enumerate(sorted(rail_routes.items())):
        print(f"  [{i+1}/{total}] Rail {line} -> {headsign}")
        stop_coords = []
        for stop in trip_stops[tid]:
            s = stops.get(stop["stop_id"])
            if s:
                stop_coords.append((s["lat"], s["lon"]))
        if len(stop_coords) >= 2:
            geometries[(line, headsign)] = route_between_stops_rail(rail_graph, stop_coords)
        else:
            print(f"    Skipping (only {len(stop_coords)} stops)")
    return geometries
```

- [ ] **Step 2: Wire rail geometry into main block**

Add after the bus geometry generation:

```python
    # Step 7: Generate rail geometries via OSM
    rail_graph = None
    if rail_routes:
        print(f"\nFetching OSM rail network...")
        rail_graph = fetch_rail_network(LAUSANNE_LAT, LAUSANNE_LON, radius_m=RADIUS_KM * 1000 + 3000)
        print(f"\nGenerating rail geometries ({len(rail_routes)} routes)...")
        rail_geometries = generate_rail_geometries(rail_routes, trip_stops, stops, rail_graph)
        print(f"  Generated {len(rail_geometries)} rail geometries")
    else:
        rail_geometries = {}
```

- [ ] **Step 3: Commit**

```bash
git add data/extract_routes_v3.py
git commit -m "feat: OSM rail network extraction and graph routing for train/tram/metro geometries"
```

---

### Task 6: GeoJSON & JSON Output

**Files:**
- Modify: `data/extract_routes_v3.py`

- [ ] **Step 1: Add output generation function**

Add after `generate_rail_geometries`:

```python
def write_outputs(best_trips, trip_info, trip_stops, stops, routes_meta,
                  bus_geometries, rail_geometries, best_trip_modes, output_dir):
    """Write routes.geojson, route_stops.json, and stops.geojson."""
    features = []
    stop_features = []
    seen_stops = set()
    route_data = {}

    for (line, headsign), tid in sorted(best_trips.items()):
        route_type = best_trip_modes[(line, headsign)]
        route_id = trip_info[tid]["route_id"]
        color = routes_meta[route_id].get("color", "")

        # Get geometry
        if (line, headsign) in bus_geometries:
            coords = bus_geometries[(line, headsign)]
        elif (line, headsign) in rail_geometries:
            coords = rail_geometries[(line, headsign)]
        else:
            continue  # skip routes with no geometry

        # Build stop list for route_stops.json
        stops_list = []
        for stop in trip_stops[tid]:
            sid = stop["stop_id"]
            s = stops.get(sid)
            if s:
                stops_list.append({
                    "stop_id": sid,
                    "name": s["name"],
                    "lat": s["lat"],
                    "lon": s["lon"],
                    "arrival": stop["arrival"],
                    "departure": stop["departure"],
                })
                if sid not in seen_stops:
                    seen_stops.add(sid)
                    stop_features.append({
                        "type": "Feature",
                        "geometry": {"type": "Point", "coordinates": [s["lon"], s["lat"]]},
                        "properties": {"name": s["name"], "stop_id": sid},
                    })

        features.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": coords},
            "properties": {
                "line": line,
                "headsign": headsign,
                "route_type": route_type,
                "color": f"#{color}" if color and not color.startswith("#") else color,
                "num_stops": len(stops_list),
            },
        })
        route_data[f"{line}_{headsign}"] = stops_list

    # Write files
    routes_geojson = {"type": "FeatureCollection", "features": features}
    stops_geojson = {"type": "FeatureCollection", "features": stop_features}

    routes_path = output_dir / "routes.geojson"
    stops_path = output_dir / "stops.geojson"
    route_stops_path = output_dir / "route_stops.json"

    with open(routes_path, "w") as f:
        json.dump(routes_geojson, f)
    with open(stops_path, "w") as f:
        json.dump(stops_geojson, f)
    with open(route_stops_path, "w") as f:
        json.dump(route_data, f)

    print(f"\nOutput written:")
    print(f"  {routes_path}: {len(features)} routes ({routes_path.stat().st_size // 1024} KB)")
    print(f"  {stops_path}: {len(stop_features)} stops ({stops_path.stat().st_size // 1024} KB)")
    print(f"  {route_stops_path}: {len(route_data)} route variants ({route_stops_path.stat().st_size // 1024} KB)")
```

- [ ] **Step 2: Wire output into main block**

Add at the end of `__main__`:

```python
    # Step 8: Write output files
    print("\nWriting output files...")
    write_outputs(
        best_trips, trip_info, trip_stops, stops, routes_meta,
        bus_geometries, rail_geometries, best_trip_modes, OUTPUT_DIR,
    )

    print("\nDone! Copy files to backend with:")
    print("  cp data/routes.geojson backend/tl_backend/priv/static/")
    print("  cp data/route_stops.json backend/tl_backend/priv/static/")
    print("  cp data/stops.geojson backend/tl_backend/priv/static/")
```

- [ ] **Step 3: Commit**

```bash
git add data/extract_routes_v3.py
git commit -m "feat: GeoJSON and route_stops.json output generation"
```

---

### Task 7: Shell Wrapper Script

**Files:**
- Create: `scripts/generate_data.sh`

- [ ] **Step 1: Create the shell wrapper**

```bash
#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_DIR/data"
STATIC_DIR="$PROJECT_DIR/backend/tl_backend/priv/static"

# --- Configuration ---
# Swiss national GTFS feed (all operators, all modes)
# Dataset page: https://data.opentransportdata.swiss/dataset/timetable-2026-gtfs2020
# The feed is updated twice/week. No API key required.
# To get the latest download URL:
# 1. Visit the dataset page above
# 2. Copy the download link for the latest .zip file
GTFS_URL="${GTFS_URL:-https://data.opentransportdata.swiss/dataset/3d2c18f9-9ef1-463f-a249-5c67604efd74/resource/8e267b6b-3b2c-4a65-b257-cd4a7ce76f3e/download/gtfs_fp2026_20260408.zip}"

echo "=== TL Live Data Generator ==="
echo ""

# Step 1: Download GTFS if not present (or if --fresh flag)
if [[ "${1:-}" == "--fresh" ]] || [[ ! -d "$DATA_DIR/gtfs_national" ]]; then
    echo "Downloading Swiss national GTFS feed..."
    curl -L -o "$DATA_DIR/gtfs_national.zip" "$GTFS_URL"
    echo "Extracting..."
    rm -rf "$DATA_DIR/gtfs_national"
    mkdir -p "$DATA_DIR/gtfs_national"
    unzip -o "$DATA_DIR/gtfs_national.zip" -d "$DATA_DIR/gtfs_national/"
    echo "GTFS extracted to $DATA_DIR/gtfs_national/"
else
    echo "Using existing GTFS data at $DATA_DIR/gtfs_national/"
    echo "(Run with --fresh to re-download)"
fi

# Step 2: Install Python dependencies
echo ""
echo "Checking Python dependencies..."
pip install -q -r "$DATA_DIR/requirements.txt"

# Step 3: Run extraction
echo ""
echo "Running route extraction..."
cd "$DATA_DIR"
python3 extract_routes_v3.py

# Step 4: Copy to backend static directory
echo ""
echo "Copying output to backend static directory..."
cp "$DATA_DIR/routes.geojson" "$STATIC_DIR/routes.geojson"
cp "$DATA_DIR/route_stops.json" "$STATIC_DIR/route_stops.json"
cp "$DATA_DIR/stops.geojson" "$STATIC_DIR/stops.geojson"

echo ""
echo "=== Done! ==="
echo "Restart the backend to pick up the new data."
```

- [ ] **Step 2: Make executable**

Run: `chmod +x /Users/tgieruc/Documents/projects/tl/scripts/generate_data.sh`

- [ ] **Step 3: Commit**

```bash
git add scripts/generate_data.sh
git commit -m "feat: add generate_data.sh wrapper for GTFS download and route extraction"
```

---

### Task 8: Frontend — activeLines Store

**Files:**
- Create: `frontend/tl-dashboard/src/lib/stores/activeLines.ts`

- [ ] **Step 1: Create the store**

```typescript
import { writable } from 'svelte/store';

export const activeLines = writable<Set<string>>(new Set());
```

- [ ] **Step 2: Commit**

```bash
git add frontend/tl-dashboard/src/lib/stores/activeLines.ts
git commit -m "feat: add activeLines writable store"
```

---

### Task 9: Frontend — DepartureBoard Emits Active Lines

**Files:**
- Modify: `frontend/tl-dashboard/src/lib/components/DepartureBoard.svelte`

- [ ] **Step 1: Import activeLines store and update it after fetching departures**

In `DepartureBoard.svelte`, add the import at line 5 (after the `stop` store import):

```typescript
	import { activeLines } from '$lib/stores/activeLines';
```

Then in the `fetchDepartures` function, after the line `departures = data.departures` filtering/sorting block (after `.slice(0, 12);` on line 47), add:

```typescript
			// Update active lines for map emphasis
			activeLines.set(new Set(departures.map((d) => d.line)));
```

This goes right before the `} catch (e) {` line.

- [ ] **Step 2: Run svelte-check**

Run: `cd /Users/tgieruc/Documents/projects/tl/frontend/tl-dashboard && npx svelte-check --tsconfig ./tsconfig.json`

Expected: No new errors related to activeLines

- [ ] **Step 3: Commit**

```bash
git add frontend/tl-dashboard/src/lib/components/DepartureBoard.svelte
git commit -m "feat: DepartureBoard emits active line names to activeLines store"
```

---

### Task 10: Frontend — Extend types.ts with Mode Styles & Colors

**Files:**
- Modify: `frontend/tl-dashboard/src/lib/types.ts`

- [ ] **Step 1: Add missing line colors and route type styles**

Replace the entire `LINE_COLORS` object with:

```typescript
export const LINE_COLORS: Record<string, string> = {
	// TL Bus lines
	'1': '#2ecc71',
	'2': '#9b59b6',
	'3': '#1abc9c',
	'4': '#e67e22',
	'6': '#27ae60',
	'7': '#8e44ad',
	'8': '#2980b9',
	'9': '#c0392b',
	'12': '#16a085',
	'17': '#d35400',
	'18': '#f1c40f',
	'21': '#e74c3c',
	'22': '#3498db',
	'24': '#e67e22',
	'25': '#e74c3c',
	'32': '#3498db',
	'33': '#f39c12',
	'45': '#1abc9c',
	'46': '#9b59b6',
	'47': '#2ecc71',
	'54': '#c0392b',
	'60': '#d35400',
	'85': '#16a085',
	// Metro
	M1: '#e74c3c',
	M2: '#f39c12',
	// Night buses
	N1: '#6c5ce7',
	N2: '#a29bfe',
	N3: '#74b9ff',
	N4: '#55efc4',
	N5: '#ffeaa7',
	N6: '#fab1a0',
	// S-Bahn
	S1: '#2980b9',
	S2: '#27ae60',
	S3: '#e67e22',
	S4: '#8e44ad',
	S11: '#3498db',
	S21: '#2ecc71',
	S31: '#e74c3c',
	// Regional/Intercity
	IR: '#e74c3c',
	RE: '#2ecc71',
	IC: '#e74c3c',
	ICE: '#c0392b',
	S: '#3498db',
};
```

- [ ] **Step 2: Add ROUTE_TYPE_STYLES constant**

Add after the `LINE_COLORS` object:

```typescript
/** Maplibre line-dasharray values by GTFS route_type */
export const ROUTE_TYPE_STYLES: Record<number, { dasharray: number[] | null; width: number }> = {
	0: { dasharray: null, width: 3 },      // Tram: solid, slightly thicker
	1: { dasharray: null, width: 3.5 },     // Metro: solid, thicker
	2: { dasharray: [2, 1.5], width: 2.5 }, // Rail: dashed
	3: { dasharray: null, width: 2.5 },     // Bus: solid (default)
};

export function getRouteTypeStyle(routeType: number): { dasharray: number[] | null; width: number } {
	return ROUTE_TYPE_STYLES[routeType] ?? ROUTE_TYPE_STYLES[3];
}
```

- [ ] **Step 3: Run svelte-check**

Run: `cd /Users/tgieruc/Documents/projects/tl/frontend/tl-dashboard && npx svelte-check --tsconfig ./tsconfig.json`

Expected: No errors

- [ ] **Step 4: Commit**

```bash
git add frontend/tl-dashboard/src/lib/types.ts
git commit -m "feat: extend line colors and add route type styles for multimodal map"
```

---

### Task 11: Frontend — Map.svelte Route Emphasis & Mode Styling

**Files:**
- Modify: `frontend/tl-dashboard/src/lib/components/Map.svelte`

This is the largest frontend change. The map currently creates two layers per line (glow + stroke). We'll switch to a simpler approach: two global layers (active + inactive) using data-driven styling, plus mode-based dash patterns.

- [ ] **Step 1: Add imports**

At the top of `Map.svelte`, update the imports (lines 5-6):

```typescript
	import { LINE_COLORS, getLineColor, getRouteTypeStyle } from '$lib/types';
	import { stopId, stopCoords, stopName } from '$lib/stores/stop';
	import { activeLines } from '$lib/stores/activeLines';
	import { base } from '$app/paths';
```

- [ ] **Step 2: Replace the route layer creation in loadRoutes**

Replace the entire `for (const line of knownRouteLines)` loop (lines 134-152) with data-driven layers that use `route_type` for styling and will be updated dynamically for emphasis:

```typescript
		// Inactive routes (faded background)
		m.addLayer({
			id: 'routes-inactive-glow',
			type: 'line',
			source: 'routes',
			layout: { 'line-join': 'round', 'line-cap': 'round' },
			paint: {
				'line-color': ['coalesce', ['get', 'color'], '#888888'],
				'line-width': 4,
				'line-opacity': 0.05,
				'line-blur': 3
			}
		});
		m.addLayer({
			id: 'routes-inactive',
			type: 'line',
			source: 'routes',
			layout: { 'line-join': 'round', 'line-cap': 'round' },
			paint: {
				'line-color': ['coalesce', ['get', 'color'], '#888888'],
				'line-width': 1.5,
				'line-opacity': 0.15
			}
		});

		// Active routes (emphasized)
		m.addLayer({
			id: 'routes-active-glow',
			type: 'line',
			source: 'routes',
			filter: ['in', ['get', 'line'], ['literal', []]],
			layout: { 'line-join': 'round', 'line-cap': 'round' },
			paint: {
				'line-color': ['coalesce', ['get', 'color'], '#888888'],
				'line-width': 6,
				'line-opacity': 0.12,
				'line-blur': 3
			}
		});
		m.addLayer({
			id: 'routes-active',
			type: 'line',
			source: 'routes',
			filter: ['in', ['get', 'line'], ['literal', []]],
			layout: { 'line-join': 'round', 'line-cap': 'round' },
			paint: {
				'line-color': ['coalesce', ['get', 'color'], '#888888'],
				'line-width': 2.5,
				'line-opacity': 0.7
			}
		});
```

- [ ] **Step 3: Override per-feature colors using getLineColor**

The GeoJSON `color` property from GTFS may be empty or missing for many routes. We need to set colors using our `getLineColor` function after the data loads. Add this right after the route layer creation, before the stops source:

```typescript
		// Override colors: set each feature's color using our LINE_COLORS map
		for (const feat of routes.features) {
			if (!feat.properties.color) {
				feat.properties.color = getLineColor(feat.properties.line);
			}
		}
		// Re-set the source data with colors filled in
		(m.getSource('routes') as maplibregl.GeoJSONSource).setData(routes);
```

- [ ] **Step 4: Add activeLines subscription to update filters**

Add a function and subscription inside `onMount`, after `animateBuses(map);` (line 333) and before the trajectory interval (line 337):

```typescript
			// React to active lines changes — update route emphasis
			const unsubActiveLines = activeLines.subscribe((lines) => {
				if (!map || !map.getLayer('routes-active')) return;
				const lineArray = Array.from(lines);
				const filter: any = lineArray.length > 0
					? ['in', ['get', 'line'], ['literal', lineArray]]
					: ['in', ['get', 'line'], ['literal', []]]; // show nothing as active
				map.setFilter('routes-active', filter);
				map.setFilter('routes-active-glow', filter);

				// Set inactive filter to the inverse
				const inactiveFilter: any = lineArray.length > 0
					? ['!', ['in', ['get', 'line'], ['literal', lineArray]]]
					: true; // show all as inactive when no active lines
				map.setFilter('routes-inactive', inactiveFilter);
				map.setFilter('routes-inactive-glow', inactiveFilter);
			});
```

Add `unsubActiveLines();` to the cleanup return, alongside the other unsubs.

- [ ] **Step 5: Clean up the unused `knownRouteLines` variable**

Remove line 10:
```typescript
	let knownRouteLines: Set<string> = new Set();
```

And remove line 129 inside `loadRoutes`:
```typescript
			knownRouteLines.add(line);
```

- [ ] **Step 6: Run svelte-check**

Run: `cd /Users/tgieruc/Documents/projects/tl/frontend/tl-dashboard && npx svelte-check --tsconfig ./tsconfig.json`

Expected: No new errors

- [ ] **Step 7: Commit**

```bash
git add frontend/tl-dashboard/src/lib/components/Map.svelte
git commit -m "feat: route emphasis with active/inactive layers and data-driven colors"
```

---

### Task 12: Run Pipeline & Integration Test

**Files:**
- Modify: `backend/tl_backend/priv/static/routes.geojson` (generated)
- Modify: `backend/tl_backend/priv/static/route_stops.json` (generated)
- Modify: `backend/tl_backend/priv/static/stops.geojson` (generated)

- [ ] **Step 1: Download national GTFS and run pipeline**

Run: `cd /Users/tgieruc/Documents/projects/tl && bash scripts/generate_data.sh`

If the GTFS URL is stale, visit https://data.opentransportdata.swiss/dataset/timetable-2026-gtfs2020 and update `GTFS_URL` in the script, then re-run.

Expected output: Summary showing ~150-200 route variants, ~1500+ stops, output files in KB range.

- [ ] **Step 2: Verify output file structure**

Run:
```bash
cd /Users/tgieruc/Documents/projects/tl
python3 -c "
import json
with open('backend/tl_backend/priv/static/routes.geojson') as f:
    routes = json.load(f)
with open('backend/tl_backend/priv/static/route_stops.json') as f:
    rs = json.load(f)
with open('backend/tl_backend/priv/static/stops.geojson') as f:
    stops = json.load(f)

print(f'Routes: {len(routes[\"features\"])} features')
print(f'Route stops: {len(rs)} keys')
print(f'Stops: {len(stops[\"features\"])} features')

# Check required properties exist
feat = routes['features'][0]
for prop in ['line', 'headsign', 'route_type', 'num_stops']:
    assert prop in feat['properties'], f'Missing property: {prop}'
print('All required properties present')

# Check route_type distribution
from collections import Counter
types = Counter(f['properties']['route_type'] for f in routes['features'])
print(f'Route types: {dict(types)}')
"
```

Expected: Multiple route types (0, 1, 2, 3), 100+ features, all required properties present.

- [ ] **Step 3: Start backend and frontend, verify in browser**

Run backend: `cd /Users/tgieruc/Documents/projects/tl/backend/tl_backend && gleam run`
Run frontend: `cd /Users/tgieruc/Documents/projects/tl/frontend/tl-dashboard && npm run dev`

Open the dashboard and verify:
1. Route lines appear on the map for multiple modes
2. Selecting a stop highlights the relevant lines and fades others
3. Bus dots animate along routes
4. Departure board shows departures for all transport types

- [ ] **Step 4: Commit generated data**

```bash
git add backend/tl_backend/priv/static/routes.geojson backend/tl_backend/priv/static/route_stops.json backend/tl_backend/priv/static/stops.geojson
git commit -m "data: regenerate static files for all Lausanne public transport"
```
