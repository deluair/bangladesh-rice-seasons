"""Build one national GeoTIFF per year from the per-tile predictions in <work>/predictions.

Each pixel is taken from exactly one tile (the tile whose lat/lon cell holds its centre),
so overlapping tile grids are not double counted. 255 = no data.

    uv run python scripts/build_mosaics.py --work work
"""
import argparse
from pathlib import Path

import rasterio
from rasterio.enums import Resampling
from rasterio.merge import merge

from ricemap.national import YEARS
from ricemap.tiles import own_cell_mask

ap = argparse.ArgumentParser()
ap.add_argument("--work", required=True)
W = Path(ap.parse_args().work)
tmp = W / "mosaic_tmp"
tmp.mkdir(exist_ok=True)

for yr in YEARS:
    srcs = []
    for tif in sorted((W / "predictions").glob(f"*_{yr}_rice_20m.tif")):
        tid = "_".join(tif.name.split("_")[:2])
        with rasterio.open(tif) as s:
            a = s.read(1)
            a[~own_cell_mask(tid, s.transform, s.shape)] = 255
            prof = s.profile | {"nodata": 255}
        out = tmp / tif.name
        with rasterio.open(out, "w", **prof) as d:
            d.write(a, 1)
        srcs.append(out)
    arr, tr = merge([str(p) for p in srcs], nodata=255, method="first")
    prof = {"driver": "GTiff", "dtype": "uint8", "count": 1, "width": arr.shape[2], "height": arr.shape[1],
            "crs": "EPSG:32646", "transform": tr, "nodata": 255, "compress": "deflate", "predictor": 2,
            "tiled": True, "blockxsize": 512, "blockysize": 512, "BIGTIFF": "IF_SAFER"}
    out = W / f"bangladesh_rice_seasons_{yr}_20m.tif"
    with rasterio.open(out, "w", **prof) as d:
        d.write(arr[0], 1)
        d.build_overviews([2, 4, 8, 16, 32], Resampling.nearest)
        d.update_tags(bits="1=Aus, 2=Aman, 4=Boro; 255=no data", crs="EPSG:32646", pixel="20 m")
    for p in srcs:
        p.unlink()
    print(f"{out}: {out.stat().st_size:,} bytes, shape {arr.shape[1:]}")
