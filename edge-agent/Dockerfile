# EvoIoT Edge Agent
# Bento + Python/BAC0 for BACnet discovery and polling

FROM ghcr.io/warpstreamlabs/bento:latest AS bento

FROM python:3.11-slim

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    supervisor \
    && rm -rf /var/lib/apt/lists/*

# Copy Bento binary from official image
COPY --from=bento /bento /usr/local/bin/bento

# Install Python dependencies
RUN pip install --no-cache-dir BAC0

# Create directories
RUN mkdir -p /scripts /config /data

# Copy scripts
COPY scripts/ /scripts/
RUN chmod +x /scripts/*.py

# Copy Bento configs
COPY config/ /config/

# Copy supervisor config
COPY supervisord.conf /etc/supervisor/conf.d/supervisord.conf

# Environment defaults
ENV EDGE_DB_PATH=/data/edge.db
ENV BUILDING_ID=bldg-001
ENV AGENT_ID=agent-001
ENV BACNET_NETWORK=192.168.100.1/24
ENV POLL_INTERVAL=10
ENV DISCOVERY_INTERVAL=300
ENV LOG_LEVEL=INFO

VOLUME /data

# Run supervisor to manage all processes
CMD ["/usr/bin/supervisord", "-c", "/etc/supervisor/conf.d/supervisord.conf"]
