# PoolMon - Pool Chemistry Tracker & Recovery Dashboard
# Single-container image: FastAPI backend + plain HTML/JS frontend
#
# Build:  docker build -t poolmon .
# Run:    docker run -d \
#           --name poolmon \
#           -p 8078:8078 \
#           -v /your/nas/path/poolmon-data:/data \
#           --restart unless-stopped \
#           poolmon

FROM python:3.12-slim

# Set working directory
WORKDIR /app

# Install Python dependencies first (cached layer - only rebuilds if requirements change)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY app/      ./app/
COPY engine/   ./engine/
COPY schema_v4.sql .

# Copy frontend (plain HTML/JS - no build step needed)
COPY frontend/ ./frontend/

# Data directory: mounted as a Docker volume so the database and photos
# survive container restarts and updates. Never bake data into the image.
RUN mkdir -p /data/photos
VOLUME ["/data"]

# Tell PoolMon where its data lives
ENV POOLMON_DATA_DIR=/data

# Port the API listens on
EXPOSE 8078

# Health check - Portainer will show container as healthy once the API responds
HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python3 -c "import urllib.request; urllib.request.urlopen('http://localhost:8078/api/dashboard')" \
    || exit 1

# Start the server
# --host 0.0.0.0 required so Docker can route traffic to the container
# --workers 1 is correct for SQLite (no concurrent-write contention)
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8078", "--workers", "1"]
