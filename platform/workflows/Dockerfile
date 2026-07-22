FROM python:3.11-slim

WORKDIR /app

# curl for Restate registration; openssh-client for the SSH transport
# (collectors reach BMS-LAN edges over SSH)
RUN apt-get update && apt-get install -y --no-install-recommends curl openssh-client \
    && rm -rf /var/lib/apt/lists/*

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Make startup script executable
RUN chmod +x start.sh

# Expose port for Restate to call
EXPOSE 9080

# Run startup script (starts service and registers with Restate)
CMD ["./start.sh"]
