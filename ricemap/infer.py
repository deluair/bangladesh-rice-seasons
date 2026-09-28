"""Inference module for seasonal rice mapping.

Generates 20m uint8 classification rasters per tile-year where bits represent seasonal presence:
  - Bit 1 (1): Aus
  - Bit 2 (2): Aman
  - Bit 4 (4): Boro
Values range from 0 (no rice) to 7 (triple-cropped Aus + Aman + Boro).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import numpy as np
import rasterio
import torch
from rasterio.transform import Affine

from ricemap.model import load_checkpoint

SEASONS = ["Aus", "Aman", "Boro"]


def run_tile_inference(
    model_checkpoint: str | Path,
    timeseries_npz: str | Path,
    out_dir: str | Path,
    batch_size: int = 16384,
    device: torch.device | None = None,
    force: bool = False,
) -> dict[str, Any]:
    """Run model inference on a tile-year time series and save 20m uint8 GeoTIFF.

    Output format:
      - GeoTIFF named {tile_id}_{year}_prediction_20m.tif
      - Data type: uint8
      - Bit 1: Aus, Bit 2: Aman, Bit 4: Boro
    """
    timeseries_p = Path(timeseries_npz)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)

    with np.load(timeseries_p) as npz:
        raw_data = npz["data"].astype(np.float32)  # [pixels, 30, 2]
        dst_crs = str(npz["dst_crs"])
        dst_transform = Affine(*npz["dst_transform"])
        dst_shape = list(npz["dst_shape"])
        meta = json.loads(str(npz["metadata"]))

    tile_id = meta["tile_id"]
    year = meta["year"]
    height, width = dst_shape
    total_pixels = height * width

    out_tif = out_dir / f"{tile_id}_{year}_rice_20m.tif"
    out_meta_json = out_dir / f"{tile_id}_{year}_prediction_metrics.json"

    if out_tif.exists() and not force:
        print(f"Prediction {out_tif.name} already exists. Skipping.")
        if out_meta_json.exists():
            with open(out_meta_json) as f:
                return json.load(f)

    model, ch_means, ch_stds, extra = load_checkpoint(model_checkpoint, device=device)
    # Per-season thresholds chosen on the validation tiles; 0.5 if not calibrated.
    thr = torch.tensor(extra.get("thresholds", [0.5, 0.5, 0.5]))
    dev = next(model.parameters()).device

    # Normalize strictly using checkpoint float64-derived stats
    data_norm = (raw_data - ch_means) / ch_stds

    # Transpose to (pixels, 2, 30) for CNN/Transformer
    X_t = torch.from_numpy(np.ascontiguousarray(np.transpose(data_norm, (0, 2, 1))))

    preds_list = []
    with torch.no_grad():
        for i in range(0, total_pixels, batch_size):
            bx = X_t[i : i + batch_size].to(dev)
            logits = model(bx)
            probs = torch.sigmoid(logits)
            # Binary threshold 0.5
            bin_preds = (probs >= thr.to(probs.device)).cpu().numpy().astype(np.uint8)
            preds_list.append(bin_preds)

    binary_all = np.vstack(preds_list)  # [pixels, 3] (0=Aus, 1=Aman, 2=Boro)

    aus = binary_all[:, 0]
    aman = binary_all[:, 1]
    boro = binary_all[:, 2]

    # Combine into uint8 bitmask:
    # bit 1: Aus (value 1)
    # bit 2: Aman (value 2)
    # bit 4: Boro (value 4)
    bitmask = (aus * 1) | (aman * 2) | (boro * 4)
    bitmask_2d = bitmask.reshape((height, width)).astype(np.uint8)

    # Save Cloud-Optimized / Deflate compressed GeoTIFF
    profile = {
        "driver": "GTiff",
        "dtype": "uint8",
        "nodata": None,
        "width": width,
        "height": height,
        "count": 1,
        "crs": dst_crs,
        "transform": dst_transform,
        "compress": "deflate",
        "tiled": True,
        "blockxsize": 256,
        "blockysize": 256,
    }

    with rasterio.open(out_tif, "w", **profile) as dst:
        dst.write(bitmask_2d, 1)

    total_pixels = int(height) * int(width)
    pixel_area_ha = 0.04
    aus_pixels = int(aus.sum())
    aman_pixels = int(aman.sum())
    boro_pixels = int(boro.sum())
    total_rice_pixels = int((bitmask > 0).sum())

    summary = {
        "tile_id": str(tile_id),
        "year": int(year),
        "out_tif": str(out_tif),
        "total_pixels": total_pixels,
        "pixel_area_ha": pixel_area_ha,
        "counts": {
            "Aus": aus_pixels,
            "Aman": aman_pixels,
            "Boro": boro_pixels,
            "any_rice": total_rice_pixels,
        },
        "area_ha": {
            "Aus": round(float(aus_pixels * pixel_area_ha), 2),
            "Aman": round(float(aman_pixels * pixel_area_ha), 2),
            "Boro": round(float(boro_pixels * pixel_area_ha), 2),
            "any_rice": round(float(total_rice_pixels * pixel_area_ha), 2),
        },
        "shares": {
            "Aus": round(float(aus_pixels / total_pixels), 4),
            "Aman": round(float(aman_pixels / total_pixels), 4),
            "Boro": round(float(boro_pixels / total_pixels), 4),
            "any_rice": round(float(total_rice_pixels / total_pixels), 4),
        },
    }

    with open(out_meta_json, "w") as f:
        json.dump(summary, f, indent=2)

    print(
        f"[{tile_id} {year}] Generated 20m rice map {out_tif.name}: "
        f"Aus: {summary['area_ha']['Aus']:,} ha, "
        f"Aman: {summary['area_ha']['Aman']:,} ha, "
        f"Boro: {summary['area_ha']['Boro']:,} ha"
    )
    return summary
