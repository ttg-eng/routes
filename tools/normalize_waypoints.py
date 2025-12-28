#!/usr/bin/env python3
"""Normalize route waypoints to consistent spacing using OSRM for road-aware interpolation.

This script ensures waypoints are evenly spaced (~20m by default) along the actual road
geometry, not straight lines between points. Stops are preserved exactly as-is.

Prerequisites
-------------
Requires Docker and a local OSRM server with Philippines map data.

Step 1: Download Philippines OSM data
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~
Download the latest Philippines OSM extract into the osrm-data directory:

    cd data/routes/tools
    mkdir -p osrm-data
    curl -L -o osrm-data/philippines-latest.osm.pbf https://download.geofabrik.de/asia/philippines-latest.osm.pbf

Step 2: Process OSRM data
~~~~~~~~~~~~~~~~~~~~~~~~~
Extract, partition, and customize the map data (takes ~2-3 minutes).
Run these commands from data/routes/tools/:

    docker run -t -v "${PWD}/osrm-data:/data" ghcr.io/project-osrm/osrm-backend osrm-extract -p /opt/car.lua /data/philippines-latest.osm.pbf

    docker run -t -v "${PWD}/osrm-data:/data" ghcr.io/project-osrm/osrm-backend osrm-partition /data/philippines-latest.osrm

    docker run -t -v "${PWD}/osrm-data:/data" ghcr.io/project-osrm/osrm-backend osrm-customize /data/philippines-latest.osrm

This creates ~1.5GB of processed files in osrm-data/. These files are gitignored
due to their size - only the .osm.pbf source file needs to be re-downloaded to
regenerate them.

Step 3: Start OSRM server
~~~~~~~~~~~~~~~~~~~~~~~~~
Start the routing server on port 5001 (port 5000 conflicts with macOS AirPlay):

    docker run -d --name osrm-server -p 5001:5000 -v "${PWD}/osrm-data:/data" ghcr.io/project-osrm/osrm-backend osrm-routed --algorithm mld /data/philippines-latest.osrm

Verify it's running (should return JSON with "code":"Ok"):

    curl "http://localhost:5001/route/v1/driving/125.5,7.0;125.6,7.1"

Step 4: Run normalization
~~~~~~~~~~~~~~~~~~~~~~~~~
Process all route files with 20m waypoint spacing:

    python normalize_waypoints.py --all --spacing 20 --osrm-url http://localhost:5001

This creates .json.bak backups before modifying each file.

Step 5: Cleanup
~~~~~~~~~~~~~~~
Stop the OSRM container when done:

    docker rm -f osrm-server

Step 6: Sync to database
~~~~~~~~~~~~~~~~~~~~~~~~
Load the normalized routes into the application database:

    devbox run -- poetry run aik routes sync

Usage Examples
--------------
Process a single route:
    python normalize_waypoints.py R102-AM.json --osrm-url http://localhost:5001

Process all routes with custom spacing:
    python normalize_waypoints.py --all --spacing 15 --osrm-url http://localhost:5001

Dry run (no changes):
    python normalize_waypoints.py --all --dry-run --osrm-url http://localhost:5001
"""

import argparse
import json
import math
import shutil
import sys
import uuid
from pathlib import Path
from typing import TypedDict

import requests

# Davao City coordinate bounds for validation
DAVAO_LAT_MIN, DAVAO_LAT_MAX = 6.9, 7.2
DAVAO_LON_MIN, DAVAO_LON_MAX = 125.4, 125.7

# Earth radius in meters for haversine calculations
EARTH_RADIUS_M = 6_371_000


class RoutePoint(TypedDict):
    id: str
    name: str
    latitude: float
    longitude: float
    kind: str


def haversine_distance(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Calculate distance between two lat/lng points in meters."""
    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = math.sin(delta_phi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
    c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))

    return EARTH_RADIUS_M * c


def interpolate_point(lat1: float, lon1: float, lat2: float, lon2: float, fraction: float) -> tuple[float, float]:
    """Interpolate a point between two coordinates at a given fraction (0-1)."""
    lat = lat1 + (lat2 - lat1) * fraction
    lon = lon1 + (lon2 - lon1) * fraction
    return lat, lon


def generate_uuid7() -> str:
    """Generate a UUID7-like identifier (time-ordered UUID)."""
    # Use uuid4 for simplicity; the actual codebase uses TypeID which handles this
    return str(uuid.uuid4())


def call_osrm_match_chunk(coords: list[tuple[float, float]], osrm_url: str) -> list[tuple[float, float]] | None:
    """Call OSRM match API for a single chunk of coordinates.

    Args:
        coords: List of (lat, lon) tuples (max ~100 points).
        osrm_url: Base URL of the OSRM server.

    Returns:
        List of (lat, lon) tuples representing the road-snapped geometry,
        or None if the match failed.
    """
    if len(coords) < 2:
        return None

    # OSRM expects lon,lat format
    coord_str = ";".join(f"{lon},{lat}" for lat, lon in coords)

    # Use radiuses parameter to allow some flexibility in matching
    radiuses = ";".join(["50"] * len(coords))

    url = f"{osrm_url}/match/v1/driving/{coord_str}"
    params = {
        "geometries": "geojson",
        "overview": "full",
        "radiuses": radiuses,
    }

    try:
        response = requests.get(url, params=params, timeout=60)
        response.raise_for_status()
        data = response.json()

        if data.get("code") != "Ok":
            return None

        # Extract geometry from all matchings and combine
        matchings = data.get("matchings", [])
        if not matchings:
            return None

        all_coords: list[tuple[float, float]] = []
        for matching in matchings:
            geometry = matching.get("geometry", {})
            coordinates = geometry.get("coordinates", [])
            # Convert from [lon, lat] to (lat, lon)
            for coord in coordinates:
                point = (coord[1], coord[0])
                # Avoid duplicates at boundaries
                if not all_coords or all_coords[-1] != point:
                    all_coords.append(point)

        return all_coords if all_coords else None

    except requests.RequestException:
        return None


def call_osrm_match(coords: list[tuple[float, float]], osrm_url: str, chunk_size: int = 80) -> list[tuple[float, float]] | None:
    """Call OSRM match API with chunking for large coordinate lists.

    Args:
        coords: List of (lat, lon) tuples representing the route.
        osrm_url: Base URL of the OSRM server (e.g., http://localhost:5000).
        chunk_size: Max coordinates per request (default 80, OSRM limit is 100).

    Returns:
        List of (lat, lon) tuples representing the road-snapped geometry,
        or None if the match failed.
    """
    if len(coords) < 2:
        return None

    # If small enough, process in one request
    if len(coords) <= chunk_size:
        return call_osrm_match_chunk(coords, osrm_url)

    # Process in overlapping chunks to ensure continuity
    overlap = 5
    all_geometry: list[tuple[float, float]] = []
    i = 0

    while i < len(coords):
        end = min(i + chunk_size, len(coords))
        chunk = coords[i:end]

        chunk_geometry = call_osrm_match_chunk(chunk, osrm_url)
        if chunk_geometry is None:
            print(f"  Chunk {i}-{end} failed, trying smaller chunks...", file=sys.stderr)
            # Try with smaller chunk
            if len(chunk) > 20:
                smaller = call_osrm_match(chunk, osrm_url, chunk_size=len(chunk) // 2)
                if smaller:
                    chunk_geometry = smaller
                else:
                    return None
            else:
                return None

        # Merge with existing geometry, avoiding duplicates
        if all_geometry:
            # Skip overlapping points at the boundary
            for point in chunk_geometry:
                if point != all_geometry[-1]:
                    all_geometry.append(point)
        else:
            all_geometry.extend(chunk_geometry)

        # Move to next chunk with overlap
        i = end - overlap if end < len(coords) else end

    return all_geometry if all_geometry else None


def interpolate_waypoints_along_geometry(
    geometry: list[tuple[float, float]],
    spacing_m: float,
) -> list[tuple[float, float]]:
    """Generate evenly-spaced waypoints along a geometry.

    Args:
        geometry: List of (lat, lon) points from OSRM (dense road geometry).
        spacing_m: Target spacing between waypoints in meters.

    Returns:
        List of (lat, lon) tuples for new waypoints.
    """
    if len(geometry) < 2:
        return list(geometry)

    waypoints: list[tuple[float, float]] = [geometry[0]]
    accumulated_distance = 0.0

    for i in range(1, len(geometry)):
        prev_lat, prev_lon = geometry[i - 1]
        curr_lat, curr_lon = geometry[i]
        segment_distance = haversine_distance(prev_lat, prev_lon, curr_lat, curr_lon)

        # Walk along this segment, placing waypoints at spacing intervals
        remaining = segment_distance
        segment_start = 0.0

        while accumulated_distance + remaining >= spacing_m:
            # Distance needed to reach next waypoint
            distance_to_next = spacing_m - accumulated_distance

            # Fraction along current segment
            fraction = segment_start + (distance_to_next / segment_distance)

            if fraction <= 1.0:
                new_lat, new_lon = interpolate_point(prev_lat, prev_lon, curr_lat, curr_lon, fraction)
                waypoints.append((new_lat, new_lon))

                # Update for next iteration
                remaining -= distance_to_next
                segment_start = fraction
                accumulated_distance = 0.0
            else:
                break

        # Accumulate remaining distance for next segment
        accumulated_distance += remaining

    # Always include the final point
    if waypoints[-1] != geometry[-1]:
        waypoints.append(geometry[-1])

    return waypoints


def find_closest_waypoint_index(
    stop_lat: float,
    stop_lon: float,
    waypoints: list[tuple[float, float]],
) -> int:
    """Find the index of the waypoint closest to a stop."""
    min_dist = float("inf")
    min_idx = 0

    for i, (lat, lon) in enumerate(waypoints):
        dist = haversine_distance(stop_lat, stop_lon, lat, lon)
        if dist < min_dist:
            min_dist = dist
            min_idx = i

    return min_idx


def normalize_segment(
    segment_coords: list[tuple[float, float]],
    spacing_m: float,
    osrm_url: str,
) -> list[tuple[float, float]] | None:
    """Get normalized waypoints for a segment between two stops.

    Args:
        segment_coords: Coordinates of points in this segment (including endpoints).
        spacing_m: Target waypoint spacing in meters.
        osrm_url: OSRM server URL.

    Returns:
        List of interpolated (lat, lon) waypoints, or None if OSRM fails.
    """
    if len(segment_coords) < 2:
        return list(segment_coords)

    # Get road-snapped geometry from OSRM
    geometry = call_osrm_match(segment_coords, osrm_url)
    if geometry is None:
        # Fall back to simple linear interpolation between endpoints
        start = segment_coords[0]
        end = segment_coords[-1]
        dist = haversine_distance(start[0], start[1], end[0], end[1])
        if dist <= spacing_m:
            return [start, end]

        # Interpolate linearly
        num_points = max(2, int(dist / spacing_m) + 1)
        result = []
        for i in range(num_points):
            frac = i / (num_points - 1)
            lat = start[0] + (end[0] - start[0]) * frac
            lon = start[1] + (end[1] - start[1]) * frac
            result.append((lat, lon))
        return result

    # Interpolate waypoints along the road geometry
    return interpolate_waypoints_along_geometry(geometry, spacing_m)


def normalize_route(route: dict, spacing_m: float, osrm_url: str) -> dict | None:
    """Normalize a route's waypoints to consistent spacing.

    Processes the route segment-by-segment between stops to ensure each
    segment gets proper road-snapped waypoints.

    Args:
        route: Route data in native JSON format.
        spacing_m: Target spacing between points in meters.
        osrm_url: Base URL of the OSRM server.

    Returns:
        Normalized route dict, or None if normalization failed.
    """
    points = route["points"]
    if len(points) < 2:
        print("  Route has fewer than 2 points, skipping", file=sys.stderr)
        return None

    # Find all stops and their indices
    stop_indices: list[int] = []
    for i, point in enumerate(points):
        if point.get("kind", "stop") == "stop":
            stop_indices.append(i)

    if len(stop_indices) < 2:
        print("  Route has fewer than 2 stops, skipping", file=sys.stderr)
        return None

    # Build new points list by processing segment-by-segment
    new_points: list[RoutePoint] = []

    # Handle points before the first stop
    if stop_indices[0] > 0:
        pre_coords = [(p["latitude"], p["longitude"]) for p in points[:stop_indices[0] + 1]]
        pre_waypoints = normalize_segment(pre_coords, spacing_m, osrm_url)
        if pre_waypoints:
            for lat, lon in pre_waypoints[:-1]:  # Exclude last (it's the first stop)
                new_points.append({
                    "id": generate_uuid7(),
                    "name": "",
                    "latitude": lat,
                    "longitude": lon,
                    "kind": "waypoint",
                })

    # Process each stop-to-stop segment
    for seg_idx in range(len(stop_indices)):
        start_idx = stop_indices[seg_idx]
        start_stop = points[start_idx]

        # Add the stop
        new_points.append(start_stop)

        # If there's a next stop, add waypoints between them
        if seg_idx < len(stop_indices) - 1:
            end_idx = stop_indices[seg_idx + 1]

            # Get all original points in this segment
            segment_coords = [(p["latitude"], p["longitude"]) for p in points[start_idx:end_idx + 1]]

            # Normalize this segment
            segment_waypoints = normalize_segment(segment_coords, spacing_m, osrm_url)

            if segment_waypoints and len(segment_waypoints) > 2:
                # Add waypoints between stops (exclude first and last which are the stops)
                for lat, lon in segment_waypoints[1:-1]:
                    new_points.append({
                        "id": generate_uuid7(),
                        "name": "",
                        "latitude": lat,
                        "longitude": lon,
                        "kind": "waypoint",
                    })

    # Handle points after the last stop
    last_stop_idx = stop_indices[-1]
    if last_stop_idx < len(points) - 1:
        post_coords = [(p["latitude"], p["longitude"]) for p in points[last_stop_idx:]]
        post_waypoints = normalize_segment(post_coords, spacing_m, osrm_url)
        if post_waypoints:
            for lat, lon in post_waypoints[1:]:  # Exclude first (it's the last stop)
                new_points.append({
                    "id": generate_uuid7(),
                    "name": "",
                    "latitude": lat,
                    "longitude": lon,
                    "kind": "waypoint",
                })

    # Validate coordinates are within Davao bounds
    for point in new_points:
        lat, lon = point["latitude"], point["longitude"]
        if not (DAVAO_LAT_MIN <= lat <= DAVAO_LAT_MAX and DAVAO_LON_MIN <= lon <= DAVAO_LON_MAX):
            print(f"  Warning: Point outside Davao bounds: ({lat}, {lon})", file=sys.stderr)

    # Return normalized route
    return {
        **route,
        "points": new_points,
    }


def compute_max_gap(points: list[RoutePoint]) -> float:
    """Compute the maximum gap between adjacent waypoints."""
    max_gap = 0.0
    for i in range(1, len(points)):
        if points[i - 1].get("kind") == "waypoint" and points[i].get("kind") == "waypoint":
            dist = haversine_distance(
                points[i - 1]["latitude"],
                points[i - 1]["longitude"],
                points[i]["latitude"],
                points[i]["longitude"],
            )
            max_gap = max(max_gap, dist)
    return max_gap


def process_route_file(
    input_path: Path,
    spacing_m: float,
    osrm_url: str,
    backup: bool = True,
) -> bool:
    """Process a single route file.

    Args:
        input_path: Path to the route JSON file.
        spacing_m: Target spacing in meters.
        osrm_url: OSRM server URL.
        backup: Whether to create a .bak backup file.

    Returns:
        True if successful, False otherwise.
    """
    print(f"Processing {input_path.name}...", file=sys.stderr)

    with open(input_path) as f:
        route = json.load(f)

    original_count = len(route["points"])
    original_stops = sum(1 for p in route["points"] if p.get("kind", "stop") == "stop")

    normalized = normalize_route(route, spacing_m, osrm_url)
    if normalized is None:
        return False

    new_count = len(normalized["points"])
    new_stops = sum(1 for p in normalized["points"] if p.get("kind", "stop") == "stop")
    max_gap = compute_max_gap(normalized["points"])

    # Verify stops are preserved
    if new_stops != original_stops:
        print(f"  Error: Stop count changed from {original_stops} to {new_stops}", file=sys.stderr)
        return False

    # Create backup
    if backup:
        backup_path = input_path.with_suffix(".json.bak")
        shutil.copy(input_path, backup_path)

    # Write normalized route
    with open(input_path, "w") as f:
        json.dump(normalized, f, indent=2)
        f.write("\n")

    print(f"  Points: {original_count} -> {new_count} ({new_stops} stops preserved)", file=sys.stderr)
    print(f"  Max waypoint gap: {max_gap:.1f}m", file=sys.stderr)

    return True


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Normalize route waypoints to consistent spacing using OSRM.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Process a single route
  python normalize_waypoints.py R102-AM.json --osrm-url http://localhost:5000

  # Process all routes with 20m spacing
  python normalize_waypoints.py --all --spacing 20 --osrm-url http://localhost:5000

  # Dry run (no changes)
  python normalize_waypoints.py --all --dry-run --osrm-url http://localhost:5000
        """,
    )
    parser.add_argument(
        "route_file",
        nargs="?",
        help="Single route JSON file to process",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Process all R*.json files in data/routes/",
    )
    parser.add_argument(
        "--spacing",
        type=float,
        default=20.0,
        help="Target spacing between waypoints in meters (default: 20)",
    )
    parser.add_argument(
        "--osrm-url",
        default="http://localhost:5000",
        help="OSRM server URL (default: http://localhost:5000)",
    )
    parser.add_argument(
        "--no-backup",
        action="store_true",
        help="Don't create .bak backup files",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show what would be done without making changes",
    )

    args = parser.parse_args()

    if not args.route_file and not args.all:
        parser.error("Either provide a route file or use --all")

    # Determine which files to process
    routes_dir = Path(__file__).parent.parent
    if args.all:
        route_files = sorted(routes_dir.glob("R*.json"))
    else:
        route_files = [Path(args.route_file)]
        if not route_files[0].is_absolute():
            route_files = [routes_dir / args.route_file]

    if not route_files:
        print("No route files found", file=sys.stderr)
        sys.exit(1)

    print(f"OSRM server: {args.osrm_url}", file=sys.stderr)
    print(f"Target spacing: {args.spacing}m", file=sys.stderr)
    print(f"Files to process: {len(route_files)}", file=sys.stderr)
    print("", file=sys.stderr)

    if args.dry_run:
        print("DRY RUN - no changes will be made", file=sys.stderr)
        print("", file=sys.stderr)

    success_count = 0
    for route_file in route_files:
        if not route_file.exists():
            print(f"File not found: {route_file}", file=sys.stderr)
            continue

        if args.dry_run:
            with open(route_file) as f:
                route = json.load(f)
            print(f"{route_file.name}: {len(route['points'])} points", file=sys.stderr)
            success_count += 1
        else:
            if process_route_file(route_file, args.spacing, args.osrm_url, backup=not args.no_backup):
                success_count += 1

    print("", file=sys.stderr)
    print(f"Processed {success_count}/{len(route_files)} files successfully", file=sys.stderr)

    if success_count < len(route_files):
        sys.exit(1)


if __name__ == "__main__":
    main()
