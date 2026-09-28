"""Temporal compositing and gap interpolation module for Sentinel-1 time series.

Groups acquisitions into 30 regular 12-day median bins per calendar year (360 days total),
evaluates temporal gaps in VV and VH channels, and applies 1D linear temporal interpolation
to fill any missing acquisitions. Stored as compressed float16 npz arrays.
"""

from __future__ import annotations

import json
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np

from ricemap.s1 import fetch_s1_band_20m, query_s1_scenes
from ricemap.tiles import Tile

NUM_BINS = 30
BIN_DAYS = 12


def assign_items_to_bins(items: list[Any], year: int) -> dict[int, list[Any]]:
    """Partition STAC items into 30 regular 12-day temporal bins."""
    start_dt = datetime(year, 1, 1, tzinfo=timezone.utc)
    binned: dict[int, list[Any]] = {b: [] for b in range(NUM_BINS)}
    for it in items:
        days = (it.datetime - start_dt).total_seconds() / 86400.0
        b = int(days // BIN_DAYS)
        if 0 <= b < NUM_BINS:
            binned[b].append(it)
    return binned


def build_tile_timeseries(
    tile: Tile,
    year: int,
    out_dir: str | Path,
    max_workers: int = 8,
    force: bool = False,
) -> Path:
    """Build, interpolate, and save 20m Sentinel-1 time series for a tile-year.

    Outputs a compressed .npz archive containing:
      - data: float16 array of shape [pixels, 30, 2] (channels: 0=VV, 1=VH)
      - row, col: coordinate arrays of shape [pixels]
      - dst_crs, dst_transform, dst_shape
      - metadata: JSON string with gap statistics and processing metrics
    """
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_npz = out_dir / f"{tile.tile_id}_{year}_timeseries.npz"

    if out_npz.exists() and not force:
        try:
            # Check if file is readable
            with np.load(out_npz) as npz:
                if "data" in npz and npz["data"].shape[1] == NUM_BINS:
                    print(f"Tile {tile.tile_id} {year} already exists at {out_npz}. Skipping.")
                    return out_npz
        except Exception:  # noqa: BLE001
            print(f"Existing file {out_npz} corrupt; re-generating...")

    t0 = time.time()
    grid = tile.get_utm_grid()
    dst_crs = grid["crs"]
    dst_transform = grid["transform"]
    dst_width = grid["width"]
    dst_height = grid["height"]
    total_pixels = grid["total_pixels"]

    print(f"[{tile.tile_id} {year}] Querying S-1 RTC scenes...")
    items = query_s1_scenes(tile.bbox, year)
    print(f"[{tile.tile_id} {year}] Found {len(items)} scenes across 365 days.")

    binned_items = assign_items_to_bins(items, year)

    # Composites accumulator: shape [30, 2, height, width], channels: 0=VV, 1=VH
    composites = np.full((NUM_BINS, 2, dst_height, dst_width), np.nan, dtype=np.float32)

    t_fetch0 = time.time()
    bin_vvs: dict[int, list[np.ndarray]] = {b: [] for b in range(NUM_BINS)}
    bin_vhs: dict[int, list[np.ndarray]] = {b: [] for b in range(NUM_BINS)}

    with ThreadPoolExecutor(max_workers=max_workers) as ex:
        future_to_info = {}
        for b in range(NUM_BINS):
            for sc in binned_items[b]:
                f_vv = ex.submit(
                    fetch_s1_band_20m, sc, "vv", dst_crs, dst_transform, dst_width, dst_height, tile.bbox
                )
                future_to_info[f_vv] = (b, "vv")
                f_vh = ex.submit(
                    fetch_s1_band_20m, sc, "vh", dst_crs, dst_transform, dst_width, dst_height, tile.bbox
                )
                future_to_info[f_vh] = (b, "vh")

        for fut in as_completed(future_to_info):
            b_idx, pol = future_to_info[fut]
            arr = fut.result()
            if arr is not None:
                if pol == "vv":
                    bin_vvs[b_idx].append(arr)
                else:
                    bin_vhs[b_idx].append(arr)

    for b in range(NUM_BINS):
        vv_list = bin_vvs[b]
        vh_list = bin_vhs[b]
        if len(vv_list) == 1:
            composites[b, 0] = vv_list[0]
        elif len(vv_list) > 1:
            composites[b, 0] = np.nanmedian(np.stack(vv_list, axis=0), axis=0)

        if len(vh_list) == 1:
            composites[b, 1] = vh_list[0]
        elif len(vh_list) > 1:
            composites[b, 1] = np.nanmedian(np.stack(vh_list, axis=0), axis=0)

    t_fetch = time.time() - t_fetch0

    # Reshape from [30, 2, H, W] to [total_pixels, 30, 2]
    # Transpose to [H, W, 30, 2] then reshape to [H*W, 30, 2]
    composites_hwbc = np.transpose(composites, (2, 3, 0, 1))
    data_pixels = composites_hwbc.reshape((total_pixels, NUM_BINS, 2))

    # Gap analysis
    vv_nans = np.isnan(data_pixels[:, :, 0]).sum(axis=1)
    vh_nans = np.isnan(data_pixels[:, :, 1]).sum(axis=1)

    any_gap_mask = (vv_nans > 0) | (vh_nans > 0)
    any_gap_count = int(any_gap_mask.sum())
    any_gap_share = float(any_gap_count / total_pixels)
    vv_gap_share = float((vv_nans > 0).sum() / total_pixels)
    vh_gap_share = float((vh_nans > 0).sum() / total_pixels)

    print(
        f"[{tile.tile_id} {year}] Gap share: {any_gap_share * 100:.2f}% pixels have gaps "
        f"(VV: {vv_gap_share * 100:.2f}%, VH: {vh_gap_share * 100:.2f}%)"
    )

    # 1D Linear temporal interpolation
    t_interp0 = time.time()
    time_indices = np.arange(NUM_BINS)
    filled_data = data_pixels.copy()

    for c in range(2):
        ch_data = filled_data[:, :, c]
        nan_rows = np.where(np.isnan(ch_data).any(axis=1))[0]
        for r in nan_rows:
            row = ch_data[r]
            valid = np.isfinite(row)
            if valid.sum() == 0:
                row[:] = -20.0  # Fallback background
            else:
                row[:] = np.interp(time_indices, time_indices[valid], row[valid])
            ch_data[r] = row
        filled_data[:, :, c] = ch_data

    t_interp = time.time() - t_interp0

    # Verify no NaNs remain
    assert not np.isnan(filled_data).any(), f"NaN values remain in {tile.tile_id} {year} time series!"

    # Coordinate grids
    row_grid, col_grid = np.indices((dst_height, dst_width), dtype=np.int16)
    row_flat = row_grid.ravel()
    col_flat = col_grid.ravel()

    # Cast to float16
    data_fp16 = filled_data.astype(np.float16)

    t_save0 = time.time()
    meta_dict = {
        "tile_id": tile.tile_id,
        "year": year,
        "bbox": tile.bbox,
        "total_pixels": total_pixels,
        "dst_crs": dst_crs,
        "dst_shape": [dst_height, dst_width],
        "res_m": grid["res"],
        "num_scenes": len(items),
        "gap_statistics": {
            "any_gap_share": any_gap_share,
            "vv_gap_share": vv_gap_share,
            "vh_gap_share": vh_gap_share,
            "vv_mean_empty_bins": float(vv_nans.mean()),
            "vh_mean_empty_bins": float(vh_nans.mean()),
        },
        "timings": {
            "fetch_seconds": round(t_fetch, 2),
            "interpolation_seconds": round(t_interp, 2),
            "total_seconds": round(time.time() - t0, 2),
        },
    }

    np.savez_compressed(
        out_npz,
        data=data_fp16,
        row=row_flat,
        col=col_flat,
        dst_crs=dst_crs,
        dst_transform=np.array(dst_transform)[:6],
        dst_shape=np.array([dst_height, dst_width]),
        gap_share=np.float32(any_gap_share),
        metadata=json.dumps(meta_dict),
    )
    t_save = time.time() - t_save0

    file_size_bytes = out_npz.stat().st_size
    print(
        f"[{tile.tile_id} {year}] Saved {out_npz.name} ({file_size_bytes / (1024*1024):.2f} MB) "
        f"in {time.time() - t0:.2f}s (fetch: {t_fetch:.1f}s, interp: {t_interp:.2f}s, save: {t_save:.2f}s)"
    )
    return out_npz
