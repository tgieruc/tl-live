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


if __name__ == "__main__":
    print("skeleton runs OK")
