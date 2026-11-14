FROM python:3.12-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
RUN pip install "fastapi>=0.115" "uvicorn[standard]>=0.30" "pydantic>=2"
WORKDIR /app
COPY app.py queue_db.py ./
CMD ["sh", "-c", "uvicorn app:from_env --factory --host 0.0.0.0 --port 8765"]
