#!/usr/bin/env python3
"""Convert GeoJSON back to route JSON after editing in geojson.io."""

import json
import sys
import uuid
from pathlib import Path

# Davao City coordinate bounds
LAT_MIN, LAT_MAX = 6.9, 7.2
LON_MIN, LON_MAX = 125.4, 125.7


def generate_uuid7() -> str:
    """Generate a UUID7-like identifier.

    Uses UUID4 as a fallback since UUID7 requires external libraries.
    The format matches what the system expects.
    """
    return str(uuid.uuid4())


def validate_coordinates(lon: float, lat: float, name: str) -> None:
    """Validate coordinates are within Davao City bounds.

    Args:
        lon: Longitude value.
        lat: Latitude value.
        name: Point name for error messages.

    Raises:
        ValueError: If coordinates are outside bounds.
    """
    if not (LAT_MIN <= lat <= LAT_MAX):
        raise ValueError(
            f"Latitude {lat} for '{name}' is outside Davao bounds ({LAT_MIN}-{LAT_MAX})"
        )
    if not (LON_MIN <= lon <= LON_MAX):
        raise ValueError(
            f"Longitude {lon} for '{name}' is outside Davao bounds ({LON_MIN}-{LON_MAX})"
        )


def geojson_to_route(geojson: dict) -> dict:
    """Convert GeoJSON FeatureCollection back to route JSON.

    Args:
        geojson: GeoJSON FeatureCollection from geojson.io.

    Returns:
        Route data in the native JSON format.

    Raises:
        ValueError: If coordinates are invalid or required properties missing.
    """
    # Extract route metadata from FeatureCollection properties
    props = geojson.get("properties", {})
    if not props.get("id"):
        raise ValueError("Missing route id in FeatureCollection properties")

    route = {
        "id": props["id"],
        "route_number": props["route_number"],
        "name": props["name"],
        "area": props["area"],
        "time_period": props["time_period"],
        "color": props.get("color", "#000000"),
        "points": [],
    }

    # Convert Point features back to route points
    for feature in geojson["features"]:
        geom = feature["geometry"]

        # Skip LineString features (they're just for visualization)
        if geom["type"] != "Point":
            continue

        fp = feature.get("properties", {})
        coords = geom["coordinates"]
        lon, lat = coords[0], coords[1]

        # Validate coordinates
        name = fp.get("name", "")
        validate_coordinates(lon, lat, name or "(unnamed)")

        # Generate new ID if missing (new point added in geojson.io)
        point_id = fp.get("id")
        if not point_id:
            point_id = generate_uuid7()
            print(f"Generated new ID for point: {name or '(waypoint)'}", file=sys.stderr)

        point = {
            "id": point_id,
            "name": name,
            "latitude": lat,
            "longitude": lon,
            "kind": fp.get("kind", "stop"),
        }
        route["points"].append(point)

    if len(route["points"]) < 2:
        raise ValueError("Route must have at least 2 points")

    return route


def main() -> None:
    """Read GeoJSON and output route JSON."""
    if len(sys.argv) < 2:
        print("Usage: python geojson_to_route.py <route.geojson> [output.json]", file=sys.stderr)
        print("Output: Route JSON to file or stdout", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path) as f:
        geojson = json.load(f)

    try:
        route = geojson_to_route(geojson)
    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)

    output = json.dumps(route, indent=2)

    # Write to file or stdout
    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
        with open(output_path, "w") as f:
            f.write(output)
            f.write("\n")
        print(f"Wrote {len(route['points'])} points to {output_path}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Next steps:", file=sys.stderr)
        print(f"  1. Review changes: git diff {output_path}", file=sys.stderr)
        print(f"  2. Validate: python -m json.tool {output_path} > /dev/null", file=sys.stderr)
        print(f"  3. Commit: git add {output_path} && git commit", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
