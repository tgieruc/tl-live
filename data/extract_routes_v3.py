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
from collections import defaultdict, Counter
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

# GTFS route_type mapping (basic + extended types)
# See: https://gtfs.org/schedule/reference/#routestxt
# Basic types: 0=Tram, 1=Metro, 2=Rail, 3=Bus, 4=Ferry, 5=Cable, 6=Gondola, 7=Funicular
# Extended types: 100-199=Rail, 200-299=Coach, 400-499=Metro, 700-799=Bus, 900-999=Tram, 1000-1199=Water


def classify_route_type(route_type):
    """Classify a GTFS route_type (basic or extended) into 'bus', 'rail', or 'other'."""
    rt = int(route_type)
    # Basic types
    if rt == 3:
        return "bus"
    if rt in (0, 1, 2, 5, 6, 7):
        return "rail"  # tram, metro, rail, cable car, gondola, funicular
    # Extended types
    if 700 <= rt <= 799:
        return "bus"
    if 100 <= rt <= 199:
        return "rail"  # all rail services
    if 400 <= rt <= 499:
        return "rail"  # metro
    if 900 <= rt <= 999:
        return "rail"  # tram
    if 200 <= rt <= 299:
        return "bus"   # coach services
    if 1000 <= rt <= 1199:
        return "other"  # water transport
    return "other"


def haversine_km(lat1, lon1, lat2, lon2):
    """Distance in km between two lat/lon points."""
    R = 6371
    dlat = math.radians(lat2 - lat1)
    dlon = math.radians(lon2 - lon1)
    a = math.sin(dlat / 2) ** 2 + math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * math.sin(dlon / 2) ** 2
    return R * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))


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


def load_all_stops(gtfs_dir):
    """Load ALL stops from stops.txt. Returns dict of stop_id -> {name, lat, lon}."""
    stops = {}
    with open(gtfs_dir / "stops.txt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            stops[row["stop_id"]] = {
                "name": row["stop_name"],
                "lat": float(row["stop_lat"]),
                "lon": float(row["stop_lon"]),
            }
    return stops


def load_stop_sequences(gtfs_dir, trip_ids):
    """Load full stop sequences for given trips (all stops, not just in-radius ones).
    Returns trip_id -> sorted list of {seq, stop_id, arrival, departure}."""
    trip_stops = defaultdict(list)
    print("  Loading stop sequences from stop_times.txt...")
    with open(gtfs_dir / "stop_times.txt", encoding="utf-8-sig") as f:
        for row in csv.DictReader(f):
            tid = row["trip_id"]
            if tid in trip_ids:
                trip_stops[tid].append({
                    "seq": int(row["stop_sequence"]),
                    "stop_id": row["stop_id"],
                    "arrival": row["arrival_time"],
                    "departure": row["departure_time"],
                })
    for tid in trip_stops:
        trip_stops[tid].sort(key=lambda x: x["seq"])
    return dict(trip_stops)


def pick_best_trips(trip_info, trip_stops, routes_meta, max_variants_per_line=2):
    """Pick the best trips per line. First selects the best trip (most stops)
    per (line, headsign), then keeps only the top max_variants_per_line variants
    per line (by stop count) to avoid cluttering the map with partial routes."""
    # Step 1: best trip per (line, headsign)
    best_per_headsign = {}
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
        if key not in best_per_headsign or len(trip_stops[tid]) > len(trip_stops[best_per_headsign[key]]):
            best_per_headsign[key] = tid

    # Step 2: keep only top N variants per line (longest routes = main directions)
    from collections import defaultdict as dd
    line_variants = dd(list)
    for (line, headsign), tid in best_per_headsign.items():
        line_variants[line].append((len(trip_stops[tid]), headsign, tid))

    best = {}
    for line, variants in line_variants.items():
        variants.sort(reverse=True)  # longest first
        for _, headsign, tid in variants[:max_variants_per_line]:
            best[(line, headsign)] = tid

    return best


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


def normalize_route_type(route_type):
    """Convert extended GTFS route_type to basic type for frontend styling."""
    rt = int(route_type)
    cls = classify_route_type(rt)
    if cls == "bus":
        return 3
    # Map rail subtypes more specifically
    if 400 <= rt <= 499 or rt == 1:
        return 1  # Metro
    if 900 <= rt <= 999 or rt == 0:
        return 0  # Tram
    if cls == "rail":
        return 2  # Rail (default for all other rail types)
    return 3  # Default to bus


def write_outputs(best_trips, trip_info, trip_stops, stops, routes_meta,
                  bus_geometries, rail_geometries, best_trip_modes, output_dir):
    """Write routes.geojson, route_stops.json, and stops.geojson."""
    features = []
    stop_features = []
    seen_stops = set()
    route_data = {}

    for (line, headsign), tid in sorted(best_trips.items()):
        route_type = normalize_route_type(best_trip_modes[(line, headsign)])
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


def fetch_rail_network(center_lat, center_lon, radius_m=15000):
    """Fetch rail/tram/subway network from OSM via osmnx.
    Returns a networkx MultiDiGraph with rail edges."""
    print("  Downloading OSM rail network...")
    custom_filter = '["railway"~"rail|light_rail|subway|tram|narrow_gauge|funicular"]'
    try:
        G = ox.graph_from_point(
            (center_lat, center_lon),
            dist=radius_m,
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


if __name__ == "__main__":
    if not GTFS_DIR.exists():
        print(f"Error: GTFS directory not found at {GTFS_DIR}")
        print("Run scripts/generate_data.sh first to download the feed.")
        sys.exit(1)

    # Step 1: Load stops within radius (for identifying relevant trips)
    print(f"Loading stops within {RADIUS_KM} km of Lausanne...")
    local_stops = load_stops_in_radius(GTFS_DIR, LAUSANNE_LAT, LAUSANNE_LON, RADIUS_KM)
    local_stop_ids = set(local_stops.keys())
    print(f"  Found {len(local_stops)} stops in radius")

    # Step 2: Find trips visiting those stops
    print("Finding trips serving these stops...")
    trip_info = load_trips_for_stops(GTFS_DIR, local_stop_ids)
    route_ids = set(info["route_id"] for info in trip_info.values())
    print(f"  Found {len(trip_info)} trips across {len(route_ids)} routes")

    # Step 3: Load route metadata
    print("Loading route metadata...")
    routes_meta = load_routes_metadata(GTFS_DIR, route_ids)
    print(f"  Loaded metadata for {len(routes_meta)} routes")

    # Summary by mode
    mode_counts = Counter()
    for meta in routes_meta.values():
        mode_counts[meta["route_type"]] += 1
    mode_names = {0: "Tram", 1: "Metro", 2: "Rail", 3: "Bus"}
    for rt, count in sorted(mode_counts.items()):
        print(f"    {mode_names.get(rt, f'Type {rt}')}: {count} routes")

    # Step 4: Load ALL stops (for geometry — routes may pass through stops outside radius)
    print("Loading all stops for geometry...")
    stops = load_all_stops(GTFS_DIR)
    print(f"  Loaded {len(stops)} total stops")

    # Step 5: Load full stop sequences (all stops per trip, not just in-radius)
    print("Loading stop sequences...")
    trip_stops = load_stop_sequences(GTFS_DIR, set(trip_info.keys()))
    print(f"  Loaded sequences for {len(trip_stops)} trips")

    # Step 5: Pick best trip per (line, headsign)
    print("Selecting best trips...")
    best_trips = pick_best_trips(trip_info, trip_stops, routes_meta)
    print(f"  Selected {len(best_trips)} route variants")

    # Build mode classification for best trips
    best_trip_modes = {}  # (line, headsign) -> route_type (original GTFS value)
    best_trip_classes = {}  # (line, headsign) -> "bus" | "rail" | "other"
    for (line, headsign), tid in best_trips.items():
        route_id = trip_info[tid]["route_id"]
        rt = routes_meta[route_id]["route_type"]
        best_trip_modes[(line, headsign)] = rt
        best_trip_classes[(line, headsign)] = classify_route_type(rt)

    bus_routes = {k: v for k, v in best_trips.items() if best_trip_classes[k] == "bus"}
    rail_routes = {k: v for k, v in best_trips.items() if best_trip_classes[k] == "rail"}
    other_routes = {k: v for k, v in best_trips.items() if best_trip_classes[k] == "other"}
    print(f"    Bus routes: {len(bus_routes)}")
    print(f"    Rail/tram/metro routes: {len(rail_routes)}")
    if other_routes:
        print(f"    Other (skipped): {len(other_routes)}")

    # Step 6: Generate bus geometries via OSRM
    print(f"\nGenerating bus geometries ({len(bus_routes)} routes)...")
    bus_geometries = generate_bus_geometries(bus_routes, trip_stops, stops)
    print(f"  Generated {len(bus_geometries)} bus geometries")

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
