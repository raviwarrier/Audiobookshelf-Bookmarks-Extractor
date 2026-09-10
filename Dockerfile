FROM python:3.11-slim

# Prevent interactive prompts during apt install
ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1

# Install system dependencies: ffmpeg (audio slicing/transcoding), curl, and wget
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    wget \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python requirements
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Pre-download transcription models into image cache so server admin does not need to install anything manually
# 1. Primary engine: faster-whisper base.en model
RUN python3 -c "from faster_whisper import WhisperModel; WhisperModel('base.en', device='cpu', compute_type='int8')"

# 2. Backup engine: Vosk lightweight speech model
RUN python3 -c "from vosk import Model; Model(model_name='vosk-model-small-en-us-0.15')"

# Copy application source and dashboard templates
COPY main.py .
COPY templates/ ./templates/

# Expose ports: 8080 (container default) and 13379 (app default port)
EXPOSE 8080
EXPOSE 13379

# Default Environment Variables
ENV ABS_SERVER_URL="http://audiobookshelf:80"
ENV VOLUME_DIR="/data"
ENV WHISPER_MODEL="base.en"
ENV WHISPER_DEVICE="cpu"
ENV WHISPER_COMPUTE_TYPE="int8"
ENV VOSK_MODEL_NAME="vosk-model-small-en-us-0.15"
ENV PORT=13379

# Start FastAPI server on port 13379
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "13379"]
