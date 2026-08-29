# FireTrack

FireTrack estimates drone trajectories from two or more static camera videos.
It uses SAM3 to track the drone in each video, then triangulates a 3D trajectory
when camera calibration is available.

## Docker

Pull the image:

```bash
docker pull ashreeku/firetrack:latest
```

Run the dashboard:

```bash
mkdir -p firetrack-work

docker run --rm -it --gpus all \
  -p 127.0.0.1:8080:8080 \
  -e HF_HOME=/hf \
  -v ~/.cache/huggingface:/hf \
  -v "$PWD/firetrack-work:/work" \
  ashreeku/firetrack:latest webui \
    --work-root /work \
    --host 0.0.0.0 \
    --port 8080
```

Open:

```text
http://127.0.0.1:8080
```

## Workflows

FireTrack supports two main workflows:

- **Dataset mode:** upload a structured multi-camera run with mocap files for
  calibration-backed 3D output and validation.
- **Upload videos mode:** upload arbitrary camera clips and provide camera
  intrinsics/extrinsics manually for mocap-free 3D triangulation.

At minimum, 2D detection requires videos and click annotations. 3D
triangulation requires at least two calibrated static cameras.

## CLI

The container exposes the `firetrack` command:

```bash
docker run --rm --gpus all ashreeku/firetrack:latest --help
```

Main commands:

```text
firetrack webui
firetrack format
firetrack clicks serve
firetrack detect
firetrack triangulate
firetrack run-all
```

Typical staged CLI flow:

```bash
docker run --rm --gpus all \
  -v /path/to/data:/data/raw:ro \
  -v /path/to/firetrack-work:/work \
  ashreeku/firetrack:latest format \
    --data-root /data/raw \
    --out-root /work/formatted

docker run --rm -it --gpus all \
  -p 127.0.0.1:8080:8080 \
  -v /path/to/firetrack-work:/work \
  ashreeku/firetrack:latest clicks serve \
    --data-root /work/formatted \
    --clicks-json /work/clicks.json \
    --host 0.0.0.0 \
    --port 8080

docker run --rm --gpus all \
  -e HF_HOME=/hf \
  -v ~/.cache/huggingface:/hf \
  -v /path/to/firetrack-work:/work \
  ashreeku/firetrack:latest detect \
    --data-root /work/formatted \
    --out-root /work/detections \
    --clicks-json /work/clicks.json

docker run --rm --gpus all \
  -v /path/to/data:/data/raw:ro \
  -v /path/to/firetrack-work:/work \
  ashreeku/firetrack:latest triangulate \
    --raw-root /data/raw \
    --formatted-root /work/formatted \
    --detections-root /work/detections \
    --out-root /work/triangulation
```

## Outputs

Common outputs are written under the mounted work directory:

```text
formatted/manifest.json
clicks.json
detections/<run>/<camera>/centroids.npz
detections/<run>/<camera>/summary.json
triangulation/<run>/trajectory.csv
triangulation/<run>/trajectory.npz
triangulation/<run>/summary.json
```

## SAM3 Weights

The detection stage uses the gated Hugging Face model `facebook/sam3`. Provide
access through an existing Hugging Face cache or an authorized Hugging Face
token. Model weights are not included in the public repository.

## Local Development

Install locally from this directory:

```bash
python -m pip install -e .
python -m firetrack --help
```
