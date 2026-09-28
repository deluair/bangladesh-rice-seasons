"""National run driver: grid, composites, labels, training, test evaluation, inference,
aggregation and BBS validation. Every stage is resumable (existing outputs are skipped).

Usage:
  python -m ricemap.national --work /content/work --labels-raw /content/labels_raw \
      --bbs-csv data/bbs/district_rice_area.csv [--stage all] [--delete-composites]
"""

from __future__ import annotations

import argparse
import json
import multiprocessing as mp
import os
import time
from concurrent.futures import ProcessPoolExecutor, as_completed
from pathlib import Path

import numpy as np

from ricemap.tiles import Tile, generate_national_grid, own_cell_mask

TRAIN_YEAR = 2017
YEARS = [2017, 2022, 2023]
SEASONS = ["Aus", "Aman", "Boro"]
T0 = time.time()
SPAWN = mp.get_context("spawn")


def log(msg: str) -> None:
    print(f"[{time.strftime('%H:%M:%S')} +{(time.time() - T0) / 60:.1f}m] {msg}", flush=True)


def load_tiles(work: Path, labels_raw: Path) -> list[Tile]:
    tiles_json = work / "tiles.json"
    if tiles_json.exists():
        return [Tile(**d) for d in json.loads(tiles_json.read_text())]
    return generate_national_grid(boro_label_path=labels_raw / "Boro_BGD_2017_V1.tif", out_json=tiles_json)


def _composite(args: tuple[dict, int, str, int]) -> tuple[str, int, float]:
    from ricemap.composite import build_tile_timeseries

    tile_d, year, comp_dir, threads = args
    t = time.time()
    build_tile_timeseries(Tile(**tile_d), year, out_dir=comp_dir, max_workers=threads)
    return tile_d["tile_id"], year, time.time() - t


def _labels(args: tuple[dict, str, str]) -> str:
    from ricemap.labels import extract_tile_labels

    tile_d, labels_raw, labels_dir = args
    extract_tile_labels(Tile(**tile_d), labels_raw, out_dir=labels_dir)
    return tile_d["tile_id"]


def run_pool(fn, tasks: list, procs: int, what: str) -> list:
    out = []
    with ProcessPoolExecutor(max_workers=procs, mp_context=SPAWN) as ex:
        futs = [ex.submit(fn, t) for t in tasks]
        for i, f in enumerate(as_completed(futs), 1):
            try:
                out.append(f.result())
            except Exception as e:  # noqa: BLE001
                log(f"{what} task failed: {e!r}")
            if i % 20 == 0 or i == len(tasks):
                log(f"{what}: {i}/{len(tasks)}")
    return out


def tile_pixels(comp_dir: Path, labels_dir: Path, tile_id: str) -> tuple[np.ndarray, np.ndarray]:
    """Series and labels for the tile's own-cell, in-footprint pixels."""
    with np.load(comp_dir / f"{tile_id}_{TRAIN_YEAR}_timeseries.npz") as z:
        data = z["data"]
        shape = tuple(int(v) for v in z["dst_shape"])
        from rasterio.transform import Affine

        transform = Affine(*z["dst_transform"])
    with np.load(labels_dir / f"{tile_id}_labels_{TRAIN_YEAR}.npz") as z:
        labels = z["labels"]
        valid = z["valid"].astype(bool)
    keep = valid & own_cell_mask(tile_id, transform, shape).ravel()
    return data[keep], labels[keep]


def build_train_set(tile_ids: list[str], comp_dir: Path, labels_dir: Path, per_tile: int, seed: int):
    rng = np.random.default_rng(seed)
    xs, ys = [], []
    for tid in tile_ids:
        try:
            x, y = tile_pixels(comp_dir, labels_dir, tid)
        except FileNotFoundError:
            log(f"train: missing inputs for {tid}, skipped")
            continue
        if len(x) > per_tile:
            idx = np.sort(rng.choice(len(x), per_tile, replace=False))
            x, y = x[idx], y[idx]
        xs.append(x)
        ys.append(y)
    return np.concatenate(xs), np.concatenate(ys)


def evaluate(model_path: Path, tile_ids: list[str], comp_dir: Path, labels_dir: Path) -> dict:
    """Confusion counts per season over every own-cell, in-footprint pixel of the tiles."""
    import torch

    from ricemap.model import load_checkpoint

    model, means, stds, _ = load_checkpoint(model_path)
    dev = next(model.parameters()).device
    model.eval()
    cm = {s: {"tp": 0, "fp": 0, "fn": 0, "tn": 0} for s in SEASONS}
    n_pix = 0
    for tid in tile_ids:
        try:
            x, y = tile_pixels(comp_dir, labels_dir, tid)
        except FileNotFoundError:
            log(f"eval: missing inputs for {tid}, skipped")
            continue
        n_pix += len(x)
        for i in range(0, len(x), 65536):
            xb = (x[i : i + 65536].astype(np.float32) - means) / stds
            xb = torch.from_numpy(np.ascontiguousarray(xb.transpose(0, 2, 1))).to(dev)
            with torch.no_grad():
                p = (torch.sigmoid(model(xb)) >= 0.5).cpu().numpy()
            t = y[i : i + 65536].astype(bool)
            for k, s in enumerate(SEASONS):
                cm[s]["tp"] += int((p[:, k] & t[:, k]).sum())
                cm[s]["fp"] += int((p[:, k] & ~t[:, k]).sum())
                cm[s]["fn"] += int((~p[:, k] & t[:, k]).sum())
                cm[s]["tn"] += int((~p[:, k] & ~t[:, k]).sum())
    res = {"pixels": n_pix, "tiles": len(tile_ids)}
    for s, c in cm.items():
        tp, fp, fn = c["tp"], c["fp"], c["fn"]
        res[s] = {
            **c,
            "precision": round(tp / (tp + fp), 4) if tp + fp else None,
            "recall": round(tp / (tp + fn), 4) if tp + fn else None,
            "f1": round(2 * tp / (2 * tp + fp + fn), 4) if tp + fp + fn else None,
            "iou": round(tp / (tp + fp + fn), 4) if tp + fp + fn else None,
        }
    return res


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", type=Path, required=True)
    ap.add_argument("--labels-raw", type=Path, required=True)
    ap.add_argument("--bbs-csv", type=Path, required=True)
    ap.add_argument("--stage", default="all", choices=["all", "grid", "composite17", "labels", "train", "eval", "stream", "aggregate"])
    ap.add_argument("--procs", type=int, default=8)
    ap.add_argument("--threads", type=int, default=4)
    ap.add_argument("--per-tile", type=int, default=100_000)
    ap.add_argument("--epochs", type=int, default=10)
    ap.add_argument("--batch-size", type=int, default=4096)
    ap.add_argument("--samples-per-epoch", type=int, default=8_000_000)
    ap.add_argument("--delete-composites", action="store_true", help="drop 2022/2023 composites after inference")
    ap.add_argument("--limit", type=int, default=0, help="first N tiles only (smoke test)")
    a = ap.parse_args()

    work = a.work
    comp, lab, models, pred, agg = (work / d for d in ["composites", "labels", "models", "predictions", "aggregates"])
    for d in (comp, lab, models, pred, agg):
        d.mkdir(parents=True, exist_ok=True)
    stages = ["grid", "composite17", "labels", "train", "eval", "stream", "aggregate"] if a.stage == "all" else [a.stage]

    tiles = load_tiles(work, a.labels_raw)
    if a.limit:
        tiles = sorted(tiles, key=lambda t: t.tile_id)[: a.limit]
    log(f"{len(tiles)} tiles")
    tds = [t.__dict__ for t in tiles]

    from ricemap.model import spatial_tile_split

    splits = spatial_tile_split([t.tile_id for t in tiles], seed=42)
    (work / "split.json").write_text(json.dumps(splits, indent=1))

    if "composite17" in stages:
        done = run_pool(_composite, [(d, TRAIN_YEAR, str(comp), a.threads) for d in tds], a.procs, "composite 2017")
        with open(work / "composite_times.jsonl", "a") as f:
            for tid, yr, sec in done:
                f.write(json.dumps({"tile": tid, "year": yr, "seconds": round(sec, 1)}) + "\n")

    if "labels" in stages:
        run_pool(_labels, [(d, str(a.labels_raw), str(lab)) for d in tds], a.procs, "labels")

    cnn_p, lr_p = models / "cnn.pt", models / "logreg.pt"
    if "train" in stages and not (cnn_p.exists() and lr_p.exists()):
        from ricemap.model import (
            BaselineLogisticRegression,
            TemporalRiceCNN,
            compute_normalization_stats,
            save_checkpoint,
            train_model,
        )

        x, y = build_train_set(splits["train"], comp, lab, a.per_tile, seed=42)
        log(f"train set: {len(x):,} pixels from {len(splits['train'])} tiles; positive rates {y.mean(axis=0).round(4).tolist()}")
        means, stds = compute_normalization_stats(np.array_split(x, max(1, len(x) // 1_000_000)))
        log(f"float64 stats: VV mean {means[0,0,0]:.3f} sd {stds[0,0,0]:.3f}; VH mean {means[0,0,1]:.3f} sd {stds[0,0,1]:.3f}")
        xn = ((x.astype(np.float32) - means) / stds).astype(np.float32)
        del x
        meta = {"train_pixels": int(len(xn)), "train_tiles": len(splits["train"]), "per_tile": a.per_tile,
                "epochs": a.epochs, "batch_size": a.batch_size, "samples_per_epoch": a.samples_per_epoch}
        for name, model, path in [("cnn", TemporalRiceCNN(), cnn_p), ("logistic_regression", BaselineLogisticRegression(), lr_p)]:
            r = train_model(model, xn, y, epochs=a.epochs, batch_size=a.batch_size, samples_per_epoch=a.samples_per_epoch)
            log(f"{name}: trained in {r['train_time_seconds']} s, final loss {r['history'][-1]['loss']:.4f}")
            save_checkpoint(model, means, stds, name, path, extra_meta={**meta, "history": r["history"]})
        del xn

    if "eval" in stages:
        out = {}
        for name, path in [("cnn", cnn_p), ("logistic_regression", lr_p)]:
            out[name] = evaluate(path, splits["test"], comp, lab)
            log(f"test {name}: " + ", ".join(f"{s} IoU {out[name][s]['iou']}" for s in SEASONS))
        (work / "test_metrics.json").write_text(json.dumps(out, indent=1))

    if "stream" in stages:
        from ricemap.infer import run_tile_inference

        for yr in YEARS:
            todo = [d for d in tds if not (pred / f"{d['tile_id']}_{yr}_rice_20m.tif").exists()]
            log(f"stream {yr}: {len(todo)} tile-years to do")
            with ProcessPoolExecutor(max_workers=a.procs, mp_context=SPAWN) as ex:
                futs = {ex.submit(_composite, (d, yr, str(comp), a.threads)): d for d in todo}
                for i, f in enumerate(as_completed(futs), 1):
                    try:
                        tid, _, sec = f.result()
                    except Exception as e:  # noqa: BLE001
                        log(f"composite {futs[f]['tile_id']} {yr} failed: {e!r}")
                        continue
                    npz = comp / f"{tid}_{yr}_timeseries.npz"
                    with np.load(npz) as z:
                        (work / "composite_meta").mkdir(exist_ok=True)
                        (work / "composite_meta" / f"{tid}_{yr}.json").write_text(str(z["metadata"]))
                    run_tile_inference(cnn_p, npz, out_dir=pred)
                    if a.delete_composites and yr != TRAIN_YEAR:
                        npz.unlink()
                    if i % 20 == 0 or i == len(todo):
                        log(f"stream {yr}: {i}/{len(todo)}")

    if "aggregate" in stages:
        from ricemap.aggregate import aggregate_rice_area_by_admin
        from ricemap.validate import validate_district_predictions

        for yr in YEARS:
            tifs = sorted(pred.glob(f"*_{yr}_rice_20m.tif"))
            if not tifs:
                continue
            aggregate_rice_area_by_admin(tifs, "ADM2", yr, cache_dir=work / "geoboundaries", out_csv=agg / f"district_area_{yr}.csv")
            aggregate_rice_area_by_admin(tifs, "ADM3", yr, cache_dir=work / "geoboundaries", out_csv=agg / f"upazila_area_{yr}.csv")
            if yr in (2022, 2023):
                validate_district_predictions(agg / f"district_area_{yr}.csv", a.bbs_csv, yr,
                                              out_csv=agg / f"validation_{yr}.csv",
                                              name_map_csv=agg / "district_name_map.csv")
        log("aggregate done")

    log("finished")


if __name__ == "__main__":
    os.environ.setdefault("OMP_NUM_THREADS", "2")
    main()
