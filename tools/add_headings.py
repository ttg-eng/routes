#!/usr/bin/env python3
"""Add heading field to route points based on bearing to next point.

The heading represents the expected bus heading when approaching each point,
computed as the bearing from this point to the next point in sequence.
For the last point, uses bearing to the first point (circular routes).

This helps prevent snapping to the wrong instance of a stop on circular
routes where the same stop appears twice (outbound and return legs).
"""

import json
import math
import sys
from pathlib import Path


def calculate_bearing(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    """Calculate initial bearing from point 1 to point 2.

    Args:
        lat1: Latitude of first point in decimal degrees.
        lng1: Longitude of first point in decimal degrees.
        lat2: Latitude of second point in decimal degrees.
        lng2: Longitude of second point in decimal degrees.

    Returns:
        Bearing in degrees (0-360, where 0=North, 90=East).
    """
    lat1_r = math.radians(lat1)
    lat2_r = math.radians(lat2)
    dlng = math.radians(lng2 - lng1)

    x = math.sin(dlng) * math.cos(lat2_r)
    y = math.cos(lat1_r) * math.sin(lat2_r) - math.sin(lat1_r) * math.cos(
        lat2_r
    ) * math.cos(dlng)

    bearing = math.degrees(math.atan2(x, y))
    return round((bearing + 360) % 360, 1)


def add_headings_to_route(route_data: dict) -> dict:
    """Add heading field to each point in a route.

    Args:
        route_data: Route JSON data.

    Returns:
        Updated route data with headings added.
    """
    points = route_data["points"]
    num_points = len(points)

    if num_points < 2:
        return route_data

    for i, point in enumerate(points):
        # Get next point (wrap around to first for last point)
        next_idx = (i + 1) % num_points
        next_point = points[next_idx]

        heading = calculate_bearing(
            point["latitude"],
            point["longitude"],
            next_point["latitude"],
            next_point["longitude"],
        )
        point["heading"] = heading

    return route_data


def process_file(file_path: Path, dry_run: bool = False) -> int:
    """Process a single route JSON file.

    Args:
        file_path: Path to the route JSON file.
        dry_run: If True, don't write changes.

    Returns:
        Number of points updated.
    """
    with open(file_path) as f:
        route_data = json.load(f)

    updated = add_headings_to_route(route_data)
    num_points = len(updated["points"])

    if not dry_run:
        with open(file_path, "w") as f:
            json.dump(updated, f, indent=2)
            f.write("\n")

    return num_points


def main() -> None:
    """Process route files to add headings."""
    dry_run = "--dry-run" in sys.argv

    # Find route JSON files
    script_dir = Path(__file__).parent
    routes_dir = script_dir.parent
    route_files = [
        f for f in routes_dir.glob("*.json")
        if f.name != "schema.json"
    ]

    if not route_files:
        print("No route files found", file=sys.stderr)
        sys.exit(1)

    total_points = 0
    for file_path in sorted(route_files):
        try:
            num_points = process_file(file_path, dry_run)
            total_points += num_points
            action = "Would update" if dry_run else "Updated"
            print(f"{action} {file_path.name}: {num_points} points")
        except (json.JSONDecodeError, KeyError) as e:
            print(f"Error processing {file_path.name}: {e}", file=sys.stderr)
            sys.exit(1)

    action = "Would update" if dry_run else "Updated"
    print(f"\n{action} {len(route_files)} files with {total_points} total points")

    if dry_run:
        print("\nRun without --dry-run to apply changes")


if __name__ == "__main__":
    main()
