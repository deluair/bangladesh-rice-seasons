"""PyTorch model architectures, spatial splitting, and training for rice season classification.

Implements:
1. TemporalRiceCNN (small 1D temporal convolutional network with 3 independent binary heads)
2. TemporalRiceTransformer (lightweight temporal transformer encoder)
3. BaselineLogisticRegression (linear classification baseline on 60 temporal features)
4. Tile-based spatial partitioning (80/10/10 or custom tile splits)
5. Float64 normalization accumulation (per PILOT_REPORT gate note)
"""

from __future__ import annotations

import math
import random
import time
from pathlib import Path
from typing import Any

import numpy as np
import torch
from sklearn.metrics import f1_score, jaccard_score, precision_score, recall_score
from torch import nn

SEASONS = ["Aus", "Aman", "Boro"]


def get_auto_device() -> torch.device:
    """Select best available device: CUDA -> MPS -> CPU."""
    if torch.cuda.is_available():
        return torch.device("cuda")
    if hasattr(torch.backends, "mps") and torch.backends.mps.is_available():
        return torch.device("mps")
    return torch.device("cpu")


class TemporalRiceCNN(nn.Module):
    """Small 1D Temporal CNN with 3 independent binary heads for Aus, Aman, Boro."""

    def __init__(self, in_channels: int = 2, seq_len: int = 30, num_classes: int = 3):
        super().__init__()
        self.conv = nn.Sequential(
            nn.Conv1d(in_channels, 32, kernel_size=3, padding=1),
            nn.BatchNorm1d(32),
            nn.ReLU(),
            nn.MaxPool1d(2),  # 30 -> 15
            nn.Conv1d(32, 64, kernel_size=3, padding=1),
            nn.BatchNorm1d(64),
            nn.ReLU(),
            nn.AdaptiveAvgPool1d(1),  # (batch, 64, 1)
        )
        self.fc = nn.Sequential(
            nn.Linear(64, 32),
            nn.ReLU(),
            nn.Dropout(0.2),
            nn.Linear(32, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, 2, 30)
        feat = self.conv(x).squeeze(-1)
        return self.fc(feat)


class PositionalEncoding(nn.Module):
    def __init__(self, d_model: int, max_len: int = 60):
        super().__init__()
        pe = torch.zeros(max_len, d_model)
        position = torch.arange(0, max_len, dtype=torch.float).unsqueeze(1)
        div_term = torch.exp(torch.arange(0, d_model, 2).float() * (-math.log(10000.0) / d_model))
        pe[:, 0::2] = torch.sin(position * div_term)
        pe[:, 1::2] = torch.cos(position * div_term)
        self.register_buffer("pe", pe.unsqueeze(0))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, seq_len, d_model)
        return x + self.pe[:, : x.size(1)]


class TemporalRiceTransformer(nn.Module):
    """Lightweight temporal transformer encoder with 3 independent binary heads."""

    def __init__(
        self,
        in_channels: int = 2,
        seq_len: int = 30,
        num_classes: int = 3,
        d_model: int = 32,
        nhead: int = 4,
        num_layers: int = 2,
        dim_feedforward: int = 64,
        dropout: float = 0.1,
    ):
        super().__init__()
        self.input_proj = nn.Linear(in_channels, d_model)
        self.pos_enc = PositionalEncoding(d_model, max_len=seq_len + 10)
        encoder_layer = nn.TransformerEncoderLayer(
            d_model=d_model,
            nhead=nhead,
            dim_feedforward=dim_feedforward,
            dropout=dropout,
            batch_first=True,
        )
        self.transformer = nn.TransformerEncoder(encoder_layer, num_layers=num_layers)
        self.classifier = nn.Sequential(
            nn.Linear(d_model, 32),
            nn.ReLU(),
            nn.Dropout(dropout),
            nn.Linear(32, num_classes),
        )

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x: (batch, 2, 30) -> transpose to (batch, 30, 2)
        x_seq = x.transpose(1, 2)
        proj = self.input_proj(x_seq)
        encoded = self.transformer(self.pos_enc(proj))
        # Global average pool over time
        pooled = encoded.mean(dim=1)
        return self.classifier(pooled)


class BaselineLogisticRegression(nn.Module):
    """Logistic Regression baseline on 60 temporal features (30 VV + 30 VH)."""

    def __init__(self, in_features: int = 60, num_classes: int = 3):
        super().__init__()
        self.linear = nn.Linear(in_features, num_classes)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        # x can be (batch, 2, 30) or (batch, 60)
        if x.dim() == 3:
            x = x.reshape(x.size(0), -1)
        return self.linear(x)


def compute_metrics(
    y_true: np.ndarray,
    y_pred: np.ndarray,
    season_names: list[str] = SEASONS,
) -> dict[str, dict[str, float]]:
    """Compute Precision, Recall, F1, and IoU (Jaccard) per season."""
    metrics = {}
    for i, name in enumerate(season_names):
        yt = y_true[:, i]
        yp = y_pred[:, i]
        prec = float(precision_score(yt, yp, zero_division=0))
        rec = float(recall_score(yt, yp, zero_division=0))
        f1 = float(f1_score(yt, yp, zero_division=0))
        iou = float(jaccard_score(yt, yp, zero_division=0))
        metrics[name] = {
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1": round(f1, 4),
            "iou": round(iou, 4),
            "positive_rate_labels": round(float(yt.mean()), 4),
            "positive_rate_predicted": round(float(yp.mean()), 4),
        }
    return metrics


def spatial_tile_split(
    tile_ids: list[str],
    train_ratio: float = 0.8,
    val_ratio: float = 0.1,
    test_ratio: float = 0.1,
    seed: int = 42,
) -> dict[str, list[str]]:
    """Partition tiles into train, validation, and test sets by tile (never by pixel)."""
    assert abs((train_ratio + val_ratio + test_ratio) - 1.0) < 1e-5
    rng = random.Random(seed)
    shuffled = sorted(tile_ids)
    rng.shuffle(shuffled)

    n_total = len(shuffled)
    n_train = round(train_ratio * n_total)
    n_val = round(val_ratio * n_total)

    train_tiles = shuffled[:n_train]
    val_tiles = shuffled[n_train : n_train + n_val]
    test_tiles = shuffled[n_train + n_val :]

    # Handle boundary case with 2 tiles
    if n_total == 2:
        return {"train": [shuffled[0]], "val": [], "test": [shuffled[1]]}

    return {
        "train": train_tiles,
        "val": val_tiles,
        "test": test_tiles,
    }


def compute_normalization_stats(
    train_arrays: list[np.ndarray],
) -> tuple[np.ndarray, np.ndarray]:
    """Accumulate mean and std across train tiles strictly in float64.

    Addresses the pilot Gate note: accumulation over >100M values must be in float64.
    """
    total_elements = 0
    sum_vals = np.zeros((1, 1, 2), dtype=np.float64)
    sum_sq_vals = np.zeros((1, 1, 2), dtype=np.float64)

    for arr in train_arrays:
        # arr shape: [pixels, 30, 2]
        arr_f64 = arr.astype(np.float64)
        n = arr_f64.shape[0] * arr_f64.shape[1]
        sum_vals += arr_f64.sum(axis=(0, 1), keepdims=True)
        sum_sq_vals += (arr_f64**2).sum(axis=(0, 1), keepdims=True)
        total_elements += n

    mean_f64 = sum_vals / total_elements
    var_f64 = (sum_sq_vals / total_elements) - (mean_f64**2)
    std_f64 = np.sqrt(np.maximum(var_f64, 1e-12)) + 1e-6

    return mean_f64.astype(np.float32), std_f64.astype(np.float32)


def train_model(
    model: nn.Module,
    train_data: np.ndarray,
    train_labels: np.ndarray,
    val_data: np.ndarray | None = None,
    val_labels: np.ndarray | None = None,
    epochs: int = 5,
    batch_size: int = 16384,
    lr: float = 0.005,
    samples_per_epoch: int | None = 200000,
    device: torch.device | None = None,
) -> dict[str, Any]:
    """Train a multi-season binary classification model."""
    if device is None:
        device = get_auto_device()
    print(f"Training on device: {device}")

    model = model.to(device)
    criterion = nn.BCEWithLogitsLoss()
    optimizer = torch.optim.Adam(model.parameters(), lr=lr)

    n_train = train_data.shape[0]

    # Pre-transpose train data to (batch, 2, 30)
    X_train_t = torch.from_numpy(np.ascontiguousarray(np.transpose(train_data, (0, 2, 1))))
    y_train_t = torch.from_numpy(np.ascontiguousarray(train_labels.astype(np.float32)))

    history: list[dict[str, float]] = []

    t0 = time.time()
    for ep in range(epochs):
        model.train()
        epoch_loss = 0.0

        if samples_per_epoch and samples_per_epoch < n_train:
            perm = torch.randperm(n_train)[:samples_per_epoch]
            n_sub = samples_per_epoch
        else:
            perm = torch.randperm(n_train)
            n_sub = n_train

        for i in range(0, n_sub, batch_size):
            idx = perm[i : i + batch_size]
            bx = X_train_t[idx].to(device)
            by = y_train_t[idx].to(device)

            optimizer.zero_grad()
            out = model(bx)
            loss = criterion(out, by)
            loss.backward()
            optimizer.step()
            epoch_loss += loss.item() * len(bx)

        mean_loss = epoch_loss / n_sub
        print(f"  Epoch {ep+1}/{epochs} - Train Loss: {mean_loss:.4f}")
        history.append({"epoch": ep + 1, "loss": mean_loss})

    train_time = time.time() - t0

    # Evaluate on validation data if provided
    val_metrics = None
    if val_data is not None and val_labels is not None:
        model.eval()
        n_val = val_data.shape[0]
        X_val_t = torch.from_numpy(np.ascontiguousarray(np.transpose(val_data, (0, 2, 1))))
        val_preds = []

        with torch.no_grad():
            for i in range(0, n_val, batch_size):
                bx = X_val_t[i : i + batch_size].to(device)
                logits = model(bx)
                probs = torch.sigmoid(logits)
                val_preds.append((probs >= 0.5).cpu().numpy().astype(np.uint8))

        y_pred = np.vstack(val_preds)
        val_metrics = compute_metrics(val_labels.astype(np.uint8), y_pred)

    return {
        "train_time_seconds": round(train_time, 2),
        "history": history,
        "val_metrics": val_metrics,
    }


def save_checkpoint(
    model: nn.Module,
    ch_means: np.ndarray,
    ch_stds: np.ndarray,
    model_type: str,
    out_path: str | Path,
    extra_meta: dict[str, Any] | None = None,
) -> Path:
    out_p = Path(out_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state_dict": model.state_dict(),
        "model_type": model_type,
        "ch_means": ch_means,
        "ch_stds": ch_stds,
        "extra_meta": extra_meta or {},
    }
    torch.save(payload, out_p)
    print(f"Saved model checkpoint to {out_p}")
    return out_p


def load_checkpoint(
    ckpt_path: str | Path,
    device: torch.device | None = None,
) -> tuple[nn.Module, np.ndarray, np.ndarray, dict[str, Any]]:
    if device is None:
        device = get_auto_device()
    payload = torch.load(ckpt_path, map_location=device, weights_only=False)
    model_type = payload.get("model_type", "cnn")
    if model_type == "cnn":
        model: nn.Module = TemporalRiceCNN()
    elif model_type == "transformer":
        model = TemporalRiceTransformer()
    elif model_type == "logistic_regression":
        model = BaselineLogisticRegression()
    else:
        raise ValueError(f"Unknown model type: {model_type}")

    model.load_state_dict(payload["state_dict"])
    model.to(device)
    model.eval()
    return model, payload["ch_means"], payload["ch_stds"], payload.get("extra_meta", {})
