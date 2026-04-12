#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PROJECT_DIR="$(dirname "$SCRIPT_DIR")"
DATA_DIR="$PROJECT_DIR/data"
STATIC_DIR="$PROJECT_DIR/backend/tl_backend/priv/static"

# --- Configuration ---
GTFS_URL="${GTFS_URL:-https://data.opentransportdata.swiss/dataset/3d2c18f9-9ef1-463f-a249-5c67604efd74/resource/8e267b6b-3b2c-4a65-b257-cd4a7ce76f3e/download/gtfs_fp2026_20260408.zip}"

echo "=== TL Live Data Generator ==="
echo ""

# Step 1: Download national GTFS if not present
if [[ "${1:-}" == "--fresh" ]] || [[ ! -d "$DATA_DIR/gtfs_national" ]]; then
    echo "Downloading Swiss national GTFS feed..."
    curl -L -o "$DATA_DIR/gtfs_national.zip" "$GTFS_URL"
    echo "Extracting..."
    rm -rf "$DATA_DIR/gtfs_national"
    mkdir -p "$DATA_DIR/gtfs_national"
    unzip -o "$DATA_DIR/gtfs_national.zip" -d "$DATA_DIR/gtfs_national/"
else
    echo "Using existing GTFS data"
fi

# Step 2: Set up Python venv
echo ""
echo "Setting up Python environment..."
if [[ ! -d "$DATA_DIR/.venv" ]]; then
    python3 -m venv "$DATA_DIR/.venv"
fi
source "$DATA_DIR/.venv/bin/activate"
pip install -q -r "$DATA_DIR/requirements.txt"

cd "$DATA_DIR"

# Step 3: Generate bus routes from TL GTFS feed (v2 - good OSRM results)
echo ""
echo "=== Bus routes (TL GTFS + OSRM) ==="
python3 extract_routes_v2.py

# Step 4: Generate rail routes from national GTFS feed (v3 - OSM graph)
echo ""
echo "=== Rail routes (national GTFS + OSM) ==="
python3 extract_routes_v3.py

# Step 5: Merge bus + rail
echo ""
echo "=== Merging bus + rail ==="
python3 merge_routes.py

deactivate

# Step 6: Copy merged output to backend
echo ""
echo "Copying to backend..."
mkdir -p "$STATIC_DIR"
cp "$DATA_DIR/merged_routes.geojson" "$STATIC_DIR/routes.geojson"
cp "$DATA_DIR/merged_route_stops.json" "$STATIC_DIR/route_stops.json"
cp "$DATA_DIR/merged_stops.geojson" "$STATIC_DIR/stops.geojson"

echo ""
echo "=== Done! ==="
echo "Restart the backend to pick up the new data."
