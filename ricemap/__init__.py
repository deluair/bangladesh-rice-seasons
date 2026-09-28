"""bangladesh-rice-seasons national pipeline package."""

from ricemap.aggregate import aggregate_rice_area_by_admin, fetch_admin_boundaries
from ricemap.composite import build_tile_timeseries
from ricemap.infer import run_tile_inference
from ricemap.labels import extract_tile_labels
from ricemap.model import (
    BaselineLogisticRegression,
    TemporalRiceCNN,
    TemporalRiceTransformer,
    load_checkpoint,
    save_checkpoint,
    train_model,
)
from ricemap.s1 import fetch_s1_band_20m, query_s1_scenes
from ricemap.tiles import Tile, generate_national_grid, get_tile_by_id
from ricemap.validate import validate_district_predictions

__all__ = [
    "BaselineLogisticRegression",
    "TemporalRiceCNN",
    "TemporalRiceTransformer",
    "Tile",
    "aggregate_rice_area_by_admin",
    "build_tile_timeseries",
    "extract_tile_labels",
    "fetch_admin_boundaries",
    "fetch_s1_band_20m",
    "generate_national_grid",
    "get_tile_by_id",
    "load_checkpoint",
    "query_s1_scenes",
    "run_tile_inference",
    "save_checkpoint",
    "train_model",
    "validate_district_predictions",
]
