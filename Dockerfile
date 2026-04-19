# Orange Bike Brewing — Data Browser
# Runs under /orangebike on crowdsaasing.com via Cloudflare Tunnel

FROM python:3.11-slim

# System deps
RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
 && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps first (cache-friendly layer)
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application + bundled database
COPY webapp/ ./webapp/
COPY orange_bike.db ./orange_bike.db
COPY data_dictionary.md ./data_dictionary.md
COPY OBB_DATA_SPEC.md ./OBB_DATA_SPEC.md

# Uploads dir exists so Flask can write scan photos (on PVC in prod)
RUN mkdir -p /data /app/webapp/uploads

EXPOSE 8080

# DB_DIR=/data makes the app use the PersistentVolumeClaim in production.
# On first boot it copies the bundled DB to /data/orange_bike.db.
ENV DB_DIR=/data \
    UPLOADS_DIR=/data/uploads \
    URL_PREFIX="" \
    READ_ONLY=true \
    PYTHONUNBUFFERED=1

# 2 workers × 4 threads — plenty for class-sized traffic, stays well under the 256Mi limit
CMD ["gunicorn", \
     "--bind", "0.0.0.0:8080", \
     "--workers", "2", \
     "--threads", "4", \
     "--timeout", "60", \
     "--access-logfile", "-", \
     "--error-logfile", "-", \
     "webapp.wsgi:application"]
