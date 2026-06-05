#!/usr/bin/env python3
"""
Add a shapefile (.zip) to the fdensemble map library.

Usage:
    uv run python scripts/add_map.py path/to/districts.zip --label "Proposed Senate Map 2026"
    uv run python scripts/add_map.py path/to/districts.zip  # uses filename as label

The map is saved to uploaded_maps/ and immediately available in the Score a Map tab
without restarting the server (the API reads from disk on each request).

If the server is running locally, you can also use the web UI's "Add map" button.
"""

import argparse
import json
import re
import uuid
from datetime import datetime
from pathlib import Path


def slugify(label: str) -> str:
    slug = ''.join(c if c.isalnum() else '_' for c in label.lower())
    slug = '_'.join(p for p in slug.split('_') if p)[:32]
    return (slug or 'map') + '_' + uuid.uuid4().hex[:6]


def parse_shapefile_zip(zip_path: Path) -> dict:
    """Parse a zipped shapefile into a GeoJSON FeatureCollection."""
    try:
        import geopandas as gpd
    except ImportError:
        raise SystemExit(
            'geopandas is required: run  uv sync  or  pip install geopandas pyogrio'
        )

    gdf = gpd.read_file(f'zip://{zip_path}')

    # Keep only geometry — drop large attribute columns
    gdf = gdf[['geometry']].copy()
    gdf = gdf[gdf.geometry.notna() & ~gdf.geometry.is_empty]

    if len(gdf) == 0:
        raise ValueError('No valid geometries found in shapefile')

    # Ensure WGS-84
    if gdf.crs and gdf.crs.to_epsg() != 4326:
        gdf = gdf.to_crs(epsg=4326)

    geojson = json.loads(gdf.to_json())
    print(f'  Parsed {len(gdf)} districts from {zip_path.name}')
    return geojson


def main():
    parser = argparse.ArgumentParser(description='Add a shapefile to the fdensemble map library')
    parser.add_argument('shapefile', type=Path, help='Path to shapefile .zip')
    parser.add_argument('--label',   default='', help='Human-readable map name')
    parser.add_argument('--maps-dir', default='uploaded_maps', help='Map library directory (default: uploaded_maps)')
    args = parser.parse_args()

    zip_path = args.shapefile.resolve()
    if not zip_path.exists():
        raise SystemExit(f'File not found: {zip_path}')
    if zip_path.suffix.lower() != '.zip':
        raise SystemExit('Expected a .zip file (zipped shapefile)')

    label    = args.label or zip_path.stem.replace('_', ' ').replace('-', ' ').title()
    maps_dir = Path(args.maps_dir)

    print(f'Parsing {zip_path.name}...')
    geojson = parse_shapefile_zip(zip_path)

    map_id   = slugify(label)
    maps_dir.mkdir(parents=True, exist_ok=True)
    geojson_path = maps_dir / f'{map_id}.geojson'
    geojson_path.write_text(json.dumps(geojson))

    # Update catalog.json
    catalog_path = maps_dir / 'catalog.json'
    catalog = json.loads(catalog_path.read_text()) if catalog_path.exists() else []
    meta = {
        'id':          map_id,
        'label':       label,
        'n_districts': len(geojson.get('features', [])),
        'created':     datetime.now().strftime('%Y-%m-%d'),
    }
    catalog.append(meta)
    catalog_path.write_text(json.dumps(catalog, indent=2))

    print(f'  Saved  → {geojson_path}')
    print(f'  ID     : {map_id}')
    print(f'  Label  : {label}')
    print(f'  Maps in library: {len(catalog)}')
    print()
    print('The map is now available in the "Score a Map" tab.')
    print('If the server is already running it will appear immediately (no restart needed).')


if __name__ == '__main__':
    main()
