"""Web dashboard that drives the whole FireTrack pipeline.

Two input modes:

- ``dataset``: uploaded 5-27 recordings + mocap -> full pipeline
  (format -> clicks -> detect -> triangulate) with per-video selection.
- ``upload``: videos dropped from the browser -> clicks + SAM3 detection, with
  triangulation available when the user supplies camera calibration.

Built on the stdlib http.server, matching the existing ``clicks serve`` pattern
(no extra dependencies).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import zipfile
from dataclasses import dataclass
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from .clicks import HTML_PAGE as CLICKS_HTML, ClicksService, FrameCache, click_status
from .dashboard import DASHBOARD_HTML
from .detect import VideoSpec, load_clicks, output_paths, run_detection_on_specs
from . import results as results_api
from .results_page import RESULTS_HTML
from .format_527 import normalize_dataset
from .jobs import JobRunner
from .sources import (
    dataset_click_videos,
    dataset_specs,
    upload_click_videos,
    upload_specs,
)
from .triangulate_527 import run_triangulation
from .triangulate_uploads import (
    rotation_issue,
    rotation_matrix,
    triangulate_uploads,
    validate_calibration,
)

UPLOAD_CHUNK = 1 << 20
SAFE_NAME = re.compile(r"[^A-Za-z0-9._-]+")
DATASET_STAGES = {"format", "detect", "triangulate", "run-all"}
UPLOAD_STAGES = {"detect", "triangulate"}
DATASET_FILE_NAMES = {
    "video.mp4",
    "metadata.json",
    "camera.json",
    "calibration.json",
    "gps.csv",
    "imu.csv",
    "rf_data.jsonl",
}


@dataclass(frozen=True)
class WebConfig:
    work_root: Path

    @property
    def formatted_root(self) -> Path:
        return self.work_root / "formatted"

    @property
    def detections_root(self) -> Path:
        return self.work_root / "detections"

    @property
    def triangulation_root(self) -> Path:
        return self.work_root / "triangulation"

    @property
    def clicks_json(self) -> Path:
        return self.work_root / "clicks.json"

    @property
    def dataset_uploads_root(self) -> Path:
        return self.work_root / "dataset_uploads"

    @property
    def uploads_root(self) -> Path:
        return self.work_root / "uploads"

    @property
    def uploads_clicks_json(self) -> Path:
        return self.work_root / "uploads_clicks.json"

    @property
    def uploads_calibration_json(self) -> Path:
        return self.work_root / "uploads_calibration.json"


def safe_stem(filename: str) -> str:
    stem = Path(filename).name.rsplit(".", 1)[0]
    cleaned = SAFE_NAME.sub("_", stem).strip("._-")
    return cleaned or "upload"


def safe_relpath(path: str) -> Path:
    parts = [SAFE_NAME.sub("_", p).strip("._-") for p in Path(path).parts]
    clean = [p for p in parts if p and p not in (".", "..")]
    if not clean:
        raise ValueError("empty path")
    return Path(*clean)


def dataset_store_rel(upload_path: str, run_hint: str | None = None) -> Path:
    """Map uploaded 5-27 files into the raw layout expected by format/triangulate.

    The existing 5-27 code expects ``<root>/<run>/<run>/<camera>/video.mp4`` and
    ``<root>/<run>/<run>/<run>_data_6D.tsv``. Browser directory uploads often
    provide ``<run>/<camera>/video.mp4``; insert the duplicate run segment when
    needed while preserving already-compatible uploads.
    """
    rel = safe_relpath(upload_path)
    parts = rel.parts
    run = run_hint or parts[0]
    if len(parts) >= 2 and parts[1] == run:
        return rel
    if run_hint is not None:
        tail = Path(*parts[1:]) if len(parts) > 1 else Path(parts[0])
        return Path(run) / run / tail
    return Path(run) / run / Path(*parts[1:])


def is_dataset_file(path: str) -> bool:
    name = Path(path).name
    return (
        name in DATASET_FILE_NAMES
        or name.endswith("_data_6D.tsv")
        or name.endswith("_data.tsv")
    )


def infer_dataset_run(paths: list[str]) -> str | None:
    """Infer a 5-27 run name from mocap TSV names inside an upload."""
    for path in paths:
        name = Path(path).name
        suffix = "_data_6D.tsv"
        if name.endswith(suffix):
            return name[: -len(suffix)]
    for path in paths:
        name = Path(path).name
        suffix = "_data.tsv"
        if name.endswith(suffix):
            return name[: -len(suffix)]
    return None


def _has_detection(cfg: WebConfig, spec: VideoSpec) -> bool:
    return output_paths(spec, cfg.detections_root).summary_path.exists()


def _filter(specs: list[VideoSpec], only: list[str] | None) -> list[VideoSpec]:
    if not only:
        return specs
    wanted = set(only)
    return [spec for spec in specs if spec.label in wanted]


def _clicks_json_for(cfg: WebConfig, source: str) -> Path:
    return cfg.uploads_clicks_json if source == "upload" else cfg.clicks_json


def _effective_clicks(path: Path) -> Path | None:
    """Return the clicks file only if it holds >=1 real approved click.

    Merely opening the annotator creates an empty manifest, so gating on file
    existence would make detect skip every un-annotated video. Gate on content.
    """
    if not path.exists():
        return None
    try:
        return path if load_clicks(path) else None
    except (ValueError, OSError):
        return None


def build_status(cfg: WebConfig, runner: JobRunner) -> dict:
    dataset = [
        {"label": s.label, "has_detection": _has_detection(cfg, s)}
        for s in dataset_specs(cfg.formatted_root)
    ]
    uploads = [
        {"label": s.label, "has_detection": _has_detection(cfg, s)}
        for s in upload_specs(cfg.uploads_root)
    ]
    return {
        "dataset": dataset,
        "uploads": uploads,
        "outputs": {
            "dataset_uploads": cfg.dataset_uploads_root.exists(),
            "formatted": cfg.formatted_root.exists(),
            "detections": cfg.detections_root.exists(),
            "triangulation": (cfg.triangulation_root / "summary.json").exists(),
            "uploads_triangulation": (cfg.triangulation_root / "uploads" / "summary.json").exists(),
        },
        "clicks": _safe_click_status(cfg.clicks_json),
        "uploads_clicks": _safe_click_status(cfg.uploads_clicks_json),
        "calibration": _calibration_status(cfg.uploads_calibration_json),
        "env": _env_info(),
        "job": runner.status(),
    }


def _calibration_status(path: Path) -> dict:
    """Report whether a valid upload calibration is present, for the UI."""
    if not path.exists():
        return {"present": False, "n_cameras": 0, "cameras": []}
    try:
        cams = validate_calibration(json.loads(path.read_text()))
        return {"present": True, "n_cameras": len(cams), "cameras": [c["video"] for c in cams]}
    except (ValueError, OSError, json.JSONDecodeError):
        return {"present": False, "n_cameras": 0, "cameras": [], "error": "invalid"}


def load_calibration_store(path: Path) -> dict:
    """Read the calibration document, or an empty one."""
    if not path.exists():
        return {"cameras": []}
    try:
        doc = json.loads(path.read_text())
        return doc if isinstance(doc.get("cameras"), list) else {"cameras": []}
    except (json.JSONDecodeError, OSError):
        return {"cameras": []}


def remove_upload(cfg: WebConfig, label: str) -> None:
    """Delete an uploaded clip, its detection outputs, and its calibration entry."""
    safe = safe_stem(label)
    for root in (cfg.uploads_root, cfg.detections_root / "uploads"):
        target = (root / safe).resolve()
        if root.resolve() in target.parents and target.exists():
            shutil.rmtree(target, ignore_errors=True)
    store = load_calibration_store(cfg.uploads_calibration_json)
    kept = [c for c in store["cameras"] if c.get("video") != safe]
    if len(kept) != len(store["cameras"]):
        cfg.uploads_calibration_json.write_text(json.dumps({"cameras": kept}, indent=2))


def upsert_camera(path: Path, camera: dict) -> int:
    """Validate one camera and merge it into the calibration store by ``video``."""
    validate_calibration({"cameras": [camera]})
    issue = rotation_issue(rotation_matrix(camera))
    if issue:
        raise ValueError(issue)
    store = load_calibration_store(path)
    others = [c for c in store["cameras"] if c.get("video") != camera["video"]]
    store["cameras"] = [*others, camera]
    path.write_text(json.dumps(store, indent=2))
    return len(store["cameras"])


def _env_info() -> dict:
    """Cheap environment readout for the dashboard HUD (no torch import)."""
    hf_home = os.environ.get("HF_HOME") or os.path.expanduser("~/.cache/huggingface")
    weights = Path(hf_home) / "hub" / "models--facebook--sam3"
    return {
        "gpu": _gpu_visible(),
        "weights_cached": weights.exists(),
        "offline": os.environ.get("HF_HUB_OFFLINE") == "1",
    }


def _gpu_visible() -> bool:
    """Detect an attached NVIDIA GPU on native Linux and WSL2 (no torch import)."""
    device_nodes = ("/proc/driver/nvidia/gpus", "/dev/nvidia0", "/dev/dxg")
    if any(Path(p).exists() for p in device_nodes):
        return True
    libdirs = ("/usr/lib/x86_64-linux-gnu", "/usr/lib/wsl/lib")
    return any(any(Path(d).glob("libcuda.so*")) for d in libdirs if Path(d).exists())


def _safe_click_status(path: Path) -> dict | None:
    try:
        return click_status(path)
    except FileNotFoundError:
        return None


def _stage_fn(cfg: WebConfig, stage: str, source: str, only: list[str] | None, progress=None):
    """Return a zero-arg callable that runs the requested stage."""
    if source == "upload":
        if stage == "triangulate":
            return _upload_triangulate_fn(cfg)
        return _upload_detect_fn(cfg, only, progress)
    if stage == "format":
        return lambda: normalize_dataset(cfg.dataset_uploads_root, cfg.formatted_root, only=only)
    if stage == "detect":
        return _dataset_detect_fn(cfg, only, progress)
    if stage == "triangulate":
        return lambda: run_triangulation(
            raw_root=cfg.dataset_uploads_root,
            formatted_root=cfg.formatted_root,
            detections_root=cfg.detections_root,
            out_root=cfg.triangulation_root,
        )
    if stage == "run-all":
        return _run_all_fn(cfg, only, progress)
    raise ValueError(f"unknown stage: {stage}")


def _dataset_detect_fn(cfg: WebConfig, only: list[str] | None, progress=None):
    def run() -> None:
        run_detection_on_specs(
            _filter(dataset_specs(cfg.formatted_root), only),
            out_root=cfg.detections_root,
            clicks_json=_effective_clicks(cfg.clicks_json),
            on_progress=progress,
        )

    return run


def _upload_detect_fn(cfg: WebConfig, only: list[str] | None, progress=None):
    def run() -> None:
        run_detection_on_specs(
            _filter(upload_specs(cfg.uploads_root), only),
            out_root=cfg.detections_root,
            clicks_json=_effective_clicks(cfg.uploads_clicks_json),
            on_progress=progress,
        )

    return run


def _upload_triangulate_fn(cfg: WebConfig):
    def run() -> None:
        triangulate_uploads(
            detections_root=cfg.detections_root,
            calibration_json=cfg.uploads_calibration_json,
            out_root=cfg.triangulation_root,
            uploads_root=cfg.uploads_root,
        )

    return run


def _run_all_fn(cfg: WebConfig, only: list[str] | None, progress=None):
    def run() -> None:
        normalize_dataset(cfg.dataset_uploads_root, cfg.formatted_root, only=only)
        _dataset_detect_fn(cfg, only, progress)()
        run_triangulation(
            raw_root=cfg.dataset_uploads_root,
            formatted_root=cfg.formatted_root,
            detections_root=cfg.detections_root,
            out_root=cfg.triangulation_root,
        )

    return run


class _ClicksRegistry:
    """Lazily builds and caches a ClicksService per source for the annotator."""

    def __init__(self, cfg: WebConfig) -> None:
        self._cfg = cfg
        self._services: dict[str, ClicksService] = {}
        self.active: ClicksService | None = None

    def select(self, source: str) -> None:
        if source == "upload":
            videos = upload_click_videos(self._cfg.uploads_root)
        else:
            videos = dataset_click_videos(self._cfg.formatted_root)
        # Rebuild every time so newly uploaded/formatted videos appear.
        service = ClicksService(videos, _clicks_json_for(self._cfg, source))
        self._services[source] = service
        self.active = service


def serve_webui(*, work_root: Path, host: str, port: int) -> None:
    cfg = WebConfig(work_root.resolve())
    cfg.work_root.mkdir(parents=True, exist_ok=True)
    cfg.dataset_uploads_root.mkdir(parents=True, exist_ok=True)
    cfg.uploads_root.mkdir(parents=True, exist_ok=True)
    runner = JobRunner()
    clicks = _ClicksRegistry(cfg)
    result_frames = FrameCache()

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, ctype: str, payload: bytes) -> None:
            try:
                self.send_response(status)
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(len(payload)))
                self.end_headers()
                self.wfile.write(payload)
            except (BrokenPipeError, ConnectionResetError):
                return

        def _json(self, status: int, obj: object) -> None:
            self._send(status, "application/json", json.dumps(obj).encode())

        def _read_json(self) -> dict:
            length = int(self.headers.get("Content-Length", "0"))
            return json.loads(self.rfile.read(length).decode()) if length else {}

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            route = parsed.path
            if route == "/":
                self._send(200, "text/html; charset=utf-8", DASHBOARD_HTML)
                return
            if route == "/clicks":
                self._send(200, "text/html; charset=utf-8", CLICKS_HTML)
                return
            if route == "/results":
                self._send(200, "text/html; charset=utf-8", RESULTS_HTML)
                return
            if route == "/api/status":
                self._json(200, build_status(cfg, runner))
                return
            if route == "/api/results":
                self._json(200, {
                    "detections": results_api.list_detections(cfg.detections_root),
                    "trajectories": results_api.list_trajectories(cfg.triangulation_root),
                })
                return
            if route == "/api/centroids":
                self._serve_results(parse_qs(parsed.query), self._load_centroids)
                return
            if route == "/api/trajectory":
                self._serve_results(parse_qs(parsed.query), self._load_trajectory)
                return
            if route == "/api/trajectory/download":
                self._serve_trajectory_download(parse_qs(parsed.query))
                return
            if route == "/api/result-frame":
                self._serve_result_frame(parse_qs(parsed.query))
                return
            if route == "/api/calibration":
                self._json(200, load_calibration_store(cfg.uploads_calibration_json))
                return
            if route == "/api/upload-frame":
                self._serve_upload_frame(parse_qs(parsed.query))
                return
            if route == "/api/log":
                since = int(parse_qs(parsed.query).get("since", ["0"])[0])
                self._json(200, runner.log_since(since))
                return
            if route == "/api/rows":
                self._json(200, [] if clicks.active is None else json.loads(clicks.active.rows_bytes()))
                return
            if route == "/frame":
                self._serve_frame(parse_qs(parsed.query))
                return
            self._send(404, "text/plain", b"not found")

        def _load_centroids(self, rel: str) -> dict:
            return results_api.load_centroids(cfg.detections_root, rel)

        def _load_trajectory(self, rel: str) -> dict:
            return results_api.load_trajectory(cfg.triangulation_root, rel)

        def _serve_results(self, query: dict, loader) -> None:
            rel = query.get("dir", [""])[0]
            if not rel:
                self._json(400, {"error": "missing ?dir="})
                return
            try:
                self._json(200, loader(rel))
            except ValueError:
                self._send(400, "text/plain", b"bad dir")
            except (FileNotFoundError, OSError, KeyError):
                self._send(404, "text/plain", b"result not found")

        def _serve_upload_frame(self, query: dict) -> None:
            label = safe_stem(query.get("label", [""])[0])
            try:
                frame_idx = int(query.get("frame", ["0"])[0])
            except ValueError:
                self._send(400, "text/plain", b"bad frame")
                return
            video = cfg.uploads_root / label / "video.mp4"
            jpg = result_frames.read(str(video), frame_idx) if video.exists() else None
            if jpg is None:
                self._send(404, "text/plain", b"frame not available")
                return
            self._send(200, "image/jpeg", jpg)

        def _serve_trajectory_download(self, query: dict) -> None:
            rel = query.get("dir", [""])[0]
            fmt = query.get("fmt", ["csv"])[0]
            if not rel:
                self._send(400, "text/plain", b"missing dir")
                return
            try:
                path = results_api.trajectory_file(cfg.triangulation_root, rel, fmt)
            except ValueError:
                self._send(400, "text/plain", b"bad fmt")
                return
            except (FileNotFoundError, OSError):
                self._send(404, "text/plain", b"trajectory not found")
                return
            data = path.read_bytes()
            fname = rel.replace("/", "_").strip("_") + "_" + path.name
            ctype = "text/csv" if fmt == "csv" else "application/octet-stream"
            self.send_response(200)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Disposition", f'attachment; filename="{fname}"')
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        def _serve_result_frame(self, query: dict) -> None:
            rel = query.get("dir", [""])[0]
            try:
                frame_idx = int(query.get("frame", ["0"])[0])
                video_path = results_api.video_path_for(str(cfg.detections_root), rel)
            except (ValueError, FileNotFoundError, OSError, KeyError):
                self._send(400, "text/plain", b"bad frame request")
                return
            jpg = result_frames.read(video_path, frame_idx)
            if jpg is None:
                self._send(404, "text/plain", b"frame read failed")
                return
            self._send(200, "image/jpeg", jpg)

        def _serve_frame(self, query: dict) -> None:
            if clicks.active is None:
                self._send(404, "text/plain", b"no active source")
                return
            try:
                index = int(query["index"][0])
                frame_idx = int(query["frame"][0])
                jpg = clicks.active.frame_jpeg(index, frame_idx)
            except (KeyError, ValueError, IndexError):
                self._send(400, "text/plain", b"bad frame request")
                return
            if jpg is None:
                self._send(404, "text/plain", b"frame read failed")
                return
            self._send(200, "image/jpeg", jpg)

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            route = parsed.path
            if route == "/api/run":
                self._handle_run(self._read_json())
                return
            if route == "/api/upload":
                self._handle_upload(parse_qs(parsed.query))
                return
            if route == "/api/dataset-upload-zip":
                self._handle_dataset_upload_zip(parse_qs(parsed.query))
                return
            if route == "/api/calibration":
                self._handle_calibration()
                return
            if route == "/api/calibration/camera":
                self._handle_calibration_camera(self._read_json())
                return
            if route == "/api/upload/remove":
                self._handle_upload_remove(self._read_json())
                return
            if route == "/api/dataset/clear":
                self._handle_dataset_clear()
                return
            if route == "/api/centroids/edit":
                self._handle_centroid_edit(self._read_json())
                return
            if route == "/api/clicks/select":
                clicks.select(self._read_json().get("source", "dataset"))
                self._json(200, {"ok": True})
                return
            if route == "/api/click":
                self._handle_click(self._read_json())
                return
            if route == "/api/skip":
                self._handle_skip(self._read_json())
                return
            self._send(404, "text/plain", b"not found")

        def _handle_run(self, body: dict) -> None:
            stage = body.get("stage", "")
            source = body.get("source", "dataset")
            only = body.get("only") or None
            valid = UPLOAD_STAGES if source == "upload" else DATASET_STAGES
            if stage not in valid:
                self._json(400, {"error": f"invalid stage {stage!r} for {source}"})
                return
            if source == "upload" and stage == "triangulate" and not cfg.uploads_calibration_json.exists():
                self._json(400, {"error": "Upload a camera calibration first."})
                return
            try:
                fn = _stage_fn(cfg, stage, source, only, runner.set_progress)
            except ValueError as exc:
                self._json(400, {"error": str(exc)})
                return
            label = f"{source}:{stage}"
            if not runner.start(label, fn):
                self._json(409, {"error": "a job is already running"})
                return
            self._json(202, {"started": label})

        def _handle_upload(self, query: dict) -> None:
            name = query.get("name", [""])[0]
            if not name:
                self._json(400, {"error": "missing ?name="})
                return
            stem = safe_stem(name)
            dest_dir = cfg.uploads_root / stem
            dest_dir.mkdir(parents=True, exist_ok=True)
            dest = dest_dir / "video.mp4"
            remaining = int(self.headers.get("Content-Length", "0"))
            if remaining <= 0:
                self._json(400, {"error": "empty upload"})
                return
            with dest.open("wb") as fh:
                while remaining > 0:
                    chunk = self.rfile.read(min(UPLOAD_CHUNK, remaining))
                    if not chunk:
                        break
                    fh.write(chunk)
                    remaining -= len(chunk)
            self._json(200, {"label": stem})

        def _handle_dataset_upload_zip(self, query: dict) -> None:
            name = query.get("name", ["dataset.zip"])[0]
            if not name.lower().endswith(".zip"):
                self._json(400, {"error": "upload a .zip file"})
                return
            remaining = int(self.headers.get("Content-Length", "0"))
            if remaining <= 0:
                self._json(400, {"error": "empty upload"})
                return
            tmp = cfg.work_root / f".dataset_upload_{safe_stem(name)}.zip"
            with tmp.open("wb") as fh:
                while remaining > 0:
                    chunk = self.rfile.read(min(UPLOAD_CHUNK, remaining))
                    if not chunk:
                        break
                    fh.write(chunk)
                    remaining -= len(chunk)
            extracted = 0
            try:
                with zipfile.ZipFile(tmp) as zf:
                    names = [info.filename for info in zf.infolist()]
                    run_hint = infer_dataset_run(names)
                    for info in zf.infolist():
                        if info.is_dir() or not is_dataset_file(info.filename):
                            continue
                        rel = dataset_store_rel(info.filename, run_hint=run_hint)
                        dest = (cfg.dataset_uploads_root / rel).resolve()
                        if cfg.dataset_uploads_root.resolve() not in dest.parents:
                            continue
                        dest.parent.mkdir(parents=True, exist_ok=True)
                        with zf.open(info) as src, dest.open("wb") as out:
                            shutil.copyfileobj(src, out, length=UPLOAD_CHUNK)
                        extracted += 1
            except zipfile.BadZipFile:
                self._json(400, {"error": "invalid zip file"})
                return
            finally:
                tmp.unlink(missing_ok=True)
            self._json(200, {"extracted": extracted})

        def _handle_dataset_clear(self) -> None:
            for root in (cfg.dataset_uploads_root, cfg.formatted_root, cfg.detections_root, cfg.triangulation_root):
                if root.exists():
                    shutil.rmtree(root, ignore_errors=True)
            if cfg.clicks_json.exists():
                cfg.clicks_json.unlink()
            cfg.dataset_uploads_root.mkdir(parents=True, exist_ok=True)
            self._json(200, {"ok": True})

        def _handle_calibration(self) -> None:
            length = int(self.headers.get("Content-Length", "0"))
            raw = self.rfile.read(length) if length else b""
            try:
                cams = validate_calibration(json.loads(raw.decode()))
            except (ValueError, json.JSONDecodeError) as exc:
                self._json(400, {"error": str(exc)})
                return
            cfg.uploads_calibration_json.write_text(raw.decode())
            self._json(200, {"n_cameras": len(cams)})

        def _handle_centroid_edit(self, body: dict) -> None:
            rel = body.get("dir", "") if isinstance(body, dict) else ""
            edits = body.get("edits") if isinstance(body, dict) else None
            if not rel or not isinstance(edits, list):
                self._json(400, {"error": "need 'dir' and an 'edits' list"})
                return
            try:
                result = results_api.apply_centroid_edits(cfg.detections_root, rel, edits)
            except (ValueError, KeyError) as exc:
                self._json(400, {"error": str(exc)})
                return
            except (FileNotFoundError, OSError):
                self._send(404, "text/plain", b"detection not found")
                return
            self._json(200, result)

        def _handle_upload_remove(self, body: dict) -> None:
            label = body.get("label", "") if isinstance(body, dict) else ""
            if not label:
                self._json(400, {"error": "missing 'label'"})
                return
            remove_upload(cfg, label)
            self._json(200, {"removed": safe_stem(label)})

        def _handle_calibration_camera(self, body: dict) -> None:
            if not isinstance(body, dict) or not body.get("video"):
                self._json(400, {"error": "camera needs a 'video' label"})
                return
            try:
                n = upsert_camera(cfg.uploads_calibration_json, body)
            except (ValueError, KeyError) as exc:
                self._json(400, {"error": str(exc)})
                return
            self._json(200, {"n_cameras": n, "video": body["video"]})

        def _handle_click(self, body: dict) -> None:
            if clicks.active is None:
                self._json(400, {"error": "no active source"})
                return
            try:
                payload = clicks.active.apply_click(
                    int(body["index"]), body["x"], body["y"], body["frame"])
            except (KeyError, ValueError, IndexError):
                self._send(400, "text/plain", b"bad index")
                return
            self._send(200, "application/json", payload)

        def _handle_skip(self, body: dict) -> None:
            if clicks.active is None:
                self._json(400, {"error": "no active source"})
                return
            try:
                payload = clicks.active.toggle_skip(int(body["index"]))
            except (KeyError, ValueError, IndexError):
                self._send(400, "text/plain", b"bad index")
                return
            self._send(200, "application/json", payload)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"FireTrack dashboard at http://{host}:{port}")
    print(f"  work_root={cfg.work_root}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")
