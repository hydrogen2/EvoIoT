FROM python:3.11-slim

WORKDIR /app

# Install curl for Restate registration
RUN apt-get update && apt-get install -y --no-install-recommends curl && rm -rf /var/lib/apt/lists/*

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
