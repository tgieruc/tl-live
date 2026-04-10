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
