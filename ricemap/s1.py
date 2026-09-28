"""Sentinel-1 data access module for Microsoft Planetary Computer.

Uses anonymous SAS signing and fetches Radiometric Terrain Corrected (RTC)
Cloud-Optimized GeoTIFFs (sentinel-1-rtc).
Reads 20m overviews (average-resampling in linear power before dB conversion)
and reprojects to EPSG:32646 target grid.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np
import planetary_computer as pc
import pystac_client
import rasterio
from rasterio.transform import Affine
from rasterio.warp import Resampling, reproject, transform_bounds
from rasterio.windows import Window
from rasterio.windows import from_bounds as win_from_bounds

STAC_API_URL = "https://planetarycomputer.microsoft.com/api/stac/v1"
COLLECTION_ID = "sentinel-1-rtc"


def query_s1_scenes(
    bbox: list[float],
    year: int,
    collection: str = COLLECTION_ID,
    stac_url: str = STAC_API_URL,
) -> list[Any]:
    """Query Planetary Computer STAC for Sentinel-1 scenes covering bbox in a year."""
    start_date = f"{year}-01-01"
    end_date = f"{year}-12-31"
    datetime_range = f"{start_date}/{end_date}"

    catalog = pystac_client.Client.open(stac_url)
    search = catalog.search(
        collections=[collection],
        bbox=bbox,
        datetime=datetime_range,
    )
    items = list(search.items())
    # Sort chronologically
    items.sort(key=lambda it: it.datetime)
    return items


def fetch_s1_band_20m(
    item: Any,
    band: str,
    dst_crs: str,
    dst_transform: Affine,
    dst_width: int,
    dst_height: int,
    bbox: list[float],
    max_retries: int = 3,
) -> np.ndarray | None:
    """Fetch window from S1 RTC COG at ~20m overview, convert to dB, and reproject.

    Per decided design:
    - Reads S-1 at 20 m using COG overview with Resampling.average in linear power.
    - Clamps minimum linear power to 1e-5 (-50 dB).
    - Converts to dB scale: 10 * log10(power).
    - Reprojects to target grid in dst_crs at 20 m using bilinear resampling.
    """
    if band not in item.assets:
        return None

    signed = pc.sign(item)
    url = signed.assets[band].href

    for attempt in range(max_retries):
        try:
            with rasterio.Env(
                GDAL_DISABLE_READDIR_ON_OPEN="EMPTY_DIR",
                CPL_VSIL_CURL_ALLOWED_EXTENSIONS=".tiff,.tif",
                GDAL_HTTP_TIMEOUT="30",
                GDAL_HTTP_MAX_RETRY="3",
            ), rasterio.open(url) as src:
                src_bounds = transform_bounds("EPSG:4326", src.crs, bbox[0], bbox[1], bbox[2], bbox[3])
                src_win = win_from_bounds(*src_bounds, src.transform)
                src_win_clipped = src_win.intersection(Window(0, 0, src.width, src.height))

                if src_win_clipped.width <= 0 or src_win_clipped.height <= 0:
                    return None

                # Compute 20m overview dimensions (~half resolution from native 10m)
                out_h = max(1, round(src_win_clipped.height / 2))
                out_w = max(1, round(src_win_clipped.width / 2))

                # Read linear power from 20m overview with average resampling
                raw_linear = src.read(
                    1,
                    window=src_win_clipped,
                    out_shape=(out_h, out_w),
                    resampling=Resampling.average,
                )

                # Filter valid non-negative values and convert to dB
                valid_src = np.isfinite(raw_linear) & (raw_linear > 0)
                db_data = np.full((out_h, out_w), np.nan, dtype=np.float32)
                clamped = np.maximum(raw_linear[valid_src], 1e-5)
                db_data[valid_src] = 10.0 * np.log10(clamped)

                # Window affine transform scaled for overview
                win_trans = rasterio.windows.transform(src_win_clipped, src.transform)
                scaled_trans = win_trans * win_trans.scale(
                    src_win_clipped.width / out_w,
                    src_win_clipped.height / out_h,
                )

                # Reproject to target grid
                dst_arr = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
                reproject(
                    source=db_data,
                    destination=dst_arr,
                    src_transform=scaled_trans,
                    src_crs=src.crs,
                    dst_transform=dst_transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.bilinear,
                    src_nodata=np.nan,
                    dst_nodata=np.nan,
                )
                return dst_arr

        except Exception as e:  # noqa: BLE001
            if attempt < max_retries - 1:
                time.sleep(1.5 * (attempt + 1))
            else:
                print(f"[WARN] Failed to fetch {item.id} {band} after {max_retries} attempts: {e}")
                return None
    return None
