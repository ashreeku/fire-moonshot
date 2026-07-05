"""Extended Kalman Filter with RTS smoothing for 3D trajectory estimation.

Uses a constant-velocity motion model with adaptive measurement noise
based on triangulation quality (number of views, reprojection error).

The RTS (Rauch-Tung-Striebel) backward pass uses future observations to
refine estimates, making this an optimal offline smoother — unlike a
Gaussian blur which ignores the motion model entirely.
"""
from __future__ import annotations

import numpy as np


def _build_transition(dt: float) -> np.ndarray:
    """State transition matrix F for constant-velocity model.

    State: [x, y, z, vx, vy, vz]
    x_{k+1} = x_k + vx_k * dt, etc.
    """
    F = np.eye(6, dtype=np.float64)
    F[0, 3] = dt
    F[1, 4] = dt
    F[2, 5] = dt
    return F


def _build_process_noise(dt: float, q: float) -> np.ndarray:
    """Process noise covariance Q for piecewise-constant acceleration.

    q is the acceleration noise intensity in (m/s^2)^2.
    Higher q = more trust in observations, less in the motion model.
    """
    dt2 = dt * dt
    dt3 = dt2 * dt

    Q = np.zeros((6, 6), dtype=np.float64)
    # Position-position
    Q[0, 0] = Q[1, 1] = Q[2, 2] = dt3 / 3.0 * q
    # Position-velocity cross terms
    Q[0, 3] = Q[3, 0] = dt2 / 2.0 * q
    Q[1, 4] = Q[4, 1] = dt2 / 2.0 * q
    Q[2, 5] = Q[5, 2] = dt2 / 2.0 * q
    # Velocity-velocity
    Q[3, 3] = Q[4, 4] = Q[5, 5] = dt * q
    return Q


# Observation matrix: we directly observe [x, y, z].
_H = np.zeros((3, 6), dtype=np.float64)
_H[0, 0] = _H[1, 1] = _H[2, 2] = 1.0


def _measurement_noise(
    base_sigma: float,
    n_views: int,
    mean_reproj_px: float,
    reproj_scale: float = 0.01,
) -> np.ndarray:
    """Adaptive measurement noise covariance R.

    Noise decreases with more views (better geometry) and increases
    with larger reprojection error (worse triangulation).
    """
    view_factor = 2.0 / max(n_views, 2)  # 1.0 for 2 views, 0.5 for 4 views
    reproj_factor = 1.0 + reproj_scale * mean_reproj_px
    sigma = base_sigma * view_factor * reproj_factor
    return np.eye(3, dtype=np.float64) * (sigma * sigma)


def ekf_smooth_trajectory(
    trajectory: np.ndarray,
    sim_times: np.ndarray,
    n_views: np.ndarray | None = None,
    reproj_errors: np.ndarray | None = None,
    process_noise_intensity: float = 2.0,
    base_measurement_sigma: float = 0.15,
    max_gap_frames: int = 30,
) -> np.ndarray:
    """Smooth a 3D trajectory using EKF forward filter + RTS backward smoother.

    Args:
        trajectory: (N, 3) raw triangulated positions. NaN rows = missing.
        sim_times: (N,) simulation timestamps per frame (seconds).
        n_views: (N,) number of cameras used per frame. None = assume 2.
        reproj_errors: (N,) mean reprojection error (px) per frame. None = 0.
        process_noise_intensity: q in (m/s^2)^2. Higher = trust observations more.
        base_measurement_sigma: base measurement std (meters) for a 2-view observation.
        max_gap_frames: reset filter after this many consecutive missing frames.

    Returns:
        (N, 3) smoothed trajectory. Short NaN gaps are interpolated.
    """
    n_frames = len(trajectory)
    if n_views is None:
        n_views = np.full(n_frames, 2, dtype=int)
    if reproj_errors is None:
        reproj_errors = np.zeros(n_frames, dtype=np.float64)

    I6 = np.eye(6, dtype=np.float64)

    # Forward pass storage
    x_filt = np.full((n_frames, 6), np.nan, dtype=np.float64)
    P_filt = np.full((n_frames, 6, 6), np.nan, dtype=np.float64)
    x_pred = np.full((n_frames, 6), np.nan, dtype=np.float64)
    P_pred = np.full((n_frames, 6, 6), np.nan, dtype=np.float64)
    F_used = np.zeros((n_frames, 6, 6), dtype=np.float64)  # transition per step

    initialized = False
    gap_count = 0

    # ── Forward Kalman filter ──
    for k in range(n_frames):
        has_obs = not np.isnan(trajectory[k, 0])

        if not initialized:
            if has_obs:
                x_filt[k, :3] = trajectory[k]
                x_filt[k, 3:] = 0.0
                P_filt[k] = np.diag([0.5, 0.5, 0.5, 1.0, 1.0, 1.0])
                x_pred[k] = x_filt[k].copy()
                P_pred[k] = P_filt[k].copy()
                F_used[k] = I6
                initialized = True
                gap_count = 0
            continue

        # Find previous valid filtered state
        prev = k - 1
        if np.isnan(x_filt[prev, 0]):
            # Should not happen in normal flow, but handle gracefully
            if has_obs:
                x_filt[k, :3] = trajectory[k]
                x_filt[k, 3:] = 0.0
                P_filt[k] = np.diag([0.5, 0.5, 0.5, 1.0, 1.0, 1.0])
                x_pred[k] = x_filt[k].copy()
                P_pred[k] = P_filt[k].copy()
                F_used[k] = I6
                gap_count = 0
            continue

        dt = float(sim_times[k] - sim_times[prev])
        if dt <= 0:
            dt = 1.0 / 30.0

        F = _build_transition(dt)
        Q = _build_process_noise(dt, process_noise_intensity)
        F_used[k] = F

        # Predict
        xp = F @ x_filt[prev]
        Pp = F @ P_filt[prev] @ F.T + Q
        x_pred[k] = xp
        P_pred[k] = Pp

        if not has_obs:
            gap_count += 1
            if gap_count <= max_gap_frames:
                x_filt[k] = xp
                P_filt[k] = Pp
            else:
                # Gap too long — reset; wait for next observation
                initialized = False
            continue

        # Update with observation
        gap_count = 0
        R = _measurement_noise(
            base_measurement_sigma,
            int(n_views[k]),
            float(reproj_errors[k]),
        )
        z = trajectory[k]
        y = z - _H @ xp  # innovation
        S = _H @ Pp @ _H.T + R
        K = Pp @ _H.T @ np.linalg.inv(S)

        x_filt[k] = xp + K @ y
        P_filt[k] = (I6 - K @ _H) @ Pp

    # ── RTS backward smoothing pass ──
    x_smooth = x_filt.copy()
    P_smooth = P_filt.copy()

    for k in range(n_frames - 2, -1, -1):
        # Need valid filtered state at k AND valid smoothed state at k+1
        if np.isnan(x_filt[k, 0]) or np.isnan(x_smooth[k + 1, 0]):
            continue
        if np.isnan(P_pred[k + 1, 0, 0]):
            continue

        try:
            G = P_filt[k] @ F_used[k + 1].T @ np.linalg.inv(P_pred[k + 1])
        except np.linalg.LinAlgError:
            continue

        x_smooth[k] = x_filt[k] + G @ (x_smooth[k + 1] - x_pred[k + 1])
        P_smooth[k] = P_filt[k] + G @ (P_smooth[k + 1] - P_pred[k + 1]) @ G.T

    # Extract positions from smoothed state
    result = np.full((n_frames, 3), np.nan, dtype=np.float64)
    valid = ~np.isnan(x_smooth[:, 0])
    result[valid] = x_smooth[valid, :3]

    return result
