"""Label extraction and resampling module for Singha et al. (2019) 2017 consensus rasters.

Resamples 10m seasonal rasters (Aus, Aman, Boro) to the 20m EPSG:32646 UTM grid
as the area fraction of rice pixels.
A 20m pixel is classified positive if fraction >= 0.5.
Records the count and share of ambiguous pixels (fraction in [0.25, 0.75]).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
from rasterio.warp import Resampling, reproject
from rasterio.windows import from_bounds as win_from_bounds

from ricemap.tiles import Tile

SEASONS = ["Aus", "Aman", "Boro"]


def extract_tile_labels(
    tile: Tile,
    labels_dir: str | Path,
    out_dir: str | Path | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Extract and resample 2017 seasonal rice labels for a tile to 20m UTM grid.

    Returns a dictionary containing:
      - labels: uint8 array of shape [pixels, 3] (0=Aus, 1=Aman, 2=Boro)
      - fractions: float32 array of shape [pixels, 3] with exact fractions in [0, 1]
      - ambiguous_counts: dict of counts per season where fraction in [0.25, 0.75]
      - ambiguous_shares: dict of fractions per season
      - positive_counts: dict of counts where fraction >= 0.5
      - positive_shares: dict of positive rates
    """
    labels_dir = Path(labels_dir)
    grid = tile.get_utm_grid()
    dst_crs = grid["crs"]
    dst_transform = grid["transform"]
    dst_width = grid["width"]
    dst_height = grid["height"]
    total_pixels = grid["total_pixels"]

    out_npz = None
    if out_dir:
        out_p = Path(out_dir)
        out_p.mkdir(parents=True, exist_ok=True)
        out_npz = out_p / f"{tile.tile_id}_labels_2017.npz"
        if out_npz.exists() and not force:
            try:
                with np.load(out_npz) as npz:
                    meta = json.loads(str(npz["metadata"]))
                    return {
                        "labels": npz["labels"],
                        "valid": npz["valid"],
                        "fractions": npz["fractions"],
                        "ambiguous_counts": meta["ambiguous_counts"],
                        "ambiguous_shares": meta["ambiguous_shares"],
                        "positive_counts": meta["positive_counts"],
                        "positive_shares": meta["positive_shares"],
                        "npz_path": str(out_npz),
                    }
            except Exception as e:  # noqa: BLE001
                print(f"[WARN] Error reading cached {out_npz}: {e}. Recomputing...")

    fractions_list = []
    binary_list = []
    valid_mask = None
    ambiguous_counts = {}
    ambiguous_shares = {}
    positive_counts = {}
    positive_shares = {}

    for season in SEASONS:
        label_file = labels_dir / f"{season}_BGD_2017_V1.tif"
        assert label_file.exists(), f"Label file not found: {label_file}"

        with rasterio.open(label_file) as src:
            # Read window covering tile bbox with 1 pixel margin to avoid edge artifacts
            src_win = win_from_bounds(*tile.bbox, src.transform).round_offsets()
            src_data = src.read(1, window=src_win)
            win_transform = rasterio.windows.transform(src_win, src.transform)

            # Map values: 100 -> 1.0 (rice), 0 -> 0.0 (non-rice), nodata -> NaN
            nodata = src.nodata if src.nodata is not None else -128
            binary_10m = np.where(
                src_data == 100,
                1.0,
                np.where(src_data == nodata, np.nan, 0.0),
            ).astype(np.float32)

            # Resample to 20m UTM grid using average resampling
            dst_frac = np.full((dst_height, dst_width), np.nan, dtype=np.float32)
            reproject(
                source=binary_10m,
                destination=dst_frac,
                src_transform=win_transform,
                src_crs=src.crs,
                dst_transform=dst_transform,
                dst_crs=dst_crs,
                resampling=Resampling.average,
                src_nodata=np.nan,
                dst_nodata=np.nan,
            )

            # Footprint: a 20 m pixel is valid if >= half of its 10 m cells are inside the
            # label footprint (not nodata). Outside pixels (India, sea) are excluded from
            # training and evaluation. The three rasters share one footprint; take Aus.
            if valid_mask is None:
                valid_frac = np.zeros((dst_height, dst_width), dtype=np.float32)
                reproject(
                    source=(src_data != nodata).astype(np.float32),
                    destination=valid_frac,
                    src_transform=win_transform,
                    src_crs=src.crs,
                    dst_transform=dst_transform,
                    dst_crs=dst_crs,
                    resampling=Resampling.average,
                )
                valid_mask = (valid_frac >= 0.5).ravel().astype(np.uint8)

            # Infill any edge nodata with 0.0
            dst_frac = np.nan_to_num(dst_frac, nan=0.0)

            # Positive if fraction >= 0.5
            pos_mask = (dst_frac >= 0.5).astype(np.uint8)
            ambig_mask = (dst_frac >= 0.25) & (dst_frac <= 0.75)

            pos_count = int(pos_mask.sum())
            ambig_count = int(ambig_mask.sum())

            positive_counts[season] = pos_count
            positive_shares[season] = pos_count / total_pixels
            ambiguous_counts[season] = ambig_count
            ambiguous_shares[season] = ambig_count / total_pixels

            fractions_list.append(dst_frac.ravel())
            binary_list.append(pos_mask.ravel())

            print(
                f"[{tile.tile_id} {season}] Positive (>=0.5): {pos_count:,} ({pos_count / total_pixels * 100:.2f}%), "
                f"Ambiguous (0.25-0.75): {ambig_count:,} ({ambig_count / total_pixels * 100:.2f}%)"
            )

    labels_array = np.column_stack(binary_list).astype(np.uint8)  # [pixels, 3]
    fractions_array = np.column_stack(fractions_list).astype(np.float32)  # [pixels, 3]

    res = {
        "labels": labels_array,
        "valid": valid_mask,
        "fractions": fractions_array,
        "ambiguous_counts": ambiguous_counts,
        "ambiguous_shares": ambiguous_shares,
        "positive_counts": positive_counts,
        "positive_shares": positive_shares,
    }

    if out_npz:
        meta_dict = {
            "tile_id": tile.tile_id,
            "seasons": SEASONS,
            "total_pixels": total_pixels,
            "ambiguous_counts": ambiguous_counts,
            "ambiguous_shares": ambiguous_shares,
            "positive_counts": positive_counts,
            "positive_shares": positive_shares,
        }
        np.savez_compressed(
            out_npz,
            labels=labels_array,
            valid=valid_mask,
            fractions=fractions_array,
            metadata=json.dumps(meta_dict),
        )
        res["npz_path"] = str(out_npz)

    return res
