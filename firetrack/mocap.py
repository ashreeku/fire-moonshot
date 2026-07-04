"""Qualisys TSV mocap loaders for the cognipilot_acro dataset.

Two file formats are supported:
    *_mocap.tsv     — 3D marker positions, 3 columns per marker (X, Y, Z in mm).
    *_mocap_6D.tsv  — rigid body poses, 16 columns per body (X, Y, Z, Roll,
                      Pitch, Yaw, Residual, Rot[0..8]) with a blank separator
                      column between bodies.

All spatial outputs are converted from millimetres to metres.  Qualisys
writes 0.0 for untracked frames; those rows are replaced with NaN so
downstream code can rely on ``np.isnan`` for gap detection.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import numpy as np

# Qualisys stores positions in mm; our world works in metres.
MM_TO_M = 1e-3
# 16 numeric columns per rigid body (plus a trailing tab separator).
COLS_PER_BODY = 16


@dataclass(frozen=True)
class MocapHeader:
    n_frames: int
    n_cameras: int
    frequency: float
    wall_clock_start: datetime          # UTC datetime of frame 0
    data_included: str                  # "3D" or "6D"


@dataclass(frozen=True)
class RigidBodyTrajectory:
    """Trajectory for one mocap rigid body."""
    position: np.ndarray   # (N, 3)  in metres, NaN where untracked
    rotation: np.ndarray   # (N, 3, 3) row-major rotation matrix, NaN-masked
    euler_deg: np.ndarray  # (N, 3)  Qualisys roll/pitch/yaw in degrees
    residual: np.ndarray   # (N,)    fit residual (mm, as reported)


@dataclass(frozen=True)
class MocapRun3D:
    header: MocapHeader
    timestamps: np.ndarray                       # (N,) seconds since frame 0
    markers: dict[str, np.ndarray]               # name -> (N, 3) in metres


@dataclass(frozen=True)
class MocapRun6D:
    header: MocapHeader
    timestamps: np.ndarray                       # (N,) seconds since frame 0
    bodies: dict[str, RigidBodyTrajectory]


def _parse_wall_clock(raw: str, assume_tz: timezone) -> datetime:
    """Parse Qualisys TIME_STAMP line into an absolute UTC datetime.

    The TSV line looks like::

        TIME_STAMP<TAB>2026-04-17, 14:51:52.059<TAB>2512466.80205730

    The second field is a machine "carrier" time which we ignore.  Qualisys
    records the local wall clock (without offset), so callers must supply
    ``assume_tz`` — for the Purdue arena data this is US/Eastern.
    """
    # Drop fractional minute-of-second from "14:51:52.059" safely.
    wall_str = raw.split("\t")[1].strip() if "\t" in raw else raw.strip()
    # Accept both comma and plain space between date and time.
    wall_str = wall_str.replace(",", "")
    dt_local = datetime.strptime(wall_str, "%Y-%m-%d %H:%M:%S.%f")
    return dt_local.replace(tzinfo=assume_tz).astimezone(timezone.utc)


def _parse_header_lines(
    lines: list[str],
    assume_tz: timezone,
) -> tuple[MocapHeader, int]:
    """Parse the leading metadata lines, returning the header and the
    number of lines consumed (the first data row starts at that index).

    The parser is tolerant of missing fields — only those actually present
    in Qualisys 2.0 exports are required.
    """
    fields: dict[str, str] = {}
    data_start: int | None = None

    for idx, line in enumerate(lines):
        if not line.strip():
            continue
        key = line.split("\t", 1)[0]
        # Data rows start with a numeric value.
        if key and (key[0].isdigit() or key[0] == "-"):
            data_start = idx
            break
        fields[key] = line

    if data_start is None:
        raise ValueError("No numeric data rows found in mocap TSV")

    header = MocapHeader(
        n_frames=int(fields["NO_OF_FRAMES"].split("\t")[1]),
        n_cameras=int(fields["NO_OF_CAMERAS"].split("\t")[1]),
        frequency=float(fields["FREQUENCY"].split("\t")[1]),
        wall_clock_start=_parse_wall_clock(fields["TIME_STAMP"], assume_tz),
        data_included=fields["DATA_INCLUDED"].split("\t")[1].strip(),
    )
    return header, data_start


def _read_numeric_block(lines: list[str], start: int) -> np.ndarray:
    """Parse tab-separated numeric data rows into a float array."""
    rows: list[list[float]] = []
    for line in lines[start:]:
        if not line.strip():
            continue
        # Empty fields (body separators) become NaN; invalid tokens raise.
        tokens = line.rstrip("\n").split("\t")
        row = [float(tok) if tok != "" else np.nan for tok in tokens]
        rows.append(row)
    # Rows may differ in length by ±1 due to trailing-tab quirks; pad to max.
    width = max(len(r) for r in rows)
    padded = np.full((len(rows), width), np.nan, dtype=np.float64)
    for i, r in enumerate(rows):
        padded[i, : len(r)] = r
    return padded


def load_mocap_3d(
    path: Path | str,
    assume_tz: timezone = timezone(timedelta(hours=-4)),
) -> MocapRun3D:
    """Load a ``*_mocap.tsv`` file (3D marker trajectories).

    Args:
        path: TSV file path.
        assume_tz: timezone the mocap clock was set to (default US/Eastern
            Daylight, UTC−4, which matches the Purdue arena in April).
    """
    path = Path(path)
    text = path.read_text().splitlines()
    header, data_start = _parse_header_lines(text, assume_tz)

    # MARKER_NAMES row: "MARKER_NAMES<TAB>name1<TAB>name2<TAB>…"
    names_line = next(l for l in text if l.startswith("MARKER_NAMES"))
    names = names_line.split("\t")[1:]

    data = _read_numeric_block(text, data_start)
    n_frames = data.shape[0]
    expected = len(names) * 3
    if data.shape[1] < expected:
        raise ValueError(
            f"3D file has {data.shape[1]} cols, expected ≥ {expected}"
        )

    markers: dict[str, np.ndarray] = {}
    for i, name in enumerate(names):
        xyz = data[:, i * 3 : i * 3 + 3] * MM_TO_M
        # Qualisys writes exact 0.0 for untracked frames — mask those rows.
        zero_rows = np.all(xyz == 0.0, axis=1)
        xyz[zero_rows] = np.nan
        markers[name] = xyz

    timestamps = np.arange(n_frames, dtype=np.float64) / header.frequency
    return MocapRun3D(header=header, timestamps=timestamps, markers=markers)


def _rotation_from_cols(row: np.ndarray) -> np.ndarray:
    """Convert a 9-element Qualisys Rot[0..8] block into a 3×3 rotation.

    Qualisys documents Rot as column-major.  We return row-major so that
    ``R @ v`` behaves like the standard convention.
    """
    if np.any(np.isnan(row)):
        return np.full((3, 3), np.nan)
    # Column-major: Rot[0..2] is first column of R.
    return row.reshape(3, 3, order="F")


def load_mocap_6d(
    path: Path | str,
    assume_tz: timezone = timezone(timedelta(hours=-4)),
) -> MocapRun6D:
    """Load a ``*_mocap_6D.tsv`` file (rigid body 6D poses).

    Returns one :class:`RigidBodyTrajectory` per body, with untracked
    frames masked to NaN in both position and rotation.
    """
    path = Path(path)
    text = path.read_text().splitlines()
    header, data_start = _parse_header_lines(text, assume_tz)

    names_line = next(l for l in text if l.startswith("BODY_NAMES"))
    names = [n for n in names_line.split("\t")[1:] if n]

    data = _read_numeric_block(text, data_start)
    bodies: dict[str, RigidBodyTrajectory] = {}
    for b_idx, name in enumerate(names):
        # Body i occupies columns [i*17 : i*17 + 16]; col i*17+16 is the
        # trailing blank separator tab.
        c0 = b_idx * (COLS_PER_BODY + 1)
        block = data[:, c0 : c0 + COLS_PER_BODY]
        if block.shape[1] < COLS_PER_BODY:
            raise ValueError(f"Body '{name}' truncated: {block.shape[1]} cols")

        pos = block[:, 0:3] * MM_TO_M                      # X, Y, Z
        euler_deg = block[:, 3:6]                          # Roll, Pitch, Yaw
        residual = block[:, 6]
        rot_cols = block[:, 7:16]

        untracked = np.all(block[:, :6] == 0.0, axis=1)
        pos[untracked] = np.nan
        euler_deg[untracked] = np.nan

        rotation = np.stack([_rotation_from_cols(r) for r in rot_cols], axis=0)
        bodies[name] = RigidBodyTrajectory(
            position=pos,
            rotation=rotation,
            euler_deg=euler_deg,
            residual=residual,
        )

    timestamps = np.arange(data.shape[0], dtype=np.float64) / header.frequency
    return MocapRun6D(header=header, timestamps=timestamps, bodies=bodies)
