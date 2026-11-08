# Multi-stage Docker build for Wave Music App
FROM python:3.11-slim

# Install system dependencies including ffmpeg for audio processing
RUN apt-get update && apt-get install -y --no-install-recommends \
    ffmpeg \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Security: create non-root user (UID 1000 required for Hugging Face Spaces)
RUN useradd -m -u 1000 user
WORKDIR /home/user/app

# Copy requirements and install Python dependencies
COPY --chown=user:user requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files with proper permissions
COPY --chown=user:user app/ app/
COPY --chown=user:user frontend/ frontend/
COPY --chown=user:user run.py .

# Switch to non-root user
USER user
ENV HOME=/home/user \
    PATH=/home/user/.local/bin:$PATH \
    HOST=0.0.0.0 \
    PORT=7860 \
    PYTHONUNBUFFERED=1

EXPOSE 7860

CMD ["python", "run.py"]
