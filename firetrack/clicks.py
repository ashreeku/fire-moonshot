"""Browser click UI for SAM3 click initialization."""
from __future__ import annotations

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import cv2

from .dataset_527 import discover_normalized


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


def build_manifest(data_root: Path, clicks_json: Path) -> list[dict]:
    return build_manifest_from_videos(discover_normalized(data_root), clicks_json)


def build_manifest_from_videos(videos, clicks_json: Path) -> list[dict]:
    """Build click rows from any objects exposing label/run/phone/uuid/video_path."""
    existing: dict[str, dict] = {}
    if clicks_json.exists():
        for row in json.loads(clicks_json.read_text()):
            existing[row["label"]] = row

    rows: list[dict] = []
    for cam in videos:
        n, w, h = probe(cam.video_path)
        prev = existing.get(cam.label, {})
        rows.append(
            {
                "label": cam.label,
                "run": cam.run,
                "phone": cam.phone,
                "uuid": cam.uuid,
                "video_path": str(cam.video_path),
                "n_frames": n,
                "width": w,
                "height": h,
                "view_frame": prev.get("view_frame", int(n * 0.4)),
                "click_x": prev.get("click_x"),
                "click_y": prev.get("click_y"),
                "click_frame": prev.get("click_frame"),
                "approved": prev.get("approved", True),
            }
        )
    return rows


class FrameCache:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._path: str | None = None
        self._cap: cv2.VideoCapture | None = None

    def read(self, video_path: str, frame_index: int) -> bytes | None:
        with self._lock:
            if self._path != video_path:
                if self._cap is not None:
                    self._cap.release()
                self._cap = cv2.VideoCapture(video_path)
                self._path = video_path
            cap = self._cap
            if cap is None or not cap.isOpened():
                self._path = None  # don't cache a failed open; retry next time
                return None
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, frame_index))
            ok, frame = cap.read()
            if not ok:
                return None
            ok, buf = cv2.imencode(".jpg", frame, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            return buf.tobytes() if ok else None


class ClicksService:
    """Holds click rows for one video source and serves frames + edits.

    Shared by the standalone ``clicks serve`` command and the dashboard so both
    use identical annotation logic and on-disk format.
    """

    def __init__(self, videos, clicks_json: Path) -> None:
        self.clicks_json = Path(clicks_json).resolve()
        self.clicks_json.parent.mkdir(parents=True, exist_ok=True)
        self.rows = build_manifest_from_videos(videos, self.clicks_json)
        self._cache = FrameCache()
        self._lock = threading.Lock()
        self.save()

    def save(self) -> None:
        self.clicks_json.write_text(json.dumps(self.rows, indent=2))

    def rows_bytes(self) -> bytes:
        return json.dumps(self.rows).encode()

    def frame_jpeg(self, index: int, frame_index: int) -> bytes | None:
        row = self.rows[index]
        return self._cache.read(row["video_path"], frame_index)

    def apply_click(self, index: int, x: float, y: float, frame: int) -> bytes:
        with self._lock:
            row = self.rows[index]
            row["click_x"] = round(float(x), 3)
            row["click_y"] = round(float(y), 3)
            row["click_frame"] = int(frame)
            row["approved"] = True
            self.save()
            return self.rows_bytes()

    def toggle_skip(self, index: int) -> bytes:
        with self._lock:
            row = self.rows[index]
            row["approved"] = not row.get("approved", True)
            self.save()
            return self.rows_bytes()


HTML_PAGE = b"""<!doctype html>
<html><head><meta charset="utf-8"><title>FireTrack Clicks</title>
<style>
body{margin:0;font-family:system-ui,sans-serif;background:#111;color:#eee}header{padding:10px 14px;background:#1d1d1d;display:flex;gap:10px;align-items:center;flex-wrap:wrap}button{padding:7px 11px;border:1px solid #555;background:#2b2b2b;color:#fff;cursor:pointer;border-radius:4px}#wrap{position:relative;margin:10px auto;width:min(95vw,1400px)}#frame{display:block;width:100%;height:auto;border:1px solid #333;cursor:crosshair}#marker{position:absolute;width:24px;height:24px;margin:-12px 0 0 -12px;border:3px solid #00ff5a;border-radius:50%;pointer-events:none;display:none;box-shadow:0 0 0 2px #000}#scrub{width:100%}#status{padding:4px 14px 12px;color:#bbb;font-size:13px}.done{color:#66d17a}.skip{color:#e0a14a}input[type=number]{width:80px;background:#222;color:#eee;border:1px solid #555;padding:5px}
</style></head><body>
<header><button onclick="prevRow()">&lt; Prev</button><button onclick="nextRow()">Next &gt;</button><button onclick="jumpUnclicked()">Next unclicked</button><button onclick="toggleSkip()">Toggle skip</button><span id="meta"></span></header>
<div style="padding:0 14px;display:flex;gap:8px;align-items:center;flex-wrap:wrap"><button onclick="step(-30)">-30</button><button onclick="step(-5)">-5</button><button onclick="step(-1)">-1</button><input id="fnum" type="number" onchange="gotoFrame(this.value)"><button onclick="step(1)">+1</button><button onclick="step(5)">+5</button><button onclick="step(30)">+30</button><span id="fcount"></span></div>
<div style="padding:6px 14px"><input id="scrub" type="range" min="0" value="0" oninput="gotoFrame(this.value)"></div><div id="wrap"><img id="frame" onclick="saveClick(event)"><div id="marker"></div></div><div id="status"></div>
<script>
let rows=[],idx=0,frame=0;async function loadRows(){rows=await(await fetch('/api/rows')).json();const m=rows.findIndex(r=>r.click_x==null&&r.approved!==false);idx=m>=0?m:0;showRow()}function row(){return rows[idx]}function showRow(){if(!rows.length)return;idx=Math.max(0,Math.min(idx,rows.length-1));const r=row();frame=(r.click_x!=null)?r.click_frame:r.view_frame;document.getElementById('meta').textContent=`${idx+1}/${rows.length}  ${r.label}  (${r.width}x${r.height}, ${r.n_frames} frames)`;document.getElementById('scrub').max=r.n_frames-1;renderFrame()}function renderFrame(){const r=row();frame=Math.max(0,Math.min(frame,r.n_frames-1));const img=document.getElementById('frame');img.src=`/frame?index=${idx}&frame=${frame}&t=${Date.now()}`;img.onload=updateMarker;document.getElementById('fnum').value=frame;document.getElementById('scrub').value=frame;document.getElementById('fcount').textContent=`frame ${frame} / ${r.n_frames-1}`;let s='Scrub to a clear drone frame, then click it.';if(r.approved===false)s='<span class="skip">SKIPPED</span>';else if(r.click_x!=null)s=`<span class="done">saved click (${r.click_x.toFixed(1)}, ${r.click_y.toFixed(1)}) @ frame ${r.click_frame}</span>`;document.getElementById('status').innerHTML=s;updateMarker()}function updateMarker(){const r=row(),img=document.getElementById('frame'),mk=document.getElementById('marker');if(r.click_x==null||r.click_frame!==frame||!img.naturalWidth){mk.style.display='none';return}mk.style.left=`${r.click_x*img.clientWidth/img.naturalWidth}px`;mk.style.top=`${r.click_y*img.clientHeight/img.naturalHeight}px`;mk.style.display='block'}function step(d){frame+=d;renderFrame()}function gotoFrame(v){frame=parseInt(v)||0;renderFrame()}async function saveClick(e){const img=e.currentTarget,rect=img.getBoundingClientRect();const x=(e.clientX-rect.left)*img.naturalWidth/rect.width;const y=(e.clientY-rect.top)*img.naturalHeight/rect.height;rows=await(await fetch('/api/click',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:idx,x,y,frame})})).json();renderFrame();setTimeout(jumpUnclicked,200)}async function toggleSkip(){rows=await(await fetch('/api/skip',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({index:idx})})).json();showRow()}function nextRow(){idx++;showRow()}function prevRow(){idx--;showRow()}function jumpUnclicked(){let n=rows.findIndex((r,i)=>i>idx&&r.click_x==null&&r.approved!==false);if(n<0)n=rows.findIndex(r=>r.click_x==null&&r.approved!==false);if(n>=0){idx=n;showRow()}else showRow()}window.addEventListener('resize',updateMarker);document.addEventListener('keydown',e=>{if(e.target.tagName==='INPUT')return;if(e.key==='ArrowRight')step(e.shiftKey?5:1);if(e.key==='ArrowLeft')step(e.shiftKey?-5:-1)});loadRows();
</script></body></html>"""


def serve_click_ui(*, data_root: Path, clicks_json: Path, host: str, port: int) -> None:
    data_root = data_root.resolve()
    service = ClicksService(discover_normalized(data_root), clicks_json)

    class Handler(BaseHTTPRequestHandler):
        def _send(self, status: int, ctype: str, payload: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", ctype)
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

        def do_GET(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            if parsed.path == "/":
                self._send(200, "text/html; charset=utf-8", HTML_PAGE)
                return
            if parsed.path == "/api/rows":
                self._send(200, "application/json", service.rows_bytes())
                return
            if parsed.path == "/frame":
                q = parse_qs(parsed.query)
                try:
                    index = int(q["index"][0])
                    frame_idx = int(q["frame"][0])
                    jpg = service.frame_jpeg(index, frame_idx)
                except (KeyError, ValueError, IndexError):
                    self._send(400, "text/plain", b"bad frame request")
                    return
                if jpg is None:
                    self._send(404, "text/plain", b"frame read failed")
                    return
                self._send(200, "image/jpeg", jpg)
                return
            self._send(404, "text/plain", b"not found")

        def do_POST(self) -> None:  # noqa: N802
            parsed = urlparse(self.path)
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode())
            try:
                index = int(payload["index"])
                if parsed.path == "/api/click":
                    self._send(200, "application/json", service.apply_click(
                        index, payload["x"], payload["y"], payload["frame"]))
                    return
                if parsed.path == "/api/skip":
                    self._send(200, "application/json", service.toggle_skip(index))
                    return
            except (KeyError, ValueError, IndexError):
                self._send(400, "text/plain", b"bad index")
                return
            self._send(404, "text/plain", b"not found")

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002
            return

    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Serving click UI at http://{host}:{port}")
    print(f"Writing clicks to {service.clicks_json}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped.")


def click_status(clicks_json: Path) -> dict[str, int]:
    if not clicks_json.exists():
        raise FileNotFoundError(f"No clicks file: {clicks_json}")
    rows = json.loads(clicks_json.read_text())
    clicked = [r for r in rows if r.get("click_x") is not None]
    skipped = [r for r in rows if r.get("approved") is False]
    pending = [r for r in rows if r.get("click_x") is None and r.get("approved") is not False]
    return {"total": len(rows), "clicked": len(clicked), "skipped": len(skipped), "pending": len(pending)}
