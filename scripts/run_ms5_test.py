"""End-to-End ms5 Test Runner for bangladesh-rice-seasons.

Executes every pipeline stage on 2 adjacent tiles (89.4_24.2 and 89.6_24.2)
for 2017 and 2023:
  1. Generate 408 tiles grid from 2017 label footprint
  2. Query & Composite 20m Sentinel-1 time series for (89.4_24.2, 2017), (89.4_24.2, 2023), (89.6_24.2, 2017), (89.6_24.2, 2023)
  3. Extract 20m Singha et al. labels for both tiles (positive & ambiguous stats)
  4. Train PyTorch TemporalRiceCNN and BaselineLogisticRegression on 89.4_24.2; evaluate on held-out 89.6_24.2
  5. Run 20m uint8 bitmask inference across all 4 tile-years
  6. Aggregate seasonal rice areas to ADM2 (districts) and ADM3 (upazilas)
  7. Validate against BBS 2023 yearbook data with explicit name reconciliation
  8. Project national run resource requirements (408 tiles x 3 years on 12-CPU VM)
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import numpy as np

from ricemap.aggregate import aggregate_rice_area_by_admin, fetch_admin_boundaries
from ricemap.composite import build_tile_timeseries
from ricemap.infer import run_tile_inference
from ricemap.labels import extract_tile_labels
from ricemap.model import (
    BaselineLogisticRegression,
    TemporalRiceCNN,
    compute_normalization_stats,
    get_auto_device,
    save_checkpoint,
    train_model,
)
from ricemap.tiles import generate_national_grid, get_tile_by_id
from ricemap.validate import validate_district_predictions

LABELS_DIR = Path("/Users/ms5/bdml/rice-prep/data/labels")
BBS_CSV = Path("/Users/ms5/bdml/rice-prep/data/bbs/district_rice_area.csv")
BORO_LABEL_FILE = LABELS_DIR / "Boro_BGD_2017_V1.tif"

WORK_DIR = Path("work")
COMP_DIR = WORK_DIR / "composites"
LABELS_OUT_DIR = WORK_DIR / "labels"
MODELS_DIR = WORK_DIR / "models"
PRED_DIR = WORK_DIR / "predictions"
AGG_DIR = WORK_DIR / "aggregates"
VAL_DIR = WORK_DIR / "validation"
DATA_DIR = Path("data")


def main() -> None:
    t_start_total = time.time()
    results: dict[str, any] = {"timings": {}, "metrics": {}, "storage": {}}

    print("=" * 70)
    print("BANGLADESH RICE SEASONS: 2-TILE PIPELINE TEST ON MS5")
    print("=" * 70)

    # -------------------------------------------------------------
    # Stage 1: Grid Tiling
    # -------------------------------------------------------------
    print("\n>>> Stage 1: Scanning Bangladesh 0.2 deg grid tiles...")
    t0 = time.time()
    tiles = generate_national_grid(boro_label_path=BORO_LABEL_FILE, out_json=DATA_DIR / "tiles_408.json")
    t_tiles = time.time() - t0
    results["timings"]["stage1_tiles_seconds"] = round(t_tiles, 2)
    results["stage1"] = {
        "total_active_tiles": len(tiles),
        "top_tile": tiles[0].tile_id,
        "top_tile_boro_pixels": tiles[0].boro_pixels,
        "elapsed_seconds": round(t_tiles, 2),
    }
    print(f"Scanned {len(tiles)} active tiles in {t_tiles:.2f}s. Top tile: {tiles[0].tile_id}")

    # Verify tile 89.4_24.2 is present
    tile1 = get_tile_by_id("89.4_24.2")
    tile2 = get_tile_by_id("89.6_24.2")
    test_tiles = [tile1, tile2]
    test_years = [2017, 2023]

    # -------------------------------------------------------------
    # Stage 2: S-1 Ingestion, 20m Compositing & Gap Interpolation
    # -------------------------------------------------------------
    print("\n>>> Stage 2: Sentinel-1 20m Ingestion & Compositing...")
    t_comp_start = time.time()
    comp_records = {}

    for t in test_tiles:
        for yr in test_years:
            print(f"\n--- Building composite for Tile {t.tile_id}, Year {yr} ---")
            t_tile_start = time.time()
            npz_path = build_tile_timeseries(t, yr, out_dir=COMP_DIR, max_workers=8, force=False)
            t_tile = time.time() - t_tile_start

            with np.load(npz_path) as npz:
                meta = json.loads(str(npz["metadata"]))
                file_bytes = npz_path.stat().st_size
                data_shape = list(npz["data"].shape)
                actual_seconds = meta.get("timings", {}).get("total_seconds", t_tile)

            comp_records[f"{t.tile_id}_{yr}"] = {
                "tile_id": t.tile_id,
                "year": yr,
                "npz_path": str(npz_path),
                "file_bytes": file_bytes,
                "file_mb": round(file_bytes / (1024 * 1024), 2),
                "data_shape": data_shape,
                "num_scenes": meta["num_scenes"],
                "gap_statistics": meta["gap_statistics"],
                "elapsed_seconds": round(actual_seconds, 2),
            }

    t_comp_total = time.time() - t_comp_start
    results["timings"]["stage2_compositing_seconds"] = round(t_comp_total, 2)
    results["stage2"] = comp_records
    print(f"\nStage 2 completed: 4 tile-years composited in {t_comp_total:.2f}s")

    # -------------------------------------------------------------
    # Stage 3: 2017 Label Resampling to 20m Grid
    # -------------------------------------------------------------
    print("\n>>> Stage 3: Resampling Singha et al. 2017 Labels to 20m Grid...")
    t_lab_start = time.time()
    label_records = {}

    for t in test_tiles:
        print(f"\n--- Extracting 20m labels for Tile {t.tile_id} ---")
        l_res = extract_tile_labels(t, labels_dir=LABELS_DIR, out_dir=LABELS_OUT_DIR, force=False)
        label_records[t.tile_id] = {
            "ambiguous_counts": l_res["ambiguous_counts"],
            "ambiguous_shares": l_res["ambiguous_shares"],
            "positive_counts": l_res["positive_counts"],
            "positive_shares": l_res["positive_shares"],
        }

    t_lab_total = time.time() - t_lab_start
    results["timings"]["stage3_labels_seconds"] = round(t_lab_total, 2)
    results["stage3"] = label_records
    print(f"\nStage 3 completed: 20m labels extracted in {t_lab_total:.2f}s")

    # -------------------------------------------------------------
    # Stage 4: Spatial Split Training & Evaluation
    # -------------------------------------------------------------
    print("\n>>> Stage 4: Spatial Split Training & Model Evaluation...")
    print("Train tile: 89.4_24.2 (Sirajganj/Tangail west)")
    print("Held-out test tile: 89.6_24.2 (Tangail/Dhaka east)")

    t_train_start = time.time()

    # Load train data (89.4_24.2, 2017)
    with np.load(COMP_DIR / "89.4_24.2_2017_timeseries.npz") as npz:
        train_raw = npz["data"].astype(np.float32)
    with np.load(LABELS_OUT_DIR / "89.4_24.2_labels_2017.npz") as npz:
        train_labels = npz["labels"]

    # Load test data (89.6_24.2, 2017)
    with np.load(COMP_DIR / "89.6_24.2_2017_timeseries.npz") as npz:
        test_raw = npz["data"].astype(np.float32)
    with np.load(LABELS_OUT_DIR / "89.6_24.2_labels_2017.npz") as npz:
        test_labels = npz["labels"]

    # Compute float64 normalization on Train tile strictly
    ch_means, ch_stds = compute_normalization_stats([train_raw])
    print(f"Computed Normalization Stats in float64: VV={ch_means[0,0,0]:.4f} dB, VH={ch_means[0,0,1]:.4f} dB")

    # Normalize arrays
    X_train = (train_raw - ch_means) / ch_stds
    X_test = (test_raw - ch_means) / ch_stds

    device = get_auto_device()
    print(f"Using compute device: {device}")

    # 4a. Train Baseline Logistic Regression
    print("\n--- Training Baseline Logistic Regression ---")
    baseline_model = BaselineLogisticRegression(in_features=60, num_classes=3)
    t_bl_start = time.time()
    res_bl = train_model(
        model=baseline_model,
        train_data=X_train,
        train_labels=train_labels,
        val_data=X_test,
        val_labels=test_labels,
        epochs=5,
        batch_size=16384,
        lr=0.01,
        samples_per_epoch=None,  # Train on all 1.18M pixels
        device=device,
    )
    t_bl = time.time() - t_bl_start

    save_checkpoint(
        model=baseline_model,
        ch_means=ch_means,
        ch_stds=ch_stds,
        model_type="logistic_regression",
        out_path=MODELS_DIR / "baseline_lr_model.pt",
        extra_meta={"metrics": res_bl["val_metrics"]},
    )

    # 4b. Train Temporal 1D CNN
    print("\n--- Training Temporal Rice CNN (1D CNN) ---")
    cnn_model = TemporalRiceCNN(in_channels=2, seq_len=30, num_classes=3)
    t_cnn_start = time.time()
    res_cnn = train_model(
        model=cnn_model,
        train_data=X_train,
        train_labels=train_labels,
        val_data=X_test,
        val_labels=test_labels,
        epochs=5,
        batch_size=16384,
        lr=0.005,
        samples_per_epoch=200000,  # 200k samples per epoch
        device=device,
    )
    t_cnn = time.time() - t_cnn_start

    save_checkpoint(
        model=cnn_model,
        ch_means=ch_means,
        ch_stds=ch_stds,
        model_type="cnn",
        out_path=MODELS_DIR / "temporal_cnn_model.pt",
        extra_meta={"metrics": res_cnn["val_metrics"]},
    )

    t_train_total = time.time() - t_train_start
    results["timings"]["stage4_training_seconds"] = round(t_train_total, 2)
    results["stage4"] = {
        "device": str(device),
        "normalization": {
            "vv_mean": float(ch_means[0, 0, 0]),
            "vh_mean": float(ch_means[0, 0, 1]),
            "vv_std": float(ch_stds[0, 0, 0]),
            "vh_std": float(ch_stds[0, 0, 1]),
        },
        "baseline_logistic_regression": {
            "training_time_seconds": round(t_bl, 2),
            "metrics": res_bl["val_metrics"],
        },
        "temporal_cnn": {
            "training_time_seconds": round(t_cnn, 2),
            "metrics": res_cnn["val_metrics"],
        },
    }

    print("\n=== Model Comparison on Held-Out Test Tile (89.6_24.2) ===")
    for season in ["Aus", "Aman", "Boro"]:
        bl_iou = res_bl["val_metrics"][season]["iou"]
        cnn_iou = res_cnn["val_metrics"][season]["iou"]
        print(f"  {season:5s}: Baseline IoU = {bl_iou:.4f} | Temporal CNN IoU = {cnn_iou:.4f}")

    # -------------------------------------------------------------
    # Stage 5: 20m uint8 Bitmask Inference
    # -------------------------------------------------------------
    print("\n>>> Stage 5: Generating 20m uint8 Bitmask Classification Rasters...")
    t_infer_start = time.time()
    infer_records = {}
    pred_tifs = {2017: [], 2023: []}

    for t in test_tiles:
        for yr in test_years:
            npz_p = COMP_DIR / f"{t.tile_id}_{yr}_timeseries.npz"
            inf_res = run_tile_inference(
                model_checkpoint=MODELS_DIR / "temporal_cnn_model.pt",
                timeseries_npz=npz_p,
                out_dir=PRED_DIR,
                device=device,
                force=True,
            )
            infer_records[f"{t.tile_id}_{yr}"] = inf_res
            pred_tifs[yr].append(inf_res["out_tif"])

    t_infer_total = time.time() - t_infer_start
    results["timings"]["stage5_inference_seconds"] = round(t_infer_total, 2)
    results["stage5"] = infer_records
    print(f"\nStage 5 completed: 4 classification rasters generated in {t_infer_total:.2f}s")

    # -------------------------------------------------------------
    # Stage 6: Administrative Aggregation (ADM2 & ADM3)
    # -------------------------------------------------------------
    print("\n>>> Stage 6: Aggregating Rice Area to Districts (ADM2) and Upazilas (ADM3)...")
    t_agg_start = time.time()
    agg_records = {}

    for yr in test_years:
        # ADM2 (Districts)
        df_adm2 = aggregate_rice_area_by_admin(
            pred_tifs=pred_tifs[yr],
            admin_level="ADM2",
            year=yr,
            cache_dir=DATA_DIR / "geoboundaries",
            out_csv=AGG_DIR / f"rice_area_by_district_{yr}.csv",
        )
        # ADM3 (Upazilas)
        df_adm3 = aggregate_rice_area_by_admin(
            pred_tifs=pred_tifs[yr],
            admin_level="ADM3",
            year=yr,
            cache_dir=DATA_DIR / "geoboundaries",
            out_csv=AGG_DIR / f"rice_area_by_upazila_{yr}.csv",
        )

        active_adm2 = df_adm2[df_adm2["pixel_count_total"] > 0]
        active_adm3 = df_adm3[df_adm3["pixel_count_total"] > 0]

        agg_records[str(yr)] = {
            "districts_intersected": len(active_adm2),
            "upazilas_intersected": len(active_adm3),
            "district_names": list(active_adm2["unit_name"]),
            "upazila_names": list(active_adm3["unit_name"]),
            "license": active_adm2["license"].iloc[0] if not active_adm2.empty else "",
        }

    t_agg_total = time.time() - t_agg_start
    results["timings"]["stage6_aggregation_seconds"] = round(t_agg_total, 2)
    results["stage6"] = agg_records

    # Fetch and record exact license string
    _, adm2_meta = fetch_admin_boundaries("ADM2", cache_dir=DATA_DIR / "geoboundaries")
    license_str = adm2_meta.get("boundaryLicense", "")
    results["admin_license"] = license_str
    print(f"\nRecorded geoBoundaries License String: '{license_str}'")

    # -------------------------------------------------------------
    # Stage 7: BBS Ground-Truth Validation
    # -------------------------------------------------------------
    print("\n>>> Stage 7: Validating District Predictions with BBS Agricultural Statistics...")
    t_val_start = time.time()

    val_df_2023 = validate_district_predictions(
        pred_district_csv=AGG_DIR / "rice_area_by_district_2023.csv",
        bbs_csv_path=BBS_CSV,
        calendar_year=2023,
        out_csv=VAL_DIR / "validation_district_2023.csv",
        name_map_csv=DATA_DIR / "district_name_map.csv",
    )

    t_val_total = time.time() - t_val_start
    results["timings"]["stage7_validation_seconds"] = round(t_val_total, 2)
    results["stage7"] = {
        "validatable_rows": int(val_df_2023["validatable"].sum()),
        "total_comparison_rows": len(val_df_2023),
        "sample_comparisons": val_df_2023.to_dict(orient="records"),
    }

    # -------------------------------------------------------------
    # Stage 8: National Run Resource Projections
    # -------------------------------------------------------------
    print("\n>>> Stage 8: Computing National Scale Projections (408 tiles x 3 years)...")
    # Average empirical metrics across the 4 tile-years measured at 20m
    avg_bytes_per_tile_year = float(np.mean([r["file_bytes"] for r in comp_records.values()]))
    avg_fetch_sec_per_tile_year = float(np.mean([r["elapsed_seconds"] for r in comp_records.values()]))

    total_tiles = 408
    years_count = 3  # 2017, 2022, 2023
    total_tile_years = total_tiles * years_count

    # Compressed storage projection
    national_compressed_bytes = total_tile_years * avg_bytes_per_tile_year
    national_compressed_gb = national_compressed_bytes / (1024**3)

    # 12-CPU VM parallel speedup projection
    # With 12 CPUs / 12 concurrent workers on a VM with fast cloud pipe:
    # Wall clock time = (total_tile_years * avg_fetch_sec) / 12
    proj_vm_fetch_hours = (total_tile_years * avg_fetch_sec_per_tile_year) / (12 * 3600.0)

    # GPU Training time projection (national spatial split 80/10/10)
    # Training on ~326 tiles for 10 epochs on Colab T4/V100/A100: ~15-20 minutes
    # GPU Inference time projection (1224 tiles * 1.5s): ~30.6 minutes
    proj_train_hours = 0.35  # ~21 minutes
    proj_infer_hours = (total_tile_years * 1.5) / 3600.0  # ~0.51 hours
    proj_total_hours = proj_vm_fetch_hours + proj_train_hours + proj_infer_hours

    results["national_projections"] = {
        "total_active_tiles": total_tiles,
        "years": [2017, 2022, 2023],
        "total_tile_years": total_tile_years,
        "empirical_measured_avg_bytes_per_tile_year": avg_bytes_per_tile_year,
        "empirical_measured_avg_mb_per_tile_year": round(avg_bytes_per_tile_year / (1024 * 1024), 2),
        "empirical_measured_avg_seconds_per_tile_year": round(avg_fetch_sec_per_tile_year, 2),
        "national_compressed_storage_gb": round(national_compressed_gb, 2),
        "national_compressed_storage_tb": round(national_compressed_gb / 1024.0, 3),
        "projected_12_cpu_vm_fetching_hours": round(proj_vm_fetch_hours, 2),
        "projected_gpu_training_hours": round(proj_train_hours, 2),
        "projected_gpu_inference_hours": round(proj_infer_hours, 2),
        "projected_total_pipeline_hours": round(proj_total_hours, 2),
    }

    t_total_run = time.time() - t_start_total
    results["timings"]["total_test_run_seconds"] = round(t_total_run, 2)

    with open(WORK_DIR / "ms5_test_summary.json", "w") as f:
        json.dump(results, f, indent=2)

    print("\n" + "=" * 70)
    print(f"TEST RUN COMPLETED SUCCESSFULLY IN {t_total_run:.2f}s ({t_total_run / 60.0:.2f} min)")
    print(f"Summary written to {WORK_DIR / 'ms5_test_summary.json'}")
    print("=" * 70)


if __name__ == "__main__":
    main()
