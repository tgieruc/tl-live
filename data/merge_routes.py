"""Merge bus routes (from v2/TL GTFS) with rail routes (from v3/national GTFS)."""
import json
import sys

# Load bus data from v2
with open("routes.geojson") as f:
    bus_routes = json.load(f)
with open("route_stops.json") as f:
    bus_stops = json.load(f)
with open("stops.geojson") as f:
    bus_stop_points = json.load(f)

# Load rail data from v3
with open("rail_routes.geojson") as f:
    rail_routes = json.load(f)
with open("rail_route_stops.json") as f:
    rail_stops = json.load(f)
with open("rail_stops.geojson") as f:
    rail_stop_points = json.load(f)

# Merge
merged_routes = {
    "type": "FeatureCollection",
    "features": bus_routes["features"] + rail_routes["features"]
}
merged_route_stops = {**bus_stops, **rail_stops}

# Merge stop points (deduplicate by stop_id)
seen = set()
merged_stop_features = []
for feat in bus_stop_points["features"] + rail_stop_points["features"]:
    sid = feat["properties"]["stop_id"]
    if sid not in seen:
        seen.add(sid)
        merged_stop_features.append(feat)
merged_stops = {"type": "FeatureCollection", "features": merged_stop_features}

# Write merged output
with open("merged_routes.geojson", "w") as f:
    json.dump(merged_routes, f)
with open("merged_route_stops.json", "w") as f:
    json.dump(merged_route_stops, f)
with open("merged_stops.geojson", "w") as f:
    json.dump(merged_stops, f)

print(f"Merged: {len(bus_routes['features'])} bus + {len(rail_routes['features'])} rail = {len(merged_routes['features'])} routes")
print(f"Route stops: {len(bus_stops)} bus + {len(rail_stops)} rail = {len(merged_route_stops)} total")
print(f"Stops: {len(merged_stop_features)} unique")
