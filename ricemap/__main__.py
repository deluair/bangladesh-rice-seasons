"""CLI driver for bangladesh-rice-seasons pipeline.

Usage:
  python -m ricemap <stage> [options]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from ricemap.aggregate import aggregate_rice_area_by_admin
from ricemap.composite import build_tile_timeseries
from ricemap.infer import run_tile_inference
from ricemap.labels import extract_tile_labels
from ricemap.model import (
    BaselineLogisticRegression,
    TemporalRiceCNN,
    TemporalRiceTransformer,
    compute_normalization_stats,
    get_auto_device,
    save_checkpoint,
    train_model,
)
from ricemap.s1 import query_s1_scenes
from ricemap.tiles import generate_national_grid, get_tile_by_id
from ricemap.validate import validate_district_predictions


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="ricemap",
        description="National Sentinel-1 seasonal rice mapping pipeline for Bangladesh",
    )
    subparsers = parser.add_subparsers(dest="stage", required=True, help="Pipeline stage to execute")

    # 1. tiles
    p_tiles = subparsers.add_parser("tiles", help="Generate or inspect 0.2 deg national grid tiles")
    p_tiles.add_argument("--labels-path", type=str, default=None, help="Path to Boro 2017 label raster to filter tiles")
    p_tiles.add_argument("--out", type=str, default="data/tiles_408.json", help="Output path for tiles JSON")

    # 2. s1-query
    p_s1 = subparsers.add_parser("s1-query", help="Query Sentinel-1 RTC items for a tile and year")
    p_s1.add_argument("--tile", type=str, required=True, help="Tile ID (e.g. 89.4_24.2)")
    p_s1.add_argument("--year", type=int, default=2017, help="Calendar year (2017, 2022, 2023)")

    # 3. composite
    p_comp = subparsers.add_parser("composite", help="Build 20m 12-day composite npz for a tile-year")
    p_comp.add_argument("--tile", type=str, required=True, help="Tile ID (e.g. 89.4_24.2)")
    p_comp.add_argument("--year", type=int, required=True, help="Calendar year")
    p_comp.add_argument("--out-dir", type=str, default="work/composites", help="Output directory")
    p_comp.add_argument("--workers", type=int, default=8, help="Concurrent worker threads")
    p_comp.add_argument("--force", action="store_true", help="Force rebuild even if file exists")

    # 4. labels
    p_lab = subparsers.add_parser("labels", help="Extract and resample 2017 labels to 20m grid")
    p_lab.add_argument("--tile", type=str, required=True, help="Tile ID (e.g. 89.4_24.2)")
    p_lab.add_argument("--labels-dir", type=str, required=True, help="Directory containing 2017 label TIFFs")
    p_lab.add_argument("--out-dir", type=str, default="work/labels", help="Output directory")
    p_lab.add_argument("--force", action="store_true", help="Force rebuild even if file exists")

    # 5. train
    p_train = subparsers.add_parser("train", help="Train multi-season rice model")
    p_train.add_argument("--train-tiles", type=str, required=True, help="Comma-separated train tile IDs")
    p_train.add_argument("--val-tiles", type=str, default="", help="Comma-separated val/test tile IDs")
    p_train.add_argument("--comp-dir", type=str, default="work/composites", help="Directory with composites")
    p_train.add_argument("--labels-dir", type=str, default="work/labels", help="Directory with 20m labels")
    p_train.add_argument("--model-type", type=str, default="cnn", choices=["cnn", "transformer", "baseline"])
    p_train.add_argument("--epochs", type=int, default=5, help="Number of training epochs")
    p_train.add_argument("--batch-size", type=int, default=16384, help="Batch size")
    p_train.add_argument("--samples-per-epoch", type=int, default=200000, help="Random sample pixels per epoch")
    p_train.add_argument("--out", type=str, default="work/models/rice_model.pt", help="Path to save checkpoint")

    # 6. infer
    p_infer = subparsers.add_parser("infer", help="Run inference on composite npz to output 20m uint8 raster")
    p_infer.add_argument("--model", type=str, required=True, help="Path to model checkpoint .pt")
    p_infer.add_argument("--comp-npz", type=str, required=True, help="Path to composite .npz file")
    p_infer.add_argument("--out-dir", type=str, default="work/predictions", help="Directory for output GeoTIFFs")
    p_infer.add_argument("--force", action="store_true", help="Force re-inference even if GeoTIFF exists")

    # 7. aggregate
    p_agg = subparsers.add_parser("aggregate", help="Aggregate predicted rice rasters by district or upazila")
    p_agg.add_argument("--pred-tifs", type=str, nargs="+", required=True, help="Prediction GeoTIFF paths")
    p_agg.add_argument("--level", type=str, default="ADM2", choices=["ADM2", "ADM3"], help="Admin level")
    p_agg.add_argument("--year", type=int, required=True, help="Calendar year")
    p_agg.add_argument("--out-csv", type=str, required=True, help="Path to save CSV")

    # 8. validate
    p_val = subparsers.add_parser("validate", help="Validate district predictions against BBS yearbook data")
    p_val.add_argument("--pred-csv", type=str, required=True, help="Path to aggregated district predictions CSV")
    p_val.add_argument("--bbs-csv", type=str, required=True, help="Path to BBS district_rice_area.csv")
    p_val.add_argument("--year", type=int, required=True, help="Calendar year (2017, 2022, 2023)")
    p_val.add_argument("--out-csv", type=str, default="work/validation_district.csv", help="Output comparison CSV")
    p_val.add_argument("--name-map-csv", type=str, default="data/district_name_map.csv", help="Output name map CSV")

    args = parser.parse_args()

    if args.stage == "tiles":
        tiles = generate_national_grid(boro_label_path=args.labels_path, out_json=args.out)
        print(f"Generated {len(tiles)} tiles. Top tile: {tiles[0].tile_id} ({tiles[0].boro_pixels:,} boro pixels)")

    elif args.stage == "s1-query":
        tile = get_tile_by_id(args.tile)
        items = query_s1_scenes(tile.bbox, args.year)
        print(f"Found {len(items)} scenes for tile {tile.tile_id} in {args.year}")
        if items:
            print(f"First scene: {items[0].id} ({items[0].datetime})")
            print(f"Last scene: {items[-1].id} ({items[-1].datetime})")

    elif args.stage == "composite":
        tile = get_tile_by_id(args.tile)
        out_npz = build_tile_timeseries(tile, args.year, out_dir=args.out_dir, max_workers=args.workers, force=args.force)
        print(f"Composite ready: {out_npz}")

    elif args.stage == "labels":
        tile = get_tile_by_id(args.tile)
        res = extract_tile_labels(tile, args.labels_dir, out_dir=args.out_dir, force=args.force)
        print(f"Labels ready for {tile.tile_id}: shape={res['labels'].shape}")

    elif args.stage == "train":
        train_ids = [t.strip() for t in args.train_tiles.split(",") if t.strip()]
        val_ids = [t.strip() for t in args.val_tiles.split(",") if t.strip()]

        train_data_list = []
        train_lbl_list = []
        for tid in train_ids:
            c_p = Path(args.comp_dir) / f"{tid}_2017_timeseries.npz"
            l_p = Path(args.labels_dir) / f"{tid}_labels_2017.npz"
            with np.load(c_p) as npz:
                train_data_list.append(npz["data"].astype(np.float32))
            with np.load(l_p) as npz:
                train_lbl_list.append(npz["labels"])

        # Compute float64 normalization across all train data
        ch_means, ch_stds = compute_normalization_stats(train_data_list)
        print(f"Normalization stats (float64): VV mean={ch_means[0,0,0]:.2f}, VH mean={ch_means[0,0,1]:.2f}")

        # Normalize train data
        X_train = np.vstack([(d - ch_means) / ch_stds for d in train_data_list])
        y_train = np.vstack(train_lbl_list)

        X_val, y_val = None, None
        if val_ids:
            val_data_list = []
            val_lbl_list = []
            for tid in val_ids:
                c_p = Path(args.comp_dir) / f"{tid}_2017_timeseries.npz"
                l_p = Path(args.labels_dir) / f"{tid}_labels_2017.npz"
                with np.load(c_p) as npz:
                    val_data_list.append(npz["data"].astype(np.float32))
                with np.load(l_p) as npz:
                    val_lbl_list.append(npz["labels"])
            X_val = np.vstack([(d - ch_means) / ch_stds for d in val_data_list])
            y_val = np.vstack(val_lbl_list)

        if args.model_type == "cnn":
            model = TemporalRiceCNN()
        elif args.model_type == "transformer":
            model = TemporalRiceTransformer()
        else:
            model = BaselineLogisticRegression()

        device = get_auto_device()
        res = train_model(
            model=model,
            train_data=X_train,
            train_labels=y_train,
            val_data=X_val,
            val_labels=y_val,
            epochs=args.epochs,
            batch_size=args.batch_size,
            samples_per_epoch=args.samples_per_epoch,
            device=device,
        )

        save_checkpoint(
            model=model,
            ch_means=ch_means,
            ch_stds=ch_stds,
            model_type=args.model_type,
            out_path=args.out,
            extra_meta={"metrics": res.get("val_metrics")},
        )
        print(f"Training completed in {res['train_time_seconds']}s")
        if res.get("val_metrics"):
            print("Validation Metrics:")
            print(json.dumps(res["val_metrics"], indent=2))

    elif args.stage == "infer":
        run_tile_inference(
            model_checkpoint=args.model,
            timeseries_npz=args.comp_npz,
            out_dir=args.out_dir,
            force=args.force,
        )

    elif args.stage == "aggregate":
        aggregate_rice_area_by_admin(
            pred_tifs=args.pred_tifs,
            admin_level=args.level,
            year=args.year,
            out_csv=args.out_csv,
        )

    elif args.stage == "validate":
        validate_district_predictions(
            pred_district_csv=args.pred_csv,
            bbs_csv_path=args.bbs_csv,
            calendar_year=args.year,
            out_csv=args.out_csv,
            name_map_csv=args.name_map_csv,
        )


if __name__ == "__main__":
    main()
