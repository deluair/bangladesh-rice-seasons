"""Grid tiling module for bangladesh-rice-seasons.

Partitions Bangladesh land area into regular 0.2 deg x 0.2 deg geographic tiles
and maps each tile to the national standard projected coordinate system
(EPSG:32646, UTM Zone 46N) at 20-meter resolution.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.transform import from_bounds
from rasterio.warp import transform_bounds
from rasterio.windows import from_bounds as win_from_bounds

GRID_RESOLUTION_DEG = 0.2
TARGET_CRS = "EPSG:32646"
TARGET_RES_M = 20.0
# Bounding box encompassing all Bangladesh territory
BANGLADESH_BBOX = [88.0, 20.6, 92.8, 26.8]


@dataclass
class Tile:
    tile_id: str
    min_lon: float
    min_lat: float
    max_lon: float
    max_lat: float
    boro_pixels: int = 0
    total_pixels_10m: int = 0

    @property
    def bbox(self) -> list[float]:
        return [self.min_lon, self.min_lat, self.max_lon, self.max_lat]

    def get_utm_grid(
        self, target_crs: str = TARGET_CRS, res: float = TARGET_RES_M
    ) -> dict[str, Any]:
        """Compute snapped UTM grid bounds, shape, and affine transform."""
        tb = transform_bounds("EPSG:4326", target_crs, self.min_lon, self.min_lat, self.max_lon, self.max_lat)
        minx = float(np.floor(tb[0] / res) * res)
        miny = float(np.floor(tb[1] / res) * res)
        maxx = float(np.ceil(tb[2] / res) * res)
        maxy = float(np.ceil(tb[3] / res) * res)
        width = round((maxx - minx) / res)
        height = round((maxy - miny) / res)
        transform = from_bounds(minx, miny, maxx, maxy, width, height)
        return {
            "crs": target_crs,
            "minx": minx,
            "miny": miny,
            "maxx": maxx,
            "maxy": maxy,
            "width": width,
            "height": height,
            "transform": transform,
            "res": res,
            "pixel_area_ha": (res * res) / 10000.0,  # 400 m2 = 0.04 ha
            "total_pixels": width * height,
        }


def make_tile_id(min_lon: float, min_lat: float) -> str:
    return f"{min_lon:.1f}_{min_lat:.1f}"


def parse_tile_id(tile_id: str) -> tuple[float, float, float, float]:
    parts = tile_id.replace("tile_", "").split("_")
    min_lon = float(parts[0])
    min_lat = float(parts[1])
    return (
        round(min_lon, 4),
        round(min_lat, 4),
        round(min_lon + GRID_RESOLUTION_DEG, 4),
        round(min_lat + GRID_RESOLUTION_DEG, 4),
    )


def generate_national_grid(
    boro_label_path: str | Path | None = None,
    out_json: str | Path | None = None,
) -> list[Tile]:
    """Scan Bangladesh territory and identify all 0.2 deg tiles.

    If boro_label_path is given, filters to tiles with >0 rice pixels,
    reproducing the 408 tiles identified in the pilot report.
    """
    min_lon, min_lat, max_lon, max_lat = BANGLADESH_BBOX
    lon_bins = np.arange(min_lon, max_lon + 1e-6, GRID_RESOLUTION_DEG)
    lat_bins = np.arange(min_lat, max_lat + 1e-6, GRID_RESOLUTION_DEG)

    tiles: list[Tile] = []

    if boro_label_path and Path(boro_label_path).exists():
        with rasterio.open(boro_label_path) as src:
            for lon in lon_bins:
                for lat in lat_bins:
                    w = win_from_bounds(lon, lat, lon + GRID_RESOLUTION_DEG, lat + GRID_RESOLUTION_DEG, src.transform)
                    try:
                        w_clipped = w.intersection(rasterio.windows.Window(0, 0, src.width, src.height))
                    except rasterio.errors.WindowError:
                        continue
                    if w_clipped.width <= 0 or w_clipped.height <= 0:
                        continue
                    w_int = w_clipped.round_offsets()
                    data = src.read(1, window=w_int)
                    boro_pixels = int((data == 100).sum())
                    if boro_pixels > 0:
                        t = Tile(
                            tile_id=make_tile_id(lon, lat),
                            min_lon=round(float(lon), 4),
                            min_lat=round(float(lat), 4),
                            max_lon=round(float(lon + GRID_RESOLUTION_DEG), 4),
                            max_lat=round(float(lat + GRID_RESOLUTION_DEG), 4),
                            boro_pixels=boro_pixels,
                            total_pixels_10m=int(data.size),
                        )
                        tiles.append(t)
    else:
        for lon in lon_bins:
            for lat in lat_bins:
                t = Tile(
                    tile_id=make_tile_id(lon, lat),
                    min_lon=round(float(lon), 4),
                    min_lat=round(float(lat), 4),
                    max_lon=round(float(lon + GRID_RESOLUTION_DEG), 4),
                    max_lat=round(float(lat + GRID_RESOLUTION_DEG), 4),
                )
                tiles.append(t)

    tiles.sort(key=lambda t: t.boro_pixels, reverse=True)

    if out_json:
        out_p = Path(out_json)
        out_p.parent.mkdir(parents=True, exist_ok=True)
        with open(out_p, "w") as f:
            json.dump([asdict(t) for t in tiles], f, indent=2)

    return tiles


def get_tile_by_id(tile_id: str) -> Tile:
    min_lon, min_lat, max_lon, max_lat = parse_tile_id(tile_id)
    return Tile(
        tile_id=make_tile_id(min_lon, min_lat),
        min_lon=min_lon,
        min_lat=min_lat,
        max_lon=max_lon,
        max_lat=max_lat,
    )
