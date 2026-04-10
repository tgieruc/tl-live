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
    mode_counts = Counter()
    for meta in routes_meta.values():
        mode_counts[meta["route_type"]] += 1
    mode_names = {0: "Tram", 1: "Metro", 2: "Rail", 3: "Bus"}
    for rt, count in sorted(mode_counts.items()):
        print(f"    {mode_names.get(rt, f'Type {rt}')}: {count} routes")

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

    # Step 6: Generate bus geometries via OSRM
    print(f"\nGenerating bus geometries ({len(bus_routes)} routes)...")
    bus_geometries = generate_bus_geometries(bus_routes, trip_stops, stops)
    print(f"  Generated {len(bus_geometries)} bus geometries")
