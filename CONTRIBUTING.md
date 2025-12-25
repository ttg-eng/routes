# Contributing Bus Route Data

Thank you for helping improve the Davao City HPB route data!

## How to Contribute

1. **Fork this repository** and create a branch for your changes

2. **Edit the route JSON files**:
   - Each file represents one route (e.g., `R102-AM.json`)
   - You can correct stop names, coordinates, or add missing stops

3. **Validate your changes** before submitting:
   ```bash
   # Install jq if you don't have it
   brew install jq  # macOS

   # Validate JSON syntax
   jq . R102-AM.json > /dev/null && echo "Valid JSON"
   ```

4. **Create a Pull Request** with a clear description of what you changed and why

## What You Can Change

- **Stop names**: Correct misspellings or use the actual signage name
- **Stop coordinates**: Fix incorrect latitude/longitude values
- **Add missing stops**: Insert new stops in the correct sequence position
- **Route names**: Correct route name descriptions

## What You CANNOT Change

- **Route IDs** (`"id": "..."` at the top level)
- **Stop IDs** (`"id": "..."` for each stop)

These UUIDs are permanent identifiers used by the system. Changing them will cause your PR to be rejected automatically.

## Adding a New Stop

To add a stop, insert a new entry in the `"stops"` array at the correct position. You'll need to generate a new UUID7:

```bash
# Using Python (if you have typeid-python installed)
python -c "from typeid import TypeID; print(TypeID(prefix='bstop').uuid)"

# Or use an online UUID7 generator
```

Example new stop:
```json
{
  "id": "YOUR-NEW-UUID7-HERE",
  "name": "New Stop Name",
  "latitude": 7.05,
  "longitude": 125.55
}
```

## Coordinate Guidelines

- Use at least 6 decimal places for accuracy
- Verify coordinates using Google Maps or OpenStreetMap
- Davao City coordinates should be in these ranges:
  - Latitude: 6.9 to 7.2
  - Longitude: 125.4 to 125.7
- Test your coordinates: `https://maps.google.com/?q={latitude},{longitude}`

## File Naming

Files are named `{route_number}-{time_period}.json`:
- `R102-AM.json` = Route 102, morning service
- `R102-PM.json` = Route 102, afternoon service

## Getting Help

If you're unsure about something, open an issue to discuss before making changes.
