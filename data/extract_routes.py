import csv
import json
from collections import defaultdict

# 1. Find route IDs for TL lines 25, 32, 33
target_lines = {'25', '32', '33'}
route_ids = {}  # route_id -> line_number

with open('gtfs_bus/routes.txt') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['agency_id'] == '000151' and row['route_short_name'] in target_lines:
            route_ids[row['route_id']] = row['route_short_name']

print(f"Found {len(route_ids)} route variants")

# 2. Find trips for these routes, pick one trip per route direction
# trip_id -> (route_id, direction)
trips = {}  # We'll collect all, then pick representative ones
trip_to_route = {}

with open('gtfs_bus/trips.txt') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['route_id'] in route_ids:
            trip_to_route[row['trip_id']] = {
                'route_id': row['route_id'],
                'line': route_ids[row['route_id']],
                'direction': row.get('direction_id', '0'),
            }

print(f"Found {len(trip_to_route)} trips for target routes")

# 3. Get stop sequences for these trips
trip_stops = defaultdict(list)  # trip_id -> [(seq, stop_id)]

with open('gtfs_bus/stop_times.txt') as f:
    reader = csv.DictReader(f)
    for row in reader:
        if row['trip_id'] in trip_to_route:
            trip_stops[row['trip_id']].append({
                'seq': int(row['stop_sequence']),
                'stop_id': row['stop_id'],
                'arrival': row['arrival_time'],
                'departure': row['departure_time'],
            })

# Sort by sequence
for tid in trip_stops:
    trip_stops[tid].sort(key=lambda x: x['seq'])

print(f"Got stop sequences for {len(trip_stops)} trips")

# 4. Load stop coordinates
stops = {}
with open('gtfs_bus/stops.txt') as f:
    reader = csv.DictReader(f)
    for row in reader:
        stops[row['stop_id']] = {
            'name': row['stop_name'],
            'lat': float(row['stop_lat']),
            'lon': float(row['stop_lon']),
        }

# 5. Pick one representative trip per (line, direction) - the one with most stops
best_trips = {}  # (line, direction) -> trip_id
for tid, info in trip_to_route.items():
    key = (info['line'], info['direction'])
    if tid in trip_stops:
        if key not in best_trips or len(trip_stops[tid]) > len(trip_stops[best_trips[key]]):
            best_trips[key] = tid

print(f"Selected {len(best_trips)} representative trips")
for key, tid in sorted(best_trips.items()):
    print(f"  Line {key[0]} dir {key[1]}: {len(trip_stops[tid])} stops")

# 6. Build GeoJSON
features = []
stop_features = []
seen_stops = set()

for (line, direction), tid in sorted(best_trips.items()):
    coords = []
    for stop in trip_stops[tid]:
        sid = stop['stop_id']
        if sid in stops:
            s = stops[sid]
            coords.append([s['lon'], s['lat']])
            if sid not in seen_stops:
                seen_stops.add(sid)
                stop_features.append({
                    'type': 'Feature',
                    'geometry': {'type': 'Point', 'coordinates': [s['lon'], s['lat']]},
                    'properties': {'name': s['name'], 'stop_id': sid}
                })

    features.append({
        'type': 'Feature',
        'geometry': {'type': 'LineString', 'coordinates': coords},
        'properties': {
            'line': line,
            'direction': direction,
            'trip_id': tid,
            'num_stops': len(coords),
        }
    })

# Also build stop_times data for interpolation
route_data = {}
for (line, direction), tid in sorted(best_trips.items()):
    stops_list = []
    for stop in trip_stops[tid]:
        sid = stop['stop_id']
        if sid in stops:
            s = stops[sid]
            stops_list.append({
                'stop_id': sid,
                'name': s['name'],
                'lat': s['lat'],
                'lon': s['lon'],
                'arrival': stop['arrival'],
                'departure': stop['departure'],
            })
    route_data[f"{line}_{direction}"] = stops_list

geojson = {
    'type': 'FeatureCollection',
    'features': features
}

stops_geojson = {
    'type': 'FeatureCollection',
    'features': stop_features
}

with open('routes.geojson', 'w') as f:
    json.dump(geojson, f)

with open('stops.geojson', 'w') as f:
    json.dump(stops_geojson, f)

with open('route_stops.json', 'w') as f:
    json.dump(route_data, f)

print(f"\nWrote routes.geojson ({len(features)} route lines)")
print(f"Wrote stops.geojson ({len(stop_features)} stops)")
print(f"Wrote route_stops.json ({len(route_data)} route variants with stop times)")
