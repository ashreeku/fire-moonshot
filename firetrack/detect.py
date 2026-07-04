"""SAM3 2D detection for normalized 5-27 videos."""
from __future__ import annotations

import gc
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from .dataset_527 import discover_normalized

TEXT_PROMPT = "drone"
CLICK_OBJ_ID = 9999


@dataclass(frozen=True)
class VideoSpec:
    label: str
    relative_dir: Path
    video_path: Path


@dataclass(frozen=True)
class DetectionOutputPaths:
    output_dir: Path
    centroids_path: Path
    masks_path: Path
    summary_path: Path


@dataclass(frozen=True)
class DetectionResult:
    spec: VideoSpec
    output_paths: DetectionOutputPaths
    n_frames: int
    width: int
    height: int
    n_detected: int
    anchor_frames: list[int]

    @property
    def detection_rate(self) -> float:
        return self.n_detected / self.n_frames if self.n_frames else 0.0


def discover_specs(data_root: Path) -> list[VideoSpec]:
    return [
        VideoSpec(cam.label, cam.relative_dir, cam.video_path)
        for cam in discover_normalized(data_root)
    ]


def select_specs(specs: list[VideoSpec], labels: list[str] | None) -> list[VideoSpec]:
    if not labels:
        return specs
    by_label = {spec.label: spec for spec in specs}
    missing = sorted(set(labels) - set(by_label))
    if missing:
        raise SystemExit(f"Unknown labels: {', '.join(missing)}")
    return [by_label[label] for label in labels]


def output_paths(spec: VideoSpec, out_root: Path | str) -> DetectionOutputPaths:
    output_dir = Path(out_root) / spec.relative_dir
    return DetectionOutputPaths(
        output_dir=output_dir,
        centroids_path=output_dir / "centroids.npz",
        masks_path=output_dir / "masks.npz",
        summary_path=output_dir / "summary.json",
    )


def anchor_frames(n_frames: int) -> list[int]:
    if n_frames <= 0:
        raise ValueError("n_frames must be positive")
    anchors = [int(n_frames * 0.35), int(n_frames * 0.60), int(n_frames * 0.85)]
    return sorted({min(max(frame, 0), n_frames - 1) for frame in anchors})


def probe_video(video_path: Path) -> tuple[int, int, int, float]:
    cap = cv2.VideoCapture(str(video_path))
    if not cap.isOpened():
        raise RuntimeError(f"Could not open video: {video_path}")
    try:
        n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        width = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        height = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fps = float(cap.get(cv2.CAP_PROP_FPS))
    finally:
        cap.release()
    if n_frames <= 0 or width <= 0 or height <= 0:
        raise RuntimeError(f"Invalid video metadata for {video_path}")
    return n_frames, width, height, fps


def load_clicks(clicks_json: Path) -> dict[str, tuple[float, float, int]]:
    if not clicks_json.exists():
        raise FileNotFoundError(f"No clicks file: {clicks_json}")
    clicks: dict[str, tuple[float, float, int]] = {}
    for row in json.loads(clicks_json.read_text()):
        if row.get("approved") is False:
            continue
        if row.get("click_x") is None or row.get("click_frame") is None:
            continue
        clicks[row["label"]] = (
            float(row["click_x"]),
            float(row["click_y"]),
            int(row["click_frame"]),
        )
    return clicks


def build_predictor():
    from sam3.model_builder import build_sam3_video_predictor

    return build_sam3_video_predictor()


def extract_mask(outputs: dict, *, use_click: bool) -> np.ndarray | None:
    if not outputs:
        return None
    obj_ids = outputs.get("out_obj_ids", [])
    if len(obj_ids) == 0:
        return None
    mask_idx = 0
    if use_click:
        matches = np.where(np.asarray(obj_ids) == CLICK_OBJ_ID)[0]
        if len(matches) == 0:
            return None
        mask_idx = int(matches[0])
    mask = outputs["out_binary_masks"][mask_idx]
    if hasattr(mask, "cpu"):
        mask = mask.cpu().numpy()
    mask = mask.astype(bool)
    if mask.ndim == 3:
        mask = mask[0]
    return mask if mask.any() else None


def outputs_complete(paths: DetectionOutputPaths, *, save_masks: bool) -> bool:
    required = [paths.centroids_path, paths.summary_path]
    if save_masks:
        required.append(paths.masks_path)
    return all(path.exists() for path in required)


def save_detection_outputs(
    spec: VideoSpec,
    paths: DetectionOutputPaths,
    *,
    centroids: np.ndarray,
    width: int,
    height: int,
    fps: float,
    text_prompt: str,
    anchor_frames: list[int],
    click: tuple[float, float, int] | None,
    masks_by_frame: dict[int, np.ndarray] | None,
) -> DetectionResult:
    paths.output_dir.mkdir(parents=True, exist_ok=True)
    np.savez(
        paths.centroids_path,
        centroids=centroids,
        frame_indices=np.arange(len(centroids), dtype=np.int64),
        width=width,
        height=height,
        fps=fps,
        video_path=str(spec.video_path),
        relative_dir=str(spec.relative_dir),
        label=spec.label,
        anchor_frames=np.array(anchor_frames, dtype=np.int64),
        text_prompt=text_prompt,
    )
    if masks_by_frame is not None:
        np.savez_compressed(paths.masks_path, **{str(k): v for k, v in masks_by_frame.items()})

    n_detected = int(np.sum(np.isfinite(centroids[:, 0])))
    summary = {
        "label": spec.label,
        "video_path": str(spec.video_path),
        "relative_dir": str(spec.relative_dir),
        "centroids_path": str(paths.centroids_path),
        "masks_path": str(paths.masks_path) if masks_by_frame is not None else None,
        "n_frames": int(len(centroids)),
        "width": int(width),
        "height": int(height),
        "fps": float(fps),
        "n_detected": n_detected,
        "detection_rate": n_detected / len(centroids) if len(centroids) else 0.0,
        "anchor_frames": anchor_frames,
        "text_prompt": text_prompt,
        "click": (
            {"x": click[0], "y": click[1], "frame": click[2]} if click is not None else None
        ),
    }
    paths.summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True))
    return DetectionResult(spec, paths, len(centroids), width, height, n_detected, anchor_frames)


def run_sam3_on_video(
    spec: VideoSpec,
    out_root: Path,
    *,
    text_prompt: str = TEXT_PROMPT,
    save_masks: bool = False,
    overwrite: bool = False,
    click: tuple[float, float, int] | None = None,
    predictor: Any = None,
    on_progress: Any = None,
) -> DetectionResult:
    import torch

    paths = output_paths(spec, out_root)
    if not overwrite and outputs_complete(paths, save_masks=save_masks):
        summary = json.loads(paths.summary_path.read_text())
        return DetectionResult(
            spec,
            paths,
            int(summary["n_frames"]),
            int(summary["width"]),
            int(summary["height"]),
            int(summary["n_detected"]),
            [int(v) for v in summary.get("anchor_frames", [])],
        )

    n_frames, width, height, fps = probe_video(spec.video_path)
    anchors: list[int] = []
    use_click = click is not None
    if use_click:
        assert click is not None
        if not 0 <= click[2] < n_frames:
            raise ValueError(f"click frame {click[2]} outside [0, {n_frames}) for {spec.label}")
        print(f"  [{spec.label}] click=({click[0]:.1f},{click[1]:.1f}) frame {click[2]}")
    else:
        anchors = anchor_frames(n_frames)
        print(f"  [{spec.label}] text anchors={anchors}")

    owns_predictor = predictor is None
    if owns_predictor:
        predictor = build_predictor()
    try:
        response = predictor.handle_request(
            request={"type": "start_session", "resource_path": str(spec.video_path)}
        )
        session_id = response["session_id"]
        try:
            if use_click:
                x, y, frame = click  # type: ignore[misc]
                predictor.handle_request(request={
                    "type": "add_prompt",
                    "session_id": session_id,
                    "frame_index": int(frame),
                    "text": text_prompt,
                })
                for _ in predictor.handle_stream_request(request={
                    "type": "propagate_in_video",
                    "session_id": session_id,
                    "propagation_direction": "both",
                }):
                    pass
                predictor.handle_request(request={
                    "type": "add_prompt",
                    "session_id": session_id,
                    "frame_index": int(frame),
                    "obj_id": CLICK_OBJ_ID,
                    "points": [[float(x) / width, float(y) / height]],
                    "point_labels": [1],
                })
            else:
                for frame in anchors:
                    predictor.handle_request(request={
                        "type": "add_prompt",
                        "session_id": session_id,
                        "frame_index": frame,
                        "text": text_prompt,
                    })

            centroids = np.full((n_frames, 2), np.nan, dtype=np.float64)
            masks_by_frame: dict[int, np.ndarray] | None = {} if save_masks else None
            processed = 0
            for result in predictor.handle_stream_request(request={
                "type": "propagate_in_video",
                "session_id": session_id,
                "propagation_direction": "both",
            }):
                processed += 1
                if on_progress is not None and processed % 8 == 0:
                    on_progress({"label": spec.label, "frame": min(processed, n_frames), "total": n_frames})
                frame_idx = int(result["frame_index"])
                if frame_idx < 0 or frame_idx >= n_frames:
                    continue
                mask = extract_mask(result["outputs"], use_click=use_click)
                if mask is None:
                    continue
                ys, xs = np.where(mask)
                centroids[frame_idx] = [xs.mean(), ys.mean()]
                if masks_by_frame is not None:
                    masks_by_frame[frame_idx] = mask
            if on_progress is not None:
                on_progress({"label": spec.label, "frame": n_frames, "total": n_frames})
        finally:
            predictor.handle_request(request={"type": "close_session", "session_id": session_id})
    finally:
        if owns_predictor:
            del predictor
            gc.collect()
        torch.cuda.empty_cache()

    result = save_detection_outputs(
        spec,
        paths,
        centroids=centroids,
        width=width,
        height=height,
        fps=fps,
        text_prompt=text_prompt,
        anchor_frames=anchors,
        click=click,
        masks_by_frame=masks_by_frame,
    )
    print(f"  [{spec.label}] detected {result.n_detected}/{result.n_frames}")
    return result


def run_detection_on_specs(
    specs: list[VideoSpec],
    *,
    out_root: Path,
    clicks_json: Path | None,
    text_prompt: str = TEXT_PROMPT,
    save_masks: bool = False,
    overwrite: bool = False,
    on_progress: Any = None,
) -> list[DetectionResult]:
    clicks = load_clicks(clicks_json) if clicks_json is not None else {}
    predictor = build_predictor()
    results: list[DetectionResult] = []
    n_videos = len(specs)
    try:
        for index, spec in enumerate(specs):
            click = clicks.get(spec.label)
            if clicks_json is not None and click is None:
                print(f"  [{spec.label}] skip: no approved click")
                continue
            spec_progress = None
            if on_progress is not None:
                def spec_progress(p, _i=index):
                    on_progress({**p, "video": _i + 1, "n_videos": n_videos, "stage": "detect"})
            results.append(
                run_sam3_on_video(
                    spec,
                    out_root,
                    text_prompt=text_prompt,
                    save_masks=save_masks,
                    overwrite=overwrite,
                    click=click,
                    predictor=predictor,
                    on_progress=spec_progress,
                )
            )
    finally:
        del predictor
        gc.collect()
    return results


def run_detection(
    *,
    data_root: Path,
    out_root: Path,
    clicks_json: Path | None,
    only: list[str] | None = None,
    text_prompt: str = TEXT_PROMPT,
    save_masks: bool = False,
    overwrite: bool = False,
) -> list[DetectionResult]:
    specs = select_specs(discover_specs(data_root), only)
    return run_detection_on_specs(
        specs,
        out_root=out_root,
        clicks_json=clicks_json,
        text_prompt=text_prompt,
        save_masks=save_masks,
        overwrite=overwrite,
    )
