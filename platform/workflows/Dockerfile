FROM python:3.11-slim

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application
COPY . .

# Expose port for Restate to call
EXPOSE 9080

# Run with hypercorn
CMD ["python", "-m", "hypercorn", "main:app", "--bind", "0.0.0.0:9080"]
