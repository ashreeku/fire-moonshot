"""Mocap-calibrated triangulation for normalized 5-27 recordings."""
from __future__ import annotations

import csv
import json
import math
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np

from .ekf import ekf_smooth_trajectory
from .mocap import MocapRun6D, load_mocap_6d

RUNS = [
    "ardu_run1",
    "ardu_run2",
    "ardu_run3",
    "px4_points1",
    "px4_points2",
    "px4_points3",
    "px4_traj1",
    "px4_traj2",
    "px4_traj3",
]
PHONES = ["galaxyS21", "galaxyS8", "pixel9"]
MOCAP_BODY = {"galaxyS21": "Camera2", "galaxyS8": "camera3", "pixel9": "camera1"}
CALIB_RUN = {
    ("galaxyS8", "all"): "ardu_run1",
    ("pixel9", "all"): "ardu_run1",
    ("galaxyS21", "ardu"): "ardu_run1",
    ("galaxyS21", "px4"): "px4_points1",
}
EXCLUDE_CAMERAS = {"px4_traj1": {"galaxyS21"}}
DRONE_BODY = "drone"


@dataclass(frozen=True)
class Intrinsics:
    K: np.ndarray
    dist_coeffs: np.ndarray
    source_resolution: tuple[int, int]
    target_resolution: tuple[int, int]


@dataclass(frozen=True)
class SessionData:
    label: str
    phone: str
    session_dir: Path
    centroids_path: Path
    centroids: np.ndarray
    fps: float
    width: int
    height: int
    video_start_epoch_s: float
    intrinsics: Intrinsics


@dataclass(frozen=True)
class Correspondences:
    frame_indices: np.ndarray
    mocap_indices: np.ndarray
    points_world: np.ndarray
    points_image: np.ndarray


@dataclass(frozen=True)
class FitResult:
    rvec: np.ndarray
    tvec: np.ndarray
    inlier_indices: np.ndarray
    errors_px: np.ndarray


@dataclass(frozen=True)
class Observation:
    cam_name: str
    P: np.ndarray
    R: np.ndarray
    t: np.ndarray
    xy: np.ndarray


@dataclass(frozen=True)
class PointResult:
    point: np.ndarray
    cam_names: list[str]
    n_views: int
    mean_reproj_px: float
    max_reproj_px: float
    all_observation_median_px: float


@dataclass(frozen=True)
class CamCalib:
    phone: str
    config: str
    mocap_body: str
    calib_run: str
    K: np.ndarray
    dist_coeffs: np.ndarray
    rvec: np.ndarray
    tvec: np.ndarray
    nominal_offset_s: float
    calib_reproj_med_px: float


def config_for(run: str, phone: str) -> str:
    if phone == "galaxyS21":
        return "ardu" if run.startswith("ardu") else "px4"
    return "all"


def mocap_path(data_root: Path, run: str) -> Path:
    d = data_root / run / run
    for name in (f"{run}_data_6D.tsv", f"{run}_6D.tsv"):
        path = d / name
        if path.exists():
            return path
    raise FileNotFoundError(f"No 6D mocap TSV for {run} under {d}")


def scaled_intrinsics(raw_calibration: dict, *, target_width: int, target_height: int) -> Intrinsics:
    source_width, source_height = raw_calibration["resolution"]
    sx = float(target_width) / float(source_width)
    sy = float(target_height) / float(source_height)
    K = np.array(raw_calibration["K-matrix"], dtype=np.float64).copy()
    K[0, 0] *= sx
    K[0, 2] *= sx
    K[1, 1] *= sy
    K[1, 2] *= sy
    dist = np.array(raw_calibration.get("distCoeff", []), dtype=np.float64)
    return Intrinsics(K, dist, (int(source_width), int(source_height)), (target_width, target_height))


def make_session(formatted_root: Path, detections_root: Path, run: str, phone: str) -> SessionData:
    session_dir = formatted_root / run / f"{run}_{phone}"
    centroids_path = detections_root / run / f"{run}_{phone}" / "centroids.npz"
    with np.load(centroids_path) as z:
        centroids = np.array(z["centroids"], dtype=np.float64)
        fps = float(z["fps"])
        width = int(z["width"])
        height = int(z["height"])
        label = str(z["label"])
    metadata = json.loads((session_dir / "metadata.json").read_text())
    raw_calib = json.loads((session_dir / "calibration.json").read_text())
    intrinsics = scaled_intrinsics(raw_calib, target_width=width, target_height=height)
    return SessionData(
        label=label,
        phone=phone,
        session_dir=session_dir,
        centroids_path=centroids_path,
        centroids=centroids,
        fps=fps,
        width=width,
        height=height,
        video_start_epoch_s=float(metadata["startTime"]) * 1e-6,
        intrinsics=intrinsics,
    )


def evenly_sample_indices(valid_mask: np.ndarray, count: int) -> np.ndarray:
    valid_indices = np.flatnonzero(valid_mask)
    if len(valid_indices) <= count:
        return valid_indices.astype(np.int64)
    positions = np.linspace(0, len(valid_indices) - 1, count)
    return valid_indices[np.unique(np.round(positions).astype(np.int64))].astype(np.int64)


def frame_mocap_indices(session: SessionData, mocap: MocapRun6D, *, time_offset_s: float) -> np.ndarray:
    frame_times = session.video_start_epoch_s + np.arange(len(session.centroids)) / session.fps + time_offset_s
    rel = frame_times - mocap.header.wall_clock_start.timestamp()
    return np.rint(rel * mocap.header.frequency).astype(np.int64)


def build_correspondences(
    session: SessionData,
    mocap: MocapRun6D,
    *,
    sample_count: int,
    time_offset_s: float,
) -> Correspondences:
    mocap_indices = frame_mocap_indices(session, mocap, time_offset_s=time_offset_s)
    drone = mocap.bodies[DRONE_BODY].position
    in_range = (mocap_indices >= 0) & (mocap_indices < len(drone))
    centroid_ok = np.isfinite(session.centroids[:, 0])
    drone_ok = np.zeros(len(session.centroids), dtype=bool)
    in_range_indices = np.flatnonzero(in_range)
    if len(in_range_indices):
        drone_ok[in_range_indices] = np.isfinite(drone[mocap_indices[in_range_indices], 0])
    valid = centroid_ok & in_range & drone_ok
    frame_indices = evenly_sample_indices(valid, sample_count)
    if len(frame_indices) == 0:
        return Correspondences(frame_indices, np.array([], dtype=np.int64), np.empty((0, 3)), np.empty((0, 2)))
    sampled_mocap = mocap_indices[frame_indices]
    return Correspondences(
        frame_indices,
        sampled_mocap,
        drone[sampled_mocap].astype(np.float64),
        session.centroids[frame_indices].astype(np.float64),
    )


def projection_errors(
    points_world: np.ndarray,
    points_image: np.ndarray,
    *,
    K: np.ndarray,
    dist_coeffs: np.ndarray,
    rvec: np.ndarray,
    tvec: np.ndarray,
) -> np.ndarray:
    projected, _ = cv2.projectPoints(points_world.reshape(-1, 1, 3), rvec, tvec, K, dist_coeffs)
    return np.linalg.norm(projected.reshape(-1, 2) - points_image, axis=1)


def fit_extrinsic(corr: Correspondences, intr: Intrinsics, *, ransac_reproj_px: float) -> FitResult:
    if len(corr.points_world) < 8:
        raise RuntimeError(f"Need at least 8 correspondences, got {len(corr.points_world)}")
    obj = corr.points_world.reshape(-1, 1, 3)
    img = corr.points_image.reshape(-1, 1, 2)
    ok, rvec, tvec, inliers = cv2.solvePnPRansac(
        obj,
        img,
        intr.K,
        intr.dist_coeffs,
        reprojectionError=ransac_reproj_px,
        iterationsCount=1000,
        confidence=0.999,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok or inliers is None or len(inliers) < 8:
        raise RuntimeError("PnP RANSAC failed")
    idx = inliers.flatten()
    ok, rvec, tvec = cv2.solvePnP(
        obj[idx],
        img[idx],
        intr.K,
        intr.dist_coeffs,
        rvec,
        tvec,
        useExtrinsicGuess=True,
        flags=cv2.SOLVEPNP_ITERATIVE,
    )
    if not ok:
        raise RuntimeError("PnP refinement failed")
    errors = projection_errors(
        corr.points_world,
        corr.points_image,
        K=intr.K,
        dist_coeffs=intr.dist_coeffs,
        rvec=rvec,
        tvec=tvec,
    )
    return FitResult(rvec.flatten(), tvec.flatten(), idx.astype(np.int64), errors)


def find_calibration_time_offset(
    session: SessionData,
    mocap: MocapRun6D,
    *,
    sample_count: int = 80,
    radius_s: float = 5.0,
    coarse_step_s: float = 0.1,
    fine_step_s: float = 0.01,
    ransac_reproj_px: float = 8.0,
) -> tuple[float, Correspondences, FitResult]:
    def score(offset: float) -> tuple[float, Correspondences | None, FitResult | None]:
        corr = build_correspondences(session, mocap, sample_count=sample_count, time_offset_s=offset)
        if len(corr.points_world) < 8:
            return math.inf, None, None
        try:
            fit = fit_extrinsic(corr, session.intrinsics, ransac_reproj_px=ransac_reproj_px)
        except RuntimeError:
            return math.inf, None, None
        return float(np.median(fit.errors_px)), corr, fit

    best_offset = 0.0
    best_score = math.inf
    best_corr = None
    best_fit = None
    for offset in np.arange(-radius_s, radius_s + 1e-9, coarse_step_s):
        current, corr, fit = score(float(offset))
        if current < best_score:
            best_offset, best_score, best_corr, best_fit = float(offset), current, corr, fit
    for offset in np.arange(best_offset - coarse_step_s, best_offset + coarse_step_s + 1e-9, fine_step_s):
        current, corr, fit = score(float(offset))
        if current < best_score:
            best_offset, best_score, best_corr, best_fit = float(offset), current, corr, fit
    if best_corr is None or best_fit is None:
        raise RuntimeError(f"Could not calibrate {session.label} at any time offset")
    return best_offset, best_corr, best_fit


def camera_center_world(rvec: np.ndarray, tvec: np.ndarray) -> np.ndarray:
    R, _ = cv2.Rodrigues(rvec)
    return (-R.T @ np.asarray(tvec).reshape(3)).astype(np.float64)


def finite_body_center(mocap: MocapRun6D, body_name: str) -> np.ndarray | None:
    if body_name not in mocap.bodies:
        return None
    pos = mocap.bodies[body_name].position
    valid = np.isfinite(pos[:, 0])
    if not valid.any():
        return None
    return np.nanmedian(pos[valid], axis=0).astype(np.float64)


def calibrate(
    *,
    raw_root: Path,
    formatted_root: Path,
    detections_root: Path,
    ransac_px: float = 8.0,
    sample: int = 80,
    needed_configs: set[tuple[str, str]] | None = None,
) -> dict[tuple[str, str], CamCalib]:
    calib: dict[tuple[str, str], CamCalib] = {}
    print("=== Calibrating extrinsics ===")
    items = CALIB_RUN.items()
    if needed_configs is not None:
        items = [(key, run) for key, run in items if key in needed_configs]
    for (phone, config), run in items:
        mocap = load_mocap_6d(mocap_path(raw_root, run))
        session = make_session(formatted_root, detections_root, run, phone)
        offset, _, fit = find_calibration_time_offset(
            session,
            mocap,
            sample_count=sample,
            radius_s=5.0,
            coarse_step_s=0.1,
            fine_step_s=0.01,
            ransac_reproj_px=ransac_px,
        )
        center = camera_center_world(fit.rvec, fit.tvec)
        bodies = {b: finite_body_center(mocap, b) for b in MOCAP_BODY.values()}
        nearest = min((b for b, c in bodies.items() if c is not None), key=lambda b: float(np.linalg.norm(center - bodies[b])))
        med = float(np.median(fit.errors_px))
        flag = "" if nearest == MOCAP_BODY[phone] else f" nearest={nearest}"
        print(f"  {phone:10s} [{config:4s}] calib={run:12s} reproj_med={med:5.2f}px dt={offset:+.2f}s{flag}")
        calib[(phone, config)] = CamCalib(
            phone,
            config,
            MOCAP_BODY[phone],
            run,
            session.intrinsics.K,
            session.intrinsics.dist_coeffs,
            fit.rvec,
            fit.tvec,
            offset,
            med,
        )
    return calib


def save_calibration(calib: dict[tuple[str, str], CamCalib], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    out = {}
    for (phone, config), c in calib.items():
        out[f"{phone}/{config}"] = {
            "phone": phone,
            "config": config,
            "mocap_body": c.mocap_body,
            "calib_run": c.calib_run,
            "K": c.K.tolist(),
            "dist_coeffs": c.dist_coeffs.tolist(),
            "rvec": c.rvec.tolist(),
            "tvec": c.tvec.tolist(),
            "nominal_offset_s": c.nominal_offset_s,
            "calib_reproj_med_px": c.calib_reproj_med_px,
        }
    path.write_text(json.dumps(out, indent=2, sort_keys=True))


def load_calibration(path: Path) -> dict[tuple[str, str], CamCalib]:
    raw = json.loads(path.read_text())
    out: dict[tuple[str, str], CamCalib] = {}
    for value in raw.values():
        c = CamCalib(
            phone=value["phone"],
            config=value["config"],
            mocap_body=value["mocap_body"],
            calib_run=value["calib_run"],
            K=np.array(value["K"], dtype=np.float64),
            dist_coeffs=np.array(value["dist_coeffs"], dtype=np.float64),
            rvec=np.array(value["rvec"], dtype=np.float64),
            tvec=np.array(value["tvec"], dtype=np.float64),
            nominal_offset_s=float(value["nominal_offset_s"]),
            calib_reproj_med_px=float(value["calib_reproj_med_px"]),
        )
        out[(c.phone, c.config)] = c
    return out


def sync_time_offset(
    session: SessionData,
    mocap: MocapRun6D,
    rvec: np.ndarray,
    tvec: np.ndarray,
    *,
    nominal_s: float,
    radius_s: float = 1.5,
    step_s: float = 0.02,
    sample: int = 120,
) -> tuple[float, float, int]:
    drone = mocap.bodies[DRONE_BODY].position
    best = (nominal_s, math.inf, 0)
    for off in np.arange(nominal_s - radius_s, nominal_s + radius_s + 1e-9, step_s):
        mi = frame_mocap_indices(session, mocap, time_offset_s=float(off))
        in_range = (mi >= 0) & (mi < len(drone))
        centroid_ok = np.isfinite(session.centroids[:, 0])
        drone_ok = np.zeros(len(session.centroids), dtype=bool)
        idx = np.flatnonzero(in_range)
        if len(idx):
            drone_ok[idx] = np.isfinite(drone[mi[idx], 0])
        valid_idx = np.flatnonzero(centroid_ok & in_range & drone_ok)
        if len(valid_idx) < 8:
            continue
        sel = valid_idx[np.linspace(0, len(valid_idx) - 1, min(sample, len(valid_idx))).round().astype(int)]
        err = projection_errors(
            drone[mi[sel]].astype(np.float64),
            session.centroids[sel].astype(np.float64),
            K=session.intrinsics.K,
            dist_coeffs=session.intrinsics.dist_coeffs,
            rvec=rvec,
            tvec=tvec,
        )
        med = float(np.median(err))
        if med < best[1]:
            best = (float(off), med, len(sel))
    return best


def triangulate_point_dlt(projections: list[np.ndarray], points: list[np.ndarray]) -> np.ndarray:
    if len(projections) < 2:
        raise ValueError("At least two projections are required")
    A = np.zeros((2 * len(projections), 4), dtype=np.float64)
    for idx, (P, xy) in enumerate(zip(projections, points)):
        x, y = xy
        A[2 * idx] = x * P[2] - P[0]
        A[2 * idx + 1] = y * P[2] - P[1]
    _, _, vt = np.linalg.svd(A)
    X = vt[-1]
    return (X[:3] / X[3]).astype(np.float64)


def reprojection_error(P: np.ndarray, X: np.ndarray, xy: np.ndarray) -> float:
    projected = P @ np.append(X, 1.0)
    if abs(projected[2]) < 1e-12:
        return math.inf
    uv = projected[:2] / projected[2]
    return float(np.linalg.norm(uv - xy))


def has_positive_depth(observations: list[Observation], X: np.ndarray) -> bool:
    return all((obs.R @ X + obs.t)[2] > 0 for obs in observations)


def select_best_triangulation(observations: list[Observation], *, max_reproj_px: float) -> PointResult | None:
    import itertools

    if len(observations) < 2:
        return None
    candidates: list[tuple[float, float, int, PointResult]] = []
    for size in range(len(observations), 1, -1):
        for combo in itertools.combinations(observations, size):
            combo_list = list(combo)
            X = triangulate_point_dlt([obs.P for obs in combo_list], [obs.xy for obs in combo_list])
            if not has_positive_depth(combo_list, X):
                continue
            used_errors = np.array([reprojection_error(obs.P, X, obs.xy) for obs in combo_list])
            all_errors = np.array([reprojection_error(obs.P, X, obs.xy) for obs in observations])
            mean_error = float(np.mean(used_errors))
            max_error = float(np.max(used_errors))
            median_all = float(np.median(all_errors))
            if max_error > max_reproj_px:
                continue
            result = PointResult(X, [obs.cam_name for obs in combo_list], size, mean_error, max_error, median_all)
            candidates.append((median_all, mean_error, -size, result))
    if not candidates:
        return None
    return min(candidates, key=lambda item: (item[0], item[1], item[2]))[3]


def interpolate_centroid(centroids: np.ndarray, query_epoch_s: float, *, start_epoch_s: float, fps: float) -> np.ndarray | None:
    frame_f = (query_epoch_s - start_epoch_s) * fps
    if frame_f < 0 or frame_f > len(centroids) - 1:
        return None
    i0 = int(np.floor(frame_f))
    i1 = min(i0 + 1, len(centroids) - 1)
    alpha = frame_f - i0
    c0 = centroids[i0]
    c1 = centroids[i1]
    if not np.isfinite(c0[0]) or not np.isfinite(c1[0]):
        return None
    return ((1.0 - alpha) * c0 + alpha * c1).astype(np.float64)


def undistort_pixel(K: np.ndarray, dist_coeffs: np.ndarray, xy: np.ndarray) -> np.ndarray:
    pt = np.asarray(xy, dtype=np.float64).reshape(1, 1, 2)
    out = cv2.undistortPoints(pt, K, dist_coeffs, P=K)
    return out.reshape(2).astype(np.float64)


def nearest_gt(mocap: MocapRun6D, epoch_times: np.ndarray) -> np.ndarray:
    drone = mocap.bodies[DRONE_BODY].position
    base = mocap.header.wall_clock_start.timestamp()
    idx = np.rint((epoch_times - base) * mocap.header.frequency).astype(np.int64)
    gt = np.full((len(epoch_times), 3), np.nan, dtype=np.float64)
    ok = (idx >= 0) & (idx < len(drone))
    gt[ok] = drone[idx[ok]]
    return gt


def build_camera(run: str, phone: str, calib: dict[tuple[str, str], CamCalib], mocap: MocapRun6D, formatted_root: Path, detections_root: Path) -> dict:
    config = config_for(run, phone)
    c = calib[(phone, config)]
    session = make_session(formatted_root, detections_root, run, phone)
    offset, med, n = sync_time_offset(session, mocap, c.rvec, c.tvec, nominal_s=c.nominal_offset_s)
    R, _ = cv2.Rodrigues(c.rvec)
    P = c.K @ np.hstack([R, c.tvec.reshape(3, 1)])
    return {
        "phone": phone,
        "label": session.label,
        "config": config,
        "K": c.K,
        "dist": c.dist_coeffs,
        "rvec": c.rvec,
        "tvec": c.tvec,
        "R": R,
        "P": P,
        "centroids": session.centroids,
        "fps": session.fps,
        "start_epoch": session.video_start_epoch_s,
        "offset": offset,
        "aligned_start": session.video_start_epoch_s + offset,
        "sync_med_px": med,
        "sync_n": n,
    }


def score_trajectory(trajectory: np.ndarray, gt: np.ndarray) -> dict[str, float | int]:
    valid = np.isfinite(trajectory[:, 0]) & np.isfinite(gt[:, 0])
    if valid.sum() == 0:
        return {"n_matched": 0, "rmse_m": math.nan, "mean_m": math.nan, "median_m": math.nan, "p90_m": math.nan, "max_m": math.nan}
    errors = np.linalg.norm(trajectory[valid] - gt[valid], axis=1)
    return {
        "n_matched": int(valid.sum()),
        "rmse_m": float(np.sqrt(np.mean(errors**2))),
        "mean_m": float(np.mean(errors)),
        "median_m": float(np.median(errors)),
        "p90_m": float(np.percentile(errors, 90)),
        "max_m": float(np.max(errors)),
    }


def triangulate_run(
    run: str,
    calib: dict[tuple[str, str], CamCalib],
    *,
    raw_root: Path,
    formatted_root: Path,
    detections_root: Path,
    out_root: Path,
    max_reproj_px: float,
) -> dict:
    mocap = load_mocap_6d(mocap_path(raw_root, run))
    exclude = EXCLUDE_CAMERAS.get(run, set())
    cams = [build_camera(run, phone, calib, mocap, formatted_root, detections_root) for phone in PHONES if phone not in exclude]
    if len(cams) < 2:
        raise RuntimeError(f"{run}: fewer than 2 usable cameras")
    ref = min(cams, key=lambda c: len(c["centroids"]))
    n = len(ref["centroids"])
    epoch_times = ref["aligned_start"] + np.arange(n) / ref["fps"]
    times = epoch_times - mocap.header.wall_clock_start.timestamp()
    trajectory = np.full((n, 3), np.nan, dtype=np.float64)
    n_views = np.zeros(n, dtype=np.int32)
    reproj = np.full(n, np.nan, dtype=np.float64)
    used = np.full(n, "", dtype=object)

    for i, epoch in enumerate(epoch_times):
        obs: list[Observation] = []
        for cam in cams:
            xy = interpolate_centroid(cam["centroids"], epoch, start_epoch_s=cam["aligned_start"], fps=cam["fps"])
            if xy is None:
                continue
            xy_u = undistort_pixel(cam["K"], cam["dist"], xy)
            obs.append(Observation(cam["phone"], cam["P"], cam["R"], cam["tvec"], xy_u))
        result = select_best_triangulation(obs, max_reproj_px=max_reproj_px)
        if result is None:
            continue
        trajectory[i] = result.point
        n_views[i] = result.n_views
        reproj[i] = result.mean_reproj_px
        used[i] = "+".join(result.cam_names)

    smooth = ekf_smooth_trajectory(trajectory, sim_times=times, n_views=n_views, reproj_errors=reproj)
    gt = nearest_gt(mocap, epoch_times)
    raw_metrics = score_trajectory(trajectory, gt)
    smooth_metrics = score_trajectory(smooth, gt)

    out_dir = out_root / run
    out_dir.mkdir(parents=True, exist_ok=True)
    np.savez(
        out_dir / "trajectory.npz",
        times_s=times,
        mocap_times=times,
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
        "run": run,
        "reference_phone": ref["phone"],
        "n_frames": int(n),
        "cameras": {c["phone"]: c["label"] for c in cams},
        "excluded_cameras": sorted(exclude),
        "camera_configs": {c["phone"]: c["config"] for c in cams},
        "camera_time_offsets_s": {c["phone"]: c["offset"] for c in cams},
        "camera_sync_reproj_px": {c["phone"]: c["sync_med_px"] for c in cams},
        "n_raw_triangulated": int(np.isfinite(trajectory[:, 0]).sum()),
        "n_smooth_finite": int(np.isfinite(smooth[:, 0]).sum()),
        "median_reproj_px": float(np.nanmedian(reproj)) if np.isfinite(reproj).any() else None,
        "raw_metrics": raw_metrics,
        "smooth_metrics": smooth_metrics,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, sort_keys=True))
    return summary


def write_csv(path: Path, times, n_views, reproj, used, raw, smooth, gt) -> None:
    with path.open("w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["frame", "time_s", "n_views", "reproj_px", "used_cameras", "x_raw", "y_raw", "z_raw", "x_smooth", "y_smooth", "z_smooth", "gt_x", "gt_y", "gt_z"])
        for i in range(len(times)):
            writer.writerow([
                i,
                f"{times[i]:.4f}",
                int(n_views[i]),
                "" if not np.isfinite(reproj[i]) else f"{reproj[i]:.2f}",
                used[i],
                *[("" if not np.isfinite(v) else f"{v:.4f}") for v in raw[i]],
                *[("" if not np.isfinite(v) else f"{v:.4f}") for v in smooth[i]],
                *[("" if not np.isfinite(v) else f"{v:.4f}") for v in gt[i]],
            ])


def available_runs(raw_root: Path) -> list[str]:
    runs: list[str] = []
    for run_dir in sorted(Path(raw_root).iterdir() if Path(raw_root).exists() else []):
        if not run_dir.is_dir():
            continue
        nested = run_dir / run_dir.name
        if nested.is_dir() and any(nested.glob("*_6D.tsv")):
            runs.append(run_dir.name)
    return runs


def needed_calibration_configs(runs: list[str]) -> set[tuple[str, str]]:
    needed: set[tuple[str, str]] = set()
    for run in runs:
        exclude = EXCLUDE_CAMERAS.get(run, set())
        for phone in PHONES:
            if phone not in exclude:
                needed.add((phone, config_for(run, phone)))
    return needed


def run_triangulation(
    *,
    raw_root: Path,
    formatted_root: Path,
    detections_root: Path,
    out_root: Path,
    runs: list[str] | None = None,
    max_reproj_px: float = 30.0,
    calibrate_only: bool = False,
    calibration_json: Path | None = None,
) -> dict[str, dict]:
    out_root.mkdir(parents=True, exist_ok=True)
    target_runs = runs or available_runs(raw_root) or RUNS
    needed_configs = needed_calibration_configs(target_runs)
    cal_path = calibration_json or out_root / "calibration.json"
    if cal_path.exists() and not calibrate_only:
        calib = load_calibration(cal_path)
    else:
        calib = calibrate(
            raw_root=raw_root,
            formatted_root=formatted_root,
            detections_root=detections_root,
            needed_configs=needed_configs,
        )
        save_calibration(calib, cal_path)
    if calibrate_only:
        return {}

    summaries: dict[str, dict] = {}
    for run in target_runs:
        try:
            summaries[run] = triangulate_run(
                run,
                calib,
                raw_root=raw_root,
                formatted_root=formatted_root,
                detections_root=detections_root,
                out_root=out_root,
                max_reproj_px=max_reproj_px,
            )
            print(f"  {run}: {summaries[run]['n_raw_triangulated']} triangulated frames")
        except Exception as exc:  # noqa: BLE001
            print(f"  {run}: FAILED: {exc}")
            summaries[run] = {"run": run, "error": str(exc)}
    (out_root / "summary.json").write_text(json.dumps(summaries, indent=2, sort_keys=True))
    return summaries
