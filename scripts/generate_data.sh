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

# Step 2: Set up Python venv and install dependencies
echo ""
echo "Setting up Python environment..."
if [[ ! -d "$DATA_DIR/.venv" ]]; then
    python3 -m venv "$DATA_DIR/.venv"
fi
source "$DATA_DIR/.venv/bin/activate"
pip install -q -r "$DATA_DIR/requirements.txt"

# Step 3: Run extraction
echo ""
echo "Running route extraction..."
cd "$DATA_DIR"
python3 extract_routes_v3.py
deactivate

# Step 4: Copy to backend static directory
echo ""
echo "Copying output to backend static directory..."
mkdir -p "$STATIC_DIR"
cp "$DATA_DIR/routes.geojson" "$STATIC_DIR/routes.geojson"
cp "$DATA_DIR/route_stops.json" "$STATIC_DIR/route_stops.json"
cp "$DATA_DIR/stops.geojson" "$STATIC_DIR/stops.geojson"

echo ""
echo "=== Done! ==="
echo "Restart the backend to pick up the new data."
