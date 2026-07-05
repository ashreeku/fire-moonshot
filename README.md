# Docker Fire Tracking

Standalone Docker-oriented pipeline for the 5-27 Fire Tracking recordings.

The container exposes one command, `firetrack`, with stages for:

- `webui`: full-pipeline web dashboard (the default container command).
- `format`: normalize raw phone videos into scene-upright landscape clips.
- `clicks serve`: annotate one approved SAM click per video in a browser UI.
- `detect`: run SAM3 2D video processing and save centroid tracks.
- `triangulate`: calibrate static cameras with mocap and triangulate 3D drone trajectories.
- `run-all`: run the non-interactive stages in sequence.

## Web Dashboard (recommended)

Starting the container with no arguments launches a browser dashboard on port
8080 that drives the whole pipeline:

```bash
docker run --rm -it --gpus all -p 127.0.0.1:8080:8080 \
  -e HF_HOME=/hf \
  -v ~/.cache/huggingface:/hf \
  -v "$PWD/firetrack-work:/work" \
  firetrack:527
```

The dashboard has two modes:

- **5-27 dataset**: upload a 5-27 run zip from the browser. The app
  extracts it under `/work/dataset_uploads`, then runs format -> annotate clicks
  -> detect -> triangulate with live logs. The uploaded run should contain camera
  folders (`video.mp4`, `camera.json`, `calibration.json`, `metadata.json`, and
  optional sensor sidecars) plus the 6D mocap TSV.
- **Upload videos**: drop videos from your computer to run clicks + SAM3
  detection, then triangulate when you provide per-camera calibration and timing.

For browser access through an SSH tunnel, keep the port bound to localhost as
shown above and open `http://127.0.0.1:8080` locally.

The non-interactive CLI still supports mounted raw datasets via `--raw-root`;
the web dashboard no longer requires a `/data/raw` mount.

Equivalent run using a writable checkpoint cache inside `/work`:

```bash
docker run --rm -it --gpus all -p 8080:8080 \
  -v /path/to/firetrack-work:/work \
  firetrack:527
```

## Build

```bash
docker build -t firetrack:527 .
```

The image is CUDA-oriented and expects an NVIDIA runtime for SAM3 inference:

```bash
docker run --rm --gpus all firetrack:527 --help
```

## SAM3 Model Weights (required for `detect` / `run-all`)

The `detect` and `run-all` stages need the SAM3 checkpoint from the **gated**
Hugging Face repo [`facebook/sam3`](https://huggingface.co/facebook/sam3)
(`sam3.pt`, ~3.4 GB). There are two ways to provide it.

### Option A (recommended): reuse a local Hugging Face cache, offline

If you already have `facebook/sam3` in your host HF cache
(`~/.cache/huggingface/hub/models--facebook--sam3`), mount it read-only and run
fully offline — no token, no download:

```bash
docker run --rm --gpus all \
  -e HF_HOME=/hf -e HF_HUB_OFFLINE=1 \
  -v ~/.cache/huggingface:/hf:ro \
  -v /path/to/5-27:/data/raw:ro \
  -v /path/to/firetrack-work:/work \
  firetrack:527 detect \
    --data-root /work/formatted \
    --out-root /work/detections \
    --clicks-json /work/clicks.json
```

### Option B: download at runtime with a token

If you don't have a local cache, the checkpoint is downloaded on first run.
Request access to `facebook/sam3`, then pass an authorized token. The image sets
`HF_HOME=/work/.cache/huggingface`, so a writable `/work` mount persists the
download across runs:

```bash
docker run --rm --gpus all \
  -e HF_TOKEN=hf_your_token \
  -v /path/to/5-27:/data/raw:ro \
  -v /path/to/firetrack-work:/work \
  firetrack:527 detect \
    --data-root /work/formatted \
    --out-root /work/detections \
    --clicks-json /work/clicks.json
```

The `format`, `clicks`, and `triangulate` stages do not need SAM3 weights.

### Bundled image (weights baked in) — private/internal only

The default image does **not** contain the SAM3 weights, which keeps it safe to
share. For a turnkey image that runs detection with no HF mount or token, bake the
weights in. **Do not push a bundled image to a public registry** — `facebook/sam3`
is a gated, license-restricted Meta model.

```bash
./bundle-weights.sh                                          # stage local weights -> ./weights (~3.4 GB)
docker build -f Dockerfile.bundled -t firetrack:527-bundled .
docker run --rm --gpus all -p 8080:8080 -v $PWD/firetrack-work:/work firetrack:527-bundled
```

The bundled image is ~10.4 GB (base + weights) and sets `HF_HOME=/opt/hf` +
`HF_HUB_OFFLINE=1` internally.

## Expected Mounts

For the web dashboard, only `/work` is required. It stores uploaded datasets,
uploaded clips, intermediate outputs, and the Hugging Face cache by default:

```bash
docker run --rm -it --gpus all -p 127.0.0.1:8080:8080 \
  -v /path/to/firetrack-work:/work \
  firetrack:527
```

For non-interactive CLI runs, use a read-only mount for raw data and a writable
mount for outputs:

```bash
docker run --rm --gpus all \
  -v /path/to/5-27:/data/raw:ro \
  -v /path/to/firetrack-work:/work \
  firetrack:527 run-all \
    --raw-root /data/raw \
    --work-root /work \
    --clicks-json /work/clicks.json
```

## Recommended Workflow

### Web dashboard

1. Open `http://127.0.0.1:8080`.
2. In **5-27 dataset**, upload a run zip.
3. Run **Format**.
4. Run **Annotate** and click the drone once per camera.
5. Run **Detect**.
6. Run **Triangulate**.
7. Inspect/download outputs in **Results**.

### CLI mounted dataset

1. Normalize videos:

```bash
firetrack format --data-root /data/raw --out-root /work/formatted
```

2. Create or edit click annotations:

```bash
firetrack clicks serve \
  --data-root /work/formatted \
  --clicks-json /work/clicks.json \
  --host 0.0.0.0 \
  --port 8080
```

3. Run SAM3 detection:

```bash
firetrack detect \
  --data-root /work/formatted \
  --out-root /work/detections \
  --clicks-json /work/clicks.json
```

4. Triangulate:

```bash
firetrack triangulate \
  --raw-root /data/raw \
  --formatted-root /work/formatted \
  --detections-root /work/detections \
  --out-root /work/triangulation
```

## Outputs

- `/work/formatted/manifest.json`: normalized video manifest.
- `/work/clicks.json`: click UI state and approved SAM clicks.
- `/work/detections/<run>/<label>/centroids.npz`: per-frame 2D centroid tracks.
- `/work/detections/<run>/<label>/summary.json`: detection counts and metadata.
- `/work/triangulation/calibration.json`: static camera calibration.
- `/work/triangulation/<run>/trajectory.npz`: raw, smoothed, and mocap GT trajectories.
- `/work/triangulation/<run>/trajectory.csv`: human-readable trajectory table.
- `/work/triangulation/summary.json`: per-run metrics and failures.

Mask arrays are omitted by default to keep outputs lean. Add `--save-masks` to `detect` or `run-all` when debugging segmentation quality.

## Local Validation

This repository can be checked without Docker:

```bash
python -m pytest -q
python -m compileall -q firetrack
python -m firetrack --help
```
