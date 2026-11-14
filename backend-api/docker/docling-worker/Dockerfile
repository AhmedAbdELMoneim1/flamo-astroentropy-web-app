# CPU-only docling worker. No API key, no secret; the models are downloaded at BUILD time, so a worker needs only the master on the LAN.
FROM python:3.12-slim
ARG IMAGE_TAG=rag-docling-worker:3
ENV IMAGE_TAG=${IMAGE_TAG} \
    PIP_NO_CACHE_DIR=1 PYTHONUNBUFFERED=1 \
    DOCLING_ARTIFACTS_PATH=/opt/docling-models \
    HF_HUB_OFFLINE=0 TOKENIZERS_PARALLELISM=false

RUN apt-get update && apt-get install -y --no-install-recommends libgl1 libglib2.0-0 libgomp1 \
    && rm -rf /var/lib/apt/lists/*

# CPU wheels of torch (the default wheels pull ~2.5 GB of CUDA libraries that a CPU worker never uses)
RUN pip install torch==2.15.0 torchvision==0.29.2 --index-url https://download.pytorch.org/whl/cpu

WORKDIR /app
COPY requirements.txt requirements.lock ./
RUN pip install -r requirements.lock

# models at build time (layout, table structure, OCR); after this the container needs no internet
RUN docling-tools models download -o /opt/docling-models && du -sh /opt/docling-models
ENV HF_HUB_OFFLINE=1

COPY parse.py worker.py ./
RUN mkdir /work
ENTRYPOINT ["python", "worker.py"]
