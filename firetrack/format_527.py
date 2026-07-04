"""Normalize 5-27 recordings to scene-upright landscape videos."""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import cv2

from .dataset_527 import Camera527, ROTATION_STEPS_BY_PHONE, discover_cameras

SIDECARS = (
    "calibration.json",
    "camera.json",
    "gps.csv",
    "imu.csv",
    "metadata.json",
    "rf_data.jsonl",
)

TRANSPOSE_BY_STEPS: dict[int, list[str]] = {
    0: [],
    1: ["transpose=2"],
    2: ["transpose=2", "transpose=2"],
    3: ["transpose=1"],
}


def probe(video_path: Path) -> tuple[int, int, int]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    try:
        n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    finally:
        cap.release()
    return n, w, h


def build_ffmpeg_cmd(src: Path, dst: Path, steps: int) -> list[str]:
    steps = steps % 4
    vf = ",".join(TRANSPOSE_BY_STEPS[steps]) if steps else "null"
    return [
        "ffmpeg",
        "-y",
        "-loglevel",
        "error",
        "-i",
        str(src),
        "-map",
        "0:v:0",
        "-vf",
        vf,
        "-vsync",
        "0",
        "-c:v",
        "libx264",
        "-crf",
        "18",
        "-preset",
        "medium",
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(dst),
    ]


def normalize_camera(cam: Camera527, out_root: Path, *, overwrite: bool) -> dict:
    steps = ROTATION_STEPS_BY_PHONE[cam.phone]
    clip_dir = out_root / cam.relative_dir
    clip_dir.mkdir(parents=True, exist_ok=True)
    dst_video = clip_dir / "video.mp4"

    if dst_video.exists() and not overwrite:
        print(f"  [{cam.label}] skip existing normalized video")
    else:
        cmd = build_ffmpeg_cmd(cam.video_path, dst_video, steps)
        print(f"  [{cam.label}] normalize -> {dst_video}")
        subprocess.run(cmd, check=True)

    for name in SIDECARS:
        src = cam.camera_dir / name
        if src.exists():
            shutil.copy2(src, clip_dir / name)

    n, w, h = probe(dst_video)
    src_n, src_w, src_h = probe(cam.video_path)
    if n != src_n:
        print(f"    WARNING [{cam.label}] frame count changed {src_n} -> {n}")
    return {
        "label": cam.label,
        "run": cam.run,
        "phone": cam.phone,
        "source_uuid": cam.uuid,
        "source_video": str(cam.video_path),
        "video_path": str(dst_video),
        "rotation_steps_ccw": steps,
        "source_width": src_w,
        "source_height": src_h,
        "width": w,
        "height": h,
        "n_frames": n,
    }


def normalize_dataset(
    data_root: Path,
    out_root: Path,
    *,
    only: list[str] | None = None,
    overwrite: bool = False,
) -> list[dict]:
    cameras = discover_cameras(data_root)
    if only:
        wanted = set(only)
        cameras = [cam for cam in cameras if cam.label in wanted]
        unknown = wanted - {cam.label for cam in cameras}
        if unknown:
            raise SystemExit(f"Unknown labels: {', '.join(sorted(unknown))}")

    print(f"Normalizing {len(cameras)} videos")
    processed = {cam.label: normalize_camera(cam, out_root, overwrite=overwrite) for cam in cameras}

    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / "manifest.json"
    by_label = {}
    if manifest_path.exists():
        by_label = {row["label"]: row for row in json.loads(manifest_path.read_text())}
    by_label.update(processed)
    manifest = [by_label[key] for key in sorted(by_label)]
    manifest_path.write_text(json.dumps(manifest, indent=2))
    print(f"Wrote {manifest_path} ({len(manifest)} clips)")
    return manifest
