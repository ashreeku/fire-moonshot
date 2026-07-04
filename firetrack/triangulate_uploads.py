"""Mocap-free triangulation from user-supplied camera calibration (upload mode).

Reuses the generic projective-geometry helpers from ``triangulate_527`` and feeds
them camera poses the user provides (K, dist, R, t in world->camera convention)
instead of poses solved from motion capture. No mocap means no ground-truth error
metrics, but the 3D trajectory itself is produced the same way.

The proven 5-27 mocap path in ``triangulate_527`` is left completely untouched.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from .ekf import ekf_smooth_trajectory
from .triangulate_527 import (
    Observation,
    interpolate_centroid,
    select_best_triangulation,
    undistort_pixel,
    write_csv,
)

UPLOAD_SUBDIR = "uploads"
DEFAULT_DIST = (0.0, 0.0, 0.0, 0.0, 0.0)


def _is_matrix(value: object, rows: int, cols: int) -> bool:
    return (
        isinstance(value, list)
        and len(value) == rows
        and all(isinstance(r, list) and len(r) == cols for r in value)
        and all(isinstance(x, (int, float)) for r in value for x in r)
    )


def _is_vector(value: object, length: int) -> bool:
    return isinstance(value, list) and len(value) == length and all(
        isinstance(x, (int, float)) for x in value
    )


def validate_calibration(data: object) -> list[dict]:
    """Validate an upload calibration document and return its camera entries.

    Pure validation (no file/numpy work) so it is cheap to unit-test. Raises
    ValueError with a user-facing message on the first problem found.
    """
    if not isinstance(data, dict) or not isinstance(data.get("cameras"), list):
        raise ValueError("Calibration must be an object with a 'cameras' list.")
    cameras = data["cameras"]
    if not cameras:
        raise ValueError("Calibration has no cameras.")
    seen: set[str] = set()
    for i, cam in enumerate(cameras):
        where = f"cameras[{i}]"
        if not isinstance(cam, dict):
            raise ValueError(f"{where} must be an object.")
        video = cam.get("video")
        if not isinstance(video, str) or not video:
            raise ValueError(f"{where}.video must name an uploaded clip.")
        if video in seen:
            raise ValueError(f"Duplicate camera video {video!r}.")
        seen.add(video)
        if not _is_matrix(cam.get("K"), 3, 3):
            raise ValueError(f"{where}.K must be a 3x3 matrix.")
        if "R" in cam and not _is_matrix(cam["R"], 3, 3):
            raise ValueError(f"{where}.R must be a 3x3 matrix (world->camera).")
        if "rvec" in cam and not _is_vector(cam["rvec"], 3):
            raise ValueError(f"{where}.rvec must be a length-3 vector.")
        if "quat" in cam and not _is_vector(cam["quat"], 4):
            raise ValueError(f"{where}.quat must be [x, y, z, w].")
        if "euler" in cam:
            e = cam["euler"]
            if not (isinstance(e, dict) and all(isinstance(e.get(k), (int, float)) for k in ("pitch", "yaw", "roll"))):
                raise ValueError(f"{where}.euler must have numeric pitch, yaw, roll.")
            if cam.get("euler_order", "ZYX") not in ("ZYX", "XYZ", "ZXY", "YXZ", "XZY", "YZX"):
                raise ValueError(f"{where}.euler_order must be a permutation of XYZ.")
        if not any(k in cam for k in ("R", "rvec", "quat", "euler")):
            raise ValueError(f"{where} needs a rotation: R (3x3), rvec (3), quat (4), or euler.")
        has_t = _is_vector(cam.get("t"), 3)
        has_pos = _is_vector(cam.get("position"), 3)
        if "position" in cam and not has_pos:
            raise ValueError(f"{where}.position must be the camera's world position [x, y, z].")
        if not (has_t or has_pos):
            raise ValueError(f"{where} needs either t (world->camera) or position (camera world location).")
        if cam.get("pose_convention", "c2w") not in ("c2w", "w2c"):
            raise ValueError(f"{where}.pose_convention must be 'c2w' or 'w2c'.")
        if "resolution" in cam and not _is_vector(cam["resolution"], 2):
            raise ValueError(f"{where}.resolution must be [width, height].")
        if "dist" in cam and not (isinstance(cam["dist"], list) and len(cam["dist"]) >= 4):
            raise ValueError(f"{where}.dist must list >=4 distortion coefficients.")
        if "start_epoch_s" in cam and not isinstance(cam["start_epoch_s"], (int, float)):
            raise ValueError(f"{where}.start_epoch_s must be a number (seconds).")
    return cameras


def _elem_rotation(axis: str, angle: float) -> np.ndarray:
    c, s = math.cos(angle), math.sin(angle)
    if axis == "X":
        return np.array([[1, 0, 0], [0, c, -s], [0, s, c]], dtype=np.float64)
    if axis == "Y":
        return np.array([[c, 0, s], [0, 1, 0], [-s, 0, c]], dtype=np.float64)
    return np.array([[c, -s, 0], [s, c, 0], [0, 0, 1]], dtype=np.float64)  # Z


def euler_to_matrix(pitch: float, yaw: float, roll: float,
                    order: str = "ZYX", degrees: bool = True) -> np.ndarray:
    """Rotation from Tait-Bryan angles. roll->X, pitch->Y, yaw->Z.

    ``order`` lists the axes left-to-right in multiplication order, e.g. "ZYX"
    means R = Rz(yaw) @ Ry(pitch) @ Rx(roll) (apply roll, then pitch, then yaw).
    """
    if degrees:
        pitch, yaw, roll = math.radians(pitch), math.radians(yaw), math.radians(roll)
    angle = {"X": roll, "Y": pitch, "Z": yaw}
    R = np.eye(3, dtype=np.float64)
    for axis in order:
        R = R @ _elem_rotation(axis, angle[axis])
    return R


def rotation_matrix(spec: dict) -> np.ndarray:
    """Build a 3x3 rotation from whichever form the camera provides (world->camera)."""
    if "R" in spec:
        return np.array(spec["R"], dtype=np.float64)
    if "euler" in spec:
        e = spec["euler"]
        return euler_to_matrix(e["pitch"], e["yaw"], e["roll"],
                               order=spec.get("euler_order", "ZYX"),
                               degrees=spec.get("euler_degrees", True))
    if "quat" in spec:
        x, y, z, w = (float(v) for v in spec["quat"])
        norm = math.sqrt(x * x + y * y + z * z + w * w)
        if norm == 0.0:
            raise ValueError("quaternion has zero norm")
        x, y, z, w = x / norm, y / norm, z / norm, w / norm
        return np.array([
            [1 - 2 * (y * y + z * z), 2 * (x * y - w * z), 2 * (x * z + w * y)],
            [2 * (x * y + w * z), 1 - 2 * (x * x + z * z), 2 * (y * z - w * x)],
            [2 * (x * z - w * y), 2 * (y * z + w * x), 1 - 2 * (x * x + y * y)],
        ], dtype=np.float64)
    if "rvec" in spec:
        import cv2

        matrix, _ = cv2.Rodrigues(np.array(spec["rvec"], dtype=np.float64).reshape(3, 1))
        return matrix
    raise ValueError("camera needs a rotation: R, rvec, or quat")


def world_to_camera(spec: dict) -> tuple[np.ndarray, np.ndarray]:
    """Resolve a camera's world->camera (R, t) from either representation.

    - Direct: ``t`` is the world->camera translation, paired with the rotation.
    - Pose: ``position`` is the camera's world location, with the rotation read as
      camera->world (``pose_convention='c2w'``, default) or world->camera ('w2c').
      Then R_wc = orientation(.T) and t = -R_wc @ position.
    """
    orientation = rotation_matrix(spec)
    if "position" in spec:
        center = np.array(spec["position"], dtype=np.float64)
        R = orientation.T if spec.get("pose_convention", "c2w") == "c2w" else orientation
        return R, -R @ center
    return orientation, np.array(spec["t"], dtype=np.float64)


def rotation_issue(R: np.ndarray) -> str | None:
    """Return a message if R is not a proper rotation, else None."""
    if not np.allclose(R.T @ R, np.eye(3), atol=1e-2):
        return "R is not orthonormal (R^T·R != I) — check the values or convention."
    if not np.isclose(np.linalg.det(R), 1.0, atol=1e-2):
        return "det(R) != +1 — this is a reflection/improper rotation, not a camera pose."
    return None


@dataclass(frozen=True)
class UploadCamera:
    name: str
    K: np.ndarray
    dist: np.ndarray
    R: np.ndarray
    t: np.ndarray
    P: np.ndarray
    centroids: np.ndarray
    fps: float
    start_epoch_s: float


def _scaled_K(K: np.ndarray, resolution, width: int, height: int) -> np.ndarray:
    if not resolution:
        return K
    src_w, src_h = resolution
    out = K.copy()
    out[0, 0] *= width / float(src_w)
    out[0, 2] *= width / float(src_w)
    out[1, 1] *= height / float(src_h)
    out[1, 2] *= height / float(src_h)
    return out


def _load_camera(spec: dict, detections_root: Path) -> UploadCamera:
    cen_path = detections_root / UPLOAD_SUBDIR / spec["video"] / "centroids.npz"
    with np.load(cen_path) as z:
        centroids = np.array(z["centroids"], dtype=np.float64)
        fps = float(z["fps"])
        width = int(z["width"])
        height = int(z["height"])
    K = _scaled_K(np.array(spec["K"], dtype=np.float64), spec.get("resolution"), width, height)
    dist = np.array(spec.get("dist") or DEFAULT_DIST, dtype=np.float64)
    R, t = world_to_camera(spec)
    P = K @ np.hstack([R, t.reshape(3, 1)])
    return UploadCamera(
        name=spec["video"],
        K=K,
        dist=dist,
        R=R,
        t=t,
        P=P,
        centroids=centroids,
        fps=fps,
        start_epoch_s=float(spec.get("start_epoch_s", 0.0)),
    )


def _detected_labels(detections_root: Path) -> set[str]:
    base = detections_root / UPLOAD_SUBDIR
    return {p.parent.name for p in base.glob("*/centroids.npz")} if base.exists() else set()


def _uploaded_labels(uploads_root: Path | None) -> set[str] | None:
    if uploads_root is None or not uploads_root.exists():
        return None
    return {p.name for p in uploads_root.iterdir() if p.is_dir()}


def triangulate_uploads(
    *,
    detections_root: Path,
    calibration_json: Path,
    out_root: Path,
    uploads_root: Path | None = None,
    max_reproj_px: float = 30.0,
) -> dict:
    specs = validate_calibration(json.loads(Path(calibration_json).read_text()))
    detected = _detected_labels(detections_root)
    uploaded = _uploaded_labels(uploads_root)

    cameras: list[UploadCamera] = []
    skipped: list[dict] = []
    for spec in specs:
        name = spec["video"]
        if name in detected:
            cameras.append(_load_camera(spec, detections_root))
        elif uploaded is not None and name not in uploaded:
            avail = ", ".join(sorted(uploaded)) or "no clips uploaded"
            print(f"  [{name}] no uploaded clip with this name. Available: {avail}")
            skipped.append({"camera": name, "reason": "no matching uploaded clip"})
        else:
            print(f"  [{name}] uploaded but not detected yet — run 2D detection first")
            skipped.append({"camera": name, "reason": "not detected"})

    if len(cameras) < 2:
        avail = ", ".join(sorted(detected)) or "none"
        raise RuntimeError(
            f"Need at least 2 cameras with detections; matched {len(cameras)}. "
            f"Detected clips: {avail}. Check the 'video' names in your calibration."
        )

    ref = min(cameras, key=lambda c: len(c.centroids))
    n = len(ref.centroids)
    epoch_times = ref.start_epoch_s + np.arange(n) / ref.fps
    origin = min(c.start_epoch_s for c in cameras)
    times = epoch_times - origin

    trajectory = np.full((n, 3), np.nan, dtype=np.float64)
    n_views = np.zeros(n, dtype=np.int32)
    reproj = np.full(n, np.nan, dtype=np.float64)
    used = np.full(n, "", dtype=object)

    for i, epoch in enumerate(epoch_times):
        obs: list[Observation] = []
        for cam in cameras:
            xy = interpolate_centroid(cam.centroids, epoch, start_epoch_s=cam.start_epoch_s, fps=cam.fps)
            if xy is None:
                continue
            xy_u = undistort_pixel(cam.K, cam.dist, xy)
            obs.append(Observation(cam.name, cam.P, cam.R, cam.t, xy_u))
        result = select_best_triangulation(obs, max_reproj_px=max_reproj_px)
        if result is None:
            continue
        trajectory[i] = result.point
        n_views[i] = result.n_views
        reproj[i] = result.mean_reproj_px
        used[i] = "+".join(result.cam_names)

    smooth = ekf_smooth_trajectory(trajectory, sim_times=times, n_views=n_views, reproj_errors=reproj)
    gt = np.full((n, 3), np.nan, dtype=np.float64)  # no mocap ground truth

    out_dir = out_root / UPLOAD_SUBDIR
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_dir / "trajectory.npz",
        times_s=times,
        epoch_times_s=epoch_times,
        trajectory_raw=trajectory,
        trajectory_smooth=smooth,
        gt_drone=gt,
        n_views=n_views,
        reproj_errors_px=reproj,
        used_cameras=np.array([str(u) for u in used]),
    )
    write_csv(out_dir / "trajectory.csv", times, n_views, reproj, used, trajectory, smooth, gt)
    summary = {
        "run": "uploads",
        "source": "uploaded calibration (no mocap; no ground-truth metrics)",
        "n_frames": int(n),
        "reference_camera": ref.name,
        "cameras": [c.name for c in cameras],
        "skipped_cameras": skipped,
        "camera_start_epochs_s": {c.name: c.start_epoch_s for c in cameras},
        "n_raw_triangulated": int(np.isfinite(trajectory[:, 0]).sum()),
        "n_smooth_finite": int(np.isfinite(smooth[:, 0]).sum()),
        "median_reproj_px": float(np.nanmedian(reproj)) if np.isfinite(reproj).any() else None,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(f"  uploads: {summary['n_raw_triangulated']}/{n} frames from {len(cameras)} cameras")
    return summary
