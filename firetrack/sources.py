"""Video source discovery for the dashboard's two input modes.

Two modes feed the pipeline:

- ``dataset``: normalized 5-27 clips under ``<formatted>/<run>/<label>/video.mp4``.
  These carry phone/run metadata and can drive the full pipeline.
- ``upload``: arbitrary videos dropped in ``<uploads>/<name>/video.mp4`` from the
  browser. These support clicks, SAM3 detection, and calibration-backed
  triangulation.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .dataset_527 import discover_normalized
from .detect import VideoSpec

UPLOAD_SUBDIR = "uploads"


@dataclass(frozen=True)
class ClickVideo:
    """A video the clicks annotator can operate on."""

    label: str
    run: str
    phone: str
    uuid: str
    video_path: Path


def dataset_specs(formatted_root: Path) -> list[VideoSpec]:
    """Detection specs for normalized dataset clips (empty if none yet)."""
    try:
        cameras = discover_normalized(formatted_root)
    except (FileNotFoundError, ValueError):
        return []
    return [VideoSpec(cam.label, cam.relative_dir, cam.video_path) for cam in cameras]


def upload_specs(uploads_root: Path) -> list[VideoSpec]:
    """Detection specs for uploaded videos (empty if none yet)."""
    root = Path(uploads_root)
    if not root.exists():
        return []
    specs: list[VideoSpec] = []
    for video_path in sorted(root.glob("*/video.mp4")):
        label = video_path.parent.name
        specs.append(VideoSpec(label, Path(UPLOAD_SUBDIR) / label, video_path))
    return specs


def dataset_click_videos(formatted_root: Path) -> list[ClickVideo]:
    """Clicks annotator videos for normalized dataset clips."""
    try:
        cameras = discover_normalized(formatted_root)
    except (FileNotFoundError, ValueError):
        return []
    return [
        ClickVideo(cam.label, cam.run, cam.phone, cam.uuid, cam.video_path)
        for cam in cameras
    ]


def upload_click_videos(uploads_root: Path) -> list[ClickVideo]:
    """Clicks annotator videos for uploaded clips."""
    return [
        ClickVideo(spec.label, UPLOAD_SUBDIR, "", "", spec.video_path)
        for spec in upload_specs(uploads_root)
    ]
