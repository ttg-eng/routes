#!/usr/bin/env python3
"""Convert route JSON to GeoJSON for editing in geojson.io."""

import json
import sys
from pathlib import Path

# Marker colors for geojson.io visualization
STOP_COLOR = "#ff0000"  # Red for stops
WAYPOINT_COLOR = "#0000ff"  # Blue for waypoints


def route_to_geojson(route: dict) -> dict:
    """Convert route JSON to GeoJSON FeatureCollection.

    Args:
        route: Route data in the native JSON format.

    Returns:
        GeoJSON FeatureCollection with Point features for each route point
        and a LineString feature for route visualization.
    """
    features = []
    line_coordinates = []

    # Convert each point to a GeoJSON Point feature
    for point in route["points"]:
        lon = point["longitude"]
        lat = point["latitude"]
        kind = point.get("kind", "stop")

        feature = {
            "type": "Feature",
            "properties": {
                "id": point["id"],
                "name": point["name"],
                "kind": kind,
                "marker-color": STOP_COLOR if kind == "stop" else WAYPOINT_COLOR,
            },
            "geometry": {
                "type": "Point",
                "coordinates": [lon, lat],
            },
        }
        features.append(feature)
        line_coordinates.append([lon, lat])

    # Add LineString feature for route visualization
    line_feature = {
        "type": "Feature",
        "properties": {
            "stroke": route.get("color", "#000000"),
            "stroke-width": 3,
            "stroke-opacity": 0.8,
        },
        "geometry": {
            "type": "LineString",
            "coordinates": line_coordinates,
        },
    }
    features.append(line_feature)

    # Build FeatureCollection with route metadata
    return {
        "type": "FeatureCollection",
        "properties": {
            "id": route["id"],
            "route_number": route["route_number"],
            "name": route["name"],
            "area": route["area"],
            "time_period": route["time_period"],
            "color": route.get("color", "#000000"),
        },
        "features": features,
    }


def main() -> None:
    """Read route JSON and output GeoJSON."""
    if len(sys.argv) < 2:
        print("Usage: python route_to_geojson.py <route.json> [output.geojson]", file=sys.stderr)
        print("Output: GeoJSON to file or stdout", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path) as f:
        route = json.load(f)

    geojson = route_to_geojson(route)
    output = json.dumps(geojson, indent=2)

    # Write to file or stdout
    if len(sys.argv) >= 3:
        output_path = Path(sys.argv[2])
        with open(output_path, "w") as f:
            f.write(output)
            f.write("\n")
        print(f"Wrote {output_path}", file=sys.stderr)
        print("", file=sys.stderr)
        print("Next steps:", file=sys.stderr)
        print("  1. Open https://geojson.io", file=sys.stderr)
        print(f"  2. Drag and drop {output_path} onto the map", file=sys.stderr)
        print("  3. Edit points visually (red=stops, blue=waypoints)", file=sys.stderr)
        print("  4. Save -> GeoJSON to download edited file", file=sys.stderr)
        print(f"  5. Run: python geojson_to_route.py <edited.geojson> {input_path}", file=sys.stderr)
    else:
        print(output)


if __name__ == "__main__":
    main()
