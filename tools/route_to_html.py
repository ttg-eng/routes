#!/usr/bin/env python3
"""Generate a static HTML map viewer for a route using Leaflet + OSM tiles."""

import html
import json
import sys
import tempfile
import webbrowser
from pathlib import Path

HTML_TEMPLATE = """<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{title}</title>
  <link rel="stylesheet" href="https://unpkg.com/leaflet@1.9.4/dist/leaflet.css" />
  <style>
    body {{ margin: 0; padding: 0; }}
    #map {{ position: absolute; top: 0; bottom: 0; width: 100%; }}
    .stop-marker {{
      background: #ff0000;
      border: 2px solid #fff;
      border-radius: 50%;
      width: 12px;
      height: 12px;
    }}
    .waypoint-marker {{
      background: #0066ff;
      border: 1px solid #fff;
      border-radius: 50%;
      width: 6px;
      height: 6px;
    }}
    .stop-number-marker {{
      background: transparent;
    }}
    .stop-number {{
      background: #ff0000;
      color: #fff;
      border: 2px solid #fff;
      border-radius: 50%;
      width: 24px;
      height: 24px;
      display: flex;
      align-items: center;
      justify-content: center;
      font-family: sans-serif;
      font-size: 11px;
      font-weight: bold;
      box-shadow: 0 1px 3px rgba(0,0,0,0.3);
    }}
    .legend {{
      background: white;
      padding: 10px;
      border-radius: 5px;
      box-shadow: 0 1px 5px rgba(0,0,0,0.3);
      font-family: sans-serif;
      font-size: 12px;
    }}
    .legend-item {{
      display: flex;
      align-items: center;
      margin: 4px 0;
    }}
    .legend-marker {{
      width: 12px;
      height: 12px;
      border-radius: 50%;
      margin-right: 8px;
    }}
  </style>
</head>
<body>
  <div id="map"></div>
  <script src="https://unpkg.com/leaflet@1.9.4/dist/leaflet.js"></script>
  <script>
    const routeData = {route_json};

    const map = L.map('map');

    L.tileLayer('https://{{s}}.tile.openstreetmap.org/{{z}}/{{x}}/{{y}}.png', {{
      attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors'
    }}).addTo(map);

    // Draw route line
    const lineCoords = routeData.points.map(p => [p.latitude, p.longitude]);
    const routeLine = L.polyline(lineCoords, {{
      color: routeData.color || '#0066ff',
      weight: 4,
      opacity: 0.8
    }}).addTo(map);

    // Add markers for each point
    let stopNumber = 0;
    routeData.points.forEach((point, idx) => {{
      const isStop = point.kind === 'stop';

      if (isStop) {{
        stopNumber++;
        // Numbered marker for stops
        const icon = L.divIcon({{
          className: 'stop-number-marker',
          html: '<div class="stop-number">' + stopNumber + '</div>',
          iconSize: [24, 24],
          iconAnchor: [12, 12]
        }});
        const marker = L.marker([point.latitude, point.longitude], {{ icon }}).addTo(map);
        marker.bindPopup('<strong>' + stopNumber + '. ' + point.name + '</strong>');
      }} else {{
        // Small dot for waypoints
        const marker = L.circleMarker([point.latitude, point.longitude], {{
          radius: 4,
          fillColor: '#0066ff',
          color: '#fff',
          weight: 1,
          fillOpacity: 0.9
        }}).addTo(map);
      }}
    }});

    // Fit map to route bounds
    map.fitBounds(routeLine.getBounds(), {{ padding: [20, 20] }});

    // Add legend
    const legend = L.control({{ position: 'bottomright' }});
    legend.onAdd = function() {{
      const div = L.DomUtil.create('div', 'legend');
      div.innerHTML = `
        <div class="legend-item">
          <div class="legend-marker" style="background:#ff0000;border:2px solid #fff;color:#fff;font-size:9px;font-weight:bold;display:flex;align-items:center;justify-content:center;">1</div>
          <span>Bus Stop</span>
        </div>
        <div class="legend-item">
          <div class="legend-marker" style="background:#0066ff;width:8px;height:8px;border:1px solid #fff;"></div>
          <span>Waypoint</span>
        </div>
      `;
      return div;
    }};
    legend.addTo(map);
  </script>
</body>
</html>
"""


def route_to_html(route: dict) -> str:
    """Generate HTML map viewer for a route.

    Args:
        route: Route data in the native JSON format.

    Returns:
        Complete HTML document as a string.
    """
    title = f"Route {route['route_number']} - {route['name']}"
    route_json = json.dumps(route)

    return HTML_TEMPLATE.format(
        title=html.escape(title),
        route_json=route_json,
    )


def main() -> None:
    """Read route JSON and open map in browser."""
    if len(sys.argv) < 2:
        print("Usage: python route_to_html.py <route.json>", file=sys.stderr)
        print("Opens an interactive map in your default browser.", file=sys.stderr)
        sys.exit(1)

    input_path = Path(sys.argv[1])
    if not input_path.exists():
        print(f"Error: File not found: {input_path}", file=sys.stderr)
        sys.exit(1)

    with open(input_path) as f:
        route = json.load(f)

    html_content = route_to_html(route)

    # Write to temp file and open in browser
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".html", delete=False
    ) as f:
        f.write(html_content)
        temp_path = f.name

    print(f"Opening Route {route['route_number']} in browser...", file=sys.stderr)
    webbrowser.open(f"file://{temp_path}")


if __name__ == "__main__":
    main()
