"""Administrative unit aggregation module for district and upazila seasonal rice area.

Fetches geoBoundaries gbOpen ADM2 (districts) and ADM3 (upazilas), records the exact
license string, overlays administrative polygons with 20m prediction bitmasks in EPSG:32646,
and computes seasonal rice area (ha) based on true pixel area on the UTM grid (0.04 ha/pixel).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import rasterio
import requests
from pyproj import Transformer
from rasterio.features import rasterize
from shapely.geometry import box, shape
from shapely.ops import transform

GEOBOUNDARIES_API = {
    "ADM2": "https://www.geoboundaries.org/api/current/gbOpen/BGD/ADM2/",
    "ADM3": "https://www.geoboundaries.org/api/current/gbOpen/BGD/ADM3/",
}
PIXEL_AREA_HA = 0.04  # 20m x 20m UTM grid = 400 m2 = 0.04 ha


def fetch_admin_boundaries(
    level: str = "ADM2",
    cache_dir: str | Path = "data/geoboundaries",
    use_simplified: bool = True,
    force: bool = False,
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Fetch geoBoundaries metadata and GeoJSON for BGD ADM2 or ADM3.

    Records the license field exactly as returned by the API.
    Returns (geojson_dict, api_metadata_dict).
    """
    assert level in ("ADM2", "ADM3"), f"Unsupported level: {level}"
    cache_dir = Path(cache_dir)
    cache_dir.mkdir(parents=True, exist_ok=True)

    meta_file = cache_dir / f"BGD_{level}_meta.json"
    gj_file = cache_dir / f"BGD_{level}.geojson"

    if meta_file.exists() and gj_file.exists() and not force:
        with open(meta_file) as f:
            api_meta = json.load(f)
        with open(gj_file) as f:
            gj = json.load(f)
        return gj, api_meta

    print(f"Fetching geoBoundaries {level} metadata from {GEOBOUNDARIES_API[level]}...")
    resp = requests.get(GEOBOUNDARIES_API[level], timeout=30)
    resp.raise_for_status()
    api_meta = resp.json()

    # Exact license string as returned by the API
    license_str = api_meta.get("boundaryLicense", "Unknown")
    print(f"geoBoundaries {level} License: '{license_str}'")

    download_url = (
        api_meta["simplifiedGeometryGeoJSON"]
        if use_simplified and "simplifiedGeometryGeoJSON" in api_meta
        else api_meta["gjDownloadURL"]
    )
    print(f"Downloading GeoJSON from {download_url}...")
    gj_resp = requests.get(download_url, timeout=60)
    gj_resp.raise_for_status()
    gj = gj_resp.json()

    with open(meta_file, "w") as f:
        json.dump(api_meta, f, indent=2)
    with open(gj_file, "w") as f:
        json.dump(gj, f, indent=2)

    return gj, api_meta


def aggregate_rice_area_by_admin(
    pred_tifs: list[str | Path],
    admin_level: str = "ADM2",
    year: int = 2023,
    cache_dir: str | Path = "data/geoboundaries",
    out_csv: str | Path | None = None,
) -> pd.DataFrame:
    """Aggregate predicted seasonal rice area by administrative unit.

    Overlays each 20m uint8 classification GeoTIFF with reprojected administrative polygons.
    Computes area in hectares using true pixel area on UTM grid (0.04 ha/pixel).
    """
    gj, api_meta = fetch_admin_boundaries(level=admin_level, cache_dir=cache_dir)
    license_field = api_meta.get("boundaryLicense", "")

    wgs84_to_utm = Transformer.from_crs("EPSG:4326", "EPSG:32646", always_xy=True).transform

    # Prepare features and reproject geometries to EPSG:32646
    admin_units = []
    for feat in gj["features"]:
        props = feat["properties"]
        geom_wgs = shape(feat["geometry"])
        geom_utm = transform(wgs84_to_utm, geom_wgs)
        admin_units.append({
            "shapeID": props.get("shapeID", ""),
            "shapeName": props.get("shapeName", ""),
            "shapeGroup": props.get("shapeGroup", "BGD"),
            "shapeType": props.get("shapeType", admin_level),
            "geometry_utm": geom_utm,
            "bounds_utm": geom_utm.bounds,
        })

    # Accumulators for pixel counts
    counts: dict[str, dict[str, int]] = {
        u["shapeID"]: {"Aus": 0, "Aman": 0, "Boro": 0, "any_rice": 0, "total_pixels": 0}
        for u in admin_units
    }

    for tif_p in pred_tifs:
        tif_p = Path(tif_p)
        assert tif_p.exists(), f"Prediction file not found: {tif_p}"

        with rasterio.open(tif_p) as src:
            data = src.read(1)
            t_bounds = src.bounds
            tile_box = box(t_bounds.left, t_bounds.bottom, t_bounds.right, t_bounds.top)
            t_transform = src.transform
            t_shape = src.shape

            # Unpack bitmask:
            # bit 1 = Aus, bit 2 = Aman, bit 4 = Boro
            aus_mask = (data & 1) > 0
            aman_mask = (data & 2) > 0
            boro_mask = (data & 4) > 0
            any_mask = data > 0

            # Find overlapping admin units
            for u in admin_units:
                geom_utm = u["geometry_utm"]
                if not tile_box.intersects(geom_utm):
                    continue

                # Clip geometry to tile box
                clipped_geom = geom_utm.intersection(tile_box)
                if clipped_geom.is_empty:
                    continue

                # Rasterize polygon into tile grid
                poly_mask = rasterize(
                    [(clipped_geom, 1)],
                    out_shape=t_shape,
                    transform=t_transform,
                    fill=0,
                    dtype=np.uint8,
                ) == 1

                n_poly_pix = int(poly_mask.sum())
                if n_poly_pix == 0:
                    continue

                sid = u["shapeID"]
                counts[sid]["total_pixels"] += n_poly_pix
                counts[sid]["Aus"] += int((poly_mask & aus_mask).sum())
                counts[sid]["Aman"] += int((poly_mask & aman_mask).sum())
                counts[sid]["Boro"] += int((poly_mask & boro_mask).sum())
                counts[sid]["any_rice"] += int((poly_mask & any_mask).sum())

    # Build results table
    rows = []
    for u in admin_units:
        sid = u["shapeID"]
        c = counts[sid]
        # Only include units that have some pixels in the processed area, or include all with 0
        rows.append({
            "admin_level": admin_level,
            "shape_id": sid,
            "unit_name": u["shapeName"],
            "year": year,
            "pixel_count_total": c["total_pixels"],
            "aus_pixels": c["Aus"],
            "aman_pixels": c["Aman"],
            "boro_pixels": c["Boro"],
            "any_rice_pixels": c["any_rice"],
            "aus_area_ha": round(c["Aus"] * PIXEL_AREA_HA, 2),
            "aman_area_ha": round(c["Aman"] * PIXEL_AREA_HA, 2),
            "boro_area_ha": round(c["Boro"] * PIXEL_AREA_HA, 2),
            "any_rice_area_ha": round(c["any_rice"] * PIXEL_AREA_HA, 2),
            "license": license_field,
        })

    df = pd.DataFrame(rows)
    # Sort by unit name
    df.sort_values(by=["unit_name"], inplace=True)

    if out_csv:
        out_p = Path(out_csv)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        df.to_csv(out_p, index=False)
        print(f"Saved {admin_level} aggregated rice area to {out_p}")

    return df
