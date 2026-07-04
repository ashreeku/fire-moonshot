"""Read-only access to pipeline outputs for the Results view.

Surfaces what the dashboard needs to *show* the work: per-camera 2D detections
(centroids over video frames) and 3D reconstructions (triangulated trajectories).
All paths are validated against their root to prevent traversal from query params.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path

import numpy as np

from .triangulate_527 import score_trajectory

MAX_TRAJ_POINTS = 3000


def _safe_subdir(root: Path, rel: str) -> Path:
    root = root.resolve()
    target = (root / rel).resolve()
    if target != root and root not in target.parents:
        raise ValueError("path escapes root")
    return target


def _source_of(rel: str) -> str:
    return "upload" if str(rel).replace("\\", "/").startswith("uploads/") or rel == "uploads" else "dataset"


def list_detections(detections_root: Path) -> list[dict]:
    root = Path(detections_root)
    if not root.exists():
        return []
    rows: list[dict] = []
    for summ in sorted(root.glob("**/summary.json")):
        try:
            s = json.loads(summ.read_text())
        except (json.JSONDecodeError, OSError):
            continue
        rel = s.get("relative_dir")
        if not rel or not (summ.parent / "centroids.npz").exists():
            continue
        rows.append({
            "dir": str(rel),
            "label": s.get("label", str(rel)),
            "source": _source_of(str(rel)),
            "n_frames": s.get("n_frames"),
            "n_detected": s.get("n_detected"),
            "detection_rate": s.get("detection_rate"),
        })
    return rows


def list_trajectories(triangulation_root: Path) -> list[dict]:
    root = Path(triangulation_root)
    if not root.exists():
        return []
    rows: list[dict] = []
    for traj in sorted(root.glob("**/trajectory.npz")):
        rel = traj.parent.relative_to(root)
        rows.append({
            "dir": str(rel),
            "run": rel.name or str(rel),
            "source": _source_of(str(rel)),
        })
    return rows


def _clean2d(arr: np.ndarray) -> list:
    a = np.asarray(arr, dtype=np.float64)
    return [[None if not math.isfinite(v) else float(v) for v in row] for row in a]


def _clean1d(arr: np.ndarray) -> list:
    return [None if not math.isfinite(float(v)) else float(v) for v in np.asarray(arr, dtype=np.float64)]


@lru_cache(maxsize=64)
def video_path_for(detections_root: str, rel: str) -> str:
    path = _safe_subdir(Path(detections_root), rel) / "centroids.npz"
    with np.load(path) as z:
        return str(z["video_path"])


def load_centroids(detections_root: Path, rel: str) -> dict:
    path = _safe_subdir(Path(detections_root), rel) / "centroids.npz"
    with np.load(path) as z:
        centroids = np.array(z["centroids"], dtype=np.float64)
        return {
            "centroids": _clean2d(centroids),
            "width": int(z["width"]),
            "height": int(z["height"]),
            "fps": float(z["fps"]),
            "n_frames": int(len(centroids)),
            "n_detected": int(np.isfinite(centroids[:, 0]).sum()),
        }


def apply_centroid_edits(detections_root: Path, rel: str, edits: list[dict]) -> dict:
    """Apply manual per-frame corrections to a detection's centroids and save.

    Each edit is ``{"frame": i, "x": ..., "y": ...}`` to set a point, or
    ``{"frame": i, "clear": true}`` to mark the frame as no-detection. All other
    npz fields and the summary's metadata are preserved.
    """
    path = _safe_subdir(Path(detections_root), rel) / "centroids.npz"
    data = dict(np.load(path, allow_pickle=True))  # preserve every stored field
    centroids = np.array(data["centroids"], dtype=np.float64)
    n = len(centroids)
    for edit in edits:
        frame = int(edit["frame"])
        if frame < 0 or frame >= n:
            raise ValueError(f"frame {frame} out of range [0, {n})")
        if edit.get("clear"):
            centroids[frame] = [np.nan, np.nan]
            continue
        x, y = float(edit["x"]), float(edit["y"])
        if not (math.isfinite(x) and math.isfinite(y)):
            raise ValueError("x and y must be finite numbers")
        centroids[frame] = [x, y]

    data["centroids"] = centroids
    np.savez(path, **data)
    n_detected = int(np.isfinite(centroids[:, 0]).sum())

    summary = path.parent / "summary.json"
    if summary.exists():
        try:
            s = json.loads(summary.read_text())
            s["n_detected"] = n_detected
            s["detection_rate"] = n_detected / n if n else 0.0
            summary.write_text(json.dumps(s, indent=2, sort_keys=True))
        except (json.JSONDecodeError, OSError):
            pass
    return {"n_frames": n, "n_detected": n_detected}


def trajectory_file(triangulation_root: Path, rel: str, fmt: str) -> Path:
    """Resolve a downloadable trajectory artifact (csv or npz), traversal-safe."""
    name = {"csv": "trajectory.csv", "npz": "trajectory.npz"}.get(fmt)
    if name is None:
        raise ValueError("fmt must be 'csv' or 'npz'")
    path = _safe_subdir(Path(triangulation_root), rel) / name
    if not path.exists():
        raise FileNotFoundError(name)
    return path


def load_trajectory(triangulation_root: Path, rel: str) -> dict:
    path = _safe_subdir(Path(triangulation_root), rel) / "trajectory.npz"
    with np.load(path, allow_pickle=True) as z:
        raw = np.array(z["trajectory_raw"], dtype=np.float64)
        smooth = np.array(z["trajectory_smooth"], dtype=np.float64)
        gt = np.array(z["gt_drone"], dtype=np.float64)
        n_views = np.array(z["n_views"], dtype=np.int64)
        reproj = np.array(z["reproj_errors_px"], dtype=np.float64)
    n = len(raw)
    stride = max(1, math.ceil(n / MAX_TRAJ_POINTS))
    sl = slice(None, None, stride)
    has_gt = bool(np.isfinite(gt[:, 0]).any())
    return {
        "raw": _clean2d(raw[sl]),
        "smooth": _clean2d(smooth[sl]),
        "gt": _clean2d(gt[sl]) if has_gt else None,
        "n_views": [int(v) for v in n_views[sl]],
        "reproj": _clean1d(reproj[sl]),
        "n_frames": n,
        "stride": stride,
        "metrics": {
            "n_triangulated": int(np.isfinite(raw[:, 0]).sum()),
            "median_reproj_px": float(np.nanmedian(reproj)) if np.isfinite(reproj).any() else None,
            "has_gt": has_gt,
            "rmse_smooth_m": score_trajectory(smooth, gt)["rmse_m"] if has_gt else None,
        },
    }
