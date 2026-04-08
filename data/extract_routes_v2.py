import csv
import json
import time
import urllib.request
from collections import defaultdict


def snap_to_roads(coords):
    """Send stop coords to OSRM and get road-following geometry back."""
    coord_str = ';'.join(f"{c[0]},{c[1]}" for c in coords)
    url = f"http://router.project-osrm.org/route/v1/driving/{coord_str}?overview=full&geometries=geojson"

    req = urllib.request.Request(url, headers={'User-Agent': 'tl-live-dashboard/1.0'})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            data = json.loads(resp.read())
        if data.get('code') == 'Ok' and data['routes']:
            snapped = data['routes'][0]['geometry']['coordinates']
            print(f"    OSRM: {len(coords)} stops -> {len(snapped)} road points")
            return snapped
    except Exception as e:
        print(f"    OSRM failed: {e}")
    return coords  # fallback to straight lines

target_lines = {'25', '32', '33'}
route_ids = {}

with open('gtfs_bus/routes.txt') as f:
    for row in csv.DictReader(f):
        if row['agency_id'] == '000151' and row['route_short_name'] in target_lines:
            route_ids[row['route_id']] = row['route_short_name']

# Get headsigns to identify directions
trip_info = {}
headsigns_per_line = defaultdict(set)

with open('gtfs_bus/trips.txt') as f:
    for row in csv.DictReader(f):
        if row['route_id'] in route_ids:
            line = route_ids[row['route_id']]
            hs = row['trip_headsign']
            trip_info[row['trip_id']] = {'line': line, 'headsign': hs}
            headsigns_per_line[line].add(hs)

for line, hss in sorted(headsigns_per_line.items()):
    print(f"Line {line}: {hss}")

# Get stop sequences
trip_stops = defaultdict(list)
with open('gtfs_bus/stop_times.txt') as f:
    for row in csv.DictReader(f):
        if row['trip_id'] in trip_info:
            trip_stops[row['trip_id']].append({
                'seq': int(row['stop_sequence']),
                'stop_id': row['stop_id'],
                'arrival': row['arrival_time'],
                'departure': row['departure_time'],
            })

for tid in trip_stops:
    trip_stops[tid].sort(key=lambda x: x['seq'])

# Pick best trip per (line, headsign) — most stops
best = {}
for tid, info in trip_info.items():
    key = (info['line'], info['headsign'])
    if tid in trip_stops:
        if key not in best or len(trip_stops[tid]) > len(trip_stops[best[key]]):
            best[key] = tid

# Load stops
stops = {}
with open('gtfs_bus/stops.txt') as f:
    for row in csv.DictReader(f):
        stops[row['stop_id']] = {
            'name': row['stop_name'],
            'lat': float(row['stop_lat']),
            'lon': float(row['stop_lon']),
        }

# Build GeoJSON
features = []
stop_features = []
seen_stops = set()
route_data = {}

for (line, headsign), tid in sorted(best.items()):
    coords = []
    stops_list = []
    for stop in trip_stops[tid]:
        sid = stop['stop_id']
        if sid in stops:
            s = stops[sid]
            coords.append([s['lon'], s['lat']])
            stops_list.append({
                'stop_id': sid, 'name': s['name'],
                'lat': s['lat'], 'lon': s['lon'],
                'arrival': stop['arrival'], 'departure': stop['departure'],
            })
            if sid not in seen_stops:
                seen_stops.add(sid)
                stop_features.append({
                    'type': 'Feature',
                    'geometry': {'type': 'Point', 'coordinates': [s['lon'], s['lat']]},
                    'properties': {'name': s['name'], 'stop_id': sid}
                })

    # Snap to roads via OSRM
    print(f"  Snapping line {line} -> {headsign}...")
    snapped_coords = snap_to_roads(coords)
    time.sleep(1)  # be polite to the public OSRM server

    features.append({
        'type': 'Feature',
        'geometry': {'type': 'LineString', 'coordinates': snapped_coords},
        'properties': {'line': line, 'headsign': headsign, 'num_stops': len(coords)}
    })
    route_data[f"{line}_{headsign}"] = stops_list

geojson = {'type': 'FeatureCollection', 'features': features}
stops_geojson = {'type': 'FeatureCollection', 'features': stop_features}

with open('routes.geojson', 'w') as f:
    json.dump(geojson, f)
with open('stops.geojson', 'w') as f:
    json.dump(stops_geojson, f)
with open('route_stops.json', 'w') as f:
    json.dump(route_data, f)

print(f"\n{len(features)} route lines, {len(stop_features)} stops, {len(route_data)} route variants")
for (line, hs), tid in sorted(best.items()):
    print(f"  Line {line} -> {hs}: {len(trip_stops[tid])} stops")
