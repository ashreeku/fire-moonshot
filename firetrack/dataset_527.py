"""Dataset discovery for the 5-27 multi-phone recordings."""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

PHONE_BY_MODEL: dict[str, str] = {
    "Pixel 9": "pixel9",
    "SM-G950U": "galaxyS8",
    "SM-G991U": "galaxyS21",
}

ROTATION_STEPS_BY_PHONE: dict[str, int] = {
    "pixel9": 1,
    "galaxyS8": 1,
    "galaxyS21": 1,
}


@dataclass(frozen=True)
class Camera527:
    """One camera capture in a 5-27 run."""

    label: str
    run: str
    phone: str
    uuid: str
    video_path: Path
    camera_dir: Path

    @property
    def relative_dir(self) -> Path:
        return Path(self.run) / self.label


def phone_for_camera_dir(camera_dir: Path) -> str:
    camera_json = camera_dir / "camera.json"
    if not camera_json.exists():
        raise FileNotFoundError(f"Missing camera.json: {camera_json}")
    model = json.loads(camera_json.read_text()).get("device", {}).get("model", "")
    phone = PHONE_BY_MODEL.get(model)
    if phone is None:
        raise ValueError(f"Unknown device model {model!r} in {camera_json}")
    return phone


def discover_cameras(data_root: Path | str) -> list[Camera527]:
    root = Path(data_root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Data root does not exist: {root}")

    cameras: list[Camera527] = []
    for video_path in sorted(root.glob("*/*/*/video.mp4")):
        camera_dir = video_path.parent
        run = video_path.parents[2].name
        phone = phone_for_camera_dir(camera_dir)
        cameras.append(
            Camera527(
                label=f"{run}_{phone}",
                run=run,
                phone=phone,
                uuid=camera_dir.name,
                video_path=video_path,
                camera_dir=camera_dir,
            )
        )

    labels = [cam.label for cam in cameras]
    duplicates = sorted({label for label in labels if labels.count(label) > 1})
    if duplicates:
        raise ValueError(f"Duplicate camera labels: {', '.join(duplicates)}")
    return cameras


def phone_from_label(label: str) -> str:
    phone = label.rsplit("_", 1)[-1]
    if phone not in ROTATION_STEPS_BY_PHONE:
        raise ValueError(f"Cannot infer phone from label {label!r}")
    return phone


def discover_normalized(normalized_root: Path | str) -> list[Camera527]:
    root = Path(normalized_root).resolve()
    if not root.exists():
        raise FileNotFoundError(f"Normalized root does not exist: {root}")

    cameras: list[Camera527] = []
    for video_path in sorted(root.glob("*/*/video.mp4")):
        clip_dir = video_path.parent
        label = clip_dir.name
        run = clip_dir.parent.name
        cameras.append(
            Camera527(
                label=label,
                run=run,
                phone=phone_from_label(label),
                uuid="",
                video_path=video_path,
                camera_dir=clip_dir,
            )
        )
    if not cameras:
        raise FileNotFoundError(f"No <run>/<label>/video.mp4 under {root}")
    return cameras
