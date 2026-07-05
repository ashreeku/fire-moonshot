FROM pytorch/pytorch:2.6.0-cuda12.4-cudnn9-runtime

ENV DEBIAN_FRONTEND=noninteractive

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    HF_HOME=/work/.cache/huggingface \
    FIRETRACK_FFMPEG=/usr/bin/ffmpeg

WORKDIR /app

RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        build-essential \
        ca-certificates \
        ffmpeg \
        git \
        libglib2.0-0 \
        libgl1 \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt pyproject.toml README.md ./
COPY firetrack ./firetrack
COPY vendor ./vendor

RUN python -m pip install --upgrade pip \
    && python -m pip install -r requirements.txt \
    && python -m pip install --no-deps .

# The app packages the SAM3 BPE vocab under vendor/sam3_assets and passes it to
# SAM3 explicitly. Keep this compatibility copy too because sam3==0.1.2 also
# looks under <site-packages>/assets in some code paths.
RUN ASSETS_DIR="$(python -c 'import os,sam3; print(os.path.join(os.path.dirname(os.path.dirname(sam3.__file__)), "assets"))')" \
    && mkdir -p "$ASSETS_DIR" \
    && cp vendor/sam3_assets/bpe_simple_vocab_16e6.txt.gz "$ASSETS_DIR/"

# SAM3 inference downloads the gated `facebook/sam3` checkpoint from Hugging Face
# at runtime. Pass an authorized token (`-e HF_TOKEN=...`) and mount a writable
# /work volume so HF_HOME persists the checkpoint across runs.
RUN mkdir -p /work
VOLUME ["/work"]
EXPOSE 8080

ENTRYPOINT ["firetrack"]
CMD ["webui"]
